"""Host-side protocol decoding from sampled waveform data.

The DSO2000 decodes serial buses on its own screen but does not expose the
decoded data over SCPI, so to show it in the web UI we decode here from the
captured analog samples, thresholded to logic levels.

Implemented: UART, LIN (1 line); I2C, SPI (2 lines); CAN (1 line, NRZ with
bit de-stuffing). Each decoder returns:

    {"protocol": str, "frames": [{"t": sec, "text": str, "ok": bool,
                                  "char": optional}], "error": optional, ...}

CAN especially should be validated against a real bus capture; the simulator
produces sine/square test signals, not protocol traffic.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _logic(volts: np.ndarray):
    """Threshold an analog trace to a boolean logic array (mid level)."""
    if volts is None or volts.size == 0:
        return None
    hi, lo = float(np.max(volts)), float(np.min(volts))
    if hi - lo < 1e-6:
        return None
    return volts > (hi + lo) / 2.0


def _bits_to_int(bits: List[int], msb_first: bool = True) -> int:
    v = 0
    seq = bits if msb_first else list(reversed(bits))
    for b in seq:
        v = (v << 1) | (1 if b else 0)
    return v


def _char(value: int) -> str:
    return chr(value) if 32 <= value < 127 else "."


# --------------------------------------------------------------------------
# UART (one line)
# --------------------------------------------------------------------------
def decode_uart(volts, sample_rate, baud=9600, data_bits=8, parity="none",
                invert=False) -> Dict:
    logic = _logic(volts)
    if logic is None or sample_rate <= 0 or baud <= 0:
        return {"protocol": "uart", "frames": [], "error": "no signal / bad parameters"}
    if invert:
        logic = ~logic
    spb = sample_rate / baud
    if spb < 3:
        return {"protocol": "uart", "frames": [],
                "error": f"under-sampled ({spb:.1f} samples/bit)"}
    n = logic.size
    frames: List[Dict] = []
    i = 1
    span = int(spb * (2 + data_bits + 2))
    while i < n - span:
        if logic[i - 1] and not logic[i]:                 # falling edge = start bit
            start = i
            ctr = lambda k: int(round(start + (k + 0.5) * spb))
            if logic[ctr(0)]:
                i += 1
                continue
            val = 0
            for b in range(data_bits):
                if logic[ctr(1 + b)]:
                    val |= (1 << b)                        # UART is LSB-first
            idx = 1 + data_bits
            ok = True
            if parity in ("odd", "even"):
                pbit = 1 if logic[ctr(idx)] else 0
                idx += 1
                ones = bin(val).count("1") + pbit
                ok = (ones % 2 == 0) if parity == "even" else (ones % 2 == 1)
            if not logic[ctr(idx)]:
                ok = False                                 # stop bit must be high
            frames.append({"t": start / sample_rate, "value": val,
                           "hex": f"0x{val:02X}", "char": _char(val),
                           "text": f"0x{val:02X} '{_char(val)}'", "ok": ok})
            i = start + int(spb * (idx + 1))
        else:
            i += 1
    return {"protocol": "uart", "baud": baud, "frames": frames}


# --------------------------------------------------------------------------
# LIN (one line): break, sync (0x55), PID, data…, checksum — UART 8N1 framing
# --------------------------------------------------------------------------
def decode_lin(volts, sample_rate, baud=19200, invert=False) -> Dict:
    logic = _logic(volts)
    if logic is None or sample_rate <= 0 or baud <= 0:
        return {"protocol": "lin", "frames": [], "error": "no signal / bad parameters"}
    if invert:
        logic = ~logic
    spb = sample_rate / baud
    if spb < 3:
        return {"protocol": "lin", "frames": [], "error": f"under-sampled ({spb:.1f} samples/bit)"}
    n = logic.size

    def read_byte(start):
        """Decode one 8N1 byte whose start bit begins at sample `start`."""
        ctr = lambda k: int(round(start + (k + 0.5) * spb))
        if ctr(9) >= n or logic[ctr(0)]:
            return None
        val = 0
        for b in range(8):
            if logic[ctr(1 + b)]:
                val |= (1 << b)
        stop_ok = bool(logic[ctr(9)])
        return val, stop_ok, start + int(spb * 10)

    frames: List[Dict] = []
    i = 1
    while i < n - int(spb * 12):
        # Break = dominant (low) for >= ~11 bit times.
        if logic[i - 1] and not logic[i]:
            j = i
            while j < n and not logic[j]:
                j += 1
            low_bits = (j - i) / spb
            if low_bits >= 9.5:                            # break detected
                frames.append({"t": i / sample_rate, "text": f"BREAK ({low_bits:.0f} bits)", "ok": True})
                # next falling edge -> sync byte
                k = j
                while k < n - 1 and not (logic[k - 1] and not logic[k]):
                    k += 1
                role = ["SYNC", "PID"]
                bi = 0
                while k < n - int(spb * 11):
                    res = read_byte(k)
                    if res is None:
                        break
                    val, ok, nxt = res
                    label = role[bi] if bi < len(role) else "data"
                    if label == "SYNC":
                        txt = f"SYNC 0x{val:02X}" + ("" if val == 0x55 else " (!=0x55)")
                    elif label == "PID":
                        txt = f"PID 0x{val:02X} (id {val & 0x3F})"
                    else:
                        txt = f"0x{val:02X} '{_char(val)}'"
                    frames.append({"t": k / sample_rate, "value": val, "text": txt, "ok": ok})
                    bi += 1
                    # stop if a long idle (gap) follows
                    if nxt < n and logic[nxt:min(n, nxt + int(spb * 3))].all() and \
                       nxt + int(spb * 11) < n and logic[nxt:nxt + int(spb * 11)].all():
                        k = nxt
                        # peek: if next falling edge is far, end frame
                        m = nxt
                        while m < n - 1 and logic[m]:
                            m += 1
                        if (m - nxt) / spb > 10:
                            break
                        k = m
                    else:
                        k = nxt
                i = k
                continue
        i += 1
    return {"protocol": "lin", "baud": baud, "frames": frames}


# --------------------------------------------------------------------------
# SPI (clock + data): sample data on the selected clock edge, group into words
# --------------------------------------------------------------------------
def decode_spi(clk, data, sample_rate, edge="rising", width=8, msb_first=True) -> Dict:
    lc, ld = _logic(clk), _logic(data)
    if lc is None or ld is None:
        return {"protocol": "spi", "frames": [], "error": "need clock + data on two channels"}
    n = min(lc.size, ld.size)
    frames: List[Dict] = []
    bits: List[int] = []
    t0 = 0.0
    for i in range(1, n):
        active = (lc[i] and not lc[i - 1]) if edge == "rising" else (not lc[i] and lc[i - 1])
        if not active:
            continue
        if not bits:
            t0 = i / sample_rate
        bits.append(1 if ld[i] else 0)
        if len(bits) >= width:
            val = _bits_to_int(bits, msb_first)
            hexw = ("0x%0*X") % ((width + 3) // 4, val)
            frames.append({"t": t0, "value": val, "hex": hexw,
                           "char": _char(val) if width <= 8 else "",
                           "text": hexw + (f" '{_char(val)}'" if width <= 8 else "")})
            bits = []
    return {"protocol": "spi", "frames": frames, "edge": edge, "width": width}


# --------------------------------------------------------------------------
# I2C (SDA + SCL)
# --------------------------------------------------------------------------
def decode_i2c(sda, scl, sample_rate) -> Dict:
    ls, lc = _logic(sda), _logic(scl)
    if ls is None or lc is None:
        return {"protocol": "i2c", "frames": [], "error": "need SDA + SCL on two channels"}
    n = min(ls.size, lc.size)
    frames: List[Dict] = []
    bits: List[int] = []
    is_addr = False
    for i in range(1, n):
        scl_high = lc[i]
        sda_fall = ls[i - 1] and not ls[i]
        sda_rise = (not ls[i - 1]) and ls[i]
        scl_rise = lc[i] and not lc[i - 1]
        if scl_high and sda_fall:                          # START
            frames.append({"t": i / sample_rate, "text": "START", "ok": True})
            bits = []
            is_addr = True
            continue
        if scl_high and sda_rise:                          # STOP
            frames.append({"t": i / sample_rate, "text": "STOP", "ok": True})
            bits = []
            continue
        if scl_rise:
            bits.append(1 if ls[i] else 0)
            if len(bits) == 9:                             # 8 data + ACK
                val = _bits_to_int(bits[:8], msb_first=True)
                ack = (bits[8] == 0)                       # ACK = SDA low
                if is_addr:
                    rw = "R" if (val & 1) else "W"
                    txt = f"addr 0x{val >> 1:02X} {rw} {'ACK' if ack else 'NACK'}"
                    is_addr = False
                else:
                    txt = f"0x{val:02X} '{_char(val)}' {'ACK' if ack else 'NACK'}"
                frames.append({"t": i / sample_rate, "value": val, "text": txt, "ok": ack})
                bits = []
    return {"protocol": "i2c", "frames": frames}


# --------------------------------------------------------------------------
# CAN (one line, NRZ, dominant = low): standard + extended, with de-stuffing
# --------------------------------------------------------------------------
class _CanBits:
    """Sequential de-stuffed bit reader for CAN."""
    def __init__(self, logic, start, spb):
        self.logic = logic
        self.pos = start + spb / 2.0
        self.spb = spb
        self.n = logic.size
        self.run_val = None
        self.run_len = 0

    def _raw(self):
        i = int(round(self.pos))
        self.pos += self.spb
        if i >= self.n:
            return None
        return 0 if self.logic[i] else 1                   # dominant(low)=0, recessive(high)=1

    def bit(self):
        if self.run_len == 5:                              # discard the stuff bit
            if self._raw() is None:
                return None
            self.run_val = None
            self.run_len = 0
        b = self._raw()
        if b is None:
            return None
        if b == self.run_val:
            self.run_len += 1
        else:
            self.run_val = b
            self.run_len = 1
        return b

    def bits(self, k):
        out = []
        for _ in range(k):
            b = self.bit()
            if b is None:
                return None
            out.append(b)
        return out


def decode_can(volts, sample_rate, baud=500000, invert=False) -> Dict:
    logic = _logic(volts)
    if logic is None or sample_rate <= 0 or baud <= 0:
        return {"protocol": "can", "frames": [], "error": "no signal / bad parameters"}
    if invert:
        logic = ~logic
    spb = sample_rate / baud
    if spb < 4:
        return {"protocol": "can", "frames": [], "error": f"under-sampled ({spb:.1f} samples/bit)"}
    n = logic.size
    frames: List[Dict] = []
    i = 1
    guard = 0
    while i < n - int(spb * 20) and guard < 10000:
        guard += 1
        # SOF: recessive (high) then dominant (low)
        if logic[i - 1] and not logic[i]:
            r = _CanBits(logic, i, spb)
            sof = r.bit()
            if sof != 0:
                i += 1
                continue
            id_a = r.bits(11)
            if id_a is None:
                break
            ident = _bits_to_int(id_a)
            srr_rtr = r.bit()
            ide = r.bit()
            extended = (ide == 1)
            rtr = srr_rtr
            if extended:
                id_b = r.bits(18)
                if id_b is None:
                    break
                ident = (ident << 18) | _bits_to_int(id_b)
                rtr = r.bit()
                r.bit()                                    # r1
            r.bit()                                        # r0
            dlc_bits = r.bits(4)
            if dlc_bits is None:
                break
            dlc = min(_bits_to_int(dlc_bits), 8)
            data = []
            for _ in range(dlc):
                byte = r.bits(8)
                if byte is None:
                    break
                data.append(_bits_to_int(byte))
            crc_bits = r.bits(15)
            crc = _bits_to_int(crc_bits) if crc_bits else 0
            kind = "ext" if extended else "std"
            dtxt = " ".join(f"{b:02X}" for b in data)
            txt = (f"ID 0x{ident:0{8 if extended else 3}X} ({kind})"
                   f"{' RTR' if rtr else ''} DLC={dlc}"
                   f"{'  ['+dtxt+']' if data else ''}  CRC 0x{crc:04X}")
            frames.append({"t": i / sample_rate, "id": ident, "dlc": dlc,
                           "data": data, "text": txt, "ok": True})
            # advance past this frame
            i = int(r.pos) + int(spb * 8)
        else:
            i += 1
    return {"protocol": "can", "baud": baud, "frames": frames}


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------
def decode(protocol: str, channels: Dict[int, np.ndarray], sample_rate: float,
           **p) -> Dict:
    """`channels` maps channel number -> volts array. `p` carries parameters
    incl. source/sda/scl/baud/width/edge/etc."""
    proto = (protocol or "").lower()
    src = int(p.get("source", 1))

    def ch(num):
        a = channels.get(int(num))
        return a

    if proto == "uart":
        return decode_uart(ch(src), sample_rate, baud=int(p.get("baud", 9600)),
                           data_bits=int(p.get("data_bits", 8)),
                           parity=p.get("parity", "none"), invert=bool(p.get("invert", False)))
    if proto == "lin":
        return decode_lin(ch(src), sample_rate, baud=int(p.get("baud", 19200)),
                          invert=bool(p.get("invert", False)))
    if proto == "can":
        return decode_can(ch(src), sample_rate, baud=int(p.get("baud", 500000)),
                          invert=bool(p.get("invert", False)))
    if proto == "spi":
        return decode_spi(ch(p.get("scl", 1)), ch(p.get("sda", 2)), sample_rate,
                          edge=p.get("edge", "rising"), width=int(p.get("width", 8)),
                          msb_first=p.get("bit_order", "msb") != "lsb")
    if proto == "iic" or proto == "i2c":
        return decode_i2c(ch(p.get("sda", 1)), ch(p.get("scl", 2)), sample_rate)
    return {"protocol": proto, "frames": [], "error": f"unknown protocol {proto!r}"}
