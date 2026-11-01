"""Sweep engine: tune LO, wait, read the detector, convert to input-referred dBm."""
from __future__ import annotations

import time
from typing import Callable, Sequence

import numpy as np

from .cal import Cal
from .detector import Detector
from .freqplan import SweepPoint


class SweepEngine:
    """Works with any synth / attenuator / adc objects that follow the driver interfaces:
    synth.tune(point), atten.set_attenuation(db) -> float, adc.read_volts(n) -> float."""

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
    ) -> None:
        self.synth = synth
        self.atten = atten
        self.adc = adc
        self.detector = detector
        self.cal = cal
        self.averages = averages
        self.settle_s = settle_s
        self._sleep = sleep
        self.last_atten_db = 0.0
        self.last_peak_det_dbm = float("-inf")

    def run(self, points: Sequence[SweepPoint], atten_db: float) -> np.ndarray:
        self.last_atten_db = self.atten.set_attenuation(atten_db)
        out = np.empty(len(points))
        peak_det = float("-inf")
        for i, pt in enumerate(points):
            self.synth.tune(pt)
            if self.settle_s:
                self._sleep(self.settle_s)
            # The detector is logarithmic, so averaging its voltage is averaging in dB.
            p_det = self.detector.dbm_from_adc_volts(self.adc.read_volts(self.averages))
            peak_det = max(peak_det, p_det)
            out[i] = self.cal.to_dbm(p_det, pt.f_rf_hz, self.last_atten_db)
        self.last_peak_det_dbm = peak_det
        return out


def next_atten_db(
    p_det_peak_dbm: float,
    atten_db: float,
    target_det_dbm: float = -15.0,
    step_db: float = 0.5,
    max_db: float = 31.5,
) -> float:
    """Auto-range: move the attenuator so the sweep peak lands at the target detector level."""
    new = atten_db + (p_det_peak_dbm - target_det_dbm)
    new = int(new / step_db + 0.5) * step_db
    return min(max(new, 0.0), max_db)
