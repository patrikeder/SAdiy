"""Adapter between `SweepEngine` (seam 1) and a `SweepOffload`: builds and uploads the table, runs it, converts
the sums to volts. Provides the `run_points` call the engine uses when it has an offload."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from sadiy.drivers.pe4302 import DEFAULT_WEIGHTS_DB, STEP_DB

from .platform import SweepOffload, TableEntry, att_pins_for, point_words, table_from_words

DEFAULT_STEPS = tuple(int(round(w / STEP_DB)) for w in DEFAULT_WEIGHTS_DB)


def plan_chunks(words_per_point: Sequence[Sequence[int]], max_entries: Optional[int], max_points: Optional[int],
                *, full: bool = False) -> List[Tuple[int, int]]:
    """Split a sweep into runs that each fit the core: (first, stop) point index pairs, in order, no gaps.

    A run is a table of whole points. Its first point carries every register word (the table of a run does not
    know what the previous run sent), the others only the changed ones, as in `table_from_words`. A run holds at
    most `max_entries` entries and `max_points` points (None = no limit). Raises ValueError when one point alone
    does not fit."""
    chunks: List[Tuple[int, int]] = []
    start, entries, last = 0, 0, {}
    for k, words in enumerate(words_per_point):
        for attempt in (0, 1):
            seen = dict(last)
            n = 0
            for word in words:
                reg = word & 7
                if full or reg == 0 or seen.get(reg) != word:
                    seen[reg] = word
                    n += 1
            fits = (max_entries is None or entries + n <= max_entries) and \
                   (max_points is None or k - start + 1 <= max_points)
            if fits:
                last, entries = seen, entries + n
                break
            if attempt or k == start:       # a new run would not help: this point alone is too big
                raise ValueError(f"point {k} needs {n} table entries, the core holds {max_entries}")
            chunks.append((start, k))
            start, entries, last = k, 0, {}
    if words_per_point:
        chunks.append((start, len(words_per_point)))
    return chunks


class OffloadSweep:
    """`atten_steps` are the stage weights in 0.5 dB units (as in `drivers/pe4302.py`), `active_high` the
    pin polarity. `atten` is the PS-side PE4302 driver; it is only used by `safe_state()` (see there)."""

    def __init__(self, offload: SweepOffload, synth, atten_steps: Sequence[int] = DEFAULT_STEPS,
                 active_high: bool = True, *, atten=None, full: bool = False, skip_lock: bool = False) -> None:
        self.offload = offload
        self.synth = synth
        self.steps = tuple(atten_steps)
        self.active_high = active_high
        self.atten = atten
        self.full = full
        self.skip_lock = skip_lock
        self.uploads = 0                 # how often a table was sent (for tests and logging)
        self._key: Optional[tuple] = None          # the table of the whole sweep is the one in the core
        self._plan_key: Optional[tuple] = None
        self._plan: List[Tuple[int, List[TableEntry]]] = []   # (points, table) per run of the sweep
        self.chunks = 0                            # runs of the last sweep (1 = the sweep fitted the core)

    def code_for(self, db: float) -> int:
        """Attenuation in 0.5 dB steps, clamped like `PE4302.code_for`."""
        return max(0, min(sum(self.steps), int(db / STEP_DB + 0.5)))

    def _table_key(self, points, att_pins: int) -> tuple:
        s = self.synth
        return (list(points), att_pins, s.outputs, getattr(s, "cp_index", None), getattr(s, "low_spur", None),
                getattr(s, "band_select_div", None), getattr(s, "mod_max", None), self.full, self.skip_lock)

    def _build_plan(self, points: Sequence, att_pins: int) -> List[Tuple[int, List[TableEntry]]]:
        words = point_words(points, self.synth)
        chunks = plan_chunks(words, getattr(self.offload, "max_entries", None),
                             getattr(self.offload, "max_points", None), full=self.full)
        return [(stop - first, table_from_words(words[first:stop], att_pins, full=self.full, skip_lock=self.skip_lock))
                for first, stop in chunks]

    def run_points(self, points: Sequence, atten_db: float, n_avg: int) -> Tuple[List[float], List[bool], float]:
        """Returns (volts per point, unlocked per point, attenuation set in dB). A sweep that does not fit the
        core's table or result memory runs as several tables in a row (`chunks`); the caller sees one sweep. A sweep
        that fits uploads its table only when points, attenuation, output state or synth settings changed since the
        last upload; a chunked sweep uploads every table at every sweep (the core holds only the last one)."""
        code = self.code_for(atten_db)
        pins = att_pins_for(code, self.steps, self.active_high)
        key = self._table_key(points, pins)
        if getattr(self.offload, "table_dirty", False):     # single SPI words / detector reads used the table
            self._key = None
        if key != self._plan_key:
            self._plan_key, self._key = None, None
            self._plan = self._build_plan(points, pins)
            self._plan_key = key
        volts: List[float] = []
        unlocked: List[bool] = []
        self.chunks = len(self._plan)
        for n_points, table in self._plan:
            if len(self._plan) > 1 or key != self._key:
                self._key = None
                self.offload.upload(table)
                self._key = key if len(self._plan) == 1 else None
                self.uploads += 1
            res = self.offload.run(n_avg)
            if res.aborted or len(res.sums) != n_points:
                self._key = None
                raise RuntimeError(f"offloaded sweep incomplete: {len(volts) + len(res.sums)} of {len(points)} points"
                                   f"{', aborted' if res.aborted else ''}")
            volts += [self.offload.counts_to_volts(x / res.n_avg) for x in res.sums]
            unlocked += list(res.unlocked)
        return volts, unlocked, code * STEP_DB

    def safe_state(self) -> None:
        """After a failed sweep: stop the engine and give the pins back with the PS lines in the safe state
        (all stages in), so the PS can switch the synthesiser outputs off over its own SPI. Needs `atten`
        and an offload with `release_pins`; without them only the abort is done."""
        self.offload.abort()
        release = getattr(self.offload, "release_pins", None)
        if self.atten is not None and release is not None:
            self.atten.safe_state()       # the PS lines only matter once the pins are handed back
            release()
