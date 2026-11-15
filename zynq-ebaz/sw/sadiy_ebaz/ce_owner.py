"""Who drives ADF4351 CE on the EBAZ4205: Linux (EMIO GPIO 6) or the PL engine (lane L).

Since register map 1.1 `adf4351_ce` goes through the pin mux of `sadiy_top` like the SPI and PE4302 pins: while
`STATUS.pin_owner_act` is 1 the engine drives CE (its level is `ADF_PINS.ce`) and the Linux EMIO state is
ignored; with the PS as owner the pad follows EMIO GPIO 6. A regmap without `ADF_PINS.ce` (older bitstreams)
has no mux: CE is always Linux's, whatever `pin_owner` says.
"""
from __future__ import annotations

from typing import Callable

from .regmap_toml import REGS

MUX_REG, MUX_FIELD = "ADF_PINS", "ce"      # present only in maps with the CE mux
OWNER_REG, OWNER_FIELD = "STATUS", "pin_owner_act"


def has_ce_mux(regs=None) -> bool:
    regs = REGS if regs is None else regs
    mux, owner = regs.get(MUX_REG), regs.get(OWNER_REG)
    return bool(mux and MUX_FIELD in mux.fields and owner and OWNER_FIELD in owner.fields)


def ce_owner_probe(read: Callable[[int], int], regs=None) -> Callable[[], bool]:
    """A callable for `SynthCe(owner_active=...)`: True while the engine owns the pins (and so CE).
    `read` is `DevMemRegs.read` (offset -> 32-bit word). Always False when the map has no CE mux."""
    regs = REGS if regs is None else regs
    if not has_ce_mux(regs):
        return lambda: False
    reg = regs[OWNER_REG]
    field = reg.fields[OWNER_FIELD]
    return lambda: bool(field.get(read(reg.offset)))
