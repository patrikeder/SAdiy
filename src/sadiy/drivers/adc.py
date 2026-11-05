"""ADC front ends for the detector output voltage."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable

from ..hal.base import I2cBus


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
    """I2C ADS1115: 16-bit, up to 860 SPS, single-shot conversions on one single-ended channel.

    Register layout from memory of the datasheet, VERIFY on the breakout: pointer 0 = conversion,
    1 = config; config bits OS[15], MUX[14:12] (100 + channel = AINx to GND), PGA[11:9], MODE[8]
    (1 = single shot), DR[7:5], comparator[4:0] (00011 = off).
    """

    REG_CONVERSION = 0
    REG_CONFIG = 1
    FULL_SCALE_V = {6.144: 0, 4.096: 1, 2.048: 2, 1.024: 3, 0.512: 4, 0.256: 5}
    RATES_SPS = {8: 0, 16: 1, 32: 2, 64: 3, 128: 4, 250: 5, 475: 6, 860: 7}

    def __init__(self, i2c: I2cBus, full_scale_v: float = 4.096, sps: int = 128, channel: int = 0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if full_scale_v not in self.FULL_SCALE_V:
            raise ValueError(f"full scale must be one of {sorted(self.FULL_SCALE_V)} V")
        if sps not in self.RATES_SPS:
            raise ValueError(f"rate must be one of {sorted(self.RATES_SPS)} SPS")
        self._i2c = i2c
        self.full_scale_v = full_scale_v
        self.sps = sps
        self.channel = channel
        self._sleep = sleep

    def read_register(self, reg: int) -> int:
        self._i2c.write(bytes([reg]))
        data = self._i2c.read(2)
        return (data[0] << 8) | data[1]

    def write_register(self, reg: int, value: int) -> None:
        self._i2c.write(bytes([reg, value >> 8, value & 0xFF]))

    def config_word(self, channel: int) -> int:
        """Start one single-shot conversion of AINx against GND, comparator off."""
        if not 0 <= channel <= 3:
            raise ValueError("ADS1115 channel must be 0..3")
        return (1 << 15) | ((4 + channel) << 12) | (self.FULL_SCALE_V[self.full_scale_v] << 9) | (1 << 8) \
            | (self.RATES_SPS[self.sps] << 5) | 0b00011

    def convert(self, channel: int) -> int:
        """One conversion. Returns the signed code; raises TimeoutError when it never finishes."""
        self.write_register(self.REG_CONFIG, self.config_word(channel))
        for _ in range(10):
            self._sleep(1.2 / self.sps)
            if self.read_register(self.REG_CONFIG) & 0x8000:
                raw = self.read_register(self.REG_CONVERSION)
                return raw - 0x10000 if raw & 0x8000 else raw
        raise TimeoutError("ADS1115 conversion did not finish")

    def to_volts(self, code: int) -> float:
        return code * self.full_scale_v / 32768.0

    def read_volts(self, n: int = 1) -> float:
        return sum(self.to_volts(self.convert(self.channel)) for _ in range(n)) / n

    def close(self) -> None:
        self._i2c.close()
