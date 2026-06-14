"""Instrument selection dialog.

Lists every DSO2000 found on the USB bus plus simulator entries for each model,
so the user can pick a real device or run simulated — all in one place.  Shown
at start-up and reachable again from Utility ▸ Device.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..scope.models import MODELS
from ..transport.base import Transport
from ..transport.discovery import DeviceInfo, list_devices
from ..transport.simulated import SimulatedTransport
from ..transport.usbtmc import UsbTmcTransport


@dataclass
class Selection:
    kind: str                       # "usb" or "sim"
    device: Optional[DeviceInfo] = None
    model: str = "DSO2D15"

    def label(self) -> str:
        if self.kind == "usb" and self.device:
            return self.device.label
        return f"Simulator — {self.model}"

    def build_transport(self) -> Transport:
        if self.kind == "usb" and self.device:
            return UsbTmcTransport(self.device.vid, self.device.pid,
                                   serial=self.device.serial)
        return SimulatedTransport(model=self.model)


class DeviceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenDSO2000 — Select instrument")
        self.setMinimumWidth(440)
        self._selection: Optional[Selection] = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Choose an instrument to connect to:"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._accept())
        root.addWidget(self._list)

        row = QHBoxLayout()
        self._status = QLabel("")
        self._status.setStyleSheet("color:#9aa4b1;")
        refresh = QPushButton("Refresh USB")
        refresh.clicked.connect(self._populate)
        row.addWidget(self._status, 1)
        row.addWidget(refresh)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Connect")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate()

    def _populate(self):
        self._list.clear()
        try:
            devices = list_devices()
        except Exception:
            devices = []
        for info in devices:
            item = QListWidgetItem("🔌  " + info.label)
            item.setData(Qt.UserRole, Selection("usb", device=info))
            self._list.addItem(item)
        # Simulator entries, one per known model.
        for name in MODELS:
            item = QListWidgetItem(f"🖥  Simulator — {name}")
            item.setData(Qt.UserRole, Selection("sim", model=name))
            self._list.addItem(item)

        if devices:
            self._status.setText(f"{len(devices)} USB device(s) found")
            self._list.setCurrentRow(0)
        else:
            self._status.setText("No USB scope found — pick a simulator")
            # Select the first simulator entry (DSO2D15).
            for i in range(self._list.count()):
                sel = self._list.item(i).data(Qt.UserRole)
                if sel.kind == "sim" and sel.model == "DSO2D15":
                    self._list.setCurrentRow(i)
                    break

    def _accept(self):
        item = self._list.currentItem()
        if item is not None:
            self._selection = item.data(Qt.UserRole)
            self.accept()

    def selection(self) -> Optional[Selection]:
        return self._selection


def choose_device(parent=None) -> Optional[Selection]:
    """Show the dialog modally; return the chosen Selection or None if cancelled."""
    dlg = DeviceDialog(parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.selection()
    return None
