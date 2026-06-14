"""Definitions of every soft-key menu, mirroring the device's menu tree.

A :class:`MenuController` owns the soft-key bar and builds the menus that the
front-panel hardware buttons open.  Discrete options cycle on each key press
(as on the instrument); continuous values (scale, level, position) are turned
with the dedicated knobs.  Local shadow state keeps the displayed values fast
and in sync with what we push to the device.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ..scope.driver import Dso2000
from ..scope.enums import (AcquireType, Coupling, EdgeSlope, FftWindow,
                           MathOperator, TimebaseMode, TriggerMode, TriggerSweep)
from ..scope.processing import MATH_SCALE_STEPS, CursorState, MathProcessor
from .softkeys import Menu, MenuItem, SoftkeyBar
from .widgets import eng_format


def _on(b: bool) -> str:
    return "On" if b else "Off"


class MenuController:
    def __init__(self, scope: Dso2000, view, bar: SoftkeyBar,
                 math: MathProcessor, cursors: CursorState, screen=None):
        self._scope = scope
        self._view = view
        self._bar = bar
        self._math = math
        self._cursors = cursors
        self._screen = screen

        # Shadow state (defaults match the simulator/device power-on state).
        self._ch = {
            1: dict(coupling="DC", probe="1", bw=False, invert=False, display=True),
            2: dict(coupling="DC", probe="1", bw=False, invert=False, display=True),
        }
        self._acq_type = AcquireType.NORMAL.value
        self._depth = "4000"
        self._tb_mode = TimebaseMode.MAIN.value
        self._trig_type = TriggerMode.EDGE.value
        self._trig_sweep = TriggerSweep.AUTO.value
        self._trig_source = "CHANnel1"
        self._trig_slope = EdgeSlope.RISING.value
        self._display_dots = False
        self._persist = False
        # Set by MainWindow; called when the user picks Utility ▸ Device.
        self.on_change_device: Optional[Callable[[], None]] = None

        self._builders: Dict[str, Callable[[], Menu]] = {
            "CH1": lambda: self._channel_menu(1),
            "CH2": lambda: self._channel_menu(2),
            "MATH": self._math_menu,
            "HORIZ": self._horiz_menu,
            "TRIG": self._trigger_menu,
            "CURSOR": self._cursor_menu,
            "ACQUIRE": self._acquire_menu,
            "DISPLAY": self._display_menu,
            "SAVE": self._save_menu,
            "UTILITY": self._utility_menu,
            "WAVEGEN": self._wavegen_menu,
        }
        self._current_key: Optional[str] = None

    # -- public ----------------------------------------------------------

    def open(self, key: str) -> None:
        builder = self._builders.get(key)
        if not builder:
            return
        self._current_key = key
        self._bar.set_menu(builder())

    def set_measure_table(self, on: bool) -> None:
        """Show/hide the on-screen measurement table (driven by the Measure key)."""
        self._table_on = on
        if self._screen is not None:
            self._screen.show_table(on)
        for ch in (1, 2):
            try:
                self._scope.set_measure_all(ch, on)
            except Exception:
                pass

    def reopen(self) -> None:
        if self._current_key:
            self.open(self._current_key)

    def refresh(self) -> None:
        self._bar.refresh()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _cycle(current, options: List):
        try:
            i = options.index(current)
        except ValueError:
            i = -1
        return options[(i + 1) % len(options)]

    # -- channel ---------------------------------------------------------

    def _channel_menu(self, ch: int) -> Menu:
        st = self._ch[ch]

        def toggle_display():
            st["display"] = not st["display"]
            self._scope.set_channel_enabled(ch, st["display"])
            self._view.set_channel_visible(ch, st["display"])

        def cycle_coupling():
            st["coupling"] = self._cycle(st["coupling"], ["DC", "AC", "GND"])
            self._scope.set_coupling(ch, Coupling(st["coupling"]))

        def cycle_probe():
            st["probe"] = self._cycle(st["probe"], ["1", "10", "100", "1000"])
            self._scope.set_probe(ch, int(st["probe"]))

        def toggle_bw():
            st["bw"] = not st["bw"]
            self._scope.set_bandwidth_limit(ch, st["bw"])

        def toggle_invert():
            st["invert"] = not st["invert"]
            self._scope.set_invert(ch, st["invert"])

        return Menu(f"CH{ch}", [
            MenuItem("Display", lambda: _on(st["display"]), toggle_display),
            MenuItem("Coupling", lambda: st["coupling"], cycle_coupling),
            MenuItem("Probe", lambda: st["probe"] + "x", cycle_probe),
            MenuItem("BW Limit", lambda: _on(st["bw"]), toggle_bw),
            MenuItem("Invert", lambda: _on(st["invert"]), toggle_invert),
        ])

    # -- math ------------------------------------------------------------

    def _math_menu(self) -> Menu:
        m = self._math
        op_labels = {MathOperator.ADD.value: "A+B", MathOperator.SUBTRACT.value: "A-B",
                     MathOperator.MULTIPLY.value: "AxB", MathOperator.DIVIDE.value: "A/B",
                     MathOperator.FFT.value: "FFT"}

        def toggle():
            m.enabled = not m.enabled
            try:
                self._scope.set_math_enabled(m.enabled)
            except Exception:
                pass

        def cycle_op():
            order = [o.value for o in (MathOperator.ADD, MathOperator.SUBTRACT,
                                       MathOperator.MULTIPLY, MathOperator.DIVIDE,
                                       MathOperator.FFT)]
            m.operator = self._cycle(m.operator, order)
            self._mirror_math()
            self.open("MATH")           # rebuild (FFT shows different keys)

        def cycle_src1():
            m.source1 = 2 if m.source1 == 1 else 1
            self._mirror_math()

        items = [
            MenuItem("Display", lambda: _on(m.enabled), toggle),
            MenuItem("Operator", lambda: op_labels.get(m.operator, m.operator), cycle_op),
        ]
        if m.is_fft():
            def cycle_win():
                order = [w.value for w in (FftWindow.HANNING, FftWindow.HAMMING,
                                           FftWindow.BLACKMAN, FftWindow.RECTANGLE)]
                m.window = self._cycle(m.window, order)
                self._mirror_math()

            def cycle_unit():
                m.unit = "VRMS" if m.unit == "DB" else "DB"
                self._mirror_math()

            items += [
                MenuItem("Source", lambda: f"CH{m.source1}", cycle_src1),
                MenuItem("Window", lambda: m.window.rstrip("aeiounAEIOUN")[:4], cycle_win),
                MenuItem("Unit", lambda: "dBV" if m.unit == "DB" else "Vrms", cycle_unit),
            ]
        else:
            def cycle_src2():
                m.source2 = 2 if m.source2 == 1 else 1
                self._mirror_math()

            def cycle_scale():
                m.scale = self._cycle(m.scale, list(MATH_SCALE_STEPS))
                self._mirror_math()

            items += [
                MenuItem("Source A", lambda: f"CH{m.source1}", cycle_src1),
                MenuItem("Source B", lambda: f"CH{m.source2}", cycle_src2),
                MenuItem("Scale", lambda: eng_format(m.scale, "V"), cycle_scale),
            ]
        return Menu("Math", items)

    def _mirror_math(self):
        m = self._math
        try:
            self._scope.set_math_operator(MathOperator(m.operator))
            if m.is_fft():
                self._scope.set_fft_source(f"CHANnel{m.source1}")
                self._scope.set_fft_window(FftWindow(m.window))
                self._scope.write(f":MATH:FFT:UNIT {m.unit}")
            else:
                self._scope.set_math_sources(f"CHANnel{m.source1}", f"CHANnel{m.source2}")
        except Exception:
            pass

    # -- horizontal / acquire -------------------------------------------

    def _horiz_menu(self) -> Menu:
        def cycle_mode():
            order = [TimebaseMode.MAIN.value, TimebaseMode.XY.value, TimebaseMode.ROLL.value]
            self._tb_mode = self._cycle(self._tb_mode, order)
            self._scope.set_timebase_mode(TimebaseMode(self._tb_mode))
        labels = {TimebaseMode.MAIN.value: "Y-T", TimebaseMode.XY.value: "X-Y",
                  TimebaseMode.ROLL.value: "Roll"}
        return Menu("Horizontal", [
            MenuItem("Mode", lambda: labels.get(self._tb_mode, self._tb_mode), cycle_mode),
            MenuItem("Set 0", lambda: "", lambda: self._scope.set_timebase_position(0.0)),
        ])

    def _acquire_menu(self) -> Menu:
        def cycle_type():
            order = [AcquireType.NORMAL.value, AcquireType.AVERAGE.value,
                     AcquireType.PEAK.value, AcquireType.HIRES.value]
            self._acq_type = self._cycle(self._acq_type, order)
            self._scope.set_acquire_type(AcquireType(self._acq_type))

        def cycle_depth():
            order = ["4000", "40000", "400000", "4000000", "8000000"]
            self._depth = self._cycle(self._depth, order)
            self._scope.set_memory_depth(int(self._depth))

        labels = {AcquireType.NORMAL.value: "Normal", AcquireType.AVERAGE.value: "Average",
                  AcquireType.PEAK.value: "Peak", AcquireType.HIRES.value: "Hi-Res"}
        depth_lbl = {"4000": "4K", "40000": "40K", "400000": "400K",
                     "4000000": "4M", "8000000": "8M"}
        return Menu("Acquire", [
            MenuItem("Mode", lambda: labels.get(self._acq_type, self._acq_type), cycle_type),
            MenuItem("Depth", lambda: depth_lbl.get(self._depth, self._depth), cycle_depth),
        ])

    # -- trigger ---------------------------------------------------------

    def _trigger_menu(self) -> Menu:
        type_order = [t.value for t in (TriggerMode.EDGE, TriggerMode.PULSE,
                      TriggerMode.SLOPE, TriggerMode.TV, TriggerMode.TIMEOUT,
                      TriggerMode.WINDOW, TriggerMode.INTERVAL, TriggerMode.UNDERTHROW,
                      TriggerMode.PATTERN, TriggerMode.UART, TriggerMode.CAN,
                      TriggerMode.LIN, TriggerMode.IIC, TriggerMode.SPI)]
        type_lbl = {TriggerMode.EDGE.value: "Edge", TriggerMode.PULSE.value: "Pulse",
                    TriggerMode.SLOPE.value: "Slope", TriggerMode.TV.value: "Video",
                    TriggerMode.TIMEOUT.value: "Timeout", TriggerMode.WINDOW.value: "Window",
                    TriggerMode.INTERVAL.value: "Interval", TriggerMode.UNDERTHROW.value: "Runt",
                    TriggerMode.PATTERN.value: "Pattern", TriggerMode.UART.value: "UART",
                    TriggerMode.CAN.value: "CAN", TriggerMode.LIN.value: "LIN",
                    TriggerMode.IIC.value: "I2C", TriggerMode.SPI.value: "SPI"}

        def cycle_type():
            self._trig_type = self._cycle(self._trig_type, type_order)
            self._scope.set_trigger_mode(TriggerMode(self._trig_type))

        def cycle_sweep():
            order = [TriggerSweep.AUTO.value, TriggerSweep.NORMAL.value, TriggerSweep.SINGLE.value]
            self._trig_sweep = self._cycle(self._trig_sweep, order)
            self._scope.set_trigger_sweep(TriggerSweep(self._trig_sweep))

        def cycle_source():
            self._trig_source = "CHANnel2" if self._trig_source.endswith("1") else "CHANnel1"
            self._scope.set_edge_source(self._trig_source)

        def cycle_slope():
            order = [EdgeSlope.RISING.value, EdgeSlope.FALLING.value, EdgeSlope.EITHER.value]
            self._trig_slope = self._cycle(self._trig_slope, order)
            self._scope.set_edge_slope(EdgeSlope(self._trig_slope))

        sweep_lbl = {TriggerSweep.AUTO.value: "Auto", TriggerSweep.NORMAL.value: "Normal",
                     TriggerSweep.SINGLE.value: "Single"}
        slope_lbl = {EdgeSlope.RISING.value: "Rising ↑", EdgeSlope.FALLING.value: "Falling ↓",
                     EdgeSlope.EITHER.value: "Either"}
        return Menu("Trigger", [
            MenuItem("Type", lambda: type_lbl.get(self._trig_type, self._trig_type), cycle_type),
            MenuItem("Sweep", lambda: sweep_lbl.get(self._trig_sweep, self._trig_sweep), cycle_sweep),
            MenuItem("Source", lambda: "CH" + self._trig_source[-1], cycle_source),
            MenuItem("Slope", lambda: slope_lbl.get(self._trig_slope, self._trig_slope), cycle_slope),
            MenuItem("Force", lambda: "", self._scope.force_trigger),
        ])

    # -- cursor ----------------------------------------------------------

    def _cursor_menu(self) -> Menu:
        c = self._cursors

        def cycle_mode():
            c.mode = self._cycle(c.mode, ["OFF", "MANual", "TRACk"])
            self._apply_cursors()

        def cycle_type():
            c.ctype = self._cycle(c.ctype, ["X", "Y", "XY"])
            self._apply_cursors()

        def cycle_source():
            c.source = 2 if c.source == 1 else 1
            self._apply_cursors()

        mode_lbl = {"OFF": "Off", "MANual": "Manual", "TRACk": "Track"}
        return Menu("Cursor", [
            MenuItem("Mode", lambda: mode_lbl.get(c.mode, c.mode), cycle_mode),
            MenuItem("Type", lambda: c.ctype, cycle_type),
            MenuItem("Source", lambda: f"CH{c.source}", cycle_source),
        ])

    def _apply_cursors(self):
        c = self._cursors
        self._view.set_cursor_visibility(c.x_visible(), c.y_visible())
        try:
            self._scope.write(f":CURSor:MODE {c.mode}")
            if c.mode == "MANual":
                self._scope.write(f":CURSor:MANual:TYPE {c.ctype}")
                self._scope.write(f":CURSor:MANual:SOURce CHANnel{c.source}")
        except Exception:
            pass

    # -- display / save / utility ---------------------------------------

    def _display_menu(self) -> Menu:
        def toggle_type():
            self._display_dots = not self._display_dots
            self._scope.set_display_type(vector=not self._display_dots)

        def toggle_persist():
            self._persist = not self._persist
        return Menu("Display", [
            MenuItem("Draw", lambda: "Dots" if self._display_dots else "Vector", toggle_type),
            MenuItem("Persist", lambda: _on(self._persist), toggle_persist),
        ])

    def _save_menu(self) -> Menu:
        # Image save is the only export implemented; factory reset lives on the
        # top "Default" button. Setup/waveform file save is a known TODO.
        return Menu("Save", [
            MenuItem("Save PNG", lambda: "", lambda: self._save_png()),
        ])

    def _save_png(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self._view, "Save image", "dso2000.png",
                                              "PNG image (*.png)")
        if path:
            self._view.grab().save(path, "PNG")

    def _utility_menu(self) -> Menu:
        def self_cal():
            try:
                self._scope.write(":CALibrate:STARt")
            except Exception:
                pass
        def change_device():
            if self.on_change_device:
                self.on_change_device()
        return Menu("Utility", [
            MenuItem("Device", lambda: "", change_device),
            MenuItem("Self-cal", lambda: "", self_cal),
            MenuItem("System", lambda: self._scope.spec.name, None),
        ])

    # -- waveform generator (D models) ----------------------------------

    def _wavegen_menu(self) -> Menu:
        self._awg_on = getattr(self, "_awg_on", False)
        self._awg_wave = getattr(self, "_awg_wave", "SINE")

        def toggle():
            self._awg_on = not self._awg_on
            try:
                self._scope.set_awg_enabled(self._awg_on)
            except Exception:
                pass

        def cycle_wave():
            from ..scope.enums import DdsType
            order = [DdsType.SINE.value, DdsType.SQUARE.value, DdsType.RAMP.value,
                     DdsType.EXP.value, DdsType.NOISE.value, DdsType.DC.value]
            self._awg_wave = self._cycle(self._awg_wave, order)
            try:
                self._scope.set_awg_type(DdsType(self._awg_wave))
            except Exception:
                pass
        # Frequency / amplitude / offset / duty are set in the Wave Gen panel
        # fields below; this menu covers output enable and waveform type.
        return Menu("Wave Gen", [
            MenuItem("Output", lambda: _on(self._awg_on), toggle),
            MenuItem("Wave", lambda: self._awg_wave.title(), cycle_wave),
        ])
