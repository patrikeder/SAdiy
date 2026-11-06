from __future__ import annotations

from abc import ABC, abstractmethod

# Rough figures for what the Python sysfs / spidev paths can do on a BBB. Estimates, NOT measured on the
# board: the bench reports the rate it really achieved while a pattern runs.
SYSFS_WRITES_PER_S = 3000.0
SPIDEV_WORDS_PER_S = 1000.0


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

    def set_direction(self, output: bool, initial: int = 0) -> None:
        """Make the line an output at level `initial` (in one step, no glitch) or an input."""
        raise NotImplementedError


class I2cBus(ABC):
    """One device on an I2C bus."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """One write transfer."""

    @abstractmethod
    def read(self, count: int) -> bytes:
        """One read transfer."""

    def close(self) -> None:
        pass


class AnalogInput(ABC):
    @abstractmethod
    def read_raw(self) -> int:
        """One conversion, as the raw ADC code."""


class BenchBackend(ABC):
    """Everything the bench mode needs from the board. Linux in `linux.py`, recording fake in `fake.py`."""

    name = "abstract"
    simulated = False
    max_writes_per_s = SYSFS_WRITES_PER_S
    max_spi_words_per_s = SPIDEV_WORDS_PER_S
    can_mux = True      # False: bus pins can not change function here (no config-pin on this image)

    @abstractmethod
    def gpio(self, number: int, output: bool = False, initial: int = 0) -> GpioLine:
        """Open a line by its pin map number, bank * 32 + bit."""

    @abstractmethod
    def spi(self) -> SpiBus:
        """The SPI bus of the ADF4351."""

    @abstractmethod
    def i2c(self) -> I2cBus:
        """The ADS1115 on its I2C bus."""

    @abstractmethod
    def ain(self, channel: int) -> AnalogInput:
        """An on-chip ADC channel."""

    @abstractmethod
    def set_mux(self, config_pin_name: str, mode: str) -> None:
        """Switch a header pin between GPIO and its bus function, for example ("P9_22", "gpio")."""
