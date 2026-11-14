"""IF fast path of the PL engine: sample stream format, bit-exact reference of the DSP chain, test patterns.

Sample stream (the one format every ADC adapter converts to, `rtl-spec.md` section 8b):
    valid, data[15:0] signed two's complement, full scale = +/-32767 (left justified), ovr (ADC over-range)
at any rate up to one sample per fabric clock. Converters:
    AD9226, 12 bit offset binary:   data = (code - 2048) << 4, ovr = OTR
    SPI SAR ADC, 16 bit unipolar:   data = code >> 1          (0 .. 32767)
    ADS1115, 16 bit two's complement: data = code

`if_power_ref` is the arithmetic of `rtl/src/if_power.sv`, integer for integer: NCO (11-bit sine table), mixer,
3-stage CIC decimator by R, shift and saturation to 18 bit, I^2 + Q^2, sum over n_avg outputs, 22-bit mantissa /
6-bit exponent. The testbench `tb_if` and the bring-up script compare the hardware against it.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

ROM_BITS = 11
ROM_SIZE = 1 << ROM_BITS
MASK64 = (1 << 64) - 1
MANT_BITS = 22
OVR_BIT = 30                       # result word: over-range or saturation in this point
Y_MAX = (1 << 17) - 1              # 18-bit signed after the shift


def nco_rom() -> List[int]:
    """sin table of the NCO: ROM[i] = round(32767 sin(2 pi i / 2048)); cos is read at i + 512."""
    return [int(math.floor(32767.0 * math.sin(2.0 * math.pi * i / ROM_SIZE) + 0.5)) for i in range(ROM_SIZE)]


_ROM = nco_rom()


def _s64(v: int) -> int:
    v &= MASK64
    return v - (1 << 64) if v >> 63 else v


def float28(acc: int) -> int:
    """Sum as the result word carries it: {exp[5:0], mant[21:0]}, value = mant << exp (truncated)."""
    exp = 0
    while acc >> MANT_BITS:
        acc >>= 1
        exp += 1
    return (exp << MANT_BITS) | acc


def decode(word: int) -> Tuple[int, bool, bool]:
    """Result word of an IF point -> (power sum, over-range, unlocked)."""
    return (word & ((1 << MANT_BITS) - 1)) << ((word >> MANT_BITS) & 0x3F), bool(word >> OVR_BIT & 1), bool(word >> 31)


def if_power_ref(pattern: Sequence[int], nco_inc: int, r: int, shift: int, skip: int, n_avg: int,
                 ovr: bool = False) -> Tuple[int, bool]:
    """(28-bit float sum, over-range flag) of one measured point. `pattern` is played cyclically from index 0,
    the NCO starts at phase 0 and the filter is cleared (what the hardware does with GEN_CFG.sync = 1)."""
    r = max(1, r)
    n_avg = max(1, n_avg)
    n = len(pattern)
    i1 = i2 = i3 = q1 = q2 = q3 = 0
    di = [0, 0, 0]
    dq = [0, 0, 0]
    acc, outputs, k, ph = 0, 0, 0, 0
    sat = bool(ovr)
    while outputs < skip + n_avg:
        x = pattern[k % n]
        a = (ph >> (32 - ROM_BITS)) & (ROM_SIZE - 1)
        s, c = _ROM[a], _ROM[(a + ROM_SIZE // 4) & (ROM_SIZE - 1)]
        ph = (ph + nco_inc) & 0xFFFF_FFFF
        mi, mq = (x * c) >> 15, (x * s) >> 15
        i3, i2, i1 = (i3 + i2) & MASK64, (i2 + i1) & MASK64, (i1 + mi) & MASK64     # each stage adds the old value
        q3, q2, q1 = (q3 + q2) & MASK64, (q2 + q1) & MASK64, (q1 + mq) & MASK64
        k += 1
        if k % r:
            continue
        y = []
        for v, d in ((i3, di), (q3, dq)):
            for j in range(3):
                v, d[j] = (v - d[j]) & MASK64, v
            v = _s64(v) >> shift
            if v > Y_MAX or v < -Y_MAX - 1:
                sat = True
                v = Y_MAX if v > 0 else -Y_MAX - 1
            y.append(v)
        if outputs >= skip:
            acc += y[0] * y[0] + y[1] * y[1]
        outputs += 1
    return float28(acc), sat


def shift_for(r: int) -> int:
    """Shift that brings a full-scale tone to about a quarter of the 18-bit range: the CIC gain is R^3."""
    return max(0, math.ceil(3 * math.log2(max(1, r))) - 1)


def inc_for(f_hz: float, fs_hz: float) -> int:
    """NCO phase increment for f_hz at sample rate fs_hz (negative frequencies wrap)."""
    return int(round(f_hz / fs_hz * (1 << 32))) & 0xFFFF_FFFF


def make_pattern(n: int, tones: Sequence[Tuple[float, float]], noise_rms: float = 0.0, seed: int = 1) -> List[int]:
    """n samples: sum of tones (cycles per pattern, peak amplitude in codes) plus Gaussian noise, clipped to 16 bit.
    Whole numbers of cycles make the cyclic playback continuous."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        v = sum(a * math.cos(2.0 * math.pi * cyc * k / n) for cyc, a in tones)
        if noise_rms:
            v += rng.gauss(0.0, noise_rms)
        out.append(max(-32768, min(32767, int(round(v)))))
    return out


def tone_power(amplitude: float, r: int, shift: int) -> float:
    """Power sum per output sample that a tone of this peak amplitude gives at the centre of the filter."""
    return (amplitude / 2.0 * r ** 3 / (1 << shift)) ** 2
