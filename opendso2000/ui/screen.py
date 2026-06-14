"""The 'screen': the waveform plot plus the device-style status bars.

Top bar  : logo · trigger status · main timebase · sample rate · storage depth.
Bottom bar: per-channel coupling + volts/div · AWG info · cursor readout.
This reproduces the on-screen information layout of the real instrument.
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from .scopeview import ScopeView
from .style import ACCENT, CH_COLORS, MATH_COLOR, SCREEN_BG, TEXT, TEXT_DIM
from .widgets import eng_format

# (scpi item, label, unit) for the on-screen measurement table — the set the
# real instrument shows when you press Measure.
MEAS_ITEMS = [
    ("VPP", "Vpp", "V"), ("VMAX", "Vmax", "V"), ("VMIN", "Vmin", "V"),
    ("VAMP", "Vamp", "V"), ("VTOP", "Vtop", "V"), ("VBASe", "Vbase", "V"),
    ("VAVG", "Vavg", "V"), ("VRMS", "Vrms", "V"),
    ("OVERshoot", "Overshoot", "%"), ("PREShoot", "Preshoot", "%"),
    ("PERiod", "Period", "s"), ("FREQuency", "Freq", "Hz"),
    ("RTIMe", "Rise", "s"), ("FTIMe", "Fall", "s"),
    ("PWIDth", "+Width", "s"), ("NWIDth", "-Width", "s"),
    ("PDUTy", "+Duty", "%"), ("NDUTy", "-Duty", "%"),
]


def _chip(text: str, color: str = TEXT, bg: str = "#1a2029") -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{color}; background:{bg}; border-radius:3px; padding:2px 6px;"
        f" font-family:'SF Mono','Menlo','Consolas',monospace; font-size:11px;")
    return lab


class MeasureTable(QFrame):
    """Translucent overlay listing every measurement per channel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("measTable")
        self.setStyleSheet(
            "#measTable { background: rgba(6,11,16,0.90); border:1px solid #3a4658;"
            " border-radius:6px; }"
            " QLabel { font-family:'SF Mono','Menlo','Consolas',monospace; font-size:11px; }")
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 7, 10, 7)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        # Reserve room so the longest label ("Overshoot") and values never clip.
        grid.setColumnMinimumWidth(0, 84)
        grid.setColumnMinimumWidth(1, 62)
        grid.setColumnMinimumWidth(2, 62)

        hdr = QLabel("Measure")
        hdr.setStyleSheet(f"color:{TEXT}; font-weight:700;")
        grid.addWidget(hdr, 0, 0)
        for col, ch in enumerate((1, 2), start=1):
            lab = QLabel(f"CH{ch}")
            lab.setStyleSheet(f"color:{CH_COLORS[ch]}; font-weight:700;")
            lab.setAlignment(Qt.AlignRight)
            grid.addWidget(lab, 0, col)
        self._cells: Dict[tuple, QLabel] = {}
        for row, (key, label, _u) in enumerate(MEAS_ITEMS, start=1):
            name = QLabel(label)
            # High-contrast, slightly bold labels for readability on the trace.
            name.setStyleSheet(f"color:{TEXT}; font-weight:600;")
            grid.addWidget(name, row, 0)
            for col, ch in enumerate((1, 2), start=1):
                cell = QLabel("—")
                cell.setStyleSheet(f"color:{CH_COLORS[ch]}; font-weight:600;")
                cell.setAlignment(Qt.AlignRight)
                self._cells[(ch, key)] = cell
                grid.addWidget(cell, row, col)
        self.adjustSize()

    def set_value(self, ch: int, key: str, text: str):
        cell = self._cells.get((ch, key))
        if cell:
            cell.setText(text)


