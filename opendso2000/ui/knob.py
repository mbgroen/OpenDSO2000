"""A painted rotary knob, like the physical front-panel encoders.

The knob is a relative encoder: turning it (drag in a circle, drag vertically,
or scroll the wheel) emits ``turned(+1)`` / ``turned(-1)`` detents.  Callers map
those detents to whatever they control (stepping volts/div, nudging position,
changing the trigger level, …).  A short click emits ``pressed`` — the physical
knobs are also push-buttons.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .style import ACCENT


class Knob(QWidget):
    turned = Signal(int)     # +1 clockwise detent, -1 counter-clockwise
    pressed = Signal()

    _PIX_PER_DETENT = 8      # vertical-drag sensitivity

    def __init__(self, diameter: int = 44, color: str = "#3a3f48"):
        super().__init__()
        self._d = diameter
        self._color = QColor(color)
        self._angle = -90.0          # indicator angle, degrees
        self._last_y = None
        self._accum = 0
        self._moved = False
        self.setFixedSize(diameter + 6, diameter + 6)
        self.setCursor(Qt.SizeVerCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._d + 6, self._d + 6)

    # -- input -----------------------------------------------------------

    def mousePressEvent(self, ev):
        self._last_y = ev.position().y()
        self._accum = 0
        self._moved = False

    def mouseMoveEvent(self, ev):
        if self._last_y is None:
            return
        dy = self._last_y - ev.position().y()      # up = clockwise/increase
        self._last_y = ev.position().y()
        self._accum += dy
        if abs(self._accum) >= self._PIX_PER_DETENT:
            steps = int(self._accum / self._PIX_PER_DETENT)
            self._accum -= steps * self._PIX_PER_DETENT
            self._emit(steps)
            self._moved = True

    def mouseReleaseEvent(self, ev):
        if not self._moved:
            self.pressed.emit()
        self._last_y = None

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if delta:
            self._emit(1 if delta > 0 else -1)

    def _emit(self, steps: int):
        self._angle += steps * 18.0
        self.update()
        for _ in range(abs(steps)):
            self.turned.emit(1 if steps > 0 else -1)

    # -- painting --------------------------------------------------------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = self._d / 2

        grad = QRadialGradient(cx, cy - r * 0.3, r * 1.4)
        grad.setColorAt(0.0, self._color.lighter(135))
        grad.setColorAt(1.0, self._color.darker(140))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#15181d"), 2))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Knurled rim ticks.
        p.setPen(QPen(QColor("#11141a"), 1))
        for i in range(24):
            a = math.radians(i * 15)
            p.drawLine(QPointF(cx + (r - 3) * math.cos(a), cy + (r - 3) * math.sin(a)),
                       QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))

        # Indicator notch.
        a = math.radians(self._angle)
        p.setPen(QPen(QColor(ACCENT), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx + r * 0.35 * math.cos(a), cy + r * 0.35 * math.sin(a)),
                   QPointF(cx + r * 0.82 * math.cos(a), cy + r * 0.82 * math.sin(a)))
        p.end()
