"""Recording fakes for development on a PC and for tests."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

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


class FakeAds1115(I2cBus):
    """Register model of an ADS1115: a single-shot conversion finishes at once."""

    FULL_SCALE_V = (6.144, 4.096, 2.048, 1.024, 0.512, 0.256, 0.256, 0.256)

    def __init__(self, volts: Sequence[float] = (0.0, 0.0, 0.0, 0.0)) -> None:
        self.volts = list(volts)
        self.regs = {0: 0, 1: 0x8583, 2: 0x8000, 3: 0x7FFF}   # power-on values from the datasheet
        self.pointer = 0
        self.writes: List[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        self.pointer = data[0] & 3
        if len(data) == 3:
            value = (data[1] << 8) | data[2]
            if self.pointer == 1 and value & 0x8000:
                self._convert(value)
                value |= 0x8000                                # OS reads 1: not busy
            self.regs[self.pointer] = value

    def _convert(self, config: int) -> None:
        mux = (config >> 12) & 7
        volts = self.volts[mux - 4] if mux >= 4 else 0.0       # only single-ended inputs are modelled
        fs = self.FULL_SCALE_V[(config >> 9) & 7]
        code = max(-32768, min(32767, round(volts / fs * 32768)))
        self.regs[0] = code & 0xFFFF

    def read(self, count: int) -> bytes:
        return self.regs[self.pointer].to_bytes(2, "big")[:count]

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

    def __init__(self, lock_gpio: Optional[int] = None, ain_raw: int = 1500, ads_volts=(1.13, 0.0, 0.0, 0.0)) -> None:
        self.log = PinLog()
        self.lines: Dict[int, FakeGpio] = {}
        self.spi_bus: Optional[FakeSpi] = None
        self.spi_sent: List[bytes] = []          # every SPI word of every session
        self.ads = FakeAds1115(ads_volts)
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

    def i2c(self) -> FakeAds1115:
        self.ads.closed = False
        return self.ads

    def ain(self, channel: int) -> FakeAnalog:
        return self.analog.setdefault(channel, FakeAnalog(0))

    def set_mux(self, config_pin_name: str, mode: str) -> None:
        self.mux_log.append((config_pin_name, mode))
