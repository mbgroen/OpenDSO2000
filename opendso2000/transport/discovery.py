"""Locate connected DSO2000 instruments on the USB bus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..scope.models import DSO2000_PID, DSO2000_VID
from .base import Transport
from .simulated import SimulatedTransport
from .usbtmc import UsbTmcTransport, get_backend

try:
    import usb.core
    import usb.util
    _HAVE_PYUSB = True
except Exception:
    _HAVE_PYUSB = False


@dataclass
class DeviceInfo:
    vid: int
    pid: int
    serial: Optional[str]
    label: str


def list_devices() -> List[DeviceInfo]:
    """Return all attached DSO2000 instruments (empty if none/no libusb)."""
    if not _HAVE_PYUSB:
        return []
    found: List[DeviceInfo] = []
    kwargs = dict(find_all=True, idVendor=DSO2000_VID, idProduct=DSO2000_PID)
    backend = get_backend()
    if backend is not None:
        kwargs["backend"] = backend
    for dev in usb.core.find(**kwargs):
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
        except Exception:
            serial = None
        label = f"DSO2000 {dev.idVendor:04x}:{dev.idProduct:04x}"
        if serial:
            label += f" (S/N {serial})"
        found.append(DeviceInfo(dev.idVendor, dev.idProduct, serial, label))
    return found


def open_first(simulate: bool = False, sim_model: str = "DSO2D15") -> Transport:
    """Open the first available device, or a simulator.

    Falls back to the simulator automatically when no hardware is present so the
    application is always usable.
    """
    if simulate:
        return SimulatedTransport(model=sim_model)
    devices = list_devices()
    if not devices:
        return SimulatedTransport(model=sim_model)
    d = devices[0]
    return UsbTmcTransport(d.vid, d.pid, serial=d.serial)
