"""Host-side processing state for Math/FFT and cursors (no GUI dependency).

Both are driven by the soft-key menus and consumed by the acquisition frame
loop, so the logic lives here rather than inside a widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from .enums import FftWindow, MathOperator
from .waveform import Waveform

_WINDOWS = {
    FftWindow.RECTANGLE.value: lambda n: np.ones(n),
    FftWindow.HANNING.value: np.hanning,
    FftWindow.HAMMING.value: np.hamming,
    FftWindow.BLACKMAN.value: np.blackman,
}

MATH_SCALE_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)


@dataclass
class MathProcessor:
    """State + computation for the Math/FFT trace."""

    enabled: bool = False
    operator: str = MathOperator.ADD.value
    source1: int = 1
    source2: int = 2
    scale: float = 1.0
    window: str = FftWindow.HANNING.value
    unit: str = "DB"            # DB or VRMS

    def is_fft(self) -> bool:
        return self.operator == MathOperator.FFT.value

    def compute(self, wf: Waveform) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if not self.enabled or not wf.channels:
            return None
        return self._fft(wf) if self.is_fft() else self._arith(wf)

    def _ch(self, wf: Waveform, idx: int) -> Optional[np.ndarray]:
        t = wf.channels.get(idx)
        return t.volts if t else None

    def _arith(self, wf):
        a = self._ch(wf, self.source1)
        b = self._ch(wf, self.source2)
        if a is None or b is None:
            return None
        n = min(a.size, b.size)
        a, b = a[:n], b[:n]
        op = self.operator
        if op == MathOperator.ADD.value:
            r = a + b
        elif op == MathOperator.SUBTRACT.value:
            r = a - b
        elif op == MathOperator.MULTIPLY.value:
            r = a * b
        else:
            r = a / np.where(np.abs(b) < 1e-9, np.nan, b)
        y = np.clip(r / (self.scale or 1.0), -4, 4)
        return np.linspace(-7, 7, n), y

    def _fft(self, wf):
        v = self._ch(wf, self.source1)
        if v is None or v.size < 8 or wf.sample_rate <= 0:
            return None
        n = v.size
        win = _WINDOWS.get(self.window, np.hanning)(n)
        cg = win.mean() or 1.0
        mag = np.abs(np.fft.rfft((v - v.mean()) * win)) * 2.0 / (n * cg)
        if self.unit == "VRMS":
            mag = mag / np.sqrt(2.0)
            peak = mag.max() or 1.0
            y = -4.0 + (mag / peak) * 8.0
        else:
            ref = mag.max() or 1e-12
            db = 20.0 * np.log10(np.maximum(mag, 1e-12) / ref)
            y = np.clip(4.0 + db / 10.0, -4, 4)
        return np.linspace(-7, 7, mag.size), y


@dataclass
class CursorState:
    """State for measurement cursors (drawn/measured on screen)."""

    mode: str = "OFF"          # OFF | MANual | TRACk
    ctype: str = "X"           # X | Y | XY
    source: int = 1

    def x_visible(self) -> bool:
        return self.mode != "OFF" and (self.ctype in ("X", "XY") or self.mode == "TRACk")

    def y_visible(self) -> bool:
        return self.mode != "OFF" and self.ctype in ("Y", "XY")
