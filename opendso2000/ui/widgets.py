"""Small reusable Qt widgets used across the control panels."""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)


def eng_format(value: float, unit: str = "") -> str:
    """Format a number with an engineering SI prefix, e.g. 1.2 kHz."""
    if value == 0:
        return f"0 {unit}".strip()
    prefixes = [
        (1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
        (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p"),
    ]
    av = abs(value)
    for factor, prefix in prefixes:
        if av >= factor:
            return f"{value / factor:g} {prefix}{unit}".strip()
    return f"{value:g} {unit}".strip()


class StepControl(QWidget):
    """A label with -/+ buttons that step through a fixed list of values."""

    valueChanged = Signal(float)

    def __init__(self, title: str, steps: Sequence[float], unit: str,
                 index: int = 0):
        super().__init__()
        self._steps: List[float] = list(steps)
        self._index = max(0, min(index, len(self._steps) - 1))
        self._unit = unit

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(QLabel(title))

        row = QHBoxLayout()
        row.setSpacing(4)
        self._minus = QPushButton("−")
        self._plus = QPushButton("+")
        for b in (self._minus, self._plus):
            b.setFixedWidth(30)
        self._value = QLabel()
        self._value.setObjectName("valueLabel")
        self._value.setAlignment(Qt.AlignCenter)
        row.addWidget(self._minus)
        row.addWidget(self._value, 1)
        row.addWidget(self._plus)
        root.addLayout(row)

        self._minus.clicked.connect(lambda: self._step(-1))
        self._plus.clicked.connect(lambda: self._step(+1))
        self._refresh()

    def value(self) -> float:
        return self._steps[self._index]

    def set_value(self, value: float) -> None:
        # Snap to the nearest available step.
        self._index = min(range(len(self._steps)),
                          key=lambda i: abs(self._steps[i] - value))
        self._refresh()

    def _step(self, direction: int) -> None:
        new = self._index + direction
        if 0 <= new < len(self._steps):
            self._index = new
            self._refresh()
            self.valueChanged.emit(self.value())

    def _refresh(self) -> None:
        self._value.setText(eng_format(self.value(), self._unit))
        self._minus.setEnabled(self._index > 0)
        self._plus.setEnabled(self._index < len(self._steps) - 1)


class LabeledCombo(QWidget):
    valueChanged = Signal(str)

    def __init__(self, title: str, options: Sequence[Tuple[str, str]]):
        """``options`` is a list of (label, value) pairs."""
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addWidget(QLabel(title))
        self._combo = QComboBox()
        for label, value in options:
            self._combo.addItem(label, value)
        self._combo.currentIndexChanged.connect(
            lambda _: self.valueChanged.emit(self._combo.currentData())
        )
        root.addWidget(self._combo)

    def value(self) -> str:
        return self._combo.currentData()

    def set_value(self, value: str) -> None:
        idx = self._combo.findData(value)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
