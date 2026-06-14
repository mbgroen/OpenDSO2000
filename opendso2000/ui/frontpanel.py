"""The skeuomorphic front panel: hardware buttons and rotary knobs.

Operation matches the instrument: section buttons (CH1/CH2/MATH MENU, HORIZ
MENU, TRIG MENU, the top function row) open soft-key menus on the screen edge,
while the knobs directly adjust the continuous/stepped values (volts/div,
position, time/div, trigger level).
"""

from __future__ import annotations

from typing import Callable, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..scope.driver import Dso2000
from .knob import Knob
from .style import ACCENT, CH_COLORS, TEXT_DIM, TRIGGER_COLOR
from .widgets import eng_format


def _section(title: str) -> QGroupBox:
    box = QGroupBox(title)
    return box


def _knob_with_label(title: str) -> tuple:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    k = Knob()
    lab = QLabel(title)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(f"color:{TEXT_DIM}; font-size:9px;")
    lay.addWidget(k, 0, Qt.AlignHCenter)
    lay.addWidget(lab)
    return w, k


class FrontPanel(QWidget):
    def __init__(self, scope: Dso2000, view, menus, callbacks: Dict[str, Callable]):
        super().__init__()
        self._scope = scope
        self._view = view
        self._menus = menus
        self._cb = callbacks
        self.setFixedWidth(376)

        steps = scope.spec.volt_div_steps
        self._v_index = {1: steps.index(1.0) if 1.0 in steps else len(steps) // 2,
                         2: steps.index(0.5) if 0.5 in steps else len(steps) // 2}
        tsteps = scope.spec.time_div_steps
        self._t_index = tsteps.index(100e-6) if 100e-6 in tsteps else len(tsteps) // 2
        self._trig_level = 0.0
        for ch in (1, 2):
            self._view.scales[ch] = steps[self._v_index[ch]]
        self._view.timebase = tsteps[self._t_index]

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(self._build_system_row())
        root.addWidget(self._build_run_row())
        root.addWidget(self._build_vertical())
        root.addWidget(self._build_horizontal())
        root.addWidget(self._build_trigger())
        if scope.has_awg:
            root.addWidget(self._build_wavegen())
        root.addStretch(1)

    # -- builders --------------------------------------------------------

    def _menu_button(self, text: str, key: str) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(lambda: self._menus.open(key))
        return b

    def _build_system_row(self) -> QGroupBox:
        box = _section("Menu")
        grid = QGridLayout(box)
        grid.setSpacing(4)
        buttons = [("Measure", "MEASURE"), ("Acquire", "ACQUIRE"),
                   ("Cursor", "CURSOR"), ("Display", "DISPLAY"),
                   ("Save", "SAVE"), ("Utility", "UTILITY"),
                   ("Decode", "DECODE"), ("Default", "SAVE")]
        for i, (label, key) in enumerate(buttons):
            b = QPushButton(label)
            if key == "DECODE":
                b.setEnabled(False)
                b.setToolTip("Protocol decode display: not yet implemented")
            elif label == "Default":
                b.clicked.connect(self._scope.reset)
            elif key == "MEASURE":
                # Measure has no sub-menu; it just toggles the on-screen table.
                b.setCheckable(True)
                b.toggled.connect(lambda on: self._menus.set_measure_table(on))
            else:
                b.clicked.connect(lambda _=False, k=key: self._menus.open(k))
            grid.addWidget(b, i // 4, i % 4)
        return box

    def _build_run_row(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._run = QPushButton("Run")
        self._run.setCheckable(True)
        self._run.setChecked(True)
        self._run.setStyleSheet("QPushButton:checked{background:#27a34a;border-color:#27a34a;}")
        self._run.toggled.connect(self._on_run)
        single = QPushButton("Single")
        single.clicked.connect(self._cb["single"])
        auto = QPushButton("Auto Set")
        auto.clicked.connect(self._cb["autoset"])
        lay.addWidget(self._run)
        lay.addWidget(single)
        lay.addWidget(auto)
        return w

    def _on_run(self, running: bool):
        self._run.setText("Run" if running else "Stop")
        self._cb["run_toggle"](running)

    def _build_vertical(self) -> QGroupBox:
        box = _section("Vertical")
        outer = QVBoxLayout(box)
        btns = QHBoxLayout()
        btns.addWidget(self._menu_button("CH1 Menu", "CH1"))
        btns.addWidget(self._menu_button("Math Menu", "MATH"))
        btns.addWidget(self._menu_button("CH2 Menu", "CH2"))
        outer.addLayout(btns)

        knobs = QHBoxLayout()
        for ch in (1, 2):
            col = QVBoxLayout()
            head = QLabel(f"CH{ch}")
            head.setAlignment(Qt.AlignCenter)
            head.setStyleSheet(f"color:{CH_COLORS[ch]}; font-weight:700;")
            col.addWidget(head)
            row = QHBoxLayout()
            posw, posk = _knob_with_label("Position")
            volw, volk = _knob_with_label("Volts/Div")
            posk.turned.connect(lambda d, c=ch: self._on_position(c, d))
            volk.turned.connect(lambda d, c=ch: self._on_volts(c, d))
            row.addWidget(posw)
            row.addWidget(volw)
            col.addLayout(row)
            knobs.addLayout(col)
        outer.addLayout(knobs)
        return box

    def _build_horizontal(self) -> QGroupBox:
        box = _section("Horizontal")
        lay = QVBoxLayout(box)
        lay.addWidget(self._menu_button("Horiz Menu", "HORIZ"))
        row = QHBoxLayout()
        posw, posk = _knob_with_label("Position")
        secw, seck = _knob_with_label("Sec/Div")
        posk.turned.connect(self._on_h_position)
        seck.turned.connect(self._on_sec)
        row.addWidget(posw)
        row.addWidget(secw)
        row.addStretch(1)
        lay.addLayout(row)
        return box

    def _build_trigger(self) -> QGroupBox:
        box = _section("Trigger")
        lay = QVBoxLayout(box)
        btns = QHBoxLayout()
        btns.addWidget(self._menu_button("Trig Menu", "TRIG"))
        force = QPushButton("Force")
        force.clicked.connect(self._scope.force_trigger)
        fifty = QPushButton("50%")
        fifty.clicked.connect(self._on_trig_50)
        btns.addWidget(force)
        btns.addWidget(fifty)
        lay.addLayout(btns)
        row = QHBoxLayout()
        levw, levk = _knob_with_label("Level")
        levk.turned.connect(self._on_level)
        row.addWidget(levw)
        row.addStretch(1)
        lay.addLayout(row)
        return box

    def _build_wavegen(self) -> QGroupBox:
        box = _section("Wave Gen")
        lay = QVBoxLayout(box)
        lay.addWidget(self._menu_button("Wave Gen", "WAVEGEN"))
        grid = QGridLayout()
        self._awg_freq = QDoubleSpinBox()
        self._awg_freq.setRange(0.0, self._scope.spec.awg_max_freq)
        self._awg_freq.setValue(1000.0)
        self._awg_freq.setSuffix(" Hz")
        self._awg_freq.valueChanged.connect(
            lambda v: self._safe(lambda: self._scope.set_awg_frequency(v)))
        self._awg_amp = QDoubleSpinBox()
        self._awg_amp.setRange(0.0, 20.0)
        self._awg_amp.setValue(1.0)
        self._awg_amp.setSuffix(" Vpp")
        self._awg_amp.valueChanged.connect(
            lambda v: self._safe(lambda: self._scope.set_awg_amplitude(v)))
        self._awg_off = QDoubleSpinBox()
        self._awg_off.setRange(-10.0, 10.0)
        self._awg_off.setSuffix(" V")
        self._awg_off.valueChanged.connect(
            lambda v: self._safe(lambda: self._scope.set_awg_offset(v)))
        self._awg_duty = QDoubleSpinBox()
        self._awg_duty.setRange(0.0, 99.0)
        self._awg_duty.setValue(50.0)
        self._awg_duty.setSuffix(" %")
        self._awg_duty.valueChanged.connect(
            lambda v: self._safe(lambda: self._scope.set_awg_duty(v)))
        for i, (lab, w) in enumerate([("Freq", self._awg_freq), ("Ampl", self._awg_amp),
                                      ("Offset", self._awg_off), ("Duty", self._awg_duty)]):
            grid.addWidget(QLabel(lab), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(grid)
        return box

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    # -- knob handlers ---------------------------------------------------

    def _changed(self):
        self._cb["settings_changed"]()

    def _on_position(self, ch: int, d: int):
        self._view.positions[ch] = max(-4.0, min(4.0, self._view.positions.get(ch, 0.0) + d * 0.2))
        self._safe(lambda: self._scope.set_offset(ch, -self._view.positions[ch] * self._view.scales[ch]))
        self._changed()

    def _on_volts(self, ch: int, d: int):
        steps = self._scope.spec.volt_div_steps
        self._v_index[ch] = max(0, min(len(steps) - 1, self._v_index[ch] + d))
        val = steps[self._v_index[ch]]
        self._view.scales[ch] = val
        self._safe(lambda: self._scope.set_scale(ch, val))
        self._changed()

    def _on_h_position(self, d: int):
        self._safe(lambda: self._scope.set_timebase_position(
            self._scope.get_timebase_position() + d * self._view.timebase * 0.2))
        self._changed()

    def _on_sec(self, d: int):
        steps = self._scope.spec.time_div_steps
        self._t_index = max(0, min(len(steps) - 1, self._t_index + d))
        val = steps[self._t_index]
        self._view.timebase = val
        self._safe(lambda: self._scope.set_timebase_scale(val))
        self._changed()

    def _on_level(self, d: int):
        ch = 1 if self._menus._trig_source.endswith("1") else 2
        self._trig_level += d * 0.04 * self._view.scales.get(ch, 1.0)
        self._safe(lambda: self._scope.set_edge_level(self._trig_level))
        self._view.set_trigger_level_div(self._trig_level / (self._view.scales.get(ch, 1.0) or 1.0))
        self._changed()

    def _on_trig_50(self):
        self._trig_level = 0.0
        self._safe(lambda: self._scope.set_edge_level(0.0))
        self._view.set_trigger_level_div(0.0)
        self._changed()

    def set_run_checked(self, on: bool):
        self._run.blockSignals(True)
        self._run.setChecked(on)
        self._run.setText("Run" if on else "Stop")
        self._run.blockSignals(False)
