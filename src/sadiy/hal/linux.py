"""Linux backends for the BeagleBone Black and Raspberry Pi.

SPI uses spidev (stable API on both boards). GPIO uses sysfs for now because the
python libgpiod API differs between v1 (BBB Debian images) and v2 (newer images).
Replace SysfsGpio with a libgpiod backend once the target image is fixed.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

from .base import AnalogInput, BenchBackend, GpioLine, I2cBus, SpiBus


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

    def set_direction(self, output: bool, initial: int = 0) -> None:
        (self._dir / "direction").write_text(("high" if initial else "low") if output else "in")


class LinuxI2c(I2cBus):
    """One device on /dev/i2c-<bus>, through plain read / write (needs no extra package)."""

    I2C_SLAVE = 0x0703      # from linux/i2c-dev.h

    def __init__(self, bus: int, address: int) -> None:
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        try:
            fcntl.ioctl(self._fd, self.I2C_SLAVE, address)
        except OSError:
            os.close(self._fd)
            raise

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def read(self, count: int) -> bytes:
        return os.read(self._fd, count)

    def close(self) -> None:
        os.close(self._fd)


class IioChannel(AnalogInput):
    """On-chip ADC channel through IIO sysfs."""

    def __init__(self, channel: int, device: str = "iio:device0") -> None:
        self._path = Path(f"/sys/bus/iio/devices/{device}/in_voltage{channel}_raw")

    def read_raw(self) -> int:
        return int(self._path.read_text().strip())


class LinuxBackend(BenchBackend):
    """The real board. Bus and device numbers come from the [bench] config section."""

    name = "BBB (sysfs GPIO, spidev, i2c-dev, IIO)"

    def __init__(self, spi_bus: int = 1, spi_device: int = 0, spi_hz: int = 1_000_000, i2c_bus: int = 2,
                 i2c_address: int = 0x48, iio_device: str = "iio:device0") -> None:
        self._spi_args = (spi_bus, spi_device, spi_hz)
        self._i2c_args = (i2c_bus, i2c_address)
        self._iio_device = iio_device

    def gpio(self, number: int, output: bool = False, initial: int = 0) -> SysfsGpio:
        return SysfsGpio(number, output, initial)

    def spi(self) -> SpidevBus:
        return SpidevBus(*self._spi_args)

    def i2c(self) -> LinuxI2c:
        return LinuxI2c(*self._i2c_args)

    def ain(self, channel: int) -> IioChannel:
        return IioChannel(channel, self._iio_device)

    def set_mux(self, config_pin_name: str, mode: str) -> None:
        try:
            subprocess.run(["config-pin", config_pin_name, mode], check=True, capture_output=True, text=True, timeout=5)
        except subprocess.CalledProcessError as exc:
            raise OSError(f"config-pin {config_pin_name} {mode}: {exc.stderr.strip() or exc}") from exc
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"config-pin {config_pin_name} {mode}: {exc}") from exc
