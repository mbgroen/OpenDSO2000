"""A self-contained USB-TMC transport built on PyUSB / libusb.

USB-TMC (USB Test & Measurement Class) is a thin framing layer over two bulk
endpoints.  We implement just the two message types a SCPI scope needs:

* ``DEV_DEP_MSG_OUT`` (MsgID 1)        -> send a command
* ``REQUEST_DEV_DEP_MSG_IN`` (MsgID 2) -> ask for a response, then read it

Implementing it directly (rather than depending on the unmaintained
``python-usbtmc`` package) keeps the dependency surface small and works the
same on macOS (Intel/ARM) and Linux, the two platforms this app targets.

Reference: USBTMC 1.0 specification, section 3.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Optional

from .base import Transport, TransportError

try:  # PyUSB is an optional import so the simulator works without libusb.
    import usb.core
    import usb.util
    _HAVE_PYUSB = True
except Exception:  # pragma: no cover - environment without pyusb/libusb
    _HAVE_PYUSB = False


# USB-TMC bMsgID values.
_MSGID_DEV_DEP_MSG_OUT = 1
_MSGID_REQUEST_DEV_DEP_MSG_IN = 2
_MSGID_DEV_DEP_MSG_IN = 2

# USB-TMC interface class / subclass.
_USBTMC_INTERFACE_CLASS = 0xFE
_USBTMC_SUBCLASS = 0x03

_HEADER_SIZE = 12
_DEFAULT_TIMEOUT_MS = 5000


def _align4(n: int) -> int:
    return (n + 3) & ~3


class UsbTmcTransport(Transport):
    """Talk to a USB-TMC instrument identified by vendor/product id."""

    def __init__(
        self,
        vid: int,
        pid: int,
        serial: Optional[str] = None,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        if not _HAVE_PYUSB:
            raise TransportError(
                "PyUSB/libusb is not available. Install 'pyusb' and the libusb "
                "runtime (macOS: 'brew install libusb', Linux: 'libusb-1.0')."
            )
        self._vid = vid
        self._pid = pid
        self._serial = serial
        self._timeout_ms = timeout_ms
        self._dev = None
        self._cfg = None
        self._intf = None
        self._ep_in = None
        self._ep_out = None
        self._max_packet_in = 64
        self._btag = 0
        self._lock = threading.RLock()
        self.description = f"USB {vid:04x}:{pid:04x}"

    # -- lifecycle -------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._dev is not None:
                return
            kwargs = dict(idVendor=self._vid, idProduct=self._pid)
            dev = usb.core.find(**kwargs)
            if dev is None:
                raise TransportError(
                    f"No USB device {self._vid:04x}:{self._pid:04x} found. "
                    "Check the cable, power, and (on Linux) udev permissions."
                )
            try:
                serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
            except Exception:
                serial = None
            if self._serial and serial and self._serial != serial:
                raise TransportError(f"Device serial {serial!r} != requested {self._serial!r}")

            # On Linux a kernel driver (usbtmc) may already be attached.
            self._detach_kernel_driver(dev)

            try:
                dev.set_configuration()
            except usb.core.USBError:
                # Already configured by another handle; continue.
                pass

            cfg = dev.get_active_configuration()
            intf = self._find_usbtmc_interface(cfg)
            if intf is None:
                raise TransportError("No USB-TMC interface found on the device.")

            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK,
            )
            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK,
            )
            if ep_out is None or ep_in is None:
                raise TransportError("USB-TMC bulk endpoints not found.")

            self._dev = dev
            self._cfg = cfg
            self._intf = intf
            self._ep_out = ep_out
            self._ep_in = ep_in
            self._max_packet_in = ep_in.wMaxPacketSize or 64
            self.description = f"USB {self._vid:04x}:{self._pid:04x}" + (
                f" (S/N {serial})" if serial else ""
            )

    def close(self) -> None:
        with self._lock:
            if self._dev is not None:
                try:
                    usb.util.dispose_resources(self._dev)
                except Exception:
                    pass
            self._dev = None
            self._intf = self._ep_in = self._ep_out = None

    @staticmethod
    def _detach_kernel_driver(dev) -> None:
        try:
            for cfg in dev:
                for intf in cfg:
                    n = intf.bInterfaceNumber
                    if dev.is_kernel_driver_active(n):
                        dev.detach_kernel_driver(n)
        except (NotImplementedError, usb.core.USBError):
            # Not supported on this platform (e.g. macOS) -> nothing to do.
            pass

    @staticmethod
    def _find_usbtmc_interface(cfg):
        for intf in cfg:
            if (
                intf.bInterfaceClass == _USBTMC_INTERFACE_CLASS
                and intf.bInterfaceSubClass == _USBTMC_SUBCLASS
            ):
                return intf
        # Some clones mis-declare the class; fall back to the first interface
        # that exposes a bulk IN and a bulk OUT endpoint.
        for intf in cfg:
            has_in = has_out = False
            for ep in intf:
                if usb.util.endpoint_type(ep.bmAttributes) != usb.util.ENDPOINT_TYPE_BULK:
                    continue
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                    has_in = True
                else:
                    has_out = True
            if has_in and has_out:
                return intf
        return None

    # -- framing ---------------------------------------------------------

    def _next_tag(self) -> int:
        # bTag must be 1..255 and never 0.
        self._btag = (self._btag % 255) + 1
        return self._btag

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._ep_out is None:
                raise TransportError("Transport is not open.")
            tag = self._next_tag()
            header = struct.pack(
                "<BBBxIBxxx",
                _MSGID_DEV_DEP_MSG_OUT,
                tag,
                (~tag) & 0xFF,
                len(data),
                0x01,  # bmTransferAttributes: EOM = 1 (this is the last/only block)
            )
            payload = header + data
            payload += b"\x00" * (_align4(len(payload)) - len(payload))
            try:
                self._ep_out.write(payload, self._timeout_ms)
            except usb.core.USBError as exc:
                raise TransportError(f"USB write failed: {exc}") from exc

    def read(self, max_length: int = 1024 * 1024) -> bytes:
        with self._lock:
            if self._ep_in is None:
                raise TransportError("Transport is not open.")
            out = bytearray()
            remaining = max_length
            while True:
                chunk, eom = self._read_one(min(remaining, 1024 * 1024))
                out += chunk
                remaining -= len(chunk)
                if eom or remaining <= 0:
                    break
            return bytes(out)

    def _read_one(self, request_len: int):
        tag = self._next_tag()
        req = struct.pack(
            "<BBBxIBBxx",
            _MSGID_REQUEST_DEV_DEP_MSG_IN,
            tag,
            (~tag) & 0xFF,
            request_len,
            0x00,  # bmTransferAttributes: TermChar disabled
            0x0A,  # TermChar (ignored when disabled)
        )
        try:
            self._ep_out.write(req, self._timeout_ms)
            # Read header + data.  Round the request up to the endpoint size.
            want = _HEADER_SIZE + _align4(request_len)
            raw = self._ep_in.read(want, self._timeout_ms).tobytes()
        except usb.core.USBError as exc:
            raise TransportError(f"USB read failed: {exc}") from exc

        if len(raw) < _HEADER_SIZE:
            raise TransportError("Short USB-TMC response (no header).")
        msgid, _rtag, _rtaginv, transfer_size, attrs = struct.unpack(
            "<BBBxIB3x", raw[:_HEADER_SIZE]
        )
        if msgid != _MSGID_DEV_DEP_MSG_IN:
            raise TransportError(f"Unexpected USB-TMC MsgID {msgid} in response.")
        data = raw[_HEADER_SIZE:_HEADER_SIZE + transfer_size]
        # If the device promised more than this packet carried, drain it.
        while len(data) < transfer_size:
            more = self._ep_in.read(
                _align4(transfer_size - len(data)), self._timeout_ms
            ).tobytes()
            if not more:
                break
            data += more
        eom = bool(attrs & 0x01)
        return bytes(data[:transfer_size]), eom
