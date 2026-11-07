"""Log detector model (AD8318 class): Vout = slope * (Pin - intercept)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Detector:
    slope_v_per_db: float = -0.0245
    intercept_dbm: float = 20.0
    divider_ratio: float = 1.0   # Vadc / Vdet when a divider sits between detector and ADC
    floor_dbm: float = -65.0     # at or below this the output has flattened: a reading is only an upper bound
    max_dbm: float = -1.0        # at or above this the detector is in overload: the reading is not trusted

    @classmethod
    def from_config(cls, section: dict) -> "Detector":
        return cls(
            slope_v_per_db=section["slope_v_per_db"],
            intercept_dbm=section["intercept_dbm"],
            divider_ratio=section.get("divider_ratio", 1.0),
            floor_dbm=section.get("floor_dbm", -65.0),
            max_dbm=section.get("max_dbm", -1.0),
        )

    def dbm_from_volts(self, v_det: float) -> float:
        return self.intercept_dbm + v_det / self.slope_v_per_db

    def volts_from_dbm(self, p_dbm: float) -> float:
        return self.slope_v_per_db * (p_dbm - self.intercept_dbm)

    def dbm_from_adc_volts(self, v_adc: float) -> float:
        return self.dbm_from_volts(v_adc / self.divider_ratio)
