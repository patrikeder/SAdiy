"""PCF8574 I2C port expander that drives the six PE4302 inputs (user wiring, 2026-11-25).

The board is an I2C-to-LCD adapter ("LCD backpack"), so one port bit is its backlight:

    port bit   P7   P6   P5   P4   P3          P2   P1   P0
    signal     p7   V6   V5   V4   backlight   V3   V2   V1

There is no V0. The same mapping is in the PL engine (`rtl/src/pcf8574_att.sv`, register map 2.0).

The PCF8574 has no registers: every data byte of a write sets the whole port, and several data bytes in one
write are applied one after the other, which gives make-before-break in a single transaction. A read returns the
levels of the pins. A pin written high is only pulled up weakly (about 100 uA) and the PE4302 module has 10 kohm
pull-downs on V1..V6, so every V line needs a pull-up to 3.3 V (2.2 kohm). Without it the read shows a low.
It powers up with all pins high: all stages in, 31.5 dB, the safe state.

Address 0x27 (PCF8574, A0..A2 open); a PCF8574A answers at 0x38..0x3F.
"""
from __future__ import annotations

from typing import List, Sequence

from ..hal.base import GpioLine, I2cBus

DEFAULT_ADDRESS = 0x27
V_BITS = (0, 1, 2, 4, 5, 6)          # port bit of V1..V6
BACKLIGHT_BIT = 3
SPARE_BIT = 7
ALL_HIGH = 0xFF                      # power-up state


def port_byte(levels: int, p3: int = 1, p7: int = 1) -> int:
    """Port byte for the line levels of V1..V6 (`levels` bit 0 = V1)."""
    byte = (bool(p3) << BACKLIGHT_BIT) | (bool(p7) << SPARE_BIT)
    for i, bit in enumerate(V_BITS):
        byte |= ((levels >> i) & 1) << bit
    return byte


def levels_of(byte: int) -> int:
    """V1..V6 levels (bit 0 = V1) in a port byte."""
    return sum(((byte >> bit) & 1) << i for i, bit in enumerate(V_BITS))


class Pcf8574:
    """The expander on its bus. `levels` is what was written last (bit 0 = V1); nothing is written until `write`."""

    def __init__(self, i2c: I2cBus, backlight: int = 1, p7: int = 1) -> None:
        self._i2c = i2c
        self.backlight = 1 if backlight else 0
        self.p7 = 1 if p7 else 0
        self.levels = levels_of(ALL_HIGH)

    def byte_for(self, levels: int) -> int:
        return port_byte(levels, self.backlight, self.p7)

    def write(self, *levels: int) -> List[int]:
        """One transaction with one port byte per given V1..V6 state, in order. Returns the bytes."""
        if not levels:
            raise ValueError("nothing to write")
        data = [self.byte_for(v) for v in levels]
        self._i2c.write(bytes(data))
        self.levels = levels[-1] & 0x3F
        return data

    def read_byte(self) -> int:
        """The levels of the eight pins."""
        data = self._i2c.read(1)
        if len(data) != 1:
            raise OSError("the PCF8574 returned no data")
        return data[0]

    def read_levels(self) -> int:
        return levels_of(self.read_byte())

    def close(self) -> None:
        self._i2c.close()


class Pcf8574Line(GpioLine):
    """One of V1..V6 as a line, for code that works on lines (the walk tool, bench patterns). Every write is a
    transaction of its own."""

    def __init__(self, port: Pcf8574, index: int) -> None:
        self.port, self.index = port, index

    def write(self, value: int) -> None:
        mask = 1 << self.index
        self.port.write((self.port.levels & ~mask) | (mask if value else 0))

    def read(self) -> int:
        return (self.port.read_levels() >> self.index) & 1

    def direction(self) -> str:
        return "out"

    def set_direction(self, output: bool, initial: int = 0) -> None:
        self.write(initial if output else 1)       # released = written high, the weak pull-up of the chip


def lines(port: Pcf8574) -> Sequence[Pcf8574Line]:
    return [Pcf8574Line(port, i) for i in range(len(V_BITS))]
