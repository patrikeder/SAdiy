"""Virtual spectrum from the engine itself: three tones in the PL sample generator, the IF path (NCO, mixer, CIC,
power) stepping its NCO over the points, so the GUI shows a drifting spectrum with three peaks and live noise
without any RF, ADC or ADF4351. It exercises the table, the sequencer, the generator, the whole IF path, the
result memory and the readout; the result words are bit-exact against `ifpath.if_power_ref` (`verify`).

`VirtualSweep` has the call of `OffloadSweep` (`run_points`), so a SweepEngine takes it as its `offload`:

    vs = VirtualSweep(offload, detector, cal)        # offload: RegOffload
    engine = SweepEngine(..., offload=vs)            # the engine and its frames stay as they are

The volts it returns are chosen so that the normal path (`detector.dbm_from_adc_volts`, `cal.to_dbm` with the
attenuation the caller passes) shows exactly the virtual level in dBm.

Picture, all in the engine:
  * the generator plays `pattern_len` samples (tones with whole cycles, plus noise) at `clk / gen_div`
    and restarts at sample 0 in every point;
  * point i runs the NCO at `nco_start + (i + drift) * df` (IF_NCO base + i * IF_NCO_STEP); a tone shows where the
    NCO passes its frequency, with the shape of the CIC (about +-fs/R at the first null);
  * per sweep: `drift` moves the whole window by a few points (peaks wander back and forth) and `skip` (the
    filter outputs dropped before the sum) picks another stretch of the noise, so the noise is new every sweep.
Frequencies on the display are those of the points the caller passes (first and last point = the two ends of the
NCO window); the peaks are placed on the display axis (default 100, 200 and 300 MHz).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import ifpath
from .platform import SUM_MASK, TableEntry
from .reg_offload import RegOffload
from .regmap_toml import REGS

FULL_SCALE = 32767
STEP_DB = 0.5
SRC_STREAM = 2
MAX_ATTEN_CODE = 63
MIN_DBM = -150.0
MAX_DBM = 20.0
NCO_MARGIN_HZ = 0.2e6              # the window and its drift stay this far from 0 and fs / 2
STATE_REGS = ("DET_CFG", "GEN_CFG", "IF_NCO", "IF_NCO_STEP", "IF_CIC", "T_MIN_US", "T_SETTLE_US", "N_AVG")

Peak = Tuple[float, float]      # (frequency on the display axis in Hz, level in dBm)


@dataclass(frozen=True)
class SpectrumConfig:
    peaks_dbm: Tuple[Peak, ...] = ((100e6, -30.0), (200e6, -45.0), (300e6, -60.0))
    floor_dbm: float = -90.0           # noise floor of the display
    ref_dbm: float = -10.0             # display level of a full-scale tone in the pattern
    gen_div: int = 4                   # generator sample rate = clk / gen_div (25 MS/s at 100 MHz)
    pattern_len: int = 4096            # generator memory
    r: int = 128                       # CIC decimation: first null at fs / r, about 195 kHz
    nco_start_hz: float = 1.0e6        # NCO frequency of the first point (drift 0)
    nco_span_hz: float = 11.0e6        # NCO sweep over the points (below fs / 2)
    drift_points: int = 8              # peaks wander by up to this many points
    drift_period: int = 48             # sweeps for one back and forth
    skips: Tuple[int, ...] = (4, 8, 12, 6, 10, 14)  # filter outputs dropped per sweep, in turn (noise draws): 3..15
    wait_us: int = 1                   # T_MIN_US and T_SETTLE_US while the mode is on (the IF path needs no wait)
    seed: int = 7

    @property
    def shift(self) -> int:
        return ifpath.shift_for(self.r)


def cic_sum_squares(r: int) -> float:
    """Sum of the squared impulse response of the 3-stage CIC decimator by r (noise gain, before the shift)."""
    h = np.ones(r)
    h = np.convolve(np.convolve(h, np.ones(r)), np.ones(r))
    return float(np.sum(h * h))


def noise_rms_for(cfg: SpectrumConfig) -> float:
    """Pattern noise (codes, rms) that gives a display floor of `cfg.floor_dbm`.

    I and Q noise power at the CIC output: sigma^2 * sum(h^2) / 4^shift; a full-scale tone gives
    `ifpath.tone_power(32767)`; the display level is ref + 10 log10 of the ratio."""
    p_full = ifpath.tone_power(FULL_SCALE, cfg.r, cfg.shift)
    p_target = p_full * 10.0 ** ((cfg.floor_dbm - cfg.ref_dbm) / 10.0)
    return math.sqrt(p_target * 4.0 ** cfg.shift / cic_sum_squares(cfg.r))


def cic_response(offset_hz: float, fs_hz: float, r: int) -> float:
    """Amplitude of the CIC (3 stages, decimation r) at an offset from the tone, 1.0 at the centre."""
    s = math.sin(math.pi * offset_hz / fs_hz)
    if abs(s) < 1e-12:
        return 1.0
    return (math.sin(math.pi * offset_hz * r / fs_hz) / (r * s)) ** 3


class VirtualSweep:
    """`run_points(points, atten_db, n_avg)` like `OffloadSweep`, with the generator and the IF path as the source."""

    def __init__(self, offload: RegOffload, detector, cal, *, config: Optional[SpectrumConfig] = None,
                 peaks_dbm: Optional[Sequence[Peak]] = None, floor_dbm: Optional[float] = None) -> None:
        cfg = config or SpectrumConfig()
        if peaks_dbm is not None or floor_dbm is not None:
            fields = dict(cfg.__dict__)
            if peaks_dbm is not None:
                fields["peaks_dbm"] = tuple((float(f), float(p)) for f, p in peaks_dbm)
            if floor_dbm is not None:
                fields["floor_dbm"] = float(floor_dbm)
            cfg = SpectrumConfig(**fields)
        self.cfg = cfg
        self.offload = offload
        self.detector = detector
        self.cal = cal
        self.fs_hz = offload.clk_hz / cfg.gen_div
        self.sweep = 0                      # sweeps run so far
        self.drift_points = 0               # drift of the last sweep, in points
        self.drift_max = 0                  # largest drift the window has room for (few points: wide steps)
        self.skip = cfg.skips[0]
        self.points_n = 0
        self.n_avg = 0
        self.last_words: List[int] = []
        self.pattern: List[int] = []
        self.tones: List[Tuple[int, float, float, float]] = []      # (cycles, amplitude, index, level dBm)
        self.df_hz = 0.0
        self._plan: Optional[tuple] = None
        self._saved: Optional[dict] = None
        self._table_n = 0
        regs = REGS
        self._rd = lambda name: offload._rd(regs[name].offset)       # noqa: E731
        self._wr = lambda name, v: offload._wr(regs[name].offset, v)  # noqa: E731
        self.last_sweep_s = 0.0
        self.last_read_s = 0.0

    # ---- set-up ------------------------------------------------------------------------------------------------
    def _save(self) -> None:
        if self._saved is None:
            self._saved = {name: self._rd(name) for name in STATE_REGS}

    def close(self) -> None:
        """Put the registers back that this mode changed (the pattern memory is left as it is). Can be called
        any number of times and never raises."""
        saved, self._saved = self._saved, None
        self._plan = None
        self._table_n = 0
        for name, value in (saved or {}).items():
            try:
                self._wr(name, value)
            except Exception:                    # noqa: BLE001 - closing must not fail: the rest is still restored
                pass

    def safe_state(self) -> None:
        self.offload.abort()

    def _build_pattern(self, f_first_hz: float, f_last_hz: float, n_points: int) -> None:
        cfg = self.cfg
        self.df_hz = cfg.nco_span_hz / max(1, n_points - 1)
        low_room = cfg.nco_start_hz - NCO_MARGIN_HZ
        high_room = self.fs_hz / 2 - NCO_MARGIN_HZ - (cfg.nco_start_hz + cfg.nco_span_hz)
        if low_room < 0 or high_room < 0:
            raise ValueError("the NCO window does not fit between 0 and fs / 2")
        self.drift_max = int(min(cfg.drift_points, low_room // self.df_hz, high_room // self.df_hz))
        n = cfg.pattern_len
        tones, spec = [], []
        for f_disp, level in cfg.peaks_dbm:
            if not f_first_hz <= f_disp <= f_last_hz:
                continue
            index = (f_disp - f_first_hz) / (f_last_hz - f_first_hz) * (n_points - 1)
            f_nco = cfg.nco_start_hz + index * self.df_hz
            cycles = max(1, int(round(f_nco / self.fs_hz * n)))
            amp = FULL_SCALE * 10.0 ** ((level - cfg.ref_dbm) / 20.0)
            tones.append((cycles, amp))
            spec.append((cycles, amp, index, level))
        self.tones = spec
        self.pattern = ifpath.make_pattern(n, tones, noise_rms=noise_rms_for(cfg), seed=cfg.seed)

    def _upload_pattern(self) -> None:
        cfg = self.cfg
        self._wr("GEN_ADDR", 0)
        for v in self.pattern:
            self._wr("GEN_DATA", v & 0xFFFF)
        g = REGS["GEN_CFG"].fields
        self._wr("GEN_CFG", g["div"].put(cfg.gen_div) | g["len_m1"].put(len(self.pattern) - 1)
                 | g["sync"].put(1) | g["enable"].put(1))

    def _configure(self, points: Sequence, n_points: int) -> None:
        plan = (n_points, points[0].f_rf_hz, points[-1].f_rf_hz, self.cfg)
        if plan == self._plan:
            return
        off = self.offload
        if n_points > min(off.max_entries, off.max_points):
            raise ValueError(f"{n_points} points, the core holds {min(off.max_entries, off.max_points)}")
        skip_max = (1 << REGS["IF_CIC"].fields["skip"].width) - 1
        if not all(3 <= k <= skip_max for k in self.cfg.skips):
            raise ValueError(f"every skip must be 3..{skip_max} (the filter needs 3 outputs to fill; "
                             f"IF_CIC.skip is {skip_max.bit_length()} bits)")
        self._save()
        self._plan = None
        self._build_pattern(points[0].f_rf_hz, points[-1].f_rf_hz, n_points)
        self._upload_pattern()
        d = REGS["DET_CFG"].fields
        # mode 1 ignores `src`; 2 (stream) keeps RegOffload from treating the run as PS push
        self._wr("DET_CFG", d["mode"].put(1) | d["stream"].put(1) | d["src"].put(SRC_STREAM))
        self._wr("T_MIN_US", self.cfg.wait_us)
        self._wr("T_SETTLE_US", self.cfg.wait_us)
        off.upload([TableEntry(word=0, measure=True, skip_lock=True) for _ in range(n_points)])
        self._table_n = n_points
        self._plan = plan

    def _drift_for(self, sweep: int) -> int:
        cfg = self.cfg
        if not self.drift_max or not cfg.drift_period:
            return 0
        return int(round(self.drift_max * math.sin(2.0 * math.pi * sweep / cfg.drift_period)))

    def _inc_base(self) -> int:
        return ifpath.inc_for(self.cfg.nco_start_hz + self.drift_points * self.df_hz, self.fs_hz)

    def _inc_step(self) -> int:
        return ifpath.inc_for(self.df_hz, self.fs_hz)

    # ---- the sweep ---------------------------------------------------------------------------------------------
    def run_points(self, points: Sequence, atten_db: float, n_avg: int) -> Tuple[List[float], List[bool], float]:
        n_points = len(points)
        if n_points < 2:
            raise ValueError("a virtual spectrum needs at least two points")
        if getattr(self.offload, "table_dirty", False):
            self._plan = None                       # something else used the table
        self._configure(points, n_points)
        cfg = self.cfg
        self.drift_points = self._drift_for(self.sweep)
        self.skip = cfg.skips[self.sweep % len(cfg.skips)]
        self._wr("IF_NCO", self._inc_base())
        self._wr("IF_NCO_STEP", self._inc_step())
        c = REGS["IF_CIC"].fields
        self._wr("IF_CIC", c["r"].put(cfg.r) | c["shift"].put(cfg.shift) | c["skip"].put(self.skip))
        res = self.offload.run(n_avg)
        if res.aborted or len(res.sums) != n_points:
            self._plan = None
            raise RuntimeError(f"virtual sweep incomplete: {len(res.sums)} of {n_points} points"
                               f"{', aborted' if res.aborted else ''}")
        self.sweep += 1
        self.n_avg = n_avg
        self.points_n = n_points
        self.last_words = [int(w) for w in res.sums]
        self.last_sweep_s = getattr(self.offload, "last_sweep_s", 0.0)
        self.last_read_s = getattr(self.offload, "last_read_s", 0.0)
        code = max(0, min(MAX_ATTEN_CODE, int(atten_db / STEP_DB + 0.5)))
        atten = code * STEP_DB
        p_full = ifpath.tone_power(FULL_SCALE, cfg.r, cfg.shift)
        det = self.detector
        volts = []
        for pt, word in zip(points, self.last_words):
            power = ifpath.decode(word & SUM_MASK)[0] / max(1, n_avg)
            level = cfg.ref_dbm + 10.0 * math.log10(max(power, 1e-9) / p_full)
            level = max(MIN_DBM, min(MAX_DBM, level))
            p_det = level + self.cal.gain_db(pt.f_rf_hz) - atten
            volts.append(det.divider_ratio * det.volts_from_dbm(p_det))
        return volts, [False] * n_points, atten

    # ---- what the last sweep should look like -----------------------------------------------------------------------
    def state(self) -> dict:
        return {"sweep": self.sweep, "drift_points": self.drift_points, "skip": self.skip, "points": self.points_n,
                "last_sweep_s": self.last_sweep_s, "last_read_s": self.last_read_s}

    def peak_indices(self) -> List[float]:
        """Point index of each peak in the last sweep (the drift moves them: index - drift)."""
        return [index - self.drift_points for _, _, index, _ in self.tones]

    def ideal_dbm(self, points: Optional[Sequence] = None) -> List[float]:
        """Noise-free expected trace of the last sweep in dBm on the display (peak shape of the CIC, floor added
        as power): the overlay for the GUI. `points` only gives the number of points (default: the last sweep)."""
        n_points = len(points) if points is not None else self.points_n
        cfg = self.cfg
        floor = 10.0 ** ((cfg.floor_dbm - cfg.ref_dbm) / 10.0)
        out = []
        for i in range(n_points):
            f_nco = cfg.nco_start_hz + (i + self.drift_points) * self.df_hz
            p = floor
            for cycles, amp, _, _ in self.tones:
                f_tone = cycles * self.fs_hz / cfg.pattern_len
                p += (amp / FULL_SCALE) ** 2 * cic_response(f_nco - f_tone, self.fs_hz, cfg.r) ** 2
            out.append(cfg.ref_dbm + 10.0 * math.log10(p))
        return out

    def verify(self, indices: Optional[Sequence[int]] = None) -> List[Tuple[int, bool, int, int]]:
        """Bit-exact check of the last sweep: (index, ok, got, want) for each index (default: the peak centres and
        both ends) against the integer reference of the IF path with the same pattern, NCO increment and skip."""
        cfg = self.cfg
        if not self.last_words:
            raise RuntimeError("no sweep yet")
        if indices is None:
            indices = sorted({0, self.points_n - 1} | {min(self.points_n - 1, max(0, int(round(p))))
                                                        for p in self.peak_indices()})
        base, step = self._inc_base(), self._inc_step()
        rows = []
        for i in indices:
            inc = (base + i * step) & 0xFFFF_FFFF
            want = ifpath.if_power_ref(self.pattern, inc, cfg.r, cfg.shift, self.skip, max(1, self.n_avg))[0] & SUM_MASK
            got = self.last_words[i] & SUM_MASK
            rows.append((i, got == want, got, want))
        return rows
