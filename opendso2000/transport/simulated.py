"""A simulated DSO2000 that speaks the real SCPI dialect over a fake link.

This lets the whole application run, render, and be tested without hardware.
It keeps a small state model, answers queries from it, and synthesises a
``:WAVeform:DATA:ALL?`` frame in exactly the byte layout the real instrument
uses (see :mod:`opendso2000.scope.waveform`), so the acquisition and
decode pipeline is exercised end to end.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, Dict

import numpy as np

from ..scope.waveform import ADC_CENTER, CODES_PER_DIV
from .base import Transport


class SimulatedTransport(Transport):
    def __init__(self, model: str = "DSO2D15", points: int = 4000):
        self.description = f"Simulated {model}"
        self._model = model
        self._points = points
        self._t0 = time.time()
        self._out: Deque[bytes] = deque()
        # Frame streaming state for :WAVeform:DATA:ALL?
        self._frame: bytes = b""
        self._frame_pos = 0
        self._frame_active = False
        self._state: Dict[str, str] = self._default_state()

    # -- state -----------------------------------------------------------

    def _default_state(self) -> Dict[str, str]:
        st = {
            "*IDN?": f"OpenDSO2000-Sim,{self._model},SIM00000001,V1.0.0",
            ":CHANnel1:DISPlay": "1",
            ":CHANnel2:DISPlay": "1",
            ":CHANnel1:SCALe": "1.000e+00",
            ":CHANnel2:SCALe": "5.000e-01",
            ":CHANnel1:OFFSet": "0.000e+00",
            ":CHANnel2:OFFSet": "0.000e+00",
            ":CHANnel1:COUPling": "DC",
            ":CHANnel2:COUPling": "DC",
            ":CHANnel1:PROBe": "1.000e+00",
            ":CHANnel2:PROBe": "1.000e+00",
            ":CHANnel1:BWLimit": "0",
            ":CHANnel2:BWLimit": "0",
            ":CHANnel1:INVert": "0",
            ":CHANnel2:INVert": "0",
            ":TIMebase:SCALe": "1.000e-04",
            ":TIMebase:POSition": "0.000e+00",
            ":TIMebase:MODE": "MAIN",
            ":ACQuire:POINts": str(self._points),
            ":ACQuire:TYPE": "NORMal",
            ":ACQuire:SRATe": "1.000e+08",
            ":ACQuire:COUNt": "16",
            ":TRIGger:MODE": "EDGE",
            ":TRIGger:SWEep": "AUTO",
            ":TRIGger:STATus": "TRIGed",
            ":TRIGger:HOLDoff": "1.000e-07",
            ":TRIGger:EDGe:SOURce": "CHANnel1",
            ":TRIGger:EDGe:SLOPe": "RISIng",
            ":TRIGger:EDGe:LEVel": "0.000e+00",
            ":MATH:DISPlay": "0",
            ":MATH:OPERator": "ADD",
            ":DDS:SWITch": "OFF",
            ":DDS:TYPE": "SINE",
            ":DDS:FREQ": "1.00000e+03",
            ":DDS:AMP": "1.00000e+00",
            ":DDS:OFFSet": "0.0000e+00",
            ":DDS:DUTY": "50",
        }
        return st

    # -- transport interface --------------------------------------------

    def open(self) -> None:
        return None

    def close(self) -> None:
        self._out.clear()

    def write(self, data: bytes) -> None:
        text = data.decode("ascii", "ignore").strip()
        for cmd in text.split(";"):
            cmd = cmd.strip()
            if cmd:
                self._handle(cmd)

    def read(self, max_length: int = 1024 * 1024) -> bytes:
        if self._out:
            return self._out.popleft()
        return b""

    # -- command handling ------------------------------------------------

    def _handle(self, cmd: str) -> None:
        # A query may carry a trailing argument, e.g. ":MEAS:CHAN1:ITEM? VPP",
        # so detect '?' anywhere rather than only at the end.
        is_query = "?" in cmd
        head = cmd.split("?", 1)[0] if is_query else cmd
        query_arg = cmd.split("?", 1)[1].strip() if is_query else ""

        # Special: streamed waveform frame.
        if cmd == ":WAVeform:DATA:ALL?":
            self._out.append(self._next_waveform_packet())
            return

        if cmd == "*IDN?":
            self._out.append(self._state["*IDN?"].encode())
            return
        if cmd in ("*RST", "*CLS"):
            if cmd == "*RST":
                self._state = self._default_state()
            return
        if cmd == ":TRIGger:FORCe" or cmd == ":AUToscale" or cmd == ":AUTO":
            return
        if cmd in (":RUN", ":STOP", ":SINGle"):
            return

        if is_query:
            # Normalise: ":CHANnel1:SCALe?" -> key ":CHANnel1:SCALe"
            key = head
            val = self._state.get(key)
            if val is None:
                # Try measurement queries like :MEASure:CHANnel1:ITEM? VPP
                val = self._answer_measurement(head, query_arg)
            self._out.append((val if val is not None else "0").encode())
            return

        # Setter:  ":CHANnel1:SCALe 2V"  ->  key ":CHANnel1:SCALe", arg "2V"
        if " " in cmd:
            key, _, arg = cmd.partition(" ")
            self._state[key] = self._normalise_setter(key, arg.strip())

    def _normalise_setter(self, key: str, arg: str) -> str:
        a = arg.strip()
        # Numeric-with-suffix vertical settings -> store as float string.
        if key.endswith(("SCALe", "OFFSet", "LEVel", "POSition", "FREQ",
                          "AMP", "HOLDoff")):
            return self._to_float_str(a)
        if a.upper() in ("ON", "1"):
            return "1" if key.endswith(("DISPlay", "BWLimit", "INVert")) else "ON"
        if a.upper() in ("OFF", "0"):
            return "0" if key.endswith(("DISPlay", "BWLimit", "INVert")) else "OFF"
        return a

    @staticmethod
    def _to_float_str(a: str) -> str:
        s = a.upper().replace("V", "").replace("HZ", "").replace("S", "")
        mult = 1.0
        for suf, m in (("M", 1e-3), ("U", 1e-6), ("N", 1e-9), ("K", 1e3)):
            if s.endswith(suf):
                mult = m
                s = s[:-1]
                break
        try:
            return f"{float(s) * mult:.6e}"
        except ValueError:
            return a

    def _answer_measurement(self, head: str, item: str = "") -> str:
        # head like ":MEASure:CHANnel1:ITEM"; item like "VPP" or "FREQuency".
        if "ITEM" not in head:
            return "0"
        ch = 1
        for c in head:
            if c.isdigit():
                ch = int(c)
                break
        scale = float(self._state.get(f":CHANnel{ch}:SCALe", 1.0))
        tdiv = float(self._state.get(":TIMebase:SCALe", 1e-4))
        freq = 3.0 / (14 * tdiv) if tdiv > 0 else 1000.0
        period = 1.0 / freq
        amp_div = 2.5 if ch == 1 else 1.8
        vpp = 2 * amp_div * scale
        jit = 1.0 + 0.002 * math.sin(time.time())   # tiny liveliness
        it = item.upper()
        table = {
            "VPP": vpp, "VAMP": vpp, "VMAX": vpp / 2, "VTOP": vpp / 2,
            "VMIN": -vpp / 2, "VBAS": -vpp / 2, "VAVG": 0.0,
            "VRMS": vpp / 2 / 1.4142, "VUPP": vpp / 2 * 0.9, "VMID": 0.0,
            "VLOW": -vpp / 2 * 0.9, "OVER": 2.4, "PRES": 1.6,
            "PER": period, "FREQ": freq, "RTIM": period * 0.03,
            "FTIM": period * 0.03, "PWID": period * 0.5, "NWID": period * 0.5,
            "PDUT": 50.0, "NDUT": 50.0, "RDEL": 0.0, "FDEL": 0.0,
        }
        value = 0.0
        for key, v in table.items():
            if it.startswith(key):
                value = v
                break
        return f"{value * jit:.4e}"

    # -- synthetic waveform ---------------------------------------------

    def _enabled_channels(self):
        return [ch for ch in (1, 2)
                if self._state.get(f":CHANnel{ch}:DISPlay", "0") in ("1", "ON")]

    def _next_waveform_packet(self) -> bytes:
        if not self._frame_active:
            self._frame = self._render_frame()
            self._frame_pos = 0
            self._frame_active = True
            # First call returns the header packet only.
            header = self._frame[:128]
            return header
        # Subsequent calls return data packets ('#9' + 3x9 digit lengths + data).
        chunk = self._frame[128 + self._frame_pos:128 + self._frame_pos + 8192]
        self._frame_pos += len(chunk)
        if self._frame_pos >= len(self._frame) - 128:
            self._frame_active = False
        total = len(self._frame) - 128
        head = b"#9" + f"{len(chunk):09d}{total:09d}{self._frame_pos:09d}".encode()
        # pad header region to 29 bytes (data[29:] is payload)
        head = head + b"0" * (29 - len(head)) if len(head) < 29 else head[:29]
        return head + chunk

    def _render_frame(self) -> bytes:
        enabled = self._enabled_channels() or [1]
        points = int(float(self._state.get(":ACQuire:POINts", self._points)))
        points = max(100, min(points, 20000))  # keep the simulator light
        tdiv = float(self._state.get(":TIMebase:SCALe", 1e-4))
        # Generate samples spanning the full 14-division screen window.  Report
        # a sample rate consistent with that spacing so the time and FFT axes
        # are correct (on real hardware these are always consistent).
        total_time = 14 * tdiv
        srate = points / total_time if total_time > 0 else 1e8
        srate = min(srate, 999_999_999)            # keep within the 9-digit field
        t = np.linspace(0, total_time, points, endpoint=False)
        # Fixed test-signal frequency (independent of the time base), so changing
        # Time/div visibly changes how many cycles are shown — like a real input.
        freq = 2000.0

        blocks = []
        for ch in enabled:
            scale = float(self._state.get(f":CHANnel{ch}:SCALe", 1.0))
            offset = float(self._state.get(f":CHANnel{ch}:OFFSet", 0.0))
            phase = 0.0 if ch == 1 else math.pi / 2
            amp_div = 2.5 if ch == 1 else 1.8     # divisions of amplitude
            if ch == 2:  # make ch2 a square wave so the two look different
                sig = np.sign(np.sin(2 * math.pi * freq * t + phase))
            else:
                sig = np.sin(2 * math.pi * freq * t + phase)
            noise = np.random.normal(0, 0.03, points)
            codes = ADC_CENTER + (sig * amp_div + noise) * CODES_PER_DIV
            codes = np.clip(codes, 0, 255).astype(np.uint8)
            blocks.append(codes.tobytes())

        sample_bytes = b"".join(blocks)
        return self._make_header(enabled, srate, len(sample_bytes)) + sample_bytes

    def _make_header(self, enabled, srate: float, total_len: int) -> bytes:
        running = 1
        triggered = 1 if self._state.get(":TRIGger:STATus") == "TRIGed" else 0
        enable_field = "".join("1" if ch in enabled else "0" for ch in (1, 2, 3, 4))
        h = bytearray(b"0" * 128)

        def put(start: int, width: int, text: str) -> None:
            # Always write exactly ``width`` bytes so the header stays 128 long
            # even if a field (e.g. sample rate) would otherwise overflow.
            field = text.encode()[:width].rjust(width, b"0")
            h[start:start + width] = field

        h[0:2] = b"#9"
        put(2, 9, "128")               # this packet length
        put(11, 9, str(total_len))     # total data length
        put(20, 9, "0")                # uploaded length
        h[29:30] = str(running).encode()
        h[30:31] = str(triggered).encode()
        for i in range(4):
            put(31 + 4 * i, 4, "0")    # channel offsets
        for i in range(4):
            put(47 + 7 * i, 7, "0")    # channel voltages
        h[75:79] = enable_field.encode()
        put(79, 9, str(int(srate)))    # sample rate
        put(88, 6, "1")                # sample multiple
        return bytes(h)
