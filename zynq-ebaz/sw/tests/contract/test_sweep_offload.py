"""SweepEngine with an OffloadSweep on the fake PL platform, against the engine's own per-point loop."""
import numpy as np
import pytest
from sadiy_ebaz.offload_sweep import DEFAULT_STEPS, OffloadSweep
from sadiy_ebaz.platforms.fake_pl import FakePlPlatform
from sadiy_ebaz.regmap_toml import OFFSET, REGS

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.freqplan import build_opposite_sweep, build_sweep
from sadiy.core.sweep import (
    FLAG_IMAGE,
    FLAG_OVERRANGE,
    FLAG_UNDERRANGE,
    FLAG_UNLOCKED,
    SweepEngine,
)
from sadiy.drivers.adf4351 import Adf4351, Output, Outputs
from sadiy.drivers.pe4302 import PE4302

CTRL = REGS["CTRL"].fields

DET = Detector(slope_v_per_db=-0.025, intercept_dbm=20.0, divider_ratio=1.0, floor_dbm=-65.0, max_dbm=-1.0)
BASE = 10000
VPC = 4.096 / 32768.0
N_AVG = 4


def points(n=12, start=50e6, stop=450e6):
    return build_sweep(start, stop, n, 10.7e6, "high", 25e6)


class Rig:
    def __init__(self, base=BASE, **kw):
        self.plat = FakePlPlatform(det_src=1, det_test_base=base, volts_per_count=VPC)
        self.synth = Adf4351(self.plat.synth_link(), pfd_hz=25e6)
        self.synth.set_outputs(Outputs(main=Output(True, -4)))
        self.atten = PE4302(self.plat.atten_port())
        self.adapter = OffloadSweep(self.plat.offload(), self.synth, DEFAULT_STEPS, True, atten=self.atten, **kw)
        self.engine = SweepEngine(self.synth, self.atten, self.plat.detector(), DET, Cal(default_gain_db=0.0),
                                  averages=N_AVG, settle_s=0.0, sleep=lambda s: None, offload=self.adapter,
                                  lock=self.plat.lock_detect())


class ScriptSynth:
    def tune(self, pt):
        pass


class ScriptAtten:
    max_db = 31.5

    def set_attenuation(self, db):
        return db


class ScriptAdc:
    def __init__(self, volts):
        self.volts = list(volts)

    def read_samples(self, n=1):
        return [self.volts.pop(0)] * n


def reference(n_points, atten_db, base=BASE):
    """The non-offloaded engine fed with the voltages the model generates."""
    volts = [(base + (i & 0xFF)) * VPC for i in range(n_points)]
    eng = SweepEngine(ScriptSynth(), ScriptAtten(), ScriptAdc(volts), DET, Cal(default_gain_db=0.0),
                      averages=N_AVG, settle_s=0.0, sleep=lambda s: None, lock=lambda: True)
    return eng, eng.run(points(n_points), atten_db)


def test_dbm_equals_the_per_point_engine():
    rig = Rig()
    pts = points(12)
    out = rig.engine.run(pts, 10.0)
    ref_eng, ref = reference(12, 10.0)
    assert np.allclose(out, ref, rtol=0, atol=1e-9)
    assert (rig.engine.last_flags == ref_eng.last_flags).all()
    assert rig.engine.last_peak_det_dbm == pytest.approx(ref_eng.last_peak_det_dbm)


def test_attenuation_is_reported_and_reaches_the_pins():
    rig = Rig()
    rig.engine.run(points(4), 10.2)
    assert rig.engine.last_atten_db == 10.0
    rig.engine.run(points(4), 99.0)
    assert rig.engine.last_atten_db == 31.5
    rig.engine.run(points(4), 6.0)
    assert rig.engine.last_atten_db == 6.0
    assert rig.plat.offload().pin_levels() == 0b001100                # 6 dB = 2 dB (V3) + 4 dB (V4)


def test_atten_enters_the_cal_correction():
    rig = Rig()
    cal = Cal(default_gain_db=20.0)
    rig.engine.cal = cal
    pts = points(3)
    a = rig.engine.run(pts, 0.0)
    b = rig.engine.run(pts, 10.0)
    assert np.allclose(b - a, 10.0)


def test_unlocked_points_get_the_flag_and_stats():
    rig = Rig()
    rig.plat.model.lock_model = lambda i, w: i not in (3, 8)
    pts = points(12)
    out = rig.engine.run(pts, 10.0)
    flags = rig.engine.last_flags
    assert [i for i in range(12) if flags[i] & FLAG_UNLOCKED] == [3, 8]
    st = rig.engine.last_stats
    assert st.unlocked == 2 and st.first_unlocked_hz == pts[3].f_rf_hz and st.lock_checked
    assert np.isfinite(out).all()


