import numpy as np
import pytest

from sadiy.ui import sa_core as core


AX = core.Axis(100e6, 1e6, 101)          # 100 .. 200 MHz


def test_axis_geometry_and_index():
    assert AX.stop_hz == 200e6 and AX.span_hz == 100e6 and AX.center_hz == 150e6
    assert AX.index_of(150e6) == 50
    assert AX.index_of(150.4e6) == 50 and AX.index_of(150.6e6) == 51
    assert AX.index_of(99.0e6) is None and AX.index_of(201e6) is None
    assert AX.index_of(99.6e6) == 0
    assert AX.freqs()[[0, -1]].tolist() == [100e6, 200e6]


def test_axis_from_header_matches_protocol_fields():
    ax = core.Axis.from_header({"f_start_hz": 1e6, "f_step_hz": 2e3, "n": 11})
    assert ax == core.Axis(1e6, 2e3, 11)


def test_format_hz():
    assert core.format_hz(250e6) == "250.000 MHz"
    assert core.format_hz(230e3, 0) == "230 kHz"
    assert core.format_hz(1.5e9, 2) == "1.50 GHz"
    assert core.format_hz(12) == "12 Hz"
    assert core.format_hz(-21.4e6, 1) == "-21.4 MHz"


def test_center_span_is_clamped_into_limits():
    lim = core.Limits(rf_min_hz=30e6, rf_max_hz=480e6)
    s = core.SaSettings()
    s.set_center_span(475e6, 100e6, lim)               # would run past the top: shifted down
    assert (s.start_hz, s.stop_hz) == (380e6, 480e6)
    s.set_center_span(100e6, 5e9, lim)                 # span larger than the range
    assert (s.start_hz, s.stop_hz) == (30e6, 480e6)
    s.set_center_span(100e6, 1.0, lim)                 # span below the minimum
    assert s.span_hz == lim.min_span_hz


def test_start_stop_is_clamped_and_ordered():
    lim = core.Limits()
    s = core.SaSettings()
    s.set_start_stop(0.0, 1e9, lim)
    assert (s.start_hz, s.stop_hz) == (lim.rf_min_hz, lim.rf_max_hz)
    s.set_start_stop(200e6, 100e6, lim)                # stop below start
    assert s.stop_hz == pytest.approx(200e6 + lim.min_span_hz)
    s.set_start_stop(1e9, 2e9, lim)                    # start above the top
    assert s.start_hz == lim.rf_max_hz - lim.min_span_hz and s.stop_hz == lim.rf_max_hz


def test_command_matches_what_sweepd_accepts():
    from sadiy import config
    from sadiy.server.sweepd import Sweepd, build_sim_engine

    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    s = core.SaSettings(start_hz=90e6, stop_hz=110e6, points=201, averages=2, atten_db=5.0, auto_atten=False)
    assert d.apply(s.to_command())["ok"]
    assert d.settings["points"] == 201 and d.settings["auto_atten"] is False
    mirror = core.SaSettings()
    mirror.apply_server(d.apply({"cmd": "status"})["settings"])
    assert mirror.start_hz == 90e6 and mirror.points == 201 and mirror.averages == 2


def test_limits_from_server_status():
    from sadiy import config
    from sadiy.server.sweepd import Sweepd, build_sim_engine

    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    lim = core.Limits(rf_min_hz=1.0, rf_max_hz=2.0)
    lim.apply_server(d.apply({"cmd": "status"})["limits"])
    assert (lim.rf_min_hz, lim.rf_max_hz, lim.max_points) == (30e6, 480e6, 4001)


def test_points_rule_matches_architecture_doc():
    # 450 MHz span at 230 kHz RBW needs about 3900 points
    assert core.recommended_points(450e6, 230e3) == pytest.approx(3914, abs=2)
    assert core.recommended_points(450e6, 230e3, max_points=2000) == 2000
    assert core.undersampled(401, 450e6, 230e3)
    assert not core.undersampled(4001, 450e6, 230e3)
    assert core.recommended_points(1e3, 230e3) == 2


def test_autoscale():
    p = np.full(100, -90.0)
    p[40] = -28.0
    ref, dpd = core.autoscale(p)
    assert ref == -20.0 and dpd == 10.0
    assert core.autoscale([-33.0, -33.5]) == (-30.0, 1.0)
    assert core.autoscale([]) == (-20.0, 10.0)
    ref, _ = core.autoscale([-40.0, -80.0])              # peak just under a multiple of 10 gets headroom
    assert ref - (-40.0) >= 2.0


