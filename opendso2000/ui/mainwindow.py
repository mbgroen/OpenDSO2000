"""Main window assembled like the physical instrument.

Layout, left to right:  screen (plot + status bars)  |  F1–F6 soft-key strip  |
front panel (function buttons, knobs, run control).  Operation mirrors the
device: section buttons open soft-key menus, knobs adjust values.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QWidget

from ..acquisition import AcquisitionWorker
from ..scope.driver import Dso2000
from ..scope.enums import TriggerSweep
from ..scope.processing import CursorState, MathProcessor
from ..scope.waveform import Waveform
from .frontpanel import FrontPanel
from .menus import MenuController
from .screen import MEAS_ITEMS, ScreenPanel
from .scopeview import ScopeView
from .softkeys import SoftkeyBar
from .style import QSS
from .widgets import eng_format

_QUICK_MEAS = [("VPP", "Vpp", "V"), ("FREQuency", "F", "Hz"), ("VRMS", "Vrms", "V")]


class MainWindow(QWidget):
    def __init__(self, scope: Dso2000):
        super().__init__()
        self._scope = scope
        # Set by Utility ▸ Device to ask app.main to reopen the device picker.
        self.switch_requested = False
        self._last_paint = 0.0          # render-throttle timestamp
        self.setWindowTitle(f"OpenDSO2000 — {scope.spec.name}")
        # Default to a size that fits a 14" MacBook Pro (≈1512×982 pt) with the
        # menu bar; the layout can shrink further and the panel scrolls.
        self.resize(1200, 740)
        self.setMinimumSize(880, 560)

        self._view = ScopeView()
        self._screen = ScreenPanel(self._view)
        self._bar = SoftkeyBar()
        self._math = MathProcessor()
        self._cursors = CursorState()
        self._menus = MenuController(self._scope, self._view, self._bar,
                                     self._math, self._cursors, self._screen)
        self._menus.on_change_device = self._request_switch_device
        self._front = FrontPanel(self._scope, self._view, self._menus, {
            "run_toggle": self._on_run_toggle,
            "single": self._on_single,
            "autoset": self._on_autoset,
            "settings_changed": self._refresh_chrome,
        })

        # The front panel can be taller than a small screen, so make it scroll
        # vertically instead of forcing the window to grow.
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setFrameShape(QScrollArea.NoFrame)
        panel_scroll.setWidget(self._front)
        panel_scroll.setFixedWidth(self._front.width() + 18)

        body = QHBoxLayout(self)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        body.addWidget(self._screen, 1)
        body.addWidget(self._bar)
        body.addWidget(panel_scroll)

        self._view.cursorsMoved.connect(self._update_cursor_readout)
        self._menus.open("CH1")
        self._refresh_chrome()

        self._start_acquisition()
        self._start_measure_timer()

    # -- acquisition -----------------------------------------------------

    def _start_acquisition(self):
        self._thread = QThread(self)
        self._worker = AcquisitionWorker(self._scope)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.loop)
        self._worker.frameReady.connect(self._on_frame)
        self._worker.statusChanged.connect(self._screen.set_trigger_status)
        self._worker.error.connect(lambda m: self._screen.set_trigger_status("ERR"))
        self._worker.start_continuous()
        self._thread.start()

    def _start_measure_timer(self):
        self._mtimer = QTimer(self)
        self._mtimer.setInterval(600)
        self._mtimer.timeout.connect(self._update_measurements)
        self._mtimer.start()

    def _on_frame(self, wf: Waveform):
        # Cap on-screen refresh to ~30 fps. Frames that arrive faster are
        # dropped from rendering (the next one is always more recent), which
        # keeps the GUI responsive on slow displays like the Raspberry Pi.
        now = time.monotonic()
        if now - self._last_paint < 0.033:
            return
        self._last_paint = now
        self._view.update_frame(wf)
        result = self._math.compute(wf)
        self._view.show_math(result[0], result[1]) if result else self._view.show_math(None, None)
        self._screen.set_horizontal(self._view.timebase, wf.sample_rate,
                                    wf.points or self._depth_value())
        # Keep the cheap on-screen labels in sync with state that can change
        # from the soft-key menus (which don't trigger a full chrome refresh).
        self._update_dynamic_labels()
        self._update_cursor_readout()

    def _update_dynamic_labels(self):
        for ch in (1, 2):
            st = self._menus._ch[ch]
            self._screen.set_channel_info(ch, st["coupling"], self._view.scales.get(ch, 1.0),
                                          st["display"])
        m = self._math
        self._screen.set_math_info(
            f"Math {'FFT' if m.is_fft() else m.operator}" if m.enabled else "Math off")

    # -- chrome refresh --------------------------------------------------

    def _refresh_chrome(self):
        for ch in (1, 2):
            st = self._menus._ch[ch]
            self._screen.set_channel_info(ch, st["coupling"], self._view.scales.get(ch, 1.0),
                                          st["display"])
        # srate=0 -> ScreenPanel keeps the last known sample rate.
        self._screen.set_horizontal(self._view.timebase, 0, self._depth_value())
        m = self._math
        if m.enabled:
            op = "FFT" if m.is_fft() else m.operator
            self._screen.set_math_info(f"Math {op}")
        else:
            self._screen.set_math_info("Math off")
        if self._scope.has_awg:
            self._screen.set_awg_info("Gen")
        self._bar.refresh()
        self._update_cursor_readout()

    def _depth_value(self) -> int:
        try:
            return int(self._menus._depth)
        except (ValueError, AttributeError):
            return 0

    def _update_cursor_readout(self):
        c = self._cursors
        if c.mode == "OFF":
            self._screen.set_cursor_text("")
            return
        parts = []
        tdiv = self._view.timebase
        vdiv = self._view.scales.get(c.source, 1.0)
        if c.x_visible():
            ax, bx = self._view.cursor_x_divs()
            dt = abs(bx - ax) * tdiv
            parts.append(f"ΔX={eng_format(dt, 's')}")
            if dt > 0:
                parts.append(f"1/ΔX={eng_format(1.0 / dt, 'Hz')}")
        if c.y_visible():
            ay, by = self._view.cursor_y_divs()
            parts.append(f"ΔY={eng_format(abs(ay - by) * vdiv, 'V')}")
        self._screen.set_cursor_text("  ".join(parts))

    def _update_measurements(self):
        table = self._screen.table_visible()
        for ch in (1, 2):
            enabled = self._menus._ch[ch]["display"]
            try:
                if not enabled:
                    self._screen.set_measurements(ch, f"CH{ch}  off")
                else:
                    bits = []
                    for item, label, unit in _QUICK_MEAS:
                        v = self._scope.measure(ch, item)
                        bits.append(f"{label} {eng_format(v, unit)}" if v == v else f"{label} —")
                    self._screen.set_measurements(ch, f"CH{ch}  " + "  ".join(bits))
                if table:
                    self._fill_table(ch, enabled)
            except Exception:
                pass

    def _fill_table(self, ch: int, enabled: bool):
        for item, _label, unit in MEAS_ITEMS:
            if not enabled:
                self._screen.set_table_value(ch, item, "—")
                continue
            v = self._scope.measure(ch, item)
            self._screen.set_table_value(ch, item, eng_format(v, unit) if v == v else "—")

    # -- run control -----------------------------------------------------

    def _on_run_toggle(self, running: bool):
        if running:
            self._scope.run()
            self._worker.start_continuous()
        else:
            self._scope.stop()
            self._worker.stop()

    def _on_single(self):
        self._scope.set_trigger_sweep(TriggerSweep.SINGLE)
        self._scope.single()
        self._worker.request_single()
        self._front.set_run_checked(False)

    def _on_autoset(self):
        self._scope.autoset()
        QTimer.singleShot(400, self._refresh_chrome)

    def _request_switch_device(self):
        # Close the window; app.main reopens the device picker.
        self.switch_requested = True
        self.close()

    # -- shutdown --------------------------------------------------------

    def closeEvent(self, event):
        try:
            self._mtimer.stop()
            self._worker.stop()
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait(1500)
        finally:
            self._scope.disconnect()
        super().closeEvent(event)
