"""Smoke tests of the Qt front end. Skipped when PyQt / pyqtgraph / pyzmq are not installed."""
import logging
import os
import socket
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy import logs  # noqa: E402
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


def test_window_builds_with_three_tabs(win):
    tabs = win.centralWidget()
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Spectrum", "Pins", "Advanced"]
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
        # what the daemon said before the GUI connected arrives by the `log` fetch, and live after that
        _spin(app, 15, lambda: "sweeping" in w.dev_log_view.toPlainText())
        text = w.dev_log_view.toPlainText()
        assert "sweepd starting: simulated chain" in text and "sweeping 30.000 to 480.000 MHz" in text
        assert not w.dev_log.gap
        w.client.request({"cmd": "set", "points": 99999})                   # refused: a warning, live
        _spin(app, 15, lambda: "points must be 2..4001" in w.dev_log_view.toPlainText())
        assert w.tabs.tabText(2).startswith("Advanced") and "1 warning" in w.status_log.text()
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


# ---------------------------------------------------------------- device log (Advanced tab)

def _entry(seq, level, msg, boot="b1"):
    return logs.LogEntry(seq, 1000.0 + seq, level, "sadiy.server.sweepd", msg, 0, boot)


def test_device_log_shows_entries_and_counts_unread(win):
    win.tabs.setCurrentIndex(0)
    win.dev_log.add_fetched([], boot="b1", last_seq=0)
    win._show_log_entries(win.dev_log.add_live([
        _entry(1, logging.INFO, "sweepd starting"), _entry(2, logging.DEBUG, "fine detail"),
        _entry(3, logging.WARNING, "PLL unlocked on 3 points"),
    ]))
    text = win.dev_log_view.toPlainText()
    assert "sweepd starting" in text and "PLL unlocked on 3 points" in text
    assert "fine detail" not in text                                        # below the default level (info)
    assert win.tabs.tabText(2) == "Advanced (1 warning)"
    assert win.status_log.isVisibleTo(win) and win.status_log.text() == "1 warning"
    win._show_log_entries(win.dev_log.add_live([_entry(4, logging.ERROR, "SPI write failed")]))
    assert win.tabs.tabText(2) == "Advanced (1 error, 1 warning)"
    assert "SPI write failed" in win.status_msg.text()                      # errors also reach the status bar
    win.tabs.setCurrentIndex(2)                                             # looking at it: nothing is unread
    assert win.tabs.tabText(2) == "Advanced" and not win.status_log.isVisibleTo(win)


def test_device_log_level_pause_and_clear(win):
    win.dev_log.add_fetched([], boot="b1", last_seq=0)
    win._show_log_entries(win.dev_log.add_live([
        _entry(1, logging.DEBUG, "fine detail"), _entry(2, logging.INFO, "routine"), _entry(3, logging.WARNING, "careful"),
    ]))
    box = win.dev_log_view
    win.dev_level_cb.setCurrentIndex(3)                                     # Debug
    assert "fine detail" in box.toPlainText()
    win.dev_level_cb.setCurrentIndex(1)                                     # Warning
    assert box.toPlainText().strip().endswith("careful") and "routine" not in box.toPlainText()
    win.dev_pause_chk.setChecked(True)
    win._show_log_entries(win.dev_log.add_live([_entry(4, logging.WARNING, "while paused")]))
    assert "while paused" not in box.toPlainText()                          # kept, not shown yet
    win.dev_pause_chk.setChecked(False)
    assert "while paused" in box.toPlainText()
    win._clear_dev_log()
    assert box.toPlainText() == "" and win.dev_log.badge == ""
    assert win.dev_log.add_live([_entry(4, logging.WARNING, "while paused")]) == []    # does not come back


def test_status_bar_warnings_are_kept_in_the_device_log(win):
    win._msg("Could not start the simulator: boom", warn=True)
    win._msg("Could not start the simulator: boom", warn=True)             # repeats are not listed twice
    win._msg("just information")
    text = win.dev_log_view.toPlainText()
    assert text.count("Could not start the simulator: boom") == 1 and "just information" not in text
    assert "gui:" in text


def test_save_device_log(win, tmp_path, monkeypatch):
    from pyqtgraph.Qt import QtWidgets
    win.dev_log.add_fetched([_entry(1, logging.WARNING, "careful")], boot="b1", last_seq=1)
    out = tmp_path / "log.txt"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win._save_dev_log()
    line = out.read_text().strip()
    assert "WARNING" in line and "server.sweepd: careful" in line and line[:4].isdigit()   # with the date


# ---------------------------------------------------------------- flagged points

def _flags(n=101, bad=()):
    f = np.zeros(n, dtype=np.uint8)
    for i, bit in bad:
        f[i] |= bit
    return f


def test_unreliable_points_are_marked_and_named_at_the_marker(win):
    from sadiy.core.sweep import FLAG_OVERRANGE, FLAG_UNDERRANGE, FLAG_UNLOCKED
    header, p = _frame()
    win.handle_frame(header, p, flags=_flags(bad=[(20, FLAG_UNLOCKED), (30, FLAG_OVERRANGE), (40, FLAG_UNDERRANGE)]))
    xs, _ys = win.view.bad.getData()
    assert len(xs) == 2                                              # at floor is not drawn on the trace
    win.m1_chk.setChecked(True)
    win.m[0].place(win.axis, 20)
    win._redraw()
    assert "[unlocked]" in win.readout.text()
    win.m[0].place(win.axis, 40)
    win._redraw()
    assert "[at floor]" in win.readout.text() and "[unlocked]" not in win.readout.text()


def test_flags_accumulate_over_a_hold_and_clear_without_flags(win):
    from sadiy.core.sweep import FLAG_UNLOCKED
    win.mode_cb.setCurrentIndex(1)                                   # Max hold
    header, p = _frame()
    win.handle_frame(header, p, flags=_flags(bad=[(20, FLAG_UNLOCKED)]))
    win.handle_frame(header, p, flags=_flags(bad=[(50, FLAG_UNLOCKED)]))
    assert len(win.view.bad.getData()[0]) == 2                       # bad in any sweep of the hold stays marked
    win._clear_trace()
    win.handle_frame(header, p, flags=_flags(bad=[(60, FLAG_UNLOCKED)]))
    assert len(win.view.bad.getData()[0]) == 1
    win.mode_cb.setCurrentIndex(0)                                   # Clear / Write: only the last sweep
    win.handle_frame(header, p, flags=_flags())
    assert win.view.bad.getData()[0] is None or len(win.view.bad.getData()[0]) == 0
    win.handle_frame(header, p)                                      # an older sweepd sends no flags at all
    assert win.flags_a is None


# ---------------------------------------------------------------- image rejection

def test_image_reject_checkbox_goes_to_the_command_and_the_info_line(win):
    assert win.settings.to_command()["image_reject"] is False
    win.img_chk.setChecked(True)
    assert win.settings.image_reject and win.settings.to_command()["image_reject"] is True
    header, p = _frame()
    win.handle_frame(header, p)
    assert "IMG REJ" not in win.info.text()                                  # the tag follows what sweepd sends
    win.handle_frame(dict(header, image_reject=True), p)
    assert "IMG REJ" in win.info.text()
    win.settings.apply_server({"image_reject": False})                      # adopted from sweepd on connect
    win._refresh_controls()
    assert not win.img_chk.isChecked()
