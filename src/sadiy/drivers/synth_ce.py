"""ADF4351 chip enable (CE), driven from Linux on both boards (BBB and EBAZ4205).

CE low powers the chip down and it loses its registers: after every disable -> enable the six words must be
written again (`needs_reprogram`). The adapter holds CE high with a jumper / pull-up, so a released line (an
input) means "enabled by the board". `release()` goes back to that.

On the EBAZ4205 the PL may take CE over through an internal mux (the engine drives the pin and the Linux
EMIO state is ignored). `owner_active` is a callable that says so (see `sadiy_ebaz.ce_owner`); while it is
true a Linux write is remembered but does not reach the pin, and `set` returns False. The BBB has no such
mux: leave `owner_active` at None.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from ..hal.base import GpioLine


class SynthCe:
    def __init__(self, line: GpioLine, owner_active: Optional[Callable[[], bool]] = None,
                 settle_s: float = 0.005, sleep: Callable[[float], None] = time.sleep) -> None:
        self.line = line
        self.owner_active = owner_active
        self.settle_s = settle_s
        self._sleep = sleep
        self.requested: Optional[int] = None     # what Linux asked for: 1, 0, or None (released / never driven)
        self.needs_reprogram = False
        self._was_low = False

    def engine_owns(self) -> bool:
        return bool(self.owner_active and self.owner_active())

    def level(self) -> int:
        """The level on the pad (what the chip sees), whoever drives it."""
        return self.line.read()

    def set(self, on: bool) -> bool:
        """Drive CE high (`on`) or low. False when the engine owns the pin: the request is only remembered."""
        self.requested = 1 if on else 0
        if self.engine_owns():
            return False
        self.line.set_direction(True, 1 if on else 0)
        if on:
            if self._was_low:
                self.needs_reprogram = True
                self._sleep(self.settle_s)
            self._was_low = False
        else:
            self._was_low = True
        return True

    def enable(self) -> bool:
        return self.set(True)

    def disable(self) -> bool:
        return self.set(False)

    def release(self) -> bool:
        """Stop driving: the line becomes an input and the adapter's jumper / pull-up decides (high)."""
        self.requested = None
        if self.engine_owns():
            return False
        self.line.set_direction(False)
        return True

    def status(self) -> Dict[str, object]:
        engine = self.engine_owns()
        return {
            "owner": "engine" if engine else "linux",
            "requested": self.requested,
            "direction": self.line.direction(),
            "pad": self.level(),
            "needs_reprogram": self.needs_reprogram,
        }
