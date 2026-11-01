"""PE4302 6-bit digital step attenuator on a module with parallel control only.

The module has six logic inputs V1..V6, one per attenuator stage. There is no serial interface and
no latch-enable pin, so the inputs act directly. Default assumptions, both module-specific and to
be VERIFIED with tools/bringup.py pe4302-walk:
  - V1..V6 weigh 0.5, 1, 2, 4, 8, 16 dB
  - a high level switches the stage in (adds its attenuation)

The six GPIO writes are not simultaneous. To keep every intermediate state at least as attenuating
as the lower of the old and the new setting, stages that turn on are written before stages that turn
off ("make before break"). Going from 15.5 dB to 16 dB therefore passes through 31.5 dB, never
through 0 dB, which protects the amplifier, mixer and detector behind it.

At construction all stages are switched in (31.5 dB), the safe state.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..hal.base import GpioLine

STEP_DB = 0.5
DEFAULT_WEIGHTS_DB = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)


class PE4302:
    STEP_DB = STEP_DB

    def __init__(
        self,
        lines: Sequence[GpioLine],
        weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
        active_high: bool = True,
    ) -> None:
        if len(lines) != len(weights_db):
            raise ValueError("one GPIO line per stage is required")
        self._steps = [int(round(w / STEP_DB)) for w in weights_db]
        for s in self._steps:
            if s < 1 or (s & (s - 1)) != 0:
                raise ValueError("stage weights must be 0.5 dB times a power of two")
        if len(set(self._steps)) != len(self._steps):
            raise ValueError("stage weights must be distinct")
        self._lines = list(lines)
        self._active_high = active_high
        self._max_code = sum(self._steps)
        self._code: Optional[int] = None
        self.safe_state()

    @property
    def max_db(self) -> float:
        return self._max_code * STEP_DB

    @property
    def attenuation_db(self) -> float:
        return self._code * STEP_DB

    def code_for(self, db: float) -> int:
        """Attenuation in 0.5 dB steps, clamped to what the stages can produce."""
        return max(0, min(self._max_code, int(db / STEP_DB + 0.5)))

    def _drive(self, i: int, on: bool) -> None:
        self._lines[i].write(1 if on == self._active_high else 0)

    def safe_state(self) -> float:
        """Switch every stage in (maximum attenuation)."""
        for i in range(len(self._lines)):
            self._drive(i, True)
        self._code = self._max_code
        return self.attenuation_db

    def set_attenuation(self, db: float) -> float:
        """Set the attenuation (rounded to 0.5 dB, clamped). Returns the value set."""
        new, old = self.code_for(db), self._code
        turning_on = [i for i, s in enumerate(self._steps) if new & s and not old & s]
        turning_off = [i for i, s in enumerate(self._steps) if old & s and not new & s]
        for i in turning_on:      # make ...
            self._drive(i, True)
        for i in turning_off:     # ... before break
            self._drive(i, False)
        self._code = new
        return self.attenuation_db
