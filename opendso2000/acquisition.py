"""Background acquisition thread.

Polling the scope over USB-TMC is slow and blocking, so it must never run on
the Qt GUI thread.  :class:`AcquisitionWorker` lives in its own QThread, asks
the driver for frames as fast as the device allows, and emits each decoded
:class:`Waveform` back to the UI.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from .scope.driver import Dso2000
from .scope.waveform import Waveform


class AcquisitionWorker(QObject):
    frameReady = Signal(object)        # Waveform
    statusChanged = Signal(str)        # trigger status text
    error = Signal(str)

    def __init__(self, scope: Dso2000):
        super().__init__()
        self._scope = scope
        self._running = False
        self._single = False
        self._frame_interval_ms = 33      # ~30 fps; see set_target_fps()

    def set_target_fps(self, fps: int) -> None:
        """Pace the producer; lower fps cuts CPU and VNC/remote bandwidth."""
        fps = max(1, min(int(fps), 120))
        self._frame_interval_ms = max(1, round(1000 / fps))

    def start_continuous(self) -> None:
        self._running = True
        self._single = False

    def stop(self) -> None:
        self._running = False

    def request_single(self) -> None:
        self._single = True
        self._running = True

    def loop(self) -> None:
        """Slot connected to QThread.started."""
        while not QThread.currentThread().isInterruptionRequested():
            if not self._running:
                QThread.msleep(50)
                continue
            try:
                wf = self._scope.read_waveform()
                if wf is not None:
                    self.frameReady.emit(wf)
                    self.statusChanged.emit("Triggered" if wf.triggered else "Auto")
                if self._single:
                    self._running = False
                    self._single = False
            except Exception as exc:  # keep the loop alive on transient errors
                self.error.emit(str(exc))
                QThread.msleep(200)
            # Cap the frame rate. On real hardware the USB read is the
            # bottleneck anyway; on the simulator this stops us from pegging the
            # CPU and flooding the GUI thread on low-power machines (Pi / VNC).
            QThread.msleep(self._frame_interval_ms)
