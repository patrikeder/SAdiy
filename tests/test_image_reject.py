"""Two-sweep image suppression: the merge, the opposite-side sweep, the engine and sweepd with the simulator."""
import io
import logging

import numpy as np
import pytest

from sadiy import config, logs
from sadiy.core.freqplan import OUT_MIN_HZ, build_opposite_sweep, build_sweep, opposite_injection
from sadiy.core.sweep import (FLAG_IMAGE, FLAG_OUTLIER, FLAG_UNLOCKED, flag_names, merge_image_sweeps)
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_sim_engine

IF = 10.7e6


# ---------------------------------------------------------------- merge

def merge(p_m, f_m, p_o, f_o, have):
    return merge_image_sweeps(np.array(p_m, float), np.array(f_m, np.uint8), np.array(p_o, float),
                              np.array(f_o, np.uint8), np.array(have, bool))


def test_merge_keeps_the_lower_reading_and_both_sets_of_flags():
    p, f = merge([-30.0, -30.0, -90.0], [0, FLAG_OUTLIER, 0], [-95.0, -29.0, -40.0], [0, 0, 0], [True] * 3)
    assert list(p) == [-95.0, -30.0, -90.0]              # the ghost (-30 on one side only) is gone
    assert list(f) == [0, FLAG_OUTLIER, 0]


def test_merge_without_a_partner_flags_the_point():
    p, f = merge([-30.0, -40.0], [0, 0], [np.nan, -50.0], [0, 0], [False, True])
    assert list(p) == [-30.0, -50.0]
    assert f[0] == FLAG_IMAGE and f[1] == 0
    assert flag_names(int(f[0])) == ["image not suppressed"]


def test_merge_does_not_trust_an_unlocked_side():
    # the unlocked side reads garbage that happens to be low: it must not win
    p, f = merge([-30.0, -80.0], [0, FLAG_UNLOCKED], [-99.0, -40.0], [FLAG_UNLOCKED, 0], [True, True])
    assert list(p) == [-30.0, -40.0]
    assert f[0] == FLAG_IMAGE and f[1] == FLAG_IMAGE      # one reading only: an image may show, locked or not
    p, f = merge([-30.0], [FLAG_UNLOCKED], [-40.0], [FLAG_UNLOCKED], [True])
    assert p[0] == -40.0 and f[0] == FLAG_UNLOCKED        # both unlocked: still flagged as such


# ---------------------------------------------------------------- opposite sweep

def test_opposite_sweep_limits_follow_the_lo_range():
    pts = build_sweep(30e6, 480e6, 451, IF, "high", 25e6)
    other, have = build_opposite_sweep(pts, IF, "high", 25e6)
    assert len(other) == int(have.sum()) and len(other) < len(pts)
    assert all(o.f_lo_hz == pytest.approx(o.f_rf_hz - IF) and o.f_lo_hz >= OUT_MIN_HZ for o in other)
    assert all(pts[i].f_rf_hz - IF < OUT_MIN_HZ for i in np.flatnonzero(~have))      # only the low end is missing
    assert all(o.pll is not None for o in other)
    assert opposite_injection("low") == "high"
    with pytest.raises(ValueError):
        opposite_injection("both")
    # a low-side main sweep: the partner is high-side and limited by the AD831 LO maximum
    pts_low = build_sweep(300e6, 520e6, 23, IF, "low", 25e6)
    other, have = build_opposite_sweep(pts_low, IF, "low", 25e6)
    assert all(o.f_lo_hz <= 500e6 for o in other) and not have[-1] and have[0]


# ---------------------------------------------------------------- sweepd with the simulator

@pytest.fixture
def ring():
    r = logs.setup("error", stream=io.StringIO())
    yield r
    for h in list(logging.getLogger("sadiy").handlers):
        if getattr(h, "_sadiy", False):
            logging.getLogger("sadiy").removeHandler(h)


