"""Frequency plan: RF -> LO mapping and ADF4351 PLL parameters (divider, INT, FRAC, MOD)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional

import numpy as np

VCO_MIN_HZ = 2_200_000_000
VCO_MAX_HZ = 4_400_000_000
OUT_MIN_HZ = 34_375_000  # 2200 MHz VCO / 64
DIVIDERS = (1, 2, 4, 8, 16, 32, 64)
MOD_MAX = 4095


@dataclass(frozen=True)
class PllPlan:
    f_out_hz: float      # requested output frequency
    f_actual_hz: float   # what the PLL really produces with the chosen INT/FRAC/MOD
    rf_div: int          # output divider, 1..64
    int_n: int
    frac: int
    mod: int
    f_vco_hz: float
    f_pfd_hz: float


@dataclass(frozen=True)
class SweepPoint:
    f_rf_hz: float
    f_lo_hz: float
    pll: Optional[PllPlan]


def plan_pll(f_out_hz: float, f_pfd_hz: float, mod_max: int = MOD_MAX) -> PllPlan:
    """Pick divider, INT, FRAC, MOD for the closest achievable output frequency."""
    if f_out_hz < OUT_MIN_HZ or f_out_hz > VCO_MAX_HZ:
        raise ValueError(f"{f_out_hz / 1e6:.3f} MHz is outside the ADF4351 range")
    f_out = Fraction(f_out_hz)
    pfd = Fraction(f_pfd_hz)
    for div in DIVIDERS:
        vco = f_out * div
        if vco >= VCO_MIN_HZ:
            break
    else:  # pragma: no cover - guarded by the range check above
        raise ValueError("no divider puts the VCO in range")
    if vco > VCO_MAX_HZ:
        raise ValueError("VCO out of range")  # pragma: no cover
    n = vco / pfd
    int_n = math.floor(n)
    frac_part = (n - int_n).limit_denominator(mod_max)
    if frac_part == 0:
        frac, mod = 0, 2          # integer-N; MOD must still be >= 2
    elif frac_part == 1:
        int_n, frac, mod = int_n + 1, 0, 2
    else:
        frac, mod = frac_part.numerator, frac_part.denominator
    n_actual = int_n + Fraction(frac, mod)
    return PllPlan(
        f_out_hz=float(f_out_hz),
        f_actual_hz=float(n_actual * pfd / div),
        rf_div=div,
        int_n=int_n,
        frac=frac,
        mod=mod,
        f_vco_hz=float(n_actual * pfd),
        f_pfd_hz=float(pfd),
    )


def lo_for_rf(f_rf_hz: float, if_hz: float, injection: str = "high") -> float:
    if injection == "high":
        return f_rf_hz + if_hz
    if injection == "low":
        return f_rf_hz - if_hz
    raise ValueError("injection must be 'high' or 'low'")


def build_sweep(
    start_hz: float,
    stop_hz: float,
    points: int,
    if_hz: float,
    injection: str = "high",
    f_pfd_hz: Optional[float] = None,
) -> List[SweepPoint]:
    """Precompute every sweep point (and its PLL words) once, so the sweep loop does no math."""
    out = []
    for f_rf in np.linspace(start_hz, stop_hz, points):
        f_lo = lo_for_rf(float(f_rf), if_hz, injection)
        pll = plan_pll(f_lo, f_pfd_hz) if f_pfd_hz else None
        out.append(SweepPoint(float(f_rf), f_lo, pll))
    return out
