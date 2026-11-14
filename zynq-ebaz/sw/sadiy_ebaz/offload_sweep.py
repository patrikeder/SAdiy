"""Adapter between `SweepEngine` (seam 1) and a `SweepOffload`: builds and uploads the table, runs it, converts
the sums to volts. Provides the `run_points` call the engine uses when it has an offload."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from sadiy.drivers.pe4302 import DEFAULT_WEIGHTS_DB, STEP_DB

from .platform import SweepOffload, att_pins_for, build_table

DEFAULT_STEPS = tuple(int(round(w / STEP_DB)) for w in DEFAULT_WEIGHTS_DB)


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
        self._key: Optional[tuple] = None

    def code_for(self, db: float) -> int:
        """Attenuation in 0.5 dB steps, clamped like `PE4302.code_for`."""
        return max(0, min(sum(self.steps), int(db / STEP_DB + 0.5)))

    def _table_key(self, points, att_pins: int) -> tuple:
        s = self.synth
        return (list(points), att_pins, s.outputs, getattr(s, "cp_index", None), getattr(s, "low_spur", None),
                getattr(s, "band_select_div", None), getattr(s, "mod_max", None), self.full, self.skip_lock)

    def run_points(self, points: Sequence, atten_db: float, n_avg: int) -> Tuple[List[float], List[bool], float]:
        """Returns (volts per point, unlocked per point, attenuation set in dB). Uploads the table only when
        points, attenuation, output state or synth settings changed since the last upload."""
        code = self.code_for(atten_db)
        pins = att_pins_for(code, self.steps, self.active_high)
        key = self._table_key(points, pins)
        if key != self._key:
            self._key = None
            self.offload.upload(build_table(points, self.synth, pins, full=self.full, skip_lock=self.skip_lock))
            self._key = key
            self.uploads += 1
        res = self.offload.run(n_avg)
        if res.aborted or len(res.sums) != len(points):
            self._key = None
            raise RuntimeError(f"offloaded sweep incomplete: {len(res.sums)} of {len(points)} points"
                               f"{', aborted' if res.aborted else ''}")
        volts = [self.offload.counts_to_volts(s / res.n_avg) for s in res.sums]
        return volts, list(res.unlocked), code * STEP_DB

    def safe_state(self) -> None:
        """After a failed sweep: stop the engine and give the pins back with the PS lines in the safe state
        (all stages in), so the PS can switch the synthesiser outputs off over its own SPI. Needs `atten`
        and an offload with `release_pins`; without them only the abort is done."""
        self.offload.abort()
        release = getattr(self.offload, "release_pins", None)
        if self.atten is not None and release is not None:
            self.atten.safe_state()       # the PS lines only matter once the pins are handed back
            release()
