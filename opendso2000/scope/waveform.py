"""Decoding of the ``:WAVeform:DATA:ALL?`` transfer.

The DSO2000 streams a frame as a sequence of packets.  The *first* packet is a
fixed ASCII header (documented in the SCPI manual, section 7.1) describing the
frame: which channels are enabled, the sample rate, and the total payload size.
Subsequent packets each carry a small ``#9`` length header followed by raw
8-bit sample bytes, until ``total_length`` bytes have been received.

Samples are 8-bit ADC codes.  The screen spans 8 vertical divisions; the codes
are centred on 128.  The number of codes per division is not stated in the
manual, so it is exposed here as :data:`CODES_PER_DIV` and is the single value
to recalibrate once verified against real hardware.  Conversion to volts uses
the per-channel scale/offset/probe queried over normal SCPI, which is more
reliable than the scale fields embedded in the header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

#: ADC codes per vertical division (8-bit ADC, 8 divisions => ~25 codes/div).
#: Recalibrate against hardware if measured amplitudes are off by a constant.
CODES_PER_DIV = 25.0
ADC_CENTER = 128.0


@dataclass
class ChannelTrace:
    channel: int
    volts: np.ndarray            # vertical axis, volts
    scale: float                 # volts/div in effect
    offset: float                # volts


@dataclass
class Waveform:
    """One acquired frame across all enabled channels."""

    time: np.ndarray = field(default_factory=lambda: np.empty(0))
    channels: Dict[int, ChannelTrace] = field(default_factory=dict)
    sample_rate: float = 0.0
    triggered: bool = False
    running: bool = True
    points: int = 0


@dataclass
class FrameHeader:
    packet_length: int
    total_length: int
    uploaded_length: int
    running: bool
    triggered: bool
    enabled: List[int]            # 1-based channel numbers that are on
    sample_rate: float
    sample_multiple: int
    raw_offsets: List[int]
    raw_voltages: List[int]


def _digits(buf: bytes, start: int, count: int, default: int = 0) -> int:
    """Read ``count`` ASCII digits at ``start``; tolerate junk/padding."""
    chunk = buf[start:start + count]
    text = "".join(ch for ch in chunk.decode("ascii", "ignore") if ch.isdigit() or ch in "+-")
    try:
        return int(text)
    except ValueError:
        return default


def parse_header(buf: bytes) -> FrameHeader:
    """Parse the 128-byte ASCII frame header (first packet of a frame)."""
    if len(buf) < 30 or buf[0:2] != b"#9":
        raise ValueError("Not a DSO2000 waveform header (missing '#9' marker).")
    packet_length = _digits(buf, 2, 9)
    total_length = _digits(buf, 11, 9)
    uploaded_length = _digits(buf, 20, 9)
    running = _digits(buf, 29, 1) != 0
    triggered = _digits(buf, 30, 1) != 0
    raw_offsets = [_digits(buf, 31 + 4 * i, 4) for i in range(4)]
    raw_voltages = [_digits(buf, 47 + 7 * i, 7) for i in range(4)]
    enable_field = buf[75:79].decode("ascii", "ignore")
    enabled = [i + 1 for i, ch in enumerate(enable_field) if ch == "1"]
    sample_rate = float(_digits(buf, 79, 9))
    sample_multiple = _digits(buf, 88, 6, default=1) or 1
    return FrameHeader(
        packet_length=packet_length,
        total_length=total_length,
        uploaded_length=uploaded_length,
        running=running,
        triggered=triggered,
        enabled=enabled or [1],
        sample_rate=sample_rate,
        sample_multiple=sample_multiple,
        raw_offsets=raw_offsets,
        raw_voltages=raw_voltages,
    )


def codes_to_volts(codes: np.ndarray, scale: float, offset: float) -> np.ndarray:
    """Convert raw 8-bit ADC codes to volts for one channel."""
    divs = (codes.astype(np.float64) - ADC_CENTER) / CODES_PER_DIV
    return divs * scale - offset


@dataclass
class ChannelScaling:
    scale: float = 1.0
    offset: float = 0.0
    probe: float = 1.0


def build_waveform(
    header: FrameHeader,
    sample_bytes: bytes,
    scaling: Dict[int, ChannelScaling],
) -> Waveform:
    """Combine a parsed header and the concatenated sample bytes into volts.

    Sample bytes are laid out as one contiguous block per enabled channel, in
    ascending channel order (ch1 block, then ch2, ...).
    """
    enabled = header.enabled
    n = len(enabled)
    raw = np.frombuffer(sample_bytes, dtype=np.uint8)
    if n == 0 or raw.size == 0:
        return Waveform(sample_rate=header.sample_rate,
                        triggered=header.triggered, running=header.running)

    per_channel = raw.size // n
    raw = raw[: per_channel * n].reshape(n, per_channel)

    wf = Waveform(
        sample_rate=header.sample_rate,
        triggered=header.triggered,
        running=header.running,
        points=per_channel,
    )
    dt = 1.0 / header.sample_rate if header.sample_rate > 0 else 1.0
    wf.time = np.arange(per_channel, dtype=np.float64) * dt
    for idx, ch in enumerate(enabled):
        sc = scaling.get(ch, ChannelScaling())
        volts = codes_to_volts(raw[idx], sc.scale, sc.offset)
        wf.channels[ch] = ChannelTrace(channel=ch, volts=volts,
                                       scale=sc.scale, offset=sc.offset)
    return wf


class WaveformReader:
    """Drives the multi-packet ``:WAVeform:DATA:ALL?`` exchange."""

    def __init__(self, query_raw: Callable[[str], bytes]):
        self._query_raw = query_raw

    def read_frame(self, scaling: Dict[int, ChannelScaling],
                   max_packets: int = 4096) -> Optional[Waveform]:
        first = self._query_raw(":WAVeform:DATA:ALL?")
        if not first or first[0:2] != b"#9":
            return None
        header = parse_header(first)
        # The header packet itself may already carry trailing sample bytes.
        collected = bytearray(first[128:]) if len(first) > 128 else bytearray()

        guard = 0
        while len(collected) < header.total_length and guard < max_packets:
            guard += 1
            pkt = self._query_raw(":WAVeform:DATA:ALL?")
            if not pkt:
                break
            # Data packets start with '#9' + 3x9-digit lengths, payload at [29:].
            payload = pkt[29:] if pkt[0:2] == b"#9" and len(pkt) > 29 else pkt
            if not payload:
                break
            collected += payload

        return build_waveform(header, bytes(collected[: header.total_length]), scaling)
