"""ADF4351 wideband synthesizer used as the swept LO.

Status: PLL parameter math (core.freqplan.plan_pll) and the R4 word (RF outputs) are done and
tested. The other registers (R0..R3, R5) are NOT written yet. They must be done against the
datasheet register maps and checked against a known-good configuration from ADI's evaluation
software before first use.

RF outputs are OFF by default
-----------------------------
Both outputs (main = RFOUTA, aux = RFOUTB) are off after construction, and the constructor already
writes an R4 word with both disabled (`safe_state`). An output is on only after it was enabled
explicitly with `enable_output()` / `set_outputs()`. Do that after the PLL is programmed and
locked, so no unlocked VCO signal reaches the mixer LO port. Every R4 write, including the one in
`registers()`, takes the output state from `self.outputs`; never hard-code an R4 constant.
Only the output that is cabled should be enabled. The complementary pin of an enabled output
(AOUT+ / AOUT- on the eval board) cannot be switched off separately: terminate it in 50 ohm.

Checklist for `registers()`:
- R0: INT, FRAC.   R1: MOD, phase, prescaler (4/5 or 8/9 depends on INT).
- R2: R counter, MUXOUT (digital lock detect), charge pump current, low-noise vs low-spur mode.
- R3: clock divider, band select clock mode.  R4: use `self.r4_word(pll.rf_div)`.
  R5: lock detect pin mode.
- Write order at init: R5, R4, R3, R2, R1, R0. During a sweep, write R0 only when the divider
  and MOD are unchanged (writing R0 triggers VCO band-select autocalibration).
- SPI: mode 0, MSB first, 32-bit words, LE is the SPI chip select.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import List, Optional

from ..core.freqplan import DIVIDERS, PllPlan, SweepPoint, plan_pll
from ..hal.base import SpiBus

MAIN = "main"   # RFOUTA, the output used as the LO
AUX = "aux"     # RFOUTB

# Output power setting -> R4 code (RFOUT power field, 2 bits). Same steps for both outputs.
POWER_CODE = {-4: 0, -1: 1, 2: 2, 5: 3}

# R4 bit positions (ADF4351 datasheet register 4; VERIFY against the datasheet / ADI software).
_R4_ADDR = 0b100
_R4_FEEDBACK_FUNDAMENTAL = 1 << 23
_R4_RF_DIV_SHIFT = 20
_R4_BAND_SEL_DIV_SHIFT = 12
_R4_AUX_ENABLE = 1 << 8
_R4_AUX_POWER_SHIFT = 6
_R4_MAIN_ENABLE = 1 << 5
_R4_MAIN_POWER_SHIFT = 3

BAND_SEL_CLOCK_MAX_HZ = 125e3   # conservative limit for PFD / band select clock divider


@dataclass(frozen=True)
class Output:
    """State of one RF output. Off unless `enabled` is set."""

    enabled: bool = False
    power_dbm: int = -4

    def __post_init__(self) -> None:
        if self.power_dbm not in POWER_CODE:
            raise ValueError(f"output power must be one of {sorted(POWER_CODE)} dBm")


@dataclass(frozen=True)
class Outputs:
    """Both RF outputs. The default value is the safe state: everything off."""

    main: Output = field(default_factory=Output)
    aux: Output = field(default_factory=Output)

    @classmethod
    def from_config(cls, synth_cfg: dict) -> "Outputs":
        """Requested outputs from the [synth] config section. A missing key means off."""
        return cls(
            main=Output(bool(synth_cfg.get("out_main_enable", False)), int(synth_cfg.get("out_power_dbm", -4))),
            aux=Output(bool(synth_cfg.get("out_aux_enable", False)), int(synth_cfg.get("out_aux_power_dbm", -4))),
        )


def default_band_select_div(pfd_hz: float) -> int:
    """Smallest 8-bit band select clock divider that keeps PFD / divider within the limit."""
    div = max(1, math.ceil(pfd_hz / BAND_SEL_CLOCK_MAX_HZ))
    if div > 255:
        raise ValueError(f"PFD of {pfd_hz / 1e6:g} MHz is too high for an 8-bit band select divider")
    return div


def pack_r4(rf_div: int, outputs: Outputs, band_select_div: int) -> int:
    """Register 4: feedback from the VCO fundamental, RF divider, band select clock divider and
    the output enables / power. Everything else (VCO power-down, mute-till-lock-detect, aux output
    select) is left at 0. The output enables come only from `outputs`."""
    if rf_div not in DIVIDERS:
        raise ValueError(f"rf_div must be one of {DIVIDERS}")
    if not 1 <= band_select_div <= 255:
        raise ValueError("band_select_div must be 1..255")
    word = _R4_ADDR | _R4_FEEDBACK_FUNDAMENTAL
    word |= (rf_div.bit_length() - 1) << _R4_RF_DIV_SHIFT
    word |= band_select_div << _R4_BAND_SEL_DIV_SHIFT
    if outputs.main.enabled:
        word |= _R4_MAIN_ENABLE | (POWER_CODE[outputs.main.power_dbm] << _R4_MAIN_POWER_SHIFT)
    if outputs.aux.enabled:
        word |= _R4_AUX_ENABLE | (POWER_CODE[outputs.aux.power_dbm] << _R4_AUX_POWER_SHIFT)
    return word


def register_of(word: int) -> int:
    """The register a raw word goes to: its 3 address bits."""
    return word & 0b111


def r4_enables_output(word: int) -> bool:
    """True when a raw word is an R4 that switches an RF output on."""
    return register_of(word) == _R4_ADDR and bool(word & (_R4_MAIN_ENABLE | _R4_AUX_ENABLE))


def r4_with_outputs(word: int, outputs: Outputs) -> int:
    """An R4 word with its other fields kept and the output enables / power replaced."""
    if register_of(word) != _R4_ADDR:
        raise ValueError("not an R4 word")
    word &= ~(_R4_AUX_ENABLE | (3 << _R4_AUX_POWER_SHIFT) | _R4_MAIN_ENABLE | (3 << _R4_MAIN_POWER_SHIFT))
    if outputs.main.enabled:
        word |= _R4_MAIN_ENABLE | (POWER_CODE[outputs.main.power_dbm] << _R4_MAIN_POWER_SHIFT)
    if outputs.aux.enabled:
        word |= _R4_AUX_ENABLE | (POWER_CODE[outputs.aux.power_dbm] << _R4_AUX_POWER_SHIFT)
    return word


class Adf4351:
    def __init__(self, spi: SpiBus, pfd_hz: float, mod_max: int = 4095) -> None:
        self._spi = spi
        self.pfd_hz = pfd_hz
        self.mod_max = mod_max
        self.band_select_div = default_band_select_div(pfd_hz)
        self._rf_div = 1
        self.outputs = Outputs()
        self.safe_state()

    # --- RF outputs: off by default, enabled explicitly -------------------------------------
    def r4_word(self, rf_div: Optional[int] = None) -> int:
        """R4 for the current output state; `rf_div` defaults to the last divider in use."""
        return pack_r4(rf_div or self._rf_div, self.outputs, self.band_select_div)

    def safe_state(self) -> None:
        """Both RF outputs off. Done at construction, before any other register is written."""
        self.set_outputs(Outputs())

    def set_outputs(self, outputs: Outputs) -> None:
        self.outputs = outputs
        self.write_word(self.r4_word())

    def enable_output(self, which: str, power_dbm: int = -4) -> None:
        """Switch one output on (call after the PLL is programmed and locked)."""
        self.set_outputs(replace(self.outputs, **{self._name(which): Output(True, power_dbm)}))

    def disable_output(self, which: str) -> None:
        self.set_outputs(replace(self.outputs, **{self._name(which): Output(False)}))

    def disable_outputs(self) -> None:
        self.safe_state()

    @staticmethod
    def _name(which: str) -> str:
        if which not in (MAIN, AUX):
            raise ValueError(f"unknown output {which!r}, use {MAIN!r} or {AUX!r}")
        return which

    # --- PLL ----------------------------------------------------------------------------------
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
        self._rf_div = pll.rf_div
