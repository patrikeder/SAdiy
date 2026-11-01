"""ADC front ends for the detector output voltage."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Adc(ABC):
    @abstractmethod
    def read_volts(self, n: int = 1) -> float:
        """Mean of n samples, in volts at the ADC pin."""


class BbbIioAdc(Adc):
    """BeagleBone Black on-chip 12-bit ADC through IIO sysfs.

    Input range is 0 to 1.8 V. Anything above that can damage the SoC, so the detector
    output needs a divider and clamp first. sysfs reads are slow and jittery, so this is
    only for first light. Move to the IIO buffer interface or the PRU for real sweeps.
    """

    def __init__(self, channel: int = 0, vref: float = 1.8, device: str = "iio:device0") -> None:
        self._path = f"/sys/bus/iio/devices/{device}/in_voltage{channel}_raw"
        self._scale = vref / 4095.0

    def read_volts(self, n: int = 1) -> float:
        total = 0
        for _ in range(n):
            with open(self._path) as fh:
                total += int(fh.read())
        return total / n * self._scale


class Ads1115(Adc):
    """TODO: I2C ADS1115 (16-bit, up to 860 SPS). Needed on RPi, optional on BBB."""

    def read_volts(self, n: int = 1) -> float:
        raise NotImplementedError("ADS1115 driver not written yet")
