"""Python references of the standalone DSP modules (`sadiy_ebaz.dspref`)."""
import cmath
import math
import random

import pytest
from sadiy_ebaz import dspref
from sadiy_ebaz.ifpath import decode


def test_twiddle_table():
    rom = dspref.twiddle_rom()
    assert len(rom) == 2048 and rom[0] == (131071, 0) and rom[1024] == (0, -131071)


@pytest.mark.parametrize("logn", [2, 5, 9])
def test_fft_matches_a_float_dft(logn):
    n = 1 << logn
    rng = random.Random(logn)
    re = [rng.randint(-(1 << 22), 1 << 22) for _ in range(n)]
    im = [rng.randint(-(1 << 22), 1 << 22) for _ in range(n)]
    xr, xi = dspref.fft_ref(re, im, logn)
    assert max(map(abs, xr + xi)) < 1 << 23                      # no overflow at the input limit
    for k in (0, 1, n // 2, n - 1):
        exact = sum(complex(re[i], im[i]) * cmath.exp(-2j * math.pi * k * i / n) for i in range(n)) / n
        # truncation: a few LSB per stage; twiddle scale 131071 / 131072: up to 7.6 ppm of the value per stage
        assert abs(complex(xr[k], xi[k]) - exact) < 4 + 2 * logn + 7.7e-6 * logn * abs(exact) + 7.7e-6 * logn * (1 << 23)


def test_fft_tone_and_hann_window():
    logn, n = 8, 256
    re = [int(1_000_000 * math.cos(2 * math.pi * 20 * i / n)) for i in range(n)]
    xr, xi = dspref.fft_ref(re, [0] * n, logn)
    mag = [math.hypot(a, b) for a, b in zip(xr, xi)]
    assert mag[20] == pytest.approx(500_000, rel=1e-3) and mag[236] == pytest.approx(500_000, rel=1e-3)
    assert max(m for k, m in enumerate(mag) if k not in (20, 236)) < 20
    # a tone between two bins leaks without a window and much less with it
    re = [int(1_000_000 * math.cos(2 * math.pi * 20.5 * i / n)) for i in range(n)]
    plain = [math.hypot(a, b) for a, b in zip(*dspref.fft_ref(re, [0] * n, logn))]
    hann = [math.hypot(a, b) for a, b in zip(*dspref.fft_ref(re, [0] * n, logn, True))]
    assert plain[40] > 20 * hann[40]


def test_fir_gaussian_gain_step_and_decimation():
    taps = dspref.gaussian_taps(33, 0.1)
    assert taps == taps[::-1] and abs(sum(taps) - 131071) < 40
    yr, yi = dspref.fir_ref([1000] * 200, [-500] * 200, taps, decim=4, shift=17)
    assert len(yr) == 50 and yr[-1] in (999, 1000) and yi[-1] in (-501, -500)
    assert yr[0] < 10 and yr == sorted(yr)                       # the filter fills up monotonically
    with_zero = dspref.fir_ref([7, 0, 0, 0], [0] * 4, [1, 2, 3], shift=0)[0]
    assert with_zero == [7, 14, 21, 0]                           # the impulse response is the taps


def test_fir_saturates():
    yr, _ = dspref.fir_ref([131071] * 4, [0] * 4, [131071, 131071], shift=2)
    assert max(yr) == 131071


def test_power_word():
    assert decode(dspref.power_ref(3, 4))[0] == 25
    big = dspref.power_ref(-8388608, -8388608)
    assert decode(big)[0] == pytest.approx(2 * 8388608 ** 2, rel=1e-6)


def test_adc_conversions():
    assert dspref.ad9226_ref(0) == -32768 and dspref.ad9226_ref(2048) == 0 and dspref.ad9226_ref(4095) == 32752
    assert dspref.ad9226_ref(0x800, twos=True) == -32768 and dspref.ad9226_ref(0x7FF, twos=True) == 32752
    assert dspref.spi_sar_ref(0xFFFF) == 32767 and dspref.spi_sar_ref(0) == 0
