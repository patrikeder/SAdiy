"""ADF4351 wideband synthesizer used as the swept LO.

Status: PLL parameter math (core.freqplan.plan_pll), the R4 word (RF outputs) and R0..R3 and R5
are written and unit-tested for field positions. None of the words has been checked against the
datasheet text or ADI's evaluation software yet: do that (tests/test_adf4351_registers.py) before the
first RF test, and note any difference there.

RF outputs are OFF by default
-----------------------------
Both outputs (main = RFOUTA, aux = RFOUTB) are off after construction, and the constructor already
writes an R4 word with both disabled (`safe_state`). An output is on only after it was enabled
explicitly with `enable_output()` / `set_outputs()`. Do that after the PLL is programmed and
locked, so no unlocked VCO signal reaches the mixer LO port. Every R4 write, including the one in
`registers()`, takes the output state from `self.outputs`; never hard-code an R4 constant.
Only the output that is cabled should be enabled. The complementary pin of an enabled output
(AOUT+ / AOUT- on the eval board) cannot be switched off separately: terminate it in 50 ohm.

What `registers()` sets:
- R0: INT, FRAC.   R1: MOD, phase 1, prescaler 4/5 up to 3.6 GHz VCO, else 8/9.
- R2: R = 1, MUXOUT three-state, charge pump current, positive PD polarity, integer-N lock detect
  settings when FRAC = 0, low-noise mode unless `low_spur`.
- R3: band select clock mode low, clock divider off; ABP 3 ns and charge cancel when FRAC = 0.
- R4: `self.r4_word(pll.rf_div)`.   R5: LD pin = digital lock detect.
- Write order: R5, R4, R3, R2, R1, R0. `tune()` still writes all six per point. Possible speed-up once
  measured: write only the words that changed, R0 last (writing R0 triggers VCO band-select calibration).
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


# --- R0..R3 and R5 -----------------------------------------------------------------------------
# Field positions follow the datasheet register maps as cross-read from a third-party register
# description and the ADI example words 0x00580005 (R5), 0x000004B3 (R3), 0x00004E42 (R2) and
# 0x08008029 (R1), all from memory: VERIFY every word against ADI's evaluation software before the
# first RF test (tests/test_adf4351_registers.py has the fixture to compare with).
PRESCALER_89_MIN_VCO_HZ = 3.6e9     # above this VCO frequency the 8/9 prescaler is required
INT_MIN_45, INT_MIN_89 = 23, 75     # smallest INT with the 4/5 and the 8/9 prescaler
DEFAULT_CP_INDEX = 7                # 2.50 mA with the usual 5.1 kohm Rset (VERIFY on the board's loop filter)
DEFAULT_CLOCK_DIVIDER = 150         # R3 clock divider value as in ADI's words; unused while the mode is off
PHASE_WORD = 1                      # R1 phase value ADI recommends


def prescaler_89(f_vco_hz: float) -> bool:
    """4/5 up to 3.6 GHz VCO (better phase noise), 8/9 above."""
    return f_vco_hz > PRESCALER_89_MIN_VCO_HZ


def pack_r0(int_n: int, frac: int) -> int:
    if not 0 <= int_n <= 0xFFFF:
        raise ValueError("INT must fit 16 bits")
    if not 0 <= frac <= 0xFFF:
        raise ValueError("FRAC must fit 12 bits")
    return (int_n << 15) | (frac << 3)


def pack_r1(mod: int, prescaler89: bool, phase: int = PHASE_WORD) -> int:
    """Register 1: phase adjust off, prescaler, phase, MOD."""
    if not 2 <= mod <= 4095:
        raise ValueError("MOD must be 2..4095")
    if not 0 <= phase < mod:
        raise ValueError("phase must be below MOD")
    return (int(prescaler89) << 27) | (phase << 15) | (mod << 3) | 0b001


def pack_r2(int_mode: bool, cp_index: int = DEFAULT_CP_INDEX, low_spur: bool = False) -> int:
    """Register 2: R = 1 (the reference is the PFD frequency), no doubler, MUXOUT three-state (the lock
    detect comes from the LD pin, see R5), positive phase detector polarity (passive loop filter), charge
    pump on. `int_mode` (FRAC = 0) uses the integer-N lock detect settings (5 cycles, 6 ns)."""
    if not 0 <= cp_index <= 15:
        raise ValueError("charge pump current index must be 0..15")
    word = (1 << 14) | (cp_index << 9) | (1 << 6) | 0b010          # R = 1, CP current, PD polarity +
    if int_mode:
        word |= (1 << 8) | (1 << 7)                                # LDF = 1, LDP = 1
    if low_spur:
        word |= 0b11 << 29
    return word


def pack_r3(int_mode: bool, clock_divider: int = DEFAULT_CLOCK_DIVIDER) -> int:
    """Register 3: band select clock mode low (needs a band select clock of 125 kHz or less, see
    `default_band_select_div`), clock divider mode off. For integer-N the anti-backlash pulse is 3 ns and
    charge cancellation is on; for fractional-N both stay off."""
    if not 0 <= clock_divider <= 0xFFF:
        raise ValueError("clock divider value must fit 12 bits")
    word = (clock_divider << 3) | 0b011
    if int_mode:
        word |= (1 << 22) | (1 << 21)                              # ABP 3 ns, charge cancel on
    return word


def pack_r5() -> int:
    """Register 5: LD pin = digital lock detect (DB23:22 = 01), reserved bits DB20:19 = 11."""
    return (0b01 << 22) | (0b11 << 19) | 0b101


class Adf4351:
    def __init__(self, spi: SpiBus, pfd_hz: float, mod_max: int = 4095, cp_index: int = DEFAULT_CP_INDEX,
                 low_spur: bool = False) -> None:
        self._spi = spi
        self.pfd_hz = pfd_hz
        self.mod_max = mod_max
        self.cp_index = cp_index
        self.low_spur = low_spur
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
        """The six words for `pll` in write order R5, R4, R3, R2, R1, R0 (R0 last: it starts the VCO band
        calibration). R4 takes the RF output state from `self.outputs`. FRAC = 0 selects the integer-N
        settings in R2 and R3, so those two words differ between integer and fractional points."""
        if pll.rf_div not in DIVIDERS:
            raise ValueError(f"rf_div must be one of {DIVIDERS}")
        if not 0 <= pll.frac < pll.mod:
            raise ValueError("FRAC must be below MOD")
        p89 = prescaler_89(pll.f_vco_hz)
        int_min = INT_MIN_89 if p89 else INT_MIN_45
        if not int_min <= pll.int_n <= 0xFFFF:
            raise ValueError(f"INT {pll.int_n} is outside {int_min}..65535 for the "
                             f"{'8/9' if p89 else '4/5'} prescaler")
        int_mode = pll.frac == 0
        return [
            pack_r5(),
            self.r4_word(pll.rf_div),
            pack_r3(int_mode),
            pack_r2(int_mode, self.cp_index, self.low_spur),
            pack_r1(pll.mod, p89),
            pack_r0(pll.int_n, pll.frac),
        ]

    def write_word(self, word: int) -> None:
        self._spi.xfer(word.to_bytes(4, "big"))

    def tune(self, point: SweepPoint) -> None:
        pll = point.pll or self.plan(point.f_lo_hz)
        for word in self.registers(pll):
            self.write_word(word)
        self._rf_div = pll.rf_div
