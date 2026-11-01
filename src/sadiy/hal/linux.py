"""Linux backends for the BeagleBone Black and Raspberry Pi.

SPI uses spidev (stable API on both boards). GPIO uses sysfs for now because the
python libgpiod API differs between v1 (BBB Debian images) and v2 (newer images).
Replace SysfsGpio with a libgpiod backend once the target image is fixed.
"""
from __future__ import annotations

from pathlib import Path

from .base import GpioLine, SpiBus


class SpidevBus(SpiBus):
    def __init__(self, bus: int, device: int, speed_hz: int = 1_000_000, mode: int = 0) -> None:
        import spidev  # imported late so PCs without spidev can still run the sim

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = mode

    def xfer(self, data: bytes) -> bytes:
        return bytes(self._spi.xfer2(list(data)))

    def close(self) -> None:
        self._spi.close()


class SysfsGpio(GpioLine):
    """GPIO via /sys/class/gpio. `number` is the kernel GPIO number (bank*32 + bit)."""

    ROOT = Path("/sys/class/gpio")

    def __init__(self, number: int, output: bool = True, initial: int = 0) -> None:
        self._dir = self.ROOT / f"gpio{number}"
        if not self._dir.exists():
            (self.ROOT / "export").write_text(str(number))
        # "high" / "low" set the direction and the level in one step, so an output never glitches to 0
        direction = ("high" if initial else "low") if output else "in"
        (self._dir / "direction").write_text(direction)

    def write(self, value: int) -> None:
        (self._dir / "value").write_text("1" if value else "0")

    def read(self) -> int:
        return int((self._dir / "value").read_text().strip())
