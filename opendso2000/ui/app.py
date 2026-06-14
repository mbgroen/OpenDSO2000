"""Application bootstrap: parse args, connect, show the main window."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ..scope.driver import Dso2000
from ..transport.base import TransportError
from .devicedialog import Selection, choose_device
from .mainwindow import MainWindow
from .style import QSS

_RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res")


def app_icon() -> QIcon:
    """Build the application icon from the bundled assets (SVG + PNGs)."""
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512, 1024):
        png = os.path.join(_RES, f"icon_{size}.png")
        if os.path.exists(png):
            icon.addFile(png)
    if icon.isNull():
        svg = os.path.join(_RES, "icon.svg")
        if os.path.exists(svg):
            icon = QIcon(svg)
    return icon


def _set_macos_dock_icon() -> None:
    """Best-effort: set the Dock icon when running unbundled (needs pyobjc)."""
    if sys.platform != "darwin":
        return
    png = os.path.join(_RES, "icon_512.png")
    if not os.path.exists(png):
        return
    try:  # pyobjc is optional; only used to override the python-rocket Dock icon
        from AppKit import NSApplication, NSImage
        image = NSImage.alloc().initByReferencingFile_(png)
        NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass


def _set_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID so the taskbar uses our icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenDSO2000")
    except Exception:
        pass


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="opendso2000",
        description="Control software for Hantek DSO2C10/2C15/2D10/2D15 oscilloscopes.",
    )
    p.add_argument("--simulate", action="store_true",
                   help="Run against a built-in simulated instrument (no hardware).")
    p.add_argument("--model", default="DSO2D15",
                   help="Model to assume when simulating (default: DSO2D15).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    _set_windows_app_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OpenDSO2000")
    app.setApplicationDisplayName("OpenDSO2000")
    app.setOrganizationName("OpenDSO2000")
    icon = app_icon()
    app.setWindowIcon(icon)
    _set_macos_dock_icon()
    app.setStyleSheet(QSS)

    # --simulate skips the picker and connects to the requested simulator.
    selection = Selection("sim", model=args.model) if args.simulate else None

    while True:
        if selection is None:
            selection = choose_device()
            if selection is None:        # user cancelled the picker
                return 0

        scope = Dso2000(selection.build_transport())
        try:
            scope.connect()
        except TransportError as exc:
            QMessageBox.critical(None, "Connection failed",
                                 f"Could not connect to {selection.label()}:\n\n{exc}")
            selection = None             # back to the picker
            continue

        window = MainWindow(scope)
        window.setWindowIcon(icon)
        window.setWindowTitle(f"OpenDSO2000 — {selection.label()}")
        window.show()
        app.exec()

        if getattr(window, "switch_requested", False):
            selection = None             # reopen the picker to switch device
            continue
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
