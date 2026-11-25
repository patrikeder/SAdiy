"""Recording fakes for development on a PC and for tests."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from .base import AnalogInput, BenchBackend, GpioLine, I2cBus, SpiBus


class PinLog:
    """Shared, ordered log of every pin write, so tests can replay bit-banged protocols."""

    def __init__(self) -> None:
        self.events: List[Tuple[str, int]] = []
        self.directions: List[Tuple[str, str]] = []

    def writes(self, name: str) -> List[int]:
        """Every level written to one line, in order."""
        return [level for n, level in self.events if n == name]


class FakeGpio(GpioLine):
    def __init__(self, name: str, log: PinLog, initial: int = 0, output: bool = True) -> None:
        self.name = name
        self.log = log
        self.level = initial
        self.output = output
        self.external = 0                # what a board drives on the line while it is an input

    def write(self, value: int) -> None:
        if not self.output:
            raise OSError(f"{self.name} is an input")   # sysfs refuses this too
        self.level = 1 if value else 0
        self.log.events.append((self.name, self.level))

    def read(self) -> int:
        return self.level if self.output else self.external

    def direction(self) -> str:
        return "out" if self.output else "in"

    def set_direction(self, output: bool, initial: int = 0) -> None:
        self.output = output
        self.log.directions.append((self.name, "out" if output else "in"))
        if output:
            self.write(initial)


class FakeSpi(SpiBus):
    def __init__(self, on_xfer: Optional[Callable[[bytes], None]] = None) -> None:
        self.sent: List[bytes] = []
        self.on_xfer = on_xfer
        self.closed = False

    def xfer(self, data: bytes) -> bytes:
        self.sent.append(bytes(data))
        if self.on_xfer is not None:
            self.on_xfer(bytes(data))
        return bytes(len(data))

    def close(self) -> None:
        self.closed = True


class FakePcf8574(I2cBus):
    """Model of a PCF8574: each byte of a write sets the port; a read returns the pin levels. `pulled_down` is a
    mask of pins that read low although written high (a missing pull-up); with `present` False nobody answers."""

    def __init__(self) -> None:
        self.port = 0xFF                          # power-up: all pins high
        self.writes: List[bytes] = []             # one entry per transaction
        self.bytes: List[int] = []                # every port state, in order
        self.pulled_down = 0
        self.present = True
        self.closed = False

    def _check(self) -> None:
        if not self.present:
            raise OSError(121, "Remote I/O error (no acknowledge)")

    def write(self, data: bytes) -> None:
        self._check()
        self.writes.append(bytes(data))
        self.bytes.extend(data)
        self.port = data[-1]

    def read(self, count: int) -> bytes:
        self._check()
        return bytes([self.port & ~self.pulled_down & 0xFF]) * count

    def close(self) -> None:
        self.closed = True


class FakeAnalog(AnalogInput):
    def __init__(self, raw: int = 0) -> None:
        self.raw = raw

    def read_raw(self) -> int:
        return self.raw


class FakeBackend(BenchBackend):
    """A whole board made of recording fakes. Lines are named gpio<n> and remembered across opens.

    `lock_gpio` is the line that goes high once an R0 word (address bits 000) was sent over SPI, a
    crude model of the PLL locking so the "enable the outputs after lock" flow can be exercised.
    """

    name = "fake backend"
    simulated = True

    def __init__(self, lock_gpio: Optional[int] = None, ain_raw: int = 1500, can_mux: bool = True) -> None:
        self.can_mux = can_mux
        self.log = PinLog()
        self.lines: Dict[int, FakeGpio] = {}
        self.spi_bus: Optional[FakeSpi] = None
        self.spi_sent: List[bytes] = []          # every SPI word of every session
        self.pcf = FakePcf8574()
        self.analog: Dict[int, FakeAnalog] = {0: FakeAnalog(ain_raw)}
        self.mux_log: List[Tuple[str, str]] = []
        self.lock_gpio = lock_gpio

    def gpio(self, number: int, output: bool = False, initial: int = 0) -> FakeGpio:
        line = self.lines.get(number)
        if line is None:
            line = self.lines[number] = FakeGpio(f"gpio{number}", self.log, initial, output)
        line.set_direction(output, initial)
        return line

    def _on_xfer(self, data: bytes) -> None:
        self.spi_sent.append(data)
        if self.lock_gpio is not None and len(data) == 4 and data[3] & 7 == 0:
            self.gpio_line(self.lock_gpio).external = 1

    def gpio_line(self, number: int) -> FakeGpio:
        """The line itself, for tests. Does not touch its direction."""
        if number not in self.lines:
            self.lines[number] = FakeGpio(f"gpio{number}", self.log, 0, False)
        return self.lines[number]

    def spi(self) -> FakeSpi:
        self.spi_bus = FakeSpi(self._on_xfer)
        return self.spi_bus

    def i2c(self) -> FakePcf8574:
        self.pcf.closed = False
        return self.pcf

    def ain(self, channel: int) -> FakeAnalog:
        return self.analog.setdefault(channel, FakeAnalog(0))

    def set_mux(self, config_pin_name: str, mode: str) -> None:
        self.mux_log.append((config_pin_name, mode))
