"""ADF4351 wideband synthesizer used as the swept LO.

Status: PLL parameter math (core.freqplan.plan_pll) is done and tested. Register packing is
NOT written yet. It must be done against the datasheet register maps (R0..R5) and checked
against a known-good configuration from ADI's evaluation software before first use.

Checklist for `registers()`:
- R0: INT, FRAC.   R1: MOD, phase, prescaler (4/5 or 8/9 depends on INT).
- R2: R counter, MUXOUT (digital lock detect), charge pump current, low-noise vs low-spur mode.
- R3: clock divider, band select clock mode.  R4: RF divider select, band select clock
  divider, output power, aux output off, mute-till-lock-detect.  R5: lock detect pin mode.
- Write order at init: R5, R4, R3, R2, R1, R0. During a sweep, write R0 only when the divider
  and MOD are unchanged (writing R0 triggers VCO band-select autocalibration).
- SPI: mode 0, MSB first, 32-bit words, LE is the SPI chip select.
"""
from __future__ import annotations

from typing import List

from ..core.freqplan import PllPlan, SweepPoint, plan_pll
from ..hal.base import SpiBus


class Adf4351:
    def __init__(self, spi: SpiBus, pfd_hz: float, mod_max: int = 4095) -> None:
        self._spi = spi
        self.pfd_hz = pfd_hz
        self.mod_max = mod_max

    def plan(self, f_lo_hz: float) -> PllPlan:
        return plan_pll(f_lo_hz, self.pfd_hz, self.mod_max)

    def registers(self, pll: PllPlan) -> List[int]:
        raise NotImplementedError("ADF4351 register packing: see module docstring checklist")

    def write_word(self, word: int) -> None:
        self._spi.xfer(word.to_bytes(4, "big"))

    def tune(self, point: SweepPoint) -> None:
        pll = point.pll or self.plan(point.f_lo_hz)
        for word in self.registers(pll):
            self.write_word(word)
