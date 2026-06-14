"""High-level SCPI driver for the Hantek DSO2000 series.

Every public method maps to one or a few SCPI commands from the DSO2000
Programmers Manual.  The driver holds a :class:`Transport` and a detected
:class:`ModelSpec`; it has no GUI dependencies so it can also be scripted.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from ..transport.base import Transport, TransportError
from . import models
from .enums import (
    AcquireType, Coupling, DdsModType, DdsType, EdgeSlope, FftWindow,
    MathOperator, TimebaseMode, TriggerMode, TriggerStatus, TriggerSweep,
)
from .models import ModelSpec
from .waveform import ChannelScaling, Waveform, WaveformReader


def _b(value: bool) -> str:
    return "ON" if value else "OFF"


def _f(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


class Dso2000:
    """Thread-safe SCPI wrapper around a single instrument."""

    def __init__(self, transport: Transport):
        self._t = transport
        self._lock = threading.RLock()
        self.spec: ModelSpec = models.GENERIC
        self.idn: str = ""
        self._reader = WaveformReader(self._query_raw_locked)

    # -- connection ------------------------------------------------------

    def connect(self) -> ModelSpec:
        self._t.open()
        self.idn = self.query("*IDN?")
        self.spec = models.identify(self.idn)
        return self.spec

    def disconnect(self) -> None:
        try:
            self._t.close()
        except Exception:
            pass

    @property
    def has_awg(self) -> bool:
        return self.spec.has_awg

    # -- low-level -------------------------------------------------------

    def write(self, cmd: str) -> None:
        with self._lock:
            self._t.write_str(cmd)

    def query(self, cmd: str) -> str:
        with self._lock:
            return self._t.query(cmd)

    def _query_raw_locked(self, cmd: str) -> bytes:
        # Called by WaveformReader; the public read_waveform already holds lock.
        return self._t.query_raw(cmd)

    # === IEEE 488.2 common =============================================

    def reset(self) -> None:
        self.write("*RST")

    def clear(self) -> None:
        self.write("*CLS")

    # === Run control ====================================================

    def run(self) -> None:
        self.write(":RUN")

    def stop(self) -> None:
        self.write(":STOP")

    def single(self) -> None:
        self.write(":SINGle")

    def autoset(self) -> None:
        # Hantek units accept :AUToscale; some firmwares use :AUTO.
        self.write(":AUToscale")

    def force_trigger(self) -> None:
        self.write(":TRIGger:FORCe")

    # === CHANnel<n> =====================================================

    def set_channel_enabled(self, ch: int, on: bool) -> None:
        self.write(f":CHANnel{ch}:DISPlay {_b(on)}")

    def get_channel_enabled(self, ch: int) -> bool:
        return self.query(f":CHANnel{ch}:DISPlay?").strip() in ("1", "ON")

    def set_scale(self, ch: int, volts_per_div: float) -> None:
        self.write(f":CHANnel{ch}:SCALe {volts_per_div:g}V")

    def get_scale(self, ch: int) -> float:
        return _f(self.query(f":CHANnel{ch}:SCALe?"), 1.0)

    def set_offset(self, ch: int, volts: float) -> None:
        self.write(f":CHANnel{ch}:OFFSet {volts:g}V")

    def get_offset(self, ch: int) -> float:
        return _f(self.query(f":CHANnel{ch}:OFFSet?"), 0.0)

    def set_coupling(self, ch: int, coupling: Coupling) -> None:
        self.write(f":CHANnel{ch}:COUPling {coupling.value}")

    def get_coupling(self, ch: int) -> str:
        return self.query(f":CHANnel{ch}:COUPling?")

    def set_probe(self, ch: int, ratio: int) -> None:
        self.write(f":CHANnel{ch}:PROBe {ratio}")

    def get_probe(self, ch: int) -> float:
        return _f(self.query(f":CHANnel{ch}:PROBe?"), 1.0)

    def set_bandwidth_limit(self, ch: int, on: bool) -> None:
        self.write(f":CHANnel{ch}:BWLimit {_b(on)}")

    def set_invert(self, ch: int, on: bool) -> None:
        self.write(f":CHANnel{ch}:INVert {_b(on)}")

    # === TIMebase =======================================================

    def set_timebase_scale(self, seconds_per_div: float) -> None:
        self.write(f":TIMebase:SCALe {seconds_per_div:g}")

    def get_timebase_scale(self) -> float:
        return _f(self.query(":TIMebase:SCALe?"), 1e-4)

    def set_timebase_position(self, seconds: float) -> None:
        self.write(f":TIMebase:POSition {seconds:g}")

    def get_timebase_position(self) -> float:
        return _f(self.query(":TIMebase:POSition?"), 0.0)

    def set_timebase_mode(self, mode: TimebaseMode) -> None:
        self.write(f":TIMebase:MODE {mode.value}")

    def get_timebase_mode(self) -> str:
        return self.query(":TIMebase:MODE?")

    # === ACQuire ========================================================

    def set_memory_depth(self, points: int) -> None:
        self.write(f":ACQuire:POINts {points}")

    def get_memory_depth(self) -> int:
        try:
            return int(float(self.query(":ACQuire:POINts?")))
        except ValueError:
            return 4000

    def set_acquire_type(self, atype: AcquireType) -> None:
        self.write(f":ACQuire:TYPE {atype.value}")

    def get_acquire_type(self) -> str:
        return self.query(":ACQuire:TYPE?")

    def set_average_count(self, count: int) -> None:
        self.write(f":ACQuire:COUNt {count}")

    def get_sample_rate(self) -> float:
        return _f(self.query(":ACQuire:SRATe?"), 0.0)

    # === TRIGger ========================================================

    def set_trigger_mode(self, mode: TriggerMode) -> None:
        self.write(f":TRIGger:MODE {mode.value}")

    def get_trigger_mode(self) -> str:
        return self.query(":TRIGger:MODE?")

    def set_trigger_sweep(self, sweep: TriggerSweep) -> None:
        self.write(f":TRIGger:SWEep {sweep.value}")

    def get_trigger_sweep(self) -> str:
        return self.query(":TRIGger:SWEep?")

    def get_trigger_status(self) -> str:
        return self.query(":TRIGger:STATus?")

    def set_trigger_holdoff(self, seconds: float) -> None:
        self.write(f":TRIGger:HOLDoff {seconds:g}")

    def set_edge_source(self, source: str) -> None:
        self.write(f":TRIGger:EDGe:SOURce {source}")

    def get_edge_source(self) -> str:
        return self.query(":TRIGger:EDGe:SOURce?")

    def set_edge_slope(self, slope: EdgeSlope) -> None:
        self.write(f":TRIGger:EDGe:SLOPe {slope.value}")

    def get_edge_slope(self) -> str:
        return self.query(":TRIGger:EDGe:SLOPe?")

    def set_edge_level(self, volts: float) -> None:
        self.write(f":TRIGger:EDGe:LEVel {volts:g}")

    def get_edge_level(self) -> float:
        return _f(self.query(":TRIGger:EDGe:LEVel?"), 0.0)

    # Generic accessors for every other trigger sub-type. ``path`` is the part
    # after ":TRIGger:", e.g. "PULSe:WIDth" or "UART:BAUd".  This keeps the
    # driver complete without one method per parameter.
    def set_trigger_param(self, path: str, value) -> None:
        self.write(f":TRIGger:{path} {value}")

    def get_trigger_param(self, path: str) -> str:
        return self.query(f":TRIGger:{path}?")

    def get_trigger_param_float(self, path: str, default: float = 0.0) -> float:
        return _f(self.get_trigger_param(path), default)

    # === MATH ===========================================================

    def set_math_enabled(self, on: bool) -> None:
        self.write(f":MATH:DISPlay {_b(on)}")

    def set_math_operator(self, op: MathOperator) -> None:
        self.write(f":MATH:OPERator {op.value}")

    def set_math_sources(self, src1: str, src2: str) -> None:
        self.write(f":MATH:SOURce1 {src1}")
        self.write(f":MATH:SOURce2 {src2}")

    def set_fft_source(self, src: str) -> None:
        self.write(f":MATH:FFT:SOURce {src}")

    def set_fft_window(self, window: FftWindow) -> None:
        self.write(f":MATH:FFT:WINDow {window.value}")

    # === MEASure ========================================================

    def measure(self, ch: int, item: str) -> float:
        """Return a single measurement value (volts/seconds/etc.).

        The reply looks like ``VPP 3.600e-01``; we take the trailing number.
        """
        reply = self.query(f":MEASure:CHANnel{ch}:ITEM? {item}")
        token = reply.replace(",", " ").split()
        for part in reversed(token):
            try:
                return float(part)
            except ValueError:
                continue
        return float("nan")

    def set_measure_all(self, ch: int, on: bool) -> None:
        self.write(f":MEASure:ADISplay {_b(on)}")

    # === DISPlay ========================================================

    def set_display_type(self, vector: bool) -> None:
        self.write(f":DISPlay:TYPE {'VECTors' if vector else 'DOTS'}")

    # === DDS / AWG (D-models only) ======================================

    def _require_awg(self) -> None:
        if not self.has_awg:
            raise TransportError(f"{self.spec.name} has no built-in signal generator.")

    def set_awg_enabled(self, on: bool) -> None:
        self._require_awg()
        self.write(f":DDS:SWITch {_b(on)}")

    def get_awg_enabled(self) -> bool:
        return self.query(":DDS:SWITch?").strip().upper() in ("1", "ON")

    def set_awg_type(self, wtype: DdsType) -> None:
        self._require_awg()
        self.write(f":DDS:TYPE {wtype.value}")

    def set_awg_frequency(self, hz: float) -> None:
        self._require_awg()
        self.write(f":DDS:FREQ {hz:g}")

    def set_awg_amplitude(self, volts: float) -> None:
        self._require_awg()
        self.write(f":DDS:AMP {volts:g}")

    def set_awg_offset(self, volts: float) -> None:
        self._require_awg()
        self.write(f":DDS:OFFSet {volts:g}")

    def set_awg_duty(self, percent: float) -> None:
        self._require_awg()
        self.write(f":DDS:DUTY {int(percent)}")

    def set_awg_modulation(self, on: bool, mtype: DdsModType = DdsModType.AM) -> None:
        self._require_awg()
        self.write(f":DDS:WAVE:MODE {_b(on)}")
        if on:
            self.write(f":DDS:MODE:TYPE {mtype.value}")

    def upload_arbitrary(self, samples) -> None:
        """Upload a 4096-point arbitrary waveform (values 0..65535)."""
        self._require_awg()
        import numpy as np
        data = np.asarray(samples, dtype="<u2")
        if data.size != 4096:
            raise ValueError("Arbitrary waveform must be exactly 4096 points.")
        raw = data.tobytes()
        block = b"#5" + f"{len(raw):05d}".encode() + raw
        with self._lock:
            self._t.write(b":DDS:ARB:DAC16:BIN " + block)

    # === System =========================================================

    def screenshot_setup(self) -> str:
        return self.query(":SETUp:ALL?")

    # === Waveform acquisition ==========================================

    def channel_scaling(self) -> Dict[int, ChannelScaling]:
        scaling: Dict[int, ChannelScaling] = {}
        for ch in range(1, self.spec.channels + 1):
            if self.get_channel_enabled(ch):
                scaling[ch] = ChannelScaling(
                    scale=self.get_scale(ch),
                    offset=self.get_offset(ch),
                    probe=self.get_probe(ch),
                )
        return scaling

    def read_waveform(self, scaling: Optional[Dict[int, ChannelScaling]] = None) -> Optional[Waveform]:
        if scaling is None:
            scaling = self.channel_scaling()
        with self._lock:
            return self._reader.read_frame(scaling)