def test_trace_modes():
    t = core.TraceProcessor()
    a = np.array([1.0, 5.0, 3.0])
    b = np.array([4.0, 2.0, 3.5])
    assert t.update(AX, a).tolist() == [1, 5, 3]
    assert t.update(AX, b).tolist() == [4, 2, 3.5]               # clear/write replaces
    t.set_mode("max_hold")
    t.update(AX, a)
    assert t.update(AX, b).tolist() == [4, 5, 3.5]
    t.set_mode("min_hold")
    t.update(AX, a)
    assert t.update(AX, b).tolist() == [1, 2, 3]
    t.set_mode("average")
    t.avg_count = 2
    t.update(AX, a)
    assert t.update(AX, b).tolist() == [2.5, 3.5, 3.25]
    t.set_mode("view")                                           # freeze what is on screen
    frozen = t.data.copy()
    t.update(AX, np.zeros(3))
    assert t.data.tolist() == frozen.tolist()
    t.set_mode("blank")
    assert t.update(AX, a) is None and t.data is None


def test_average_converges_with_exponential_weight():
    t = core.TraceProcessor("average", avg_count=4)
    for _ in range(3):
        t.update(AX, np.zeros(2))
    for _ in range(40):
        out = t.update(AX, np.full(2, 8.0))
    assert out[0] == pytest.approx(8.0, abs=1e-3)


def test_hold_restarts_when_axis_changes():
    t = core.TraceProcessor("max_hold")
    t.update(AX, np.array([9.0, 9.0, 9.0]))
    other = core.Axis(100e6, 2e6, 3)
    assert t.update(other, np.array([1.0, 1.0, 1.0])).tolist() == [1, 1, 1]


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        core.TraceProcessor("nope")
    with pytest.raises(ValueError):
        core.TraceProcessor().set_mode("nope")


def _spectrum():
    p = np.full(101, -95.0)
    p += np.random.default_rng(1).normal(0, 0.2, p.size)
    for i, lvl in ((20, -30.0), (55, -45.0), (80, -60.0)):
        p[i - 1], p[i], p[i + 1] = lvl - 3, lvl, lvl - 3
    return p


def test_peak_search_walks_down_the_peaks():
    p = _spectrum()
    i = core.peak_index(p)
    assert i == 20
    i = core.next_peak(p, i, "lower")
    assert i == 55
    i = core.next_peak(p, i, "lower")
    assert i == 80
    assert core.next_peak(p, i, "lower") is None                 # noise bumps are below the threshold


def test_peak_left_right():
    p = _spectrum()
    assert core.next_peak(p, 55, "right") == 80
    assert core.next_peak(p, 55, "left") == 20
    assert core.next_peak(p, 80, "right") is None
    assert core.next_peak(p, 20, "left") is None
    with pytest.raises(ValueError):
        core.next_peak(p, 20, "up")


def test_next_peak_skips_the_skirt_of_the_current_signal():
    p = np.full(50, -90.0)
    p[10], p[12] = -30.0, -33.0                                  # two bumps within one RBW
    p[30] = -50.0
    assert core.next_peak(p, 10, "lower", min_sep=4) == 30
    assert core.next_peak(p, 10, "lower", min_sep=1) == 12


def test_min_separation_bins():
    assert core.min_separation_bins(230e3, 1.1e6) == 3
    assert core.min_separation_bins(230e3, 50e3) == 5
    assert core.min_separation_bins(230e3, 0.0) == 3


def test_marker_follows_frequency_across_axis_changes():
    m = core.Marker()
    assert m.index_in(AX) is None                                # disabled
    m.place(AX, 50)
    assert m.enabled and m.f_hz == 150e6
    zoom = core.Axis(140e6, 0.5e6, 41)
    assert m.index_in(zoom) == 20
    assert m.index_in(core.Axis(200e6, 1e6, 10)) is None         # off screen


def test_marker_text_and_csv():
    assert "250.0000 MHz" in core.marker_text("M1", 250e6, -45.2)
    assert core.delta_text(100e6, -30.0, 250e6, -45.0).endswith("-15.00 dB")
    csv = core.trace_to_csv(core.Axis(1e6, 1e3, 3), [-1.0, -2.5, -3.0], 10.0)
    rows = csv.strip().splitlines()
    assert rows[0] == "# SAdiy trace" and rows[2] == "freq_hz,level_dbm"
    assert rows[3:] == ["1000000,-1.000", "1001000,-2.500", "1002000,-3.000"]
