"""Host-side protocol decoding from sampled waveform data.

The DSO2000 decodes serial buses on its own screen but does not expose the
decoded data over SCPI, so to show it in the web UI we decode here from the
captured analog samples (thresholded to logic levels).

UART is implemented; CAN/LIN/SPI/I2C are scaffolded and return a clear
"not yet implemented" note (they need clock recovery / multi-line handling).
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np


def _logic(volts: np.ndarray):
    """Threshold an analog trace to a boolean logic array (mid-level)."""
    hi, lo = float(np.max(volts)), float(np.min(volts))
    if hi - lo < 1e-6:
        return None, 0.0
    mid = (hi + lo) / 2.0
    return volts > mid, mid


def decode_uart(volts: np.ndarray, sample_rate: float, baud: int,
                data_bits: int = 8, parity: str = "none",
                stop_bits: int = 1, invert: bool = False) -> Dict:
    """Decode UART. Idle is logic-high; a start bit is the falling edge."""
    logic, _mid = _logic(volts)
    if logic is None or sample_rate <= 0 or baud <= 0:
        return {"protocol": "uart", "error": "no signal / bad parameters", "frames": []}
    if invert:
        logic = ~logic
    spb = sample_rate / baud
    if spb < 3:
        return {"protocol": "uart", "frames": [],
                "error": f"under-sampled ({spb:.1f} samples/bit; increase sample rate or lower baud)"}

    n = logic.size
    frames: List[Dict] = []
    i = 1
    while i < n - int(spb * (1 + data_bits + 2)):
        # Find a falling edge (idle high -> start bit low).
        if logic[i - 1] and not logic[i]:
            start = i
            center = lambda k: int(round(start + (k + 0.5) * spb))
            if center(0) >= n or logic[center(0)]:   # start bit must be low
                i += 1
                continue
            value = 0
            for b in range(data_bits):
                c = center(1 + b)
                if c >= n:
                    break
                if logic[c]:
                    value |= (1 << b)               # LSB first
            ok = True
            idx = 1 + data_bits
            if parity in ("odd", "even"):
                c = center(idx)
                idx += 1
                pbit = 1 if (c < n and logic[c]) else 0
                ones = bin(value).count("1") + pbit
                if parity == "even" and ones % 2 != 0:
                    ok = False
                if parity == "odd" and ones % 2 != 1:
                    ok = False
            stopc = center(idx)
            if stopc < n and not logic[stopc]:
                ok = False                          # stop bit should be high
            frames.append({"t": start / sample_rate, "value": value,
                           "hex": f"0x{value:02X}",
                           "char": chr(value) if 32 <= value < 127 else ".",
                           "ok": ok})
            i = start + int(spb * (1 + data_bits + idx))  # skip past this frame
        else:
            i += 1
    return {"protocol": "uart", "baud": baud, "samples_per_bit": round(spb, 1),
            "frames": frames}


def decode(protocol: str, volts: np.ndarray, sample_rate: float, **kw) -> Dict:
    p = protocol.lower()
    if p == "uart":
        return decode_uart(volts, sample_rate,
                           baud=int(kw.get("baud", 9600)),
                           data_bits=int(kw.get("data_bits", 8)),
                           parity=kw.get("parity", "none"),
                           invert=bool(kw.get("invert", False)))
    return {"protocol": p, "frames": [],
            "error": f"{p.upper()} host-side decode is not implemented yet "
                     "(the device's own decode is not exposed over SCPI)"}
