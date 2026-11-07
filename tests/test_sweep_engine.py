"""SweepEngine per-point handling: robust combine, lock gating, flags. Fake synth / ADC, no hardware."""
import math

import numpy as np
import pytest

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.freqplan import SweepPoint
from sadiy.core import sweep
from sadiy.core.sweep import (FLAG_OUTLIER, FLAG_OVERRANGE, FLAG_UNDERRANGE, FLAG_UNLOCKED, SweepEngine,
                              combine, flag_names, next_atten_db)

DET = Detector(slope_v_per_db=-0.025, intercept_dbm=20.0, divider_ratio=1.0, floor_dbm=-65.0, max_dbm=-1.0)


def volts(p_dbm):
    return DET.volts_from_dbm(p_dbm)


def points(n=5):
    return [SweepPoint(f_rf_hz=100e6 + i * 1e6, f_lo_hz=110.7e6 + i * 1e6, pll=None) for i in range(n)]


class FakeSynth:
    """Locks after `lock_after[i]` extra checks at point i (None: never). `retune_helps` makes the
    second tune lock at once."""

    def __init__(self, lock_after=None, retune_helps=False):
        self.lock_after = lock_after or {}
        self.retune_helps = retune_helps
        self.tuned = []
        self.checks = 0
        self._i = -1
        self._tunes_here = 0

    def tune(self, pt):
        if not self.tuned or self.tuned[-1] is not pt:
            self._i += 1
            self._tunes_here = 0
        self._tunes_here += 1
        self.tuned.append(pt)
        self.checks = 0

    def locked(self):
        self.checks += 1
        if self.retune_helps and self._tunes_here > 1:
            return True
        need = self.lock_after.get(self._i, 0)
        return need is not None and self.checks > need


class FakeAtten:
    max_db = 31.5

    def set_attenuation(self, db):
        return db


class ScriptAdc:
    """Returns the sample lists in turn: one list per point."""

    def __init__(self, per_point):
        self.per_point = list(per_point)

    def read_samples(self, n=1):
        return list(self.per_point.pop(0))


def engine(adc, synth=None, **kw):
    return SweepEngine(synth or FakeSynth(), FakeAtten(), adc, DET, Cal(default_gain_db=0.0), averages=4,
                       settle_s=0.0, sleep=lambda s: None, **kw)


def test_combine_methods():
    assert combine([1.0, 2.0, 9.0], "median") == 2.0
    assert combine([1.0, 2.0, 3.0, 10.0], "median") == 2.5
    assert combine([1.0, 2.0, 9.0], "trimmed") == 2.0
    assert combine([1.0, 2.0, 3.0, 10.0], "trimmed") == 2.5
    assert combine([1.0, 2.0, 9.0], "mean") == 4.0
    assert combine([1.0, 3.0], "median") == 2.0          # two samples: nothing to tell apart
    assert combine([5.0], "trimmed") == 5.0
    with pytest.raises(ValueError):
        combine([1.0], "mode")
    with pytest.raises(ValueError):
        combine([], "median")
    with pytest.raises(ValueError):
        engine(ScriptAdc([]), combine_method="mode")


def test_median_ignores_a_glitch_and_flags_it():
    good, glitch = volts(-30.0), volts(-5.0)
    out = engine(ScriptAdc([[good, good, glitch, good]] * 2)).run(points(2), 0.0)
    assert out[0] == pytest.approx(-30.0, abs=0.01)
    eng = engine(ScriptAdc([[good, good, glitch, good]]), combine_method="mean")
    assert eng.run(points(1), 0.0)[0] > -26.0            # the old behaviour: the glitch drags the point
    eng = engine(ScriptAdc([[good, good, glitch, good]]))
    eng.run(points(1), 0.0)
    assert eng.last_flags[0] & FLAG_OUTLIER and eng.last_stats.outliers == 1


def test_small_spread_is_not_an_outlier():
    v = volts(-30.0)
    eng = engine(ScriptAdc([[v, v + 0.01, v - 0.01, v]]))      # 0.01 V is 0.4 dB
    eng.run(points(1), 0.0)
    assert eng.last_flags[0] == 0 and eng.last_stats.outliers == 0


