"""Abstract transport interface used by the SCPI driver.

The driver never talks to libusb directly; it only sees :class:`Transport`.
This keeps the SCPI logic identical whether we are connected to a real
instrument over USB-TMC or to the built-in :class:`SimulatedTransport`.
"""

from __future__ import annotations

import abc


class TransportError(Exception):
    """Raised for any communication failure with the instrument."""


class Transport(abc.ABC):
    """Minimal message-based transport (SCPI strings and binary blocks)."""

    #: Short human-readable description, e.g. "USB 049f:505e (DSO2D15)".
    description: str = "transport"

    @abc.abstractmethod
    def open(self) -> None:
        """Acquire the device handle.  Idempotent."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release the device handle.  Idempotent."""

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Send a raw message (the caller appends any terminator)."""

    @abc.abstractmethod
    def read(self, max_length: int = 1024 * 1024) -> bytes:
        """Read one complete response message."""

    # -- convenience helpers shared by every transport -------------------

    def write_str(self, text: str) -> None:
        self.write(text.encode("ascii"))

    def query(self, text: str, max_length: int = 1024 * 1024) -> str:
        """Write a command and return the textual response, stripped."""
        self.write_str(text)
        return self.read(max_length).decode("ascii", errors="replace").strip()

    def query_raw(self, text: str, max_length: int = 16 * 1024 * 1024) -> bytes:
        """Write a command and return the raw binary response."""
        self.write_str(text)
        return self.read(max_length)

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
