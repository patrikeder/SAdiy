"""Virtual spectrum: generator + IF path of the PL model show three drifting peaks through the normal detector path."""
import numpy as np
import pytest
from sadiy_ebaz.ebaz_pl_model import PlModel
from sadiy_ebaz.reg_offload import RegOffload
from sadiy_ebaz.regmap_toml import OFFSET, REGS
from sadiy_ebaz.virtual_spectrum import SpectrumConfig, VirtualSweep, cic_response, noise_rms_for

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.freqplan import build_sweep
from sadiy.core.sweep import FLAG_UNDERRANGE, SweepEngine

DET = Detector(slope_v_per_db=-0.0245, intercept_dbm=20.0, divider_ratio=1.0, floor_dbm=-65.0, max_dbm=-1.0)
CAL = Cal(default_gain_db=22.0)
N_AVG = 4
PEAKS = ((100e6, -30.0), (200e6, -45.0), (300e6, -60.0))


def points(n=401, start=30e6, stop=480e6):
    return build_sweep(start, stop, n, 10.7e6, "high", 25e6)


class Rig:
    def __init__(self, config=None, table_aw=12, result_aw=12):
        self.model = PlModel(table_aw=table_aw, result_aw=result_aw)
        self.model.ld_now = True
        self.off = RegOffload(self.model.read, self.model.write, poll_s=0.0)
        self.vs = VirtualSweep(self.off, DET, CAL, config=config)

    def rd(self, name):
        return self.model.read(OFFSET[name])

    def dbm(self, pts, atten=0.0):
        volts, unlocked, att = self.vs.run_points(pts, atten, N_AVG)
        return np.array([DET.dbm_from_adc_volts(v) - CAL.gain_db(p.f_rf_hz) + att for v, p in zip(volts, pts)]), att


def test_the_three_peaks_stand_where_they_should_with_their_levels():
    rig, pts = Rig(), points()
    dbm, _ = rig.dbm(pts)
    for index, (_, level) in zip(rig.vs.peak_indices(), PEAKS):
        i = int(round(index))
        assert dbm[i - 3:i + 4].argmax() == 3 or abs(dbm[i - 3:i + 4].max() - dbm[i]) < 0.5
        assert dbm[i - 3:i + 4].max() == pytest.approx(level, abs=1.5)
    # the peaks are at 100, 200 and 300 MHz of the display axis
    f = np.array([p.f_rf_hz for p in pts])
    for (f_peak, _), index in zip(PEAKS, rig.vs.peak_indices()):
        assert f[int(round(index))] == pytest.approx(f_peak, abs=1.5 * (f[1] - f[0]))
    floor = np.median(dbm)
    assert floor == pytest.approx(-90.0, abs=3.0)


def test_levels_follow_the_attenuator_setting_like_a_real_input():
    rig, pts = Rig(SpectrumConfig(drift_points=0)), points(101)
    flat, att = rig.dbm(pts, 0.0)
    att10, att_set = rig.dbm(pts, 10.0)
    assert att == 0.0 and att_set == 10.0
    for index in rig.vs.peak_indices():                          # the displayed level does not depend on the setting
        i = int(round(index))
        assert att10[i - 3:i + 4].max() == pytest.approx(flat[i - 3:i + 4].max(), abs=1.0)


def test_the_peaks_drift_back_and_forth_and_the_state_says_where():
    cfg = SpectrumConfig(drift_points=6, drift_period=12)
    rig, pts = Rig(cfg), points()
    seen = []
    for _ in range(13):
        dbm, _ = rig.dbm(pts)
        st = rig.vs.state()
        first = rig.vs.peak_indices()[0]
        assert first == pytest.approx(rig.vs.tones[0][2] - st["drift_points"])
        assert abs(int(dbm.argmax()) - round(first)) <= 1 or dbm[int(round(first))] > dbm.max() - 1.0   # strongest peak
        seen.append(st["drift_points"])
    assert max(seen) == 6 and min(seen) == -6 and seen[0] == 0 and seen[12] == 0


def test_noise_is_new_every_sweep_and_the_peaks_stay():
    cfg = SpectrumConfig(drift_points=0)
    rig, pts = Rig(cfg), points(101)
    a, _ = rig.dbm(pts)
    b, _ = rig.dbm(pts)
    assert rig.vs.state()["skip"] != 4
    far = [i for i in range(101) if min(abs(i - p) for p in rig.vs.peak_indices()) > 12]
    assert np.max(np.abs(a[far] - b[far])) > 1.0                    # new noise
    top = int(np.argmax(a))
    assert a[top] == pytest.approx(b[top], abs=0.5)                 # same peak


@pytest.mark.parametrize("sweeps", [1, 6])
def test_the_result_words_are_bit_exact_against_the_reference(sweeps):
    rig, pts = Rig(), points(101)
    for _ in range(sweeps):
        rig.dbm(pts)
        rows = rig.vs.verify()
        assert len(rows) >= 4 and all(ok for _, ok, _, _ in rows), rows
    assert all(ok for _, ok, _, _ in rig.vs.verify(range(0, 101, 10)))


def test_verify_notices_a_wrong_word():
    rig, pts = Rig(), points(41)
    rig.dbm(pts)
    rig.vs.last_words[6] ^= 0x10
    bad = [i for i, ok, _, _ in rig.vs.verify([0, 6, 40]) if not ok]
    assert bad == [6]


