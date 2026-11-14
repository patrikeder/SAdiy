"""Contracts between sweepd and a platform (BBB, EBAZ with PS only, EBAZ with the PL sweep engine).

Only types and pure functions here: no hardware access, no register map. The table format is the one of
`zynq-ebaz/docs/rtl-spec.md` section 5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Sequence, runtime_checkable

from sadiy.drivers.adc import Adc
from sadiy.hal.base import GpioLine, SpiBus

# Table entry word 1 (rtl-spec.md section 5)
ATT_MASK = 0x3F
SPI_EN_BIT, ATT_EN_BIT, MEASURE_BIT, SKIP_LOCK_BIT = 8, 9, 10, 11
W1_USED_MASK = ATT_MASK | (1 << SPI_EN_BIT) | (1 << ATT_EN_BIT) | (1 << MEASURE_BIT) | (1 << SKIP_LOCK_BIT)

# Result word (section 5)
SUM_MASK = 0x0FFF_FFFF
UNLOCKED_BIT = 31


@dataclass(frozen=True)
class TableEntry:
    """One sweep table entry. `att` holds PE4302 pin levels (bit 0 = V1), not dB."""

    word: int
    att: int = 0
    spi_en: bool = False
    att_en: bool = False
    measure: bool = False
    skip_lock: bool = False

    def w0(self) -> int:
        return self.word & 0xFFFF_FFFF

    def w1(self) -> int:
        return ((self.att & ATT_MASK)
                | (int(self.spi_en) << SPI_EN_BIT) | (int(self.att_en) << ATT_EN_BIT)
                | (int(self.measure) << MEASURE_BIT) | (int(self.skip_lock) << SKIP_LOCK_BIT))

    @classmethod
    def from_words(cls, w0: int, w1: int) -> "TableEntry":
        return cls(word=w0 & 0xFFFF_FFFF, att=w1 & ATT_MASK,
                   spi_en=bool(w1 >> SPI_EN_BIT & 1), att_en=bool(w1 >> ATT_EN_BIT & 1),
                   measure=bool(w1 >> MEASURE_BIT & 1), skip_lock=bool(w1 >> SKIP_LOCK_BIT & 1))


@dataclass
class OffloadResult:
    """What one offloaded sweep returned: one sum per measured point that completed."""

    sums: List[int]                 # sum of n_avg raw detector codes per point
    unlocked: List[bool]            # lock detect timed out for that point
    n_avg: int
    aborted: bool = False
    err_table: bool = False
    err_lock: bool = False          # at least one point timed out (also true when `unlocked` has a True)

    @classmethod
    def from_result_words(cls, words: Sequence[int], n_avg: int, aborted: bool = False,
                          err_table: bool = False, err_lock: Optional[bool] = None) -> "OffloadResult":
        unlocked = [bool(w >> UNLOCKED_BIT & 1) for w in words]
        return cls(sums=[w & SUM_MASK for w in words], unlocked=unlocked, n_avg=n_avg, aborted=aborted,
                   err_table=err_table, err_lock=any(unlocked) if err_lock is None else err_lock)


@dataclass(frozen=True)
class Capabilities:
    name: str
    sweep_offload: bool
    detector_bits: int
    max_entries: int
    max_points: int


@runtime_checkable
class SweepOffload(Protocol):
    """A sweep engine that runs a table by itself. `run` returns when the sweep ended (or raises)."""

    def upload(self, entries: Sequence[TableEntry]) -> None: ...

    def run(self, n_avg: int, timeout_s: float = 10.0) -> OffloadResult:
        """Raises TimeoutError (after aborting) and RuntimeError (table refused or result memory full)."""

    def abort(self) -> None: ...

    def status(self) -> dict: ...

    def counts_to_volts(self, mean_count: float) -> float:
        """Detector code (mean over n_avg) to volts at the ADC input."""


@runtime_checkable
class Platform(Protocol):
    capabilities: Capabilities

    def synth_link(self) -> SpiBus: ...

    def atten_port(self) -> Sequence[GpioLine]:
        """Six lines, V1..V6."""

    def lock_detect(self) -> Optional[Callable[[], bool]]: ...

    def detector(self) -> Adc: ...

    def offload(self) -> Optional[SweepOffload]: ...

    def close(self) -> None: ...


def att_pins_for(code: int, steps: Sequence[int], active_high: bool) -> int:
    """Pin levels (bit i = line i) for an attenuation code in 0.5 dB units; same stage logic as
    `drivers/pe4302.py`: stage i is in when `code & steps[i]`, the pin is high when that equals `active_high`."""
    pins = 0
    for i, step in enumerate(steps):
        on = bool(code & step)
        if on == active_high:
            pins |= 1 << i
    return pins


def build_table(points, synth, att_pins: int, *, full: bool = False, skip_lock: bool = False) -> List[TableEntry]:
    """Sweep table for `points`: the register words of `synth.registers()` as generic SPI entries.

    Per point the six words (write order R5..R0) are emitted, but only those that differ from the last word
    sent for the same register in this table; R0 is always sent, last, with `measure` (it starts the VCO band
    selection). `full=True` sends all six every time. The first entry also applies `att_pins`. Nothing is
    tuned or written to SPI here; R4 carries the output state of `synth.outputs`."""
    entries: List[TableEntry] = []
    last = {}
    for point in points:
        words = synth.registers(point.pll or synth.plan(point.f_lo_hz))
        for word in words:
            reg = word & 7
            is_r0 = reg == 0
            if not (full or is_r0 or last.get(reg) != word):
                continue
            last[reg] = word
            entries.append(TableEntry(word=word, spi_en=True, measure=is_r0, skip_lock=is_r0 and skip_lock))
    if entries:
        first = entries[0]
        entries[0] = TableEntry(first.word, att_pins, first.spi_en, True, first.measure, first.skip_lock)
    return entries
