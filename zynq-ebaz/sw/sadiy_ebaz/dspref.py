"""Bit-exact Python references of the standalone DSP modules in `rtl/dsp/` (interfaces: `docs/dsp-modules.md`).

Every function mirrors the integer arithmetic of its module, so a testbench can compare word for word:
    fft_ref        rtl/dsp/fft_r2.sv        radix-2 FFT, scaled by 1/N, optional Hann window
    fir_ref        rtl/dsp/fir_mac.sv       complex FIR with decimation (RBW shaping after the CIC)
    power_ref      rtl/dsp/iq_power.sv      re^2 + im^2 as {exp[5:0], mant[21:0]}
    ad9226_ref / spi_sar_ref                ADC code -> sample stream format
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .ifpath import float28

LOGN_MAX = 12
TW_BITS = 18
TW_ONE = (1 << (TW_BITS - 1)) - 1          # 131071
DATA_BITS = 24


def twiddle_rom() -> List[Tuple[int, int]]:
    """(wr, wi) = round(131071 * (cos, -sin)(2 pi k / 4096)) for k = 0 .. 2047."""
    n = 1 << LOGN_MAX
    out = []
    for k in range(n // 2):
        a = 2.0 * math.pi * k / n
        out.append((int(math.floor(TW_ONE * math.cos(a) + 0.5)), int(math.floor(-TW_ONE * math.sin(a) + 0.5))))
    return out


_TW = twiddle_rom()


def bitrev(v: int, bits: int) -> int:
    return int(format(v, f"0{bits}b")[::-1], 2) if bits else 0


def fft_ref(re: Sequence[int], im: Sequence[int], logn: int, hann: bool = False) -> Tuple[List[int], List[int]]:
    """X[k] = (1/N) sum x[n] e^(-j 2 pi k n / N), in the fixed-point steps of fft_r2 (floor after every stage).
    With `hann` the window is applied in the frequency domain: (2 X[k] - X[k-1] - X[k+1]) >> 2."""
    n = 1 << logn
    assert len(re) == n and len(im) == n
    xr, xi = [0] * n, [0] * n
    for i in range(n):
        xr[bitrev(i, logn)], xi[bitrev(i, logn)] = re[i], im[i]
    for s in range(1, logn + 1):
        half = 1 << (s - 1)
        for i in range(n // 2):
            j, group = i & (half - 1), i >> (s - 1)
            a = (group << s) | j
            b = a | half
            wr, wi = _TW[j << (LOGN_MAX - s)]
            tr = (xr[b] * wr - xi[b] * wi) >> (TW_BITS - 1)
            ti = (xr[b] * wi + xi[b] * wr) >> (TW_BITS - 1)
            xr[a], xr[b] = (xr[a] + tr) >> 1, (xr[a] - tr) >> 1
            xi[a], xi[b] = (xi[a] + ti) >> 1, (xi[a] - ti) >> 1
    if hann:
        yr = [(2 * xr[k] - xr[k - 1] - xr[(k + 1) % n]) >> 2 for k in range(n)]
        yi = [(2 * xi[k] - xi[k - 1] - xi[(k + 1) % n]) >> 2 for k in range(n)]
        return yr, yi
    return xr, xi


def _sat(v: int, bits: int) -> int:
    hi = (1 << (bits - 1)) - 1
    return hi if v > hi else -hi - 1 if v < -hi - 1 else v


def fir_ref(re: Sequence[int], im: Sequence[int], coef: Sequence[int], decim: int = 1,
            shift: int = 17) -> Tuple[List[int], List[int]]:
    """y[m] = sat18((sum_t coef[t] x[n - t]) >> shift) at n = decim - 1, 2 decim - 1, ...; history starts at 0."""
    yr, yi = [], []
    for n in range(decim - 1, len(re), decim):
        ar = sum(c * re[n - t] for t, c in enumerate(coef) if n - t >= 0)
        ai = sum(c * im[n - t] for t, c in enumerate(coef) if n - t >= 0)
        yr.append(_sat(ar >> shift, 18))
        yi.append(_sat(ai >> shift, 18))
    return yr, yi


def gaussian_taps(ntaps: int, bw_rel: float, scale: int = TW_ONE) -> List[int]:
    """Gaussian RBW filter: `bw_rel` = 3 dB bandwidth (two-sided) / input sample rate; DC gain = scale."""
    sigma_f = bw_rel / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    sigma_t = 1.0 / (2.0 * math.pi * sigma_f)
    mid = (ntaps - 1) / 2.0
    w = [math.exp(-0.5 * ((t - mid) / sigma_t) ** 2) for t in range(ntaps)]
    total = sum(w)
    return [int(round(scale * v / total)) for v in w]


def power_ref(re: int, im: int) -> int:
    return float28(re * re + im * im)


def ad9226_ref(code: int, twos: bool = False) -> int:
    """12-bit AD9226 code -> stream sample (16 bit signed, left justified)."""
    v = code & 0xFFF
    v = (v - 0x1000 if v & 0x800 else v) if twos else v - 2048
    return v << 4


def spi_sar_ref(code: int) -> int:
    """16-bit unipolar SAR ADC code -> stream sample (0 .. 32767)."""
    return (code & 0xFFFF) >> 1
