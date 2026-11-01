"""Smoke tests of the Qt front end. Skipped when PyQt / pyqtgraph / pyzmq are not installed."""
import os
import socket
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy.ui import sa_core as core  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


@pytest.fixture
def win(app):
    w = MainWindow()
    yield w
    w.close()


def _frame(n=101, atten=10.0, start=100e6, step=1e6, seq=0):
    p = np.full(n, -95.0)
    for i, lvl in ((20, -30.0), (55, -45.0), (80, -60.0)):
        if i + 1 < n:
            p[i - 1], p[i], p[i + 1] = lvl - 3, lvl, lvl - 3
    header = {"v": 1, "seq": seq, "t": 1000.0 + seq * 0.1, "f_start_hz": start, "f_step_hz": step, "n": n, "atten_db": atten}
    return header, p


def test_window_builds_with_two_tabs(win):
    tabs = win.centralWidget()
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Spectrum", "Advanced"]
    assert "REF" in win.info.text() and "Start" in win.lbl_start.text()


def test_frame_draws_trace_and_info(win):
    win.handle_frame(*_frame())
    assert win.trace_a.data is not None and win.trace_a.data.size == 101
    assert "ATT 10 dB" in win.info.text()
    assert "100.000 MHz" in win.lbl_start.text() and "200.000 MHz" in win.lbl_stop.text()
    xs, ys = win.view.trace_a.getData()
    assert len(xs) == 101 and ys.max() == pytest.approx(-30.0)


def test_peak_search_and_delta_readout(win):
    win.handle_frame(*_frame())
    win._peak()
    assert win.m[0].f_hz == 120e6
    win._next_peak("lower")
    assert win.m[0].f_hz == 155e6
    win._on_plot_click(180e6, second=True)
    text = win.readout.text()
    assert "M1" in text and "M2" in text and "Δ" in text and "-15.00 dB" in text


def test_marker_stays_on_frequency_when_axis_changes(win):
    win.handle_frame(*_frame())
    win._peak()
    win.handle_frame(*_frame(n=41, start=110e6, step=0.5e6, seq=1))      # zoom around 120 MHz
    assert win.m[0].index_in(win.axis) == 20
    win.handle_frame(*_frame(n=41, start=300e6, step=0.5e6, seq=2))      # marker now off screen
    assert win.m[0].index_in(win.axis) is None and win.readout.text() == ""


def test_max_hold_and_blank(win):
    win.handle_frame(*_frame())
    win.mode_cb.setCurrentIndex(1)                                       # Max hold (restarts the hold)
    win.handle_frame(*_frame(seq=1))
    low = _frame(seq=2)
    low[1][:] = -120.0
    win.handle_frame(*low)
    assert win.trace_a.data.max() == pytest.approx(-30.0)
    win.mode_cb.setCurrentIndex(5)                                       # Blank
    win.handle_frame(*_frame(seq=2))
    assert win.trace_a.data is None
    assert win.view.trace_a.getData()[0] is None or len(win.view.trace_a.getData()[0]) == 0


def test_frequency_entry_is_clamped_to_the_limits(win):
    win.stop_sb.setValue(600.0)
    assert win.settings.stop_hz == 480e6 and win.stop_sb.value() == pytest.approx(480.0)
    win.span_sb.setValue(40.0)
    win.center_sb.setValue(100.0)
    assert (win.settings.start_hz, win.settings.stop_hz) == (80e6, 120e6)
    assert win.start_sb.value() == pytest.approx(80.0) and win.stop_sb.value() == pytest.approx(120.0)
    win._zoom(0.5)
    assert win.settings.span_hz == pytest.approx(20e6)
    win._full_span()
    assert (win.settings.start_hz, win.settings.stop_hz) == (30e6, 480e6)


def test_undersampling_warning_and_auto_points(win):
    assert "Use about" in win.status_warn.text()                          # 401 points over 450 MHz
    win._auto_points()
    assert win.settings.points == 3915 or win.settings.points == 3914 or win.settings.points >= 3900
    assert win.status_warn.text() == ""


def test_auto_scale_and_store_b(win):
    win.handle_frame(*_frame())
    win._auto_scale()
    assert win.settings.ref_dbm == -20.0 and win.settings.db_per_div == 10.0
    win._store_b()
    assert win.show_b_chk.isChecked() and win.trace_b is not None
    xs, ys = win.view.trace_b.getData()
    assert len(xs) == 101


def test_auto_atten_follows_frames_and_manual_keeps_value(win):
    win.handle_frame(*_frame(atten=17.5))
    assert win.att_sb.value() == pytest.approx(17.5) and not win.att_sb.isEnabled()
    win.auto_att_chk.setChecked(False)
    assert win.settings.auto_atten is False and win.settings.atten_db == pytest.approx(17.5)
    assert win.att_sb.isEnabled()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spin(app, seconds, until=lambda: False):
    end = time.time() + seconds
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.01)


def test_start_simulated_hardware_end_to_end(app):
    w = MainWindow(pub_port=_free_port(), rep_port=_free_port())
    try:
        w.start_sim()
        _spin(app, 15, lambda: w._frames >= 3)
        _spin(app, 15, lambda: w.synced)
        assert w.runner.running and w._frames >= 3 and w.synced
        assert w.status_conn.text().startswith("connected")
        assert w.limits.rf_max_hz == 480e6                                  # adopted from sweepd status
        # the sim tones from the Advanced tab show up in the trace: strongest peak is the 100 MHz tone or its image
        w.span_sb.setValue(20.0)
        w.center_sb.setValue(100.0)
        n = w._frames
        _spin(app, 15, lambda: w._frames > n + 3 and abs(w.axis.center_hz - 100e6) < 1e3)
        assert abs(w.axis.center_hz - 100e6) < 1e3 and w.axis.span_hz == pytest.approx(20e6)
        assert abs(w.axis.freq_at(core.peak_index(w.trace_a.data)) - 100e6) < 1e6
        w._toggle_sim()
        assert not w.runner.running and w.sim_label.text() == "stopped"
    finally:
        w.close()