def test_the_ideal_trace_fits_the_measurement():
    rig, pts = Rig(), points()
    dbm, _ = rig.dbm(pts)
    ideal = np.array(rig.vs.ideal_dbm(pts))
    assert len(ideal) == 401 and len(rig.vs.ideal_dbm()) == 401
    near = [i for i in range(401) if min(abs(i - p) for p in rig.vs.peak_indices()) <= 3]
    assert np.max(np.abs(dbm[near] - ideal[near])) < 1.5
    assert abs(np.mean(dbm) - np.mean(ideal)) < 3.0


def test_the_ideal_trace_follows_the_drift():
    cfg = SpectrumConfig(drift_points=6, drift_period=12)
    rig, pts = Rig(cfg), points()
    for _ in range(4):
        dbm, _ = rig.dbm(pts)
        ideal = np.array(rig.vs.ideal_dbm())
        assert abs(int(ideal.argmax()) - int(round(rig.vs.peak_indices()[0]))) <= 1
        assert np.max(np.abs(dbm[ideal > -70] - ideal[ideal > -70])) < 2.5


def test_a_peak_outside_the_display_axis_is_left_out():
    rig, pts = Rig(), points(101, 30e6, 150e6)
    rig.dbm(pts)
    assert len(rig.vs.tones) == 1 and rig.vs.tones[0][3] == -30.0


def test_close_restores_the_registers_and_can_be_called_again():
    rig, pts = Rig(), points(41)
    before = {n: rig.rd(n) for n in ("DET_CFG", "GEN_CFG", "IF_NCO", "IF_NCO_STEP", "IF_CIC", "T_MIN_US",
                                      "T_SETTLE_US", "N_AVG")}
    rig.vs.close()                                              # before any sweep
    rig.dbm(pts)
    assert rig.rd("DET_CFG") != before["DET_CFG"] and rig.rd("T_MIN_US") == 1
    rig.vs.close()
    assert {n: rig.rd(n) for n in before} == before
    rig.vs.close()                                              # twice


def test_close_does_not_raise_when_a_register_write_fails():
    rig, pts = Rig(), points(41)
    rig.dbm(pts)

    def boom(name, value):
        raise OSError("bus error")

    rig.vs._wr = boom
    rig.vs.close()
    rig.vs.close()


def test_a_failed_run_raises_like_the_offload_and_the_next_sweep_recovers():
    rig, pts = Rig(), points(41)
    rig.dbm(pts)
    real = rig.off.run

    def fail(n_avg, timeout_s=10.0):
        raise TimeoutError("sweep did not finish")

    rig.off.run = fail
    with pytest.raises(TimeoutError):
        rig.dbm(pts)
    rig.off.run = real
    dbm, _ = rig.dbm(pts)
    assert len(dbm) == 41 and all(ok for _, ok, _, _ in rig.vs.verify())


def test_an_incomplete_result_is_an_error():
    rig, pts = Rig(), points(41)
    real = rig.off.run

    def short(n_avg, timeout_s=10.0):
        res = real(n_avg, timeout_s)
        res.sums = res.sums[:-1]
        return res

    rig.off.run = short
    with pytest.raises(RuntimeError, match="incomplete"):
        rig.dbm(pts)


def test_a_core_that_is_too_small_is_refused():
    rig = Rig(table_aw=4, result_aw=4)
    with pytest.raises(ValueError, match="points, the core holds"):
        rig.dbm(points(41))


def test_a_new_plan_rebuilds_the_pattern_and_the_table():
    rig = Rig()
    rig.dbm(points(41))
    n = len(rig.vs.pattern)
    first = list(rig.vs.pattern)
    rig.dbm(points(101, 30e6, 300e6))
    assert len(rig.vs.tones) == 3 and rig.vs.pattern != first and len(rig.vs.pattern) == n
    assert rig.rd("N_AVG") == N_AVG and len(rig.vs.last_words) == 101


def test_it_runs_inside_a_sweep_engine_and_the_flags_make_sense():
    class Synth:
        def tune(self, pt):
            pass

    class Atten:
        max_db = 31.5

        def set_attenuation(self, db):
            return db

    rig, pts = Rig(), points()
    engine = SweepEngine(Synth(), Atten(), None, DET, CAL, averages=N_AVG, settle_s=0.0, sleep=lambda s: None,
                         offload=rig.vs)
    out = engine.run(pts, 0.0)
    for index, (_, level) in zip(rig.vs.peak_indices(), PEAKS):
        i = int(round(index))
        assert out[i - 3:i + 4].max() == pytest.approx(level, abs=1.5)
    flags = engine.last_flags
    assert not flags[int(round(rig.vs.peak_indices()[0]))] & FLAG_UNDERRANGE      # -30 dBm is inside the window
    assert flags[0] & FLAG_UNDERRANGE                                             # the -90 dBm floor is below it


def test_a_skip_the_register_cannot_hold_is_refused():
    rig = Rig(SpectrumConfig(skips=(4, 16)))
    with pytest.raises(ValueError, match="skip must be 3..15"):
        rig.dbm(points(41))
    with pytest.raises(ValueError, match="skip must be 3..15"):
        Rig(SpectrumConfig(skips=(2,))).dbm(points(41))


def test_the_cic_shape_and_the_noise_setting_are_what_the_reference_says():
    assert cic_response(0.0, 25e6, 128) == 1.0
    assert abs(cic_response(25e6 / 128, 25e6, 128)) < 1e-9          # first null at fs / r
    assert 5 < noise_rms_for(SpectrumConfig()) < 100
    assert noise_rms_for(SpectrumConfig(floor_dbm=-80.0)) > noise_rms_for(SpectrumConfig(floor_dbm=-90.0))
