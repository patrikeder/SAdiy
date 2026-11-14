"""Who drives ADF4351 CE on the EBAZ4205: Linux (EMIO GPIO 6) or the PL engine (lane L).

Contract with the RTL (session R): when the PL has a mux in front of the CE pad, STATUS has a read-only bit
`ce_engine`: 1 = the engine's CE value reaches the pad and the Linux EMIO state is ignored. A regmap without
that bit (the current bitstreams) means CE is always Linux's, whatever `pin_owner` says.
"""
from __future__ import annotations

from typing import Callable, Optional

from .regmap_toml import REGS

REG, FIELD = "STATUS", "ce_engine"


def has_ce_mux(regs=None) -> bool:
    regs = REGS if regs is None else regs
    reg = regs.get(REG)
    return reg is not None and FIELD in reg.fields


def ce_owner_probe(read: Callable[[int], int], regs=None) -> Callable[[], bool]:
    """A callable for `SynthCe(owner_active=...)`. `read` is `DevMemRegs.read` (offset -> 32-bit word).
    Always False when the register map has no CE mux bit."""
    regs = REGS if regs is None else regs
    if not has_ce_mux(regs):
        return lambda: False
    reg: Optional[object] = regs[REG]
    field = reg.fields[FIELD]
    return lambda: bool(field.get(read(reg.offset)))
