"""Calibration: net gain from analyzer input to detector (at 0 dB attenuation) versus frequency."""
from __future__ import annotations

import json
from typing import Optional, Sequence

import numpy as np


class Cal:
    def __init__(
        self,
        freqs_hz: Optional[Sequence[float]] = None,
        gain_db: Optional[Sequence[float]] = None,
        default_gain_db: float = 22.0,
    ) -> None:
        self.freqs_hz = None if freqs_hz is None else np.asarray(freqs_hz, dtype=float)
        self.table_gain_db = None if gain_db is None else np.asarray(gain_db, dtype=float)
        self.default_gain_db = default_gain_db

    def gain_db(self, f_hz: float) -> float:
        if self.freqs_hz is None:
            return self.default_gain_db
        return float(np.interp(f_hz, self.freqs_hz, self.table_gain_db))

    def to_dbm(self, p_det_dbm: float, f_hz: float, atten_db: float) -> float:
        """Input-referred power: detector level minus net gain, plus the attenuator setting."""
        return p_det_dbm - self.gain_db(f_hz) + atten_db

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(
                {
                    "freqs_hz": [] if self.freqs_hz is None else self.freqs_hz.tolist(),
                    "gain_db": [] if self.table_gain_db is None else self.table_gain_db.tolist(),
                    "default_gain_db": self.default_gain_db,
                },
                fh,
                indent=1,
            )

    @classmethod
    def load(cls, path: str) -> "Cal":
        with open(path) as fh:
            d = json.load(fh)
        return cls(d["freqs_hz"] or None, d["gain_db"] or None, d.get("default_gain_db", 22.0))