def make(ring, tones, start=60e6, stop=140e6, points=1001, image=True):
    cfg = config.load()
    cfg["sim"] = dict(cfg.get("sim", {}), tones=tones)
    d = Sweepd(cfg, build_sim_engine(cfg), ring=ring)
    assert d.apply({"cmd": "set", "start_hz": start, "stop_hz": stop, "points": points, "auto_atten": False,
                    "atten_db": 0.0, "image_reject": image})["ok"]
    return d


def level_at(header, p, f_hz):
    i = int(round((f_hz - header["f_start_hz"]) / header["f_step_hz"]))
    return float(p[max(i - 1, 0):i + 2].max())


def test_the_image_of_a_tone_disappears_and_the_tone_stays(ring):
    tones = [[100e6, -30.0]]
    plain = make(ring, tones, image=False)
    header, p = protocol.decode_frame(plain.run_step())
    assert level_at(header, p, 100e6) == pytest.approx(-30.0, abs=1.5)
    assert level_at(header, p, 100e6 - 2 * IF) == pytest.approx(-30.0, abs=1.5)    # the ghost, as before
    d = make(ring, tones, image=True)
    header, p, flags = protocol.decode_frame_flags(d.run_step())
    assert header["image_reject"] is True
    assert level_at(header, p, 100e6) == pytest.approx(-30.0, abs=1.5)
    assert level_at(header, p, 100e6 - 2 * IF) < -80.0                               # ghost gone
    assert level_at(header, p, 100e6 + 2 * IF) < -80.0                               # and no ghost above either
    assert not (flags & FLAG_IMAGE).any()                                            # every point had a partner


def test_two_tones_exactly_two_if_apart_both_survive(ring):
    d = make(ring, [[100e6, -30.0], [100e6 + 2 * IF, -40.0]])
    header, p = protocol.decode_frame(d.run_step())
    assert level_at(header, p, 100e6) == pytest.approx(-30.0, abs=1.5)
    assert level_at(header, p, 100e6 + 2 * IF) == pytest.approx(-40.0, abs=1.5)
    assert level_at(header, p, 100e6 - 2 * IF) < -80.0


def test_points_without_a_partner_are_flagged_and_announced(ring):
    d = make(ring, [[40e6, -30.0]], start=30e6, stop=70e6, points=161)
    header, p, flags = protocol.decode_frame_flags(d.run_step())
    f = header["f_start_hz"] + np.arange(header["n"]) * header["f_step_hz"]
    low = f - IF < OUT_MIN_HZ
    assert low.any() and (~low).any()
    assert ((flags & FLAG_IMAGE) != 0).tolist() == low.tolist()
    assert d.apply({"cmd": "status"})["last_sweep"]["image_unresolved"] == int(low.sum())
    info = [e.msg for e in ring.entries(min_level=logging.INFO)]
    assert any("image rejection:" in m and "suppression starts at 45.2" in m for m in info)
    assert any("image rejection on (two sweeps per trace)" in m for m in info)


def test_setting_is_remembered_validated_and_restarts_the_announcement(ring):
    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg), ring=ring)
    assert d.apply({"cmd": "status"})["settings"]["image_reject"] is False           # the config default
    assert d.apply({"cmd": "set", "image_reject": 1})["settings"]["image_reject"] is True
    d.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "points": 21})
    d.run_step()
    d.apply({"cmd": "set", "image_reject": False})
    d.run_step()
    msgs = [e.msg for e in ring.entries(min_level=logging.INFO) if e.msg.startswith("sweeping")]
    assert len(msgs) == 2 and "image rejection" in msgs[0] and "image rejection" not in msgs[1]
    header, _ = protocol.decode_frame(d.run_step())
    assert "image_reject" not in header


def test_auto_range_uses_the_higher_peak_of_the_two_sweeps(ring):
    d = make(ring, [[100e6, -30.0]], start=90e6, stop=110e6, points=81, image=True)
    d.apply({"cmd": "set", "auto_atten": True})
    d.run_step()
    peak = d.engine.last_peak_det_dbm
    d2 = make(ring, [[100e6, -30.0]], start=90e6, stop=110e6, points=81, image=False)
    d2.run_step()
    assert peak == pytest.approx(d2.engine.last_peak_det_dbm, abs=1.5)               # same tone, same peak
