"""Qt-free logic of the spectrum analyzer GUI: axis, settings, trace modes, markers, peak search.

Everything the front end (`sa_gui.py`) decides lives here so it can be tested on a PC without Qt
or a display.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

TRACE_MODES = ("clear_write", "max_hold", "min_hold", "average", "view", "blank")
DB_PER_DIV_CHOICES = (1.0, 2.0, 5.0, 10.0, 20.0)
DIVS = 10  # graticule divisions, both directions


# ---------------------------------------------------------------- formatting

def format_hz(f_hz: float, decimals: int = 3) -> str:
    a = abs(f_hz)
    if a >= 1e9:
        return f"{f_hz / 1e9:.{decimals}f} GHz"
    if a >= 1e6:
        return f"{f_hz / 1e6:.{decimals}f} MHz"
    if a >= 1e3:
        return f"{f_hz / 1e3:.{decimals}f} kHz"
    return f"{f_hz:.0f} Hz"


# ---------------------------------------------------------------- frequency axis

@dataclass(frozen=True)
class Axis:
    """Frequency axis of one sweep frame: start, step and number of points."""

    start_hz: float
    step_hz: float
    n: int

    @property
    def stop_hz(self) -> float:
        return self.start_hz + self.step_hz * (self.n - 1)

    @property
    def span_hz(self) -> float:
        return self.stop_hz - self.start_hz

    @property
    def center_hz(self) -> float:
        return 0.5 * (self.start_hz + self.stop_hz)

    def freqs(self) -> np.ndarray:
        return self.start_hz + np.arange(self.n) * self.step_hz

    def freq_at(self, i: int) -> float:
        return self.start_hz + i * self.step_hz

    def index_of(self, f_hz: float) -> Optional[int]:
        """Nearest point, or None when `f_hz` lies outside the axis."""
        if self.step_hz <= 0:
            return None
        i = (f_hz - self.start_hz) / self.step_hz
        if i < -0.5 or i > self.n - 0.5:
            return None
        return min(max(int(round(i)), 0), self.n - 1)

    @classmethod
    def from_header(cls, header: dict) -> "Axis":
        return cls(float(header["f_start_hz"]), float(header["f_step_hz"]), int(header["n"]))


# ---------------------------------------------------------------- settings

@dataclass
class Limits:
    rf_min_hz: float = 30e6
    rf_max_hz: float = 480e6
    max_points: int = 4001
    min_points: int = 2
    min_span_hz: float = 50e3
    atten_max_db: float = 31.5

    def apply_server(self, d: dict) -> None:
        self.rf_min_hz = float(d.get("rf_min_hz", self.rf_min_hz))
        self.rf_max_hz = float(d.get("rf_max_hz", self.rf_max_hz))
        self.max_points = int(d.get("points_max", self.max_points))


@dataclass
class SaSettings:
    """What the operator sets. Frequency, points, attenuation and averages go to `sweepd`;
    reference level and scale only affect the display."""

    start_hz: float = 30e6
    stop_hz: float = 480e6
    points: int = 401
    averages: int = 4
    atten_db: float = 10.0
    auto_atten: bool = True
    image_reject: bool = False
    ref_dbm: float = -20.0
    db_per_div: float = 10.0

    @property
    def center_hz(self) -> float:
        return 0.5 * (self.start_hz + self.stop_hz)

    @property
    def span_hz(self) -> float:
        return self.stop_hz - self.start_hz

    def set_center_span(self, center_hz: float, span_hz: float, lim: Limits) -> None:
        span = min(max(span_hz, lim.min_span_hz), lim.rf_max_hz - lim.rf_min_hz)
        start = min(max(center_hz - span / 2, lim.rf_min_hz), lim.rf_max_hz - span)
        self.start_hz = round(start, 0)
        self.stop_hz = round(start + span, 0)

    def set_start_stop(self, start_hz: float, stop_hz: float, lim: Limits) -> None:
        start = min(max(start_hz, lim.rf_min_hz), lim.rf_max_hz - lim.min_span_hz)
        stop = min(max(stop_hz, start + lim.min_span_hz), lim.rf_max_hz)
        self.start_hz, self.stop_hz = round(start, 0), round(stop, 0)

    def set_points(self, points: int, lim: Limits) -> None:
        self.points = int(min(max(points, lim.min_points), lim.max_points))

    def to_command(self) -> dict:
        return {
            "cmd": "set",
            "start_hz": self.start_hz,
            "stop_hz": self.stop_hz,
            "points": int(self.points),
            "atten_db": float(self.atten_db),
            "auto_atten": bool(self.auto_atten),
            "averages": int(self.averages),
            "image_reject": bool(self.image_reject),
        }

    def apply_server(self, d: dict) -> None:
        for key in ("start_hz", "stop_hz", "atten_db"):
            if key in d:
                setattr(self, key, float(d[key]))
        for key in ("points", "averages"):
            if key in d:
                setattr(self, key, int(d[key]))
        if "auto_atten" in d:
            self.auto_atten = bool(d["auto_atten"])
        if "image_reject" in d:
            self.image_reject = bool(d["image_reject"])


def recommended_points(span_hz: float, rbw_hz: float, max_points: int = 4001) -> int:
    """Smallest point count that keeps the step at or below RBW / 2 (docs/architecture.md)."""
    return int(min(max(math.ceil(2.0 * span_hz / rbw_hz) + 1, 2), max_points))


def undersampled(points: int, span_hz: float, rbw_hz: float) -> bool:
    """True when the step is larger than RBW / 2, so narrow signals read low."""
    return points < 2.0 * span_hz / rbw_hz


def y_range(ref_dbm: float, db_per_div: float) -> Tuple[float, float]:
    return ref_dbm - DIVS * db_per_div, ref_dbm


def autoscale(p_dbm) -> Tuple[float, float]:
    """Reference level (top of the screen) and dB/div that fit the trace."""
    p = np.asarray(p_dbm, dtype=float)
    p = p[np.isfinite(p)]
    if p.size == 0:
        return -20.0, 10.0
    peak = float(p.max())
    floor = float(np.percentile(p, 2))
    ref = math.ceil(peak / 10.0) * 10.0 + 0.0
    if ref - peak < 2.0:
        ref += 10.0
    need = ref - floor
    for step in DB_PER_DIV_CHOICES:
        if step * DIVS >= need:
            return ref, step
    return ref, DB_PER_DIV_CHOICES[-1]


# ---------------------------------------------------------------- traces

class TraceProcessor:
    """Turns the stream of sweeps into the displayed trace for one trace mode.

    Averaging is done in dB, like the sweep engine does for its detector reads."""

    def __init__(self, mode: str = "clear_write", avg_count: int = 10) -> None:
        if mode not in TRACE_MODES:
            raise ValueError(f"unknown trace mode {mode!r}")
        self.mode = mode
        self.avg_count = max(1, int(avg_count))
        self.axis_key: Optional[Axis] = None
        self.data: Optional[np.ndarray] = None
        self.count = 0

    def reset(self) -> None:
        self.data = None
        self.count = 0

    def set_mode(self, mode: str) -> None:
        if mode not in TRACE_MODES:
            raise ValueError(f"unknown trace mode {mode!r}")
        if mode != "view":     # View freezes what is on screen; every other mode starts afresh
            self.reset()
        self.mode = mode

    def update(self, axis: Axis, p) -> Optional[np.ndarray]:
        p = np.asarray(p, dtype=float)
        if axis != self.axis_key or (self.data is not None and self.data.size != p.size):
            self.axis_key = axis
            self.reset()
        mode = self.mode
        if mode == "blank":
            return None
        if self.data is None:
            self.data = p.copy()
            self.count = 1
            return self.data
        if mode == "clear_write":
            self.data = p.copy()
        elif mode == "max_hold":
            self.data = np.maximum(self.data, p)
        elif mode == "min_hold":
            self.data = np.minimum(self.data, p)
        elif mode == "average":
            self.count = min(self.count + 1, self.avg_count)
            self.data = self.data + (p - self.data) / self.count
        # "view": keep the frozen data
        return self.data


# ---------------------------------------------------------------- peaks and markers

def local_maxima(p) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    if p.size == 0:
        return np.empty(0, dtype=int)
    if p.size == 1:
        return np.array([0])
    rises = np.r_[True, p[1:] > p[:-1]]
    not_falling = np.r_[p[:-1] >= p[1:], True]
    return np.flatnonzero(rises & not_falling)


def significant_peaks(p, threshold_db: float = 6.0) -> np.ndarray:
    """Local maxima at least `threshold_db` above the median (the noise floor of a sparse trace)."""
    p = np.asarray(p, dtype=float)
    idx = local_maxima(p)
    if idx.size == 0:
        return idx
    return idx[p[idx] >= np.median(p) + threshold_db]


def peak_index(p) -> int:
    return int(np.argmax(np.asarray(p, dtype=float)))


def min_separation_bins(rbw_hz: float, step_hz: float) -> int:
    """Bins around a marker that belong to the same signal (about one RBW)."""
    if step_hz <= 0:
        return 3
    return max(3, int(round(rbw_hz / step_hz)))


def next_peak(p, cur: int, mode: str = "lower", min_sep: int = 3, threshold_db: float = 6.0) -> Optional[int]:
    """Next peak from index `cur`. mode: "lower" (highest peak at or below the current level),
    "right" or "left" (nearest peak in that direction). None when there is none."""
    p = np.asarray(p, dtype=float)
    cand = significant_peaks(p, threshold_db)
    if mode == "lower":
        cand = cand[(np.abs(cand - cur) >= min_sep) & (p[cand] <= p[cur])]
        if cand.size == 0:
            return None
        order = np.lexsort((np.abs(cand - cur), -p[cand]))   # highest level first, then closest
        return int(cand[order[0]])
    if mode == "right":
        cand = cand[cand >= cur + min_sep]
        return int(cand[0]) if cand.size else None
    if mode == "left":
        cand = cand[cand <= cur - min_sep]
        return int(cand[-1]) if cand.size else None
    raise ValueError("mode must be 'lower', 'right' or 'left'")


@dataclass
class Marker:
    """A marker keeps its frequency, so it stays put when the span changes."""

    enabled: bool = False
    f_hz: float = 0.0

    def index_in(self, axis: Axis) -> Optional[int]:
        return axis.index_of(self.f_hz) if self.enabled else None

    def place(self, axis: Axis, i: int) -> None:
        self.f_hz = axis.freq_at(i)
        self.enabled = True


def marker_text(name: str, f_hz: float, level_dbm: float) -> str:
    return f"{name}  {format_hz(f_hz, 4):>12}  {level_dbm:7.2f} dBm"


def delta_text(f1: float, p1: float, f2: float, p2: float) -> str:
    return f"Δ   {format_hz(f2 - f1, 4):>12}  {p2 - p1:+7.2f} dB"


def trace_to_csv(axis: Axis, p, atten_db: float) -> str:
    p = np.asarray(p, dtype=float)
    lines = [
        "# SAdiy trace",
        f"# start_hz={axis.start_hz:.0f} step_hz={axis.step_hz:.3f} points={axis.n} atten_db={atten_db:g}",
        "freq_hz,level_dbm",
    ]
    f = axis.freqs()
    lines += [f"{f[i]:.0f},{p[i]:.3f}" for i in range(p.size)]
    return "\n".join(lines) + "\n"
