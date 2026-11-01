"""Recording fakes for development on a PC and for tests."""
from __future__ import annotations

from typing import List, Tuple

from .base import GpioLine, SpiBus


class PinLog:
    """Shared, ordered log of every pin write, so tests can replay bit-banged protocols."""

    def __init__(self) -> None:
        self.events: List[Tuple[str, int]] = []


class FakeGpio(GpioLine):
    def __init__(self, name: str, log: PinLog, initial: int = 0) -> None:
        self.name = name
        self.log = log
        self.level = initial

    def write(self, value: int) -> None:
        self.level = 1 if value else 0
        self.log.events.append((self.name, self.level))

    def read(self) -> int:
        return self.level


class FakeSpi(SpiBus):
    def __init__(self) -> None:
        self.sent: List[bytes] = []

    def xfer(self, data: bytes) -> bytes:
        self.sent.append(bytes(data))
        return bytes(len(data))
