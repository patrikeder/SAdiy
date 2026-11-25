"""PE4302 6-bit digital step attenuator on a module with parallel control only.

The module has six logic inputs V1..V6, one per attenuator stage. There is no serial interface and
no latch-enable pin, so the inputs act directly. On this analyzer they hang on a PCF8574 port expander on I2C
(`drivers/pcf8574.py`, since 2026-11-25): use `PE4302Pcf8574`. `PE4302` itself works on any six lines. Default assumptions, both module-specific and to
be VERIFIED with tools/bringup.py pe4302-walk:
  - V1..V6 weigh 0.5, 1, 2, 4, 8, 16 dB
  - a high level switches the stage in (adds its attenuation)

Six separate line writes are not simultaneous. To keep every intermediate state at least as attenuating
as the lower of the old and the new setting, stages that turn on are written before stages that turn
off ("make before break"). Going from 15.5 dB to 16 dB therefore passes through 31.5 dB, never
through 0 dB, which protects the amplifier, mixer and detector behind it.

Through the PCF8574 a change is one I2C write: the "make" byte (old and new stages in), then the final byte.

At construction all stages are switched in (31.5 dB), the safe state.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..hal.base import GpioLine
from . import pcf8574

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
        self._change(list(range(len(self._lines))), [], self._max_code)
        self._code = self._max_code
        return self.attenuation_db

    def sync_from_lines(self) -> float:
        """Adopt the attenuation the lines show now, after something else wrote them (bench mode)."""
        on = 1 if self._active_high else 0
        self._code = sum(s for ln, s in zip(self._lines, self._steps) if ln.read() == on)
        return self.attenuation_db

    def set_attenuation(self, db: float) -> float:
        """Set the attenuation (rounded to 0.5 dB, clamped). Returns the value set."""
        new, old = self.code_for(db), self._code
        turning_on = [i for i, s in enumerate(self._steps) if new & s and not old & s]
        turning_off = [i for i, s in enumerate(self._steps) if old & s and not new & s]
        self._change(turning_on, turning_off, new)
        self._code = new
        return self.attenuation_db

    def _change(self, turning_on: Sequence[int], turning_off: Sequence[int], new: int) -> None:
        """Put the stages on the lines: `turning_on` first, then `turning_off`; `new` is the code afterwards."""
        for i in turning_on:      # make ...
            self._drive(i, True)
        for i in turning_off:     # ... before break
            self._drive(i, False)


class PE4302Pcf8574(PE4302):
    """The PE4302 module behind the PCF8574. Each change is one I2C write of one or two bytes: first the "make"
    state (old and new stages in), then the final one, so no intermediate state is below the lower of the two.
    `last_bytes` holds the port bytes of the last write."""

    def __init__(self, port: pcf8574.Pcf8574, weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
                 active_high: bool = True) -> None:
        self.port = port
        self.last_bytes: List[int] = []
        super().__init__(pcf8574.lines(port), weights_db, active_high)

    def levels_for(self, code: int) -> int:
        """Line levels (bit 0 = V1) that switch in the stages of `code` (0.5 dB steps)."""
        return sum(1 << i for i, s in enumerate(self._steps) if bool(code & s) == self._active_high)

    def _change(self, turning_on: Sequence[int], turning_off: Sequence[int], new: int) -> None:
        make = new
        for i in turning_off:
            make |= self._steps[i]
        states = [self.levels_for(make)]
        if make != new:
            states.append(self.levels_for(new))
        self.last_bytes = self.port.write(*states)

    def write_current(self) -> None:
        """Write the present setting again (after something else used the I2C lines)."""
        self.last_bytes = self.port.write(self.levels_for(self._code))

    def apply_lines(self, changes: Dict[int, int]) -> None:
        """Set some of V1..V6 (index 0 = V1 -> level) and leave the others, in one write with make-before-break:
        lines that switch their stage in change in the first byte."""
        cur = self.port.levels
        in_level = 1 if self._active_high else 0
        make = final = cur
        for i, level in changes.items():
            final = final | (1 << i) if level else final & ~(1 << i)
            if level == in_level:
                make = make | (1 << i) if level else make & ~(1 << i)
        if final == cur:
            self.last_bytes = []
            return
        states = [final] if make in (cur, final) else [make, final]
        self.last_bytes = self.port.write(*states)
        self._code = self._code_of(final)

    def set_levels(self, levels: int) -> None:
        """Exactly these line levels in one byte, no make-before-break (wiring test)."""
        self.last_bytes = self.port.write(levels)
        self._code = self._code_of(levels)

    def _code_of(self, levels: int) -> int:
        return sum(s for i, s in enumerate(self._steps) if bool(levels >> i & 1) == self._active_high)

    def sync_from_lines(self) -> float:
        """Adopt what the pins show now."""
        self._code = self._code_of(self.port.read_levels())
        return self.attenuation_db

    def readback_matches(self) -> bool:
        """False when a pin does not follow what was written: a missing pull-up or a short."""
        return self.port.read_levels() == self.port.levels