def test_detector_rails_are_flagged():
    eng = engine(ScriptAdc([[volts(0.0)] * 4, [volts(-30.0)] * 4, [volts(-70.0)] * 4]))
    eng.run(points(3), 0.0)
    assert list(eng.last_flags) == [FLAG_OVERRANGE, 0, FLAG_UNDERRANGE]
    assert (eng.last_stats.overrange, eng.last_stats.underrange) == (1, 1)
    assert flag_names(FLAG_OVERRANGE | FLAG_OUTLIER) == ["overload", "outlier rejected"]


def test_lock_after_a_short_wait_is_not_flagged():
    synth = FakeSynth(lock_after={1: 2})                       # point 1 locks on the third check
    eng = engine(ScriptAdc([[volts(-30.0)] * 4] * 3), synth)
    eng.run(points(3), 0.0)
    assert list(eng.last_flags) == [0, 0, 0] and eng.last_stats.retunes == 0
    assert eng.last_stats.lock_checked


def test_a_second_tune_can_bring_the_lock():
    synth = FakeSynth(lock_after={0: None}, retune_helps=True)
    eng = engine(ScriptAdc([[volts(-30.0)] * 4]), synth)
    eng.run(points(1), 0.0)
    assert eng.last_flags[0] == 0 and eng.last_stats.retunes == 1
    assert len(synth.tuned) == 2


def test_a_point_that_never_locks_is_flagged_and_kept_out_of_auto_range():
    synth = FakeSynth(lock_after={1: None})
    # the unlocked point reads like a huge peak: it must not steer the attenuator
    adc = ScriptAdc([[volts(-30.0)] * 4, [volts(-10.0)] * 4, [volts(-40.0)] * 4])
    eng = engine(adc, synth)
    eng.run(points(3), 0.0)
    assert list(eng.last_flags) == [0, FLAG_UNLOCKED, 0]
    assert eng.last_stats.unlocked == 1 and eng.last_stats.first_unlocked_hz == 101e6
    assert eng.last_peak_det_dbm == pytest.approx(-30.0, abs=0.01)


def test_all_unlocked_leaves_the_attenuator_alone():
    synth = FakeSynth(lock_after={0: None, 1: None})
    eng = engine(ScriptAdc([[volts(-30.0)] * 4] * 2), synth)
    eng.run(points(2), 0.0)
    assert eng.last_peak_det_dbm == float("-inf")
    assert next_atten_db(eng.last_peak_det_dbm, 12.0) == 12.0
    assert next_atten_db(float("nan"), 12.0) == 12.0


def test_no_lock_detect_means_no_gating():
    class NoLock:
        def tune(self, pt):
            pass

    eng = engine(ScriptAdc([[volts(-30.0)] * 4]), NoLock())
    eng.run(points(1), 0.0)
    assert not eng.last_stats.lock_checked and eng.last_flags[0] == 0
    eng2 = engine(ScriptAdc([[volts(-30.0)] * 4]), NoLock(), lock=lambda: False)     # an explicit lock source wins
    eng2.run(points(1), 0.0)
    assert eng2.last_flags[0] == FLAG_UNLOCKED


def test_an_adc_with_only_read_volts_still_works():
    class OldAdc:
        def read_volts(self, n=1):
            return volts(-30.0)

    eng = engine(OldAdc())
    assert eng.run(points(2), 0.0)[0] == pytest.approx(-30.0, abs=0.01)
    assert list(eng.last_flags) == [0, 0]


def test_errors_from_the_adc_or_the_lock_line_reach_the_caller():
    class Broken:
        def read_samples(self, n=1):
            raise OSError("I2C write failed on /dev/i2c-2")

    with pytest.raises(OSError):
        engine(Broken()).run(points(1), 0.0)

    def bad_lock():
        raise OSError("GPIO read failed")

    with pytest.raises(OSError):
        engine(ScriptAdc([[volts(-30.0)] * 4]), lock=bad_lock).run(points(1), 0.0)


def test_flag_bits_are_distinct():
    bits = [FLAG_UNLOCKED, FLAG_OVERRANGE, FLAG_UNDERRANGE, FLAG_OUTLIER]
    assert len(set(bits)) == 4 and all(math.log2(b).is_integer() for b in bits)
    assert sweep.FLAGS_UNRELIABLE == FLAG_UNLOCKED | FLAG_OVERRANGE