def test_unlocked_points_do_not_steer_the_peak():
    rig = Rig()
    rig.plat.model.lock_model = lambda i, w: i != 0                 # point 0 would be the peak
    rig.engine.run(points(3), 0.0)
    assert rig.engine.last_peak_det_dbm < DET.dbm_from_adc_volts(BASE * VPC)


def test_range_flags_from_the_detector_volts():
    # codes near full scale: volts below the detector floor / above max
    rig = Rig(base=0)                                              # 0 V -> p_det huge -> overload
    rig.engine.run(points(2), 0.0)
    assert rig.engine.last_flags[0] & FLAG_OVERRANGE
    rig2 = Rig(base=30000)                                         # 3.75 V -> far below the floor
    rig2.engine.run(points(2), 0.0)
    assert rig2.engine.last_flags[0] & FLAG_UNDERRANGE


def test_no_outlier_flag_and_mean_semantics():
    rig = Rig()
    rig.engine.run(points(6), 0.0)
    assert not (rig.engine.last_flags & 8).any()


def test_table_is_uploaded_only_when_something_changed():
    rig = Rig()
    pts = points(8)
    rig.engine.run(pts, 10.0)
    rig.engine.run(pts, 10.0)
    assert rig.adapter.uploads == 1
    rig.engine.run(pts, 12.0)                                      # attenuation is in the table
    assert rig.adapter.uploads == 2
    rig.engine.run(list(pts), 12.0)                                # equal points, new list
    assert rig.adapter.uploads == 2
    rig.engine.run(points(9), 12.0)
    assert rig.adapter.uploads == 3
    rig.synth.disable_outputs()                                    # R4 changes
    rig.engine.run(points(9), 12.0)
    assert rig.adapter.uploads == 4


def test_run_rejecting_works_through_run():
    rig = Rig()
    pts = points(10, 50e6, 450e6)
    other, have = build_opposite_sweep(pts, 10.7e6, "high", 25e6)
    out = rig.engine.run_rejecting(pts, other, have, 10.0)
    assert out.shape == (10,) and np.isfinite(out).all()
    assert rig.adapter.uploads == 2                                # main and opposite side
    assert rig.engine.last_atten_db == 10.0
    assert not (rig.engine.last_flags & FLAG_UNLOCKED).any()


def test_run_rejecting_merges_unlock_flags():
    rig = Rig()
    pts = points(6, 100e6, 400e6)
    other, have = build_opposite_sweep(pts, 10.7e6, "high", 25e6)
    calls = []

    def lock(i, w):                                                # fail point 2 of the main sweep only
        calls.append(i)
        return not (i == 2 and calls.count(2) == 1)

    rig.plat.model.lock_model = lock
    assert have.all()
    out = rig.engine.run_rejecting(pts, other, have, 0.0)
    flags = rig.engine.last_flags
    assert len(out) == 6 and np.isfinite(out).all()
    assert flags[2] & FLAG_IMAGE and not flags[2] & FLAG_UNLOCKED   # the locked side counts, no partner to compare


def test_the_engine_does_not_touch_the_ps_spi():
    rig = Rig()
    n = len(rig.plat.synth_link().sent)
    rig.engine.run(points(5), 0.0)
    assert len(rig.plat.synth_link().sent) == n


def test_the_sweep_words_are_those_of_the_synth():
    rig = Rig()
    pts = points(5)
    rig.engine.run(pts, 0.0)
    sent = rig.plat.model.spi_words
    expect = [w for pt in pts[:1] for w in rig.synth.registers(pt.pll)]
    assert sent[:6] == expect
    assert all(w & 7 in range(6) for w in sent)


def test_safe_state_gives_the_pins_back_and_the_synth_turns_off():
    rig = Rig()
    rig.engine.run(points(4), 10.0)
    assert rig.plat.offload().status()["pin_owner_act"] == 1
    n = len(rig.plat.synth_link().sent)
    assert rig.engine.safe_state() == []
    assert rig.plat.offload().status()["pin_owner_act"] == 0
    assert [ln.level for ln in rig.plat.atten_port()] == [1] * 6
    assert len(rig.plat.synth_link().sent) > n                     # R4 with outputs off went over the PS SPI
    out = rig.engine.run(points(4), 10.0)                          # and the engine can take the pins again
    assert np.isfinite(out).all()


def test_incomplete_sweep_raises_and_reuploads():
    rig = Rig()
    pts = points(6)
    rig.plat.model.write(OFFSET["CTRL"], rig.plat.model.read(OFFSET["CTRL"]) | CTRL["stop_on_err"].mask)
    rig.plat.model.lock_model = lambda i, w: i != 3
    with pytest.raises(RuntimeError, match="incomplete"):
        rig.engine.run(pts, 0.0)
    rig.plat.model.lock_model = lambda i, w: True
    assert np.isfinite(rig.engine.run(pts, 0.0)).all()
    assert rig.adapter.uploads == 2
