"""ADC front ends for the detector output voltage."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class Adc(ABC):
    @abstractmethod
    def read_volts(self, n: int = 1) -> float:
        """Mean of n samples, in volts at the ADC pin."""

    def read_samples(self, n: int = 1) -> List[float]:
        """The n samples themselves, in volts at the ADC pin, so the sweep can reject outliers."""
        return [self.read_volts(1) for _ in range(n)]


class BbbIioAdc(Adc):
    """BeagleBone Black on-chip 12-bit ADC through IIO sysfs.

    Input range is 0 to 1.8 V. Anything above that can damage the SoC, so the detector
    output needs a divider and clamp first. sysfs reads are slow and jittery, so this is
    only for first light. Move to the IIO buffer interface or the PRU for real sweeps.
    """

    def __init__(self, channel: int = 0, vref: float = 1.8, device: str = "iio:device0") -> None:
        self._path = f"/sys/bus/iio/devices/{device}/in_voltage{channel}_raw"
        self._scale = vref / 4095.0

    def read_samples(self, n: int = 1) -> List[float]:
        out = []
        for _ in range(n):
            with open(self._path) as fh:
                out.append(int(fh.read()) * self._scale)
        return out

    def read_volts(self, n: int = 1) -> float:
        return sum(self.read_samples(n)) / n