class ScreenPanel(QWidget):
    def __init__(self, view: ScopeView):
        super().__init__()
        self._view = view
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top())
        root.addWidget(view, 1)
        root.addWidget(self._build_measurements())
        root.addWidget(self._build_bottom())

        # Floating measurement table (shown when Measure is pressed).
        self._table = MeasureTable(self)
        self._table.hide()

    # -- measurement table overlay --------------------------------------

    def show_table(self, on: bool):
        self._table.setVisible(on)
        if on:
            self._position_table()
            self._table.raise_()

    def table_visible(self) -> bool:
        return self._table.isVisible()

    def set_table_value(self, ch: int, key: str, text: str):
        self._table.set_value(ch, key, text)

    def _position_table(self):
        geo = self._view.geometry()
        self._table.adjustSize()
        self._table.move(geo.x() + 10, geo.y() + 10)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._table.isVisible():
            self._position_table()

    def _build_top(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"background:{SCREEN_BG};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        logo = QLabel("OpenDSO2000")
        logo.setStyleSheet(f"color:{ACCENT}; font-weight:800; font-style:italic; font-size:15px;")
        self._trig = _chip("AUTO", "#0a0f14", "#27a34a")
        self._tb = _chip("H —")
        self._srate = _chip("—")
        self._depth = _chip("—")
        self._ttime = _chip("D 0.00s")
        lay.addWidget(logo)
        lay.addWidget(self._trig)
        lay.addStretch(1)
        lay.addWidget(self._tb)
        lay.addWidget(self._srate)
        lay.addWidget(self._depth)
        lay.addWidget(self._ttime)
        return bar

    def _build_bottom(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"background:{SCREEN_BG};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        self._ch_info: Dict[int, QLabel] = {}
        for ch in (1, 2):
            lab = _chip(f"CH{ch}", "#0a0f14", CH_COLORS[ch])
            self._ch_info[ch] = lab
            lay.addWidget(lab)
        self._math_info = _chip("Math off", "#0a0f14", MATH_COLOR)
        lay.addWidget(self._math_info)
        lay.addStretch(1)
        self._cursor = QLabel("")
        self._cursor.setStyleSheet(f"color:{TEXT}; font-family:monospace; font-size:11px;")
        lay.addWidget(self._cursor)
        self._awg = _chip("", TEXT_DIM)
        lay.addWidget(self._awg)
        return bar

    def _build_measurements(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"background:{SCREEN_BG};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(16)
        self._meas: Dict[int, QLabel] = {}
        for ch in (1, 2):
            lab = QLabel(f"CH{ch}  —")
            lab.setStyleSheet(
                f"color:{CH_COLORS[ch]}; font-family:'SF Mono','Menlo',monospace;"
                f" font-size:11px;")
            self._meas[ch] = lab
            lay.addWidget(lab)
        lay.addStretch(1)
        return bar

    def set_measurements(self, ch: int, text: str):
        if ch in self._meas:
            self._meas[ch].setText(text)

    # -- update API ------------------------------------------------------

    def set_trigger_status(self, text: str):
        ok = text.lower().startswith("trig")
        self._trig.setText("TD" if ok else text.upper()[:5])
        self._trig.setStyleSheet(
            f"color:#0a0f14; background:{'#27a34a' if ok else '#caa000'};"
            f" border-radius:3px; padding:2px 6px; font-family:monospace; font-size:11px;")

    def set_horizontal(self, timebase: float, srate: float, depth: int, ttime: float = 0.0):
        self._tb.setText("H " + eng_format(timebase, "s"))
        if srate:
            self._srate.setText(eng_format(srate, "Sa/s"))
        self._depth.setText(eng_format(depth, "pts"))
        self._ttime.setText("D " + eng_format(ttime, "s"))

    def set_channel_info(self, ch: int, coupling: str, volts_div: float, enabled: bool):
        if ch in self._ch_info:
            txt = f"CH{ch} {coupling} {eng_format(volts_div, 'V')}"
            self._ch_info[ch].setText(txt if enabled else f"CH{ch} off")

    def set_math_info(self, text: str):
        self._math_info.setText(text)

    def set_cursor_text(self, text: str):
        self._cursor.setText(text)

    def set_awg_info(self, text: str):
        self._awg.setText(text)
