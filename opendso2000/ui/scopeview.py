"""The central oscilloscope screen, rendered with pyqtgraph.

Waveforms are drawn in *division* coordinates exactly like the real screen:
14 horizontal divisions (x: -7..+7) and 8 vertical divisions (y: -4..+4).
Volts are mapped to divisions through each channel's volts/div and vertical
position, so traces sit where the front-panel knobs would put them.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPen

from ..scope.waveform import Waveform
from .style import (CH_COLORS, GRID_AXIS_COLOR, GRID_COLOR, SCREEN_BG,
                    TRIGGER_COLOR)

H_DIV = 14
V_DIV = 8


class ScopeView(pg.GraphicsLayoutWidget):
    triggerLevelDragged = Signal(float)   # new level in divisions
    cursorsMoved = Signal()               # any measurement cursor was dragged

    def __init__(self):
        super().__init__()
        self.setBackground(SCREEN_BG)
        self.setMinimumSize(360, 260)   # allow the window to shrink on small displays
        self._plot = self.addPlot()
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setXRange(-H_DIV / 2, H_DIV / 2, padding=0)
        self._plot.setYRange(-V_DIV / 2, V_DIV / 2, padding=0)
        self._plot.getAxis("bottom").hide()
        self._plot.getAxis("left").hide()
        self._plot.setClipToView(True)

        self._draw_grid()

        self._curves: Dict[int, pg.PlotDataItem] = {}
        for ch, color in CH_COLORS.items():
            pen = pg.mkPen(QColor(color), width=1.4)
            self._curves[ch] = self._plot.plot([], [], pen=pen)
        self._math_curve = self._plot.plot([], [], pen=pg.mkPen("#c060f0", width=1.2))

        # Trigger level indicator (horizontal line, draggable).
        self._trig_line = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(QColor(TRIGGER_COLOR), width=1, style=Qt.DashLine),
        )
        self._trig_line.setValue(0)
        self._plot.addItem(self._trig_line)
        self._trig_line.sigPositionChangeFinished.connect(
            lambda: self.triggerLevelDragged.emit(self._trig_line.value())
        )

        # Measurement cursors: two vertical (X: A,B) and two horizontal (Y: A,B).
        cur_pen = pg.mkPen(QColor("#d8dee9"), width=1, style=Qt.DashLine)
        self._cur_x = [pg.InfiniteLine(pos=p, angle=90, movable=True, pen=cur_pen,
                                       label="", labelOpts={"position": 0.04})
                       for p in (-3.0, 3.0)]
        self._cur_y = [pg.InfiniteLine(pos=p, angle=0, movable=True, pen=cur_pen)
                       for p in (1.5, -1.5)]
        for line in self._cur_x + self._cur_y:
            line.setVisible(False)
            self._plot.addItem(line)
            line.sigPositionChanged.connect(lambda: self.cursorsMoved.emit())

        # Per-channel vertical position (divisions) and volts/div.
        self.positions: Dict[int, float] = {1: 0.0, 2: 0.0}
        self.scales: Dict[int, float] = {1: 1.0, 2: 1.0}
        self.timebase: float = 1e-4
        self.visible: Dict[int, bool] = {1: True, 2: True}

    # -- grid ------------------------------------------------------------

    def _draw_grid(self) -> None:
        grid_pen = pg.mkPen(QColor(GRID_COLOR), width=1)
        axis_pen = pg.mkPen(QColor(GRID_AXIS_COLOR), width=1)
        for i in range(-H_DIV // 2, H_DIV // 2 + 1):
            self._plot.addItem(pg.InfiniteLine(pos=i, angle=90, pen=grid_pen))
        for i in range(-V_DIV // 2, V_DIV // 2 + 1):
            self._plot.addItem(pg.InfiniteLine(pos=i, angle=0, pen=grid_pen))
        # Centre cross emphasised, plus minor tick marks on the axes.
        self._plot.addItem(pg.InfiniteLine(pos=0, angle=90, pen=axis_pen))
        self._plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=axis_pen))

    # -- public API ------------------------------------------------------

    def set_channel_visible(self, ch: int, visible: bool) -> None:
        self.visible[ch] = visible
        if ch in self._curves and not visible:
            self._curves[ch].setData([], [])

    def set_trigger_level_div(self, divisions: float) -> None:
        self._trig_line.blockSignals(True)
        self._trig_line.setValue(divisions)
        self._trig_line.blockSignals(False)

    def update_frame(self, wf: Waveform) -> None:
        n = wf.points or (len(wf.time) if wf.time is not None else 0)
        if n <= 0:
            return
        # x in divisions: total span = 14 divisions across the record window.
        x = np.linspace(-H_DIV / 2, H_DIV / 2, n)
        for ch, trace in wf.channels.items():
            if ch not in self._curves or not self.visible.get(ch, True):
                continue
            scale = self.scales.get(ch, trace.scale or 1.0) or 1.0
            y = trace.volts / scale + self.positions.get(ch, 0.0)
            self._curves[ch].setData(x, y)
        # Clear curves for channels not present in this frame.
        for ch, curve in self._curves.items():
            if ch not in wf.channels:
                curve.setData([], [])

    def show_math(self, x_div: Optional[np.ndarray], y_div: Optional[np.ndarray]) -> None:
        if x_div is None or y_div is None:
            self._math_curve.setData([], [])
        else:
            self._math_curve.setData(x_div, y_div)

    # -- cursors ---------------------------------------------------------

    def set_cursor_visibility(self, x_on: bool, y_on: bool) -> None:
        for line in self._cur_x:
            line.setVisible(x_on)
        for line in self._cur_y:
            line.setVisible(y_on)

    def cursor_x_divs(self):
        """Return (A, B) vertical-cursor positions in horizontal divisions."""
        return self._cur_x[0].value(), self._cur_x[1].value()

    def cursor_y_divs(self):
        """Return (A, B) horizontal-cursor positions in vertical divisions."""
        return self._cur_y[0].value(), self._cur_y[1].value()
