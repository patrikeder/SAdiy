from __future__ import annotations

from abc import ABC, abstractmethod


class SpiBus(ABC):
    @abstractmethod
    def xfer(self, data: bytes) -> bytes:
        """Full-duplex transfer. Chip select stays asserted for the whole call."""

    def close(self) -> None:
        pass


class GpioLine(ABC):
    @abstractmethod
    def write(self, value: int) -> None:
        """Drive the line to 0 or 1."""

    @abstractmethod
    def read(self) -> int:
        """Return the current level, 0 or 1."""
