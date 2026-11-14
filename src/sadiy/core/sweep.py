"""Sweep engine: tune LO, wait for lock, read the detector, convert to input-referred dBm.

Per point the engine does what only the BBB side can:
- waits for the PLL to report lock (lock detect), re-tunes once if it does not, and flags the point
  when it still is not locked (its reading is then the VCO's problem, not a measurement);
- takes the ADC samples one by one and combines them with the median (or a trimmed mean), so one
  glitch on the I2C bus or one noisy conversion does not move the point; a sample far from the result
  flags the point;
- flags points at the detector's rails (overload: not trusted, floor: only an upper bound);
- `run_rejecting()` sweeps twice, with the LO above and below the signal, and keeps the lower reading per
  point: a tone stays, its low-IF image (which moves from 2 IF below to 2 IF above the tone) drops out.

With an `offload` (platform sweep engine, see zynq-ebaz/docs/handover-F1.md) `run()` lets it do the per-point
work and only evaluates the volts it returns; there is no median or outlier flag then.

`run()` still returns the dBm values. The flags and counts of the last sweep are in `last_flags` and
`last_stats`; `sweepd` sends the flags with the frame and reports the counts in its log.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

import numpy as np

from .cal import Cal
from .detector import Detector
from .freqplan import SweepPoint

FLAG_UNLOCKED = 1      # PLL not locked when read: the value is not a measurement
FLAG_OVERRANGE = 2     # detector in overload: the value is not trusted (raise the attenuation)
FLAG_UNDERRANGE = 4    # detector at its floor: the value is only an upper bound
FLAG_OUTLIER = 8       # a sample was far from the others and did not count
FLAG_IMAGE = 16        # image rejection was on but this point had no usable opposite-side reading: an image may show
FLAG_NAMES = ((FLAG_UNLOCKED, "unlocked"), (FLAG_OVERRANGE, "overload"),
              (FLAG_UNDERRANGE, "at floor"), (FLAG_OUTLIER, "outlier rejected"),
              (FLAG_IMAGE, "image not suppressed"))
FLAGS_UNRELIABLE = FLAG_UNLOCKED | FLAG_OVERRANGE     # what the GUI marks on the trace

COMBINE_METHODS = ("median", "trimmed", "mean")


def flag_names(flags: int) -> List[str]:
    return [name for bit, name in FLAG_NAMES if flags & bit]


def combine(samples: Sequence[float], method: str = "median") -> float:
    """One value from the samples of a point. `mean` is the old behaviour; with fewer than 3 samples
    every method is the mean, because nothing can be told apart."""
    n = len(samples)
    if method not in COMBINE_METHODS:
        raise ValueError(f"unknown combine method {method!r}, use one of {COMBINE_METHODS}")
    if n == 0:
        raise ValueError("no samples")
    if n < 3 or method == "mean":
        return sum(samples) / n
    s = sorted(samples)
    if method == "trimmed":
        return sum(s[1:-1]) / (n - 2)
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


@dataclass
class SweepStats:
    points: int = 0
    unlocked: int = 0
    overrange: int = 0
    underrange: int = 0
    outliers: int = 0           # points with at least one rejected sample
    retunes: int = 0            # points that needed a second tune to lock
    first_unlocked_hz: Optional[float] = None
    lock_checked: bool = False  # False: no lock detect available, nothing was gated
    image_unresolved: int = 0   # points kept without an opposite-side partner (image rejection on)


class SweepEngine:
    """Works with any synth / attenuator / adc objects that follow the driver interfaces:
    synth.tune(point), atten.set_attenuation(db) -> float, adc.read_samples(n) -> list of volts
    (or adc.read_volts(n) -> float, which gives one mean and so no outlier handling).
    Lock detect: `lock()` when given, else `synth.locked()` when the synth has it, else not gated."""

    def __init__(
        self,
        synth,
        atten,
        adc,
        detector: Detector,
        cal: Cal,
        averages: int = 4,
        settle_s: float = 0.0005,
        sleep: Callable[[float], None] = time.sleep,
        combine_method: str = "median",
        outlier_db: float = 3.0,
        lock: Optional[Callable[[], bool]] = None,
        lock_retries: int = 2,
        offload=None,
    ) -> None:
        if combine_method not in COMBINE_METHODS:
            raise ValueError(f"unknown combine method {combine_method!r}, use one of {COMBINE_METHODS}")
        self.synth = synth
        self.atten = atten
        self.adc = adc
        self.detector = detector
        self.cal = cal
        self.averages = averages
        self.settle_s = settle_s
        self._sleep = sleep
        self.combine_method = combine_method
        self.outlier_db = outlier_db
        self._lock = lock if lock is not None else getattr(synth, "locked", None)
        self.lock_retries = lock_retries
        self.offload = offload      # duck-typed: run_points(points, atten_db, n_avg) -> (volts, unlocked, atten_db_set)
        self.last_atten_db = 0.0
        self.last_peak_det_dbm = float("-inf")
        self.last_flags = np.zeros(0, dtype=np.uint8)
        self.last_stats = SweepStats()

    def safe_state(self) -> list:
        """RF outputs off and maximum attenuation, after a failed sweep. Never raises; returns what failed."""
        return _safe_state_of(self)

    def run(self, points: Sequence[SweepPoint], atten_db: float) -> np.ndarray:
        if self.offload is not None:
            return self._run_offloaded(points, atten_db)
        self.last_atten_db = self.atten.set_attenuation(atten_db)
        out = np.empty(len(points))
        flags = np.zeros(len(points), dtype=np.uint8)
        stats = SweepStats(points=len(points), lock_checked=self._lock is not None)
        peak_det = float("-inf")
        for i, pt in enumerate(points):
            self.synth.tune(pt)
            self._settle()
            flag = 0
            if self._lock is not None and not self._wait_lock(pt, stats):
                flag |= self._mark_unlocked(pt, stats)
            samples = self._samples()
            v = combine(samples, self.combine_method)
            flag, p_det, out[i] = self._evaluate(pt, v, flag, stats, samples)
            if not flag & FLAG_UNLOCKED:        # a point read without lock must not steer the auto-range
                peak_det = max(peak_det, p_det)
            flags[i] = flag
        self.last_peak_det_dbm = peak_det
        self.last_flags = flags
        self.last_stats = stats
        return out

    def _run_offloaded(self, points: Sequence[SweepPoint], atten_db: float) -> np.ndarray:
        """Same result as `run`, with the platform's sweep engine doing the per-point work (it sums the
        samples, so there is no median and no outlier flag; lock gating is the engine's)."""
        volts, unlocked, self.last_atten_db = self.offload.run_points(points, atten_db, self.averages)
        out = np.empty(len(points))
        flags = np.zeros(len(points), dtype=np.uint8)
        stats = SweepStats(points=len(points), lock_checked=True)
        peak_det = float("-inf")
        for i, pt in enumerate(points):
            flag = self._mark_unlocked(pt, stats) if unlocked[i] else 0
            flag, p_det, out[i] = self._evaluate(pt, volts[i], flag, stats)
            if not flag & FLAG_UNLOCKED:
                peak_det = max(peak_det, p_det)
            flags[i] = flag
        self.last_peak_det_dbm = peak_det
        self.last_flags = flags
        self.last_stats = stats
        return out

    @staticmethod
    def _mark_unlocked(pt: SweepPoint, stats: SweepStats) -> int:
        stats.unlocked += 1
        if stats.first_unlocked_hz is None:
            stats.first_unlocked_hz = pt.f_rf_hz
        return FLAG_UNLOCKED

    def _evaluate(self, pt: SweepPoint, v: float, flag: int, stats: SweepStats, samples: Sequence[float] = ()):
        """Per-point step shared by `run` and `_run_offloaded`: detector power from the ADC volts `v`, outlier
        and range flags (added to `flag`), input-referred dBm. Returns (flag, detector dBm, dBm)."""
        det = self.detector
        p_det = det.dbm_from_adc_volts(v)
        volts_per_db = abs(det.slope_v_per_db) * det.divider_ratio
        if len(samples) >= 3 and max(abs(x - v) for x in samples) / volts_per_db > self.outlier_db:
            flag |= FLAG_OUTLIER
            stats.outliers += 1
        if p_det >= det.max_dbm:
            flag |= FLAG_OVERRANGE
            stats.overrange += 1
        elif p_det <= det.floor_dbm:
            flag |= FLAG_UNDERRANGE
            stats.underrange += 1
        return flag, p_det, self.cal.to_dbm(p_det, pt.f_rf_hz, self.last_atten_db)

    def run_rejecting(self, points: Sequence[SweepPoint], other_points: Sequence[SweepPoint], have_other,
                      atten_db: float) -> np.ndarray:
        """Two sweeps, one with each LO side, merged (see `merge_image_sweeps`). `other_points` and
        `have_other` come from `freqplan.build_opposite_sweep`. The attenuator is the same for both; the
        peak for auto-ranging is the higher of the two. Takes twice as long as `run`."""
        n = len(points)
        p_main = self.run(points, atten_db)
        flags_main, stats_main, peak = self.last_flags, self.last_stats, self.last_peak_det_dbm
        p_other = np.full(n, np.nan)
        flags_other = np.zeros(n, dtype=np.uint8)
        have = np.asarray(have_other, dtype=bool)
        retunes, lock_checked = stats_main.retunes, stats_main.lock_checked
        if len(other_points):
            p_other[have] = self.run(other_points, atten_db)
            flags_other[have] = self.last_flags
            peak = max(peak, self.last_peak_det_dbm)
            retunes += self.last_stats.retunes
            lock_checked = lock_checked or self.last_stats.lock_checked
        p, flags = merge_image_sweeps(p_main, flags_main, p_other, flags_other, have)
        stats = SweepStats(points=n, retunes=retunes, lock_checked=lock_checked)
        stats.unlocked = int(((flags & FLAG_UNLOCKED) != 0).sum())
        stats.overrange = int(((flags & FLAG_OVERRANGE) != 0).sum())
        stats.underrange = int(((flags & FLAG_UNDERRANGE) != 0).sum())
        stats.outliers = int(((flags & FLAG_OUTLIER) != 0).sum())
        stats.image_unresolved = int(((flags & FLAG_IMAGE) != 0).sum())
        bad = np.flatnonzero(flags & FLAG_UNLOCKED)
        if bad.size:
            stats.first_unlocked_hz = points[int(bad[0])].f_rf_hz
        self.last_flags, self.last_stats, self.last_peak_det_dbm = flags, stats, peak
        return p

    def _settle(self) -> None:
        if self.settle_s:
            self._sleep(self.settle_s)

    def _samples(self) -> List[float]:
        read = getattr(self.adc, "read_samples", None)
        if read is None:
            return [self.adc.read_volts(self.averages)]
        return list(read(self.averages))

    def _wait_lock(self, pt: SweepPoint, stats: SweepStats) -> bool:
        """Lock detect after the settle time. A short wait, then one more tune (the PLL relocks on an
        R0 write), then give up: the caller flags the point. Returns whether the PLL is locked."""
        if self._lock():
            return True
        wait = max(self.settle_s, 0.0002)
        for _ in range(self.lock_retries):
            self._sleep(wait)
            if self._lock():
                return True
        self.synth.tune(pt)
        stats.retunes += 1
        self._sleep(wait)
        return bool(self._lock())


