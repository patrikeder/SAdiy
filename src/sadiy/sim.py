"""Simulated RF chain so the whole software stack runs on a PC with no hardware.

Models: tones at the input, low-IF mixer with image response, Gaussian IF filter (RBW),
gain, attenuator, log detector and a noise floor. It is a development aid, not a
substitute for measuring the real boards.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

from .core.detector import Detector
from .core.freqplan import SweepPoint


class SimChain:
    def __init__(
        self,
        detector: Detector,
        tones: Sequence[Tuple[float, float]] = ((100e6, -30.0), (250e6, -45.0)),
        if_hz: float = 10.7e6,
        rbw_hz: float = 230e3,
        gain_db: float = 22.0,
        noise_dbm_in: float = -100.0,
        noise_v: float = 0.0005,
    ) -> None:
        self.detector = detector
        self.tones = tuple(tones)
        self.if_hz = if_hz
        self.rbw_hz = rbw_hz
        self.gain_db = gain_db
        self.noise_dbm_in = noise_dbm_in
        self.noise_v = noise_v
        self.lo_hz = 0.0
        self.atten_db = 0.0
        self.pll_unlocked = False       # set by SimSynth: the detector then sees whatever the VCO is doing

    def detector_dbm(self) -> float:
        if self.pll_unlocked:
            return random.uniform(-60.0, -10.0)
        sigma = self.rbw_hz / 2.355
        f_sig = self.lo_hz - self.if_hz      # wanted response
        f_img = self.lo_hz + self.if_hz      # image response of the low-IF mixer
        total_mw = 10 ** (self.noise_dbm_in / 10)
        for f_tone, p_tone in self.tones:
            for f_rx in (f_sig, f_img):
                resp = math.exp(-0.5 * ((f_rx - f_tone) / sigma) ** 2)
                total_mw += 10 ** (p_tone / 10) * resp
        p_in = 10 * math.log10(total_mw)
        return p_in + self.gain_db - self.atten_db

    def detector_volts(self) -> float:
        p = min(max(self.detector_dbm(), -65.0), 5.0)  # detector window and saturation
        v = self.detector.volts_from_dbm(p) + random.gauss(0.0, self.noise_v)
        return max(v, 0.0)


class SimSynth:
    def __init__(self, chain: SimChain, unlocked_rf_ranges: Sequence[Tuple[float, float]] = ()) -> None:
        self.chain = chain
        self.unlocked_rf_ranges = tuple((float(a), float(b)) for a, b in unlocked_rf_ranges)
        self._unlocked = False

    def tune(self, point: SweepPoint) -> None:
        # Use the quantised PLL frequency when available, like the real synthesizer would.
        self.chain.lo_hz = point.pll.f_actual_hz if point.pll else point.f_lo_hz
        self._unlocked = any(a <= point.f_rf_hz <= b for a, b in self.unlocked_rf_ranges)
        self.chain.pll_unlocked = self._unlocked

    def readback(self) -> dict:
        """What a status request shows while sweeping: the LO of the last point tuned, and lock detect."""
        return {"source": "sweep", "f_out_hz": self.chain.lo_hz or None, "ld": int(self.locked())}

    def locked(self) -> bool:
        """Lock detect. Fails inside the ranges given for testing the lock gating (`[sim] unlock_ranges_hz`)."""
        return not self._unlocked


class SimAtten:
    def __init__(self, chain: SimChain, max_db: float = 31.5) -> None:
        self.chain = chain
        self.max_db = max_db

    def set_attenuation(self, db: float) -> float:
        db = min(max(round(db * 2) / 2, 0.0), self.max_db)
        self.chain.atten_db = db
        return db


class SimAdc:
    def __init__(self, chain: SimChain) -> None:
        self.chain = chain

    def read_samples(self, n: int = 1) -> List[float]:
        return [self.chain.detector_volts() * self.chain.detector.divider_ratio for _ in range(n)]

    def read_volts(self, n: int = 1) -> float:
        return sum(self.read_samples(n)) / n
