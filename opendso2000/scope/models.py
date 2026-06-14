"""Definitions of the supported Hantek DSO2000-series instruments.

All four models share the same SCPI command set and the same USB identity.
The only functional difference relevant to this application is that the *D*
variants (DSO2D10 / DSO2D15) carry a built-in 1-channel arbitrary waveform
generator (the SCPI ``DDS`` subsystem), while the *C* variants do not.

The bandwidth differs (100 MHz vs 150 MHz) but does not change how the
software talks to the device; it is recorded here only for display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# The DSO2000-series benchtop scopes do not enumerate with a Hantek vendor id.
# They borrow a Compaq id and present a USB-TMC interface.  This was confirmed
# by the OpenHantek maintainer and by community reverse-engineering.
DSO2000_VID = 0x049F
DSO2000_PID = 0x505E


@dataclass(frozen=True)
class ModelSpec:
    """Static description of one instrument model."""

    name: str
    bandwidth_mhz: int
    channels: int = 2
    has_awg: bool = False
    max_sample_rate: float = 1e9          # 1 GSa/s real-time
    max_memory_depth: int = 8_000_000     # 8 M points
    # Vertical scales selectable in the 1-2-5 sequence (probe = 1x), volts/div.
    volt_div_steps: Tuple[float, ...] = (
        500e-6, 1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3,
        100e-3, 200e-3, 500e-3, 1.0, 2.0, 5.0, 10.0,
    )
    # Time/div steps, seconds/div.
    time_div_steps: Tuple[float, ...] = (
        2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9,
        1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6,
        1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3,
        1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0,
    )
    memory_depths: Tuple[int, ...] = (4_000, 40_000, 400_000, 4_000_000, 8_000_000)
    awg_max_freq: float = 5e6             # 5 MHz AWG on the D models


# Keyed by the upper-cased base model name as it appears in *IDN?.
MODELS: Dict[str, ModelSpec] = {
    "DSO2C10": ModelSpec("DSO2C10", bandwidth_mhz=100, has_awg=False),
    "DSO2C15": ModelSpec("DSO2C15", bandwidth_mhz=150, has_awg=False),
    "DSO2D10": ModelSpec("DSO2D10", bandwidth_mhz=100, has_awg=True),
    "DSO2D15": ModelSpec("DSO2D15", bandwidth_mhz=150, has_awg=True),
}

# A generic fall-back so the application still runs against an unknown but
# protocol-compatible DSO2000 unit (assume AWG present so nothing is hidden).
GENERIC = ModelSpec("DSO2000", bandwidth_mhz=150, has_awg=True)


def identify(idn: str) -> ModelSpec:
    """Map an ``*IDN?`` response to a :class:`ModelSpec`.

    The response is typically ``Hantek,DSO2D15,<serial>,<fw>`` but vendors are
    inconsistent, so we just look for any known model token anywhere in it.
    """
    text = (idn or "").upper()
    for key, spec in MODELS.items():
        if key in text:
            return spec
    return GENERIC