def merge_image_sweeps(p_main, flags_main, p_other, flags_other, have_other):
    """Combine a sweep and its opposite-LO-side sweep into one. `p_other` / `flags_other` are full length;
    where `have_other` is False they are ignored. Per point:
    - no partner: the main reading, flagged FLAG_IMAGE;
    - both locked, or both unlocked: the lower reading, flags of both;
    - only one side unlocked: the locked side's reading and flags, plus FLAG_IMAGE (nothing to compare with)."""
    p = np.array(p_main, dtype=float)
    flags = np.array(flags_main, dtype=np.uint8)
    have = np.asarray(have_other, dtype=bool)
    flags[~have] |= FLAG_IMAGE
    both = have.copy()
    unl_m = (flags_main & FLAG_UNLOCKED) != 0
    unl_o = have & ((np.asarray(flags_other) & FLAG_UNLOCKED) != 0)
    only_main_bad = have & unl_m & ~unl_o
    only_other_bad = have & unl_o & ~unl_m
    both &= ~(only_main_bad | only_other_bad)
    p[both] = np.minimum(p[both], np.asarray(p_other, dtype=float)[both])
    flags[both] = np.asarray(flags_main, dtype=np.uint8)[both] | np.asarray(flags_other, dtype=np.uint8)[both]
    p[only_main_bad] = np.asarray(p_other, dtype=float)[only_main_bad]
    flags[only_main_bad] = np.asarray(flags_other, dtype=np.uint8)[only_main_bad] | FLAG_IMAGE
    flags[only_other_bad] |= FLAG_IMAGE
    return p, flags


def _safe_state_of(engine: "SweepEngine") -> list:
    errors = []
    for what, fn in (
        ("offload", getattr(getattr(engine, "offload", None), "safe_state", None)),   # first: gives the pins back
        ("synth", getattr(engine.synth, "safe_state", None)),
        ("attenuator", lambda: engine.atten.set_attenuation(float(getattr(engine.atten, "max_db", 31.5)))),
    ):
        if fn is None:
            continue
        try:
            fn()
        except Exception as exc:        # keep going: every step that can still work must run
            errors.append(f"{what}: {exc}")
    return errors


def next_atten_db(
    p_det_peak_dbm: float,
    atten_db: float,
    target_det_dbm: float = -15.0,
    step_db: float = 0.5,
    max_db: float = 31.5,
) -> float:
    """Auto-range: move the attenuator so the sweep peak lands at the target detector level.
    No usable peak (every point unlocked): leave it where it is."""
    if not np.isfinite(p_det_peak_dbm):
        return atten_db
    new = atten_db + (p_det_peak_dbm - target_det_dbm)
    new = int(new / step_db + 0.5) * step_db
    return min(max(new, 0.0), max_db)
