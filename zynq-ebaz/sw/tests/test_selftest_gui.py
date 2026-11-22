"""The Ramp self-test box in the GUI's Advanced tab, offscreen, against a Sweepd on the model-backed fake PL."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy import config  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_hw_engine, build_sim_engine  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


class FakeAsync:
    """What `SweepClient.request_async` returns: the daemon answers after `wait` polls."""

    def __init__(self, daemon, cmd, wait=2):
        self._reply = json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))
        self.cmd, self.wait, self.closed = cmd, wait, False

    def poll(self):
        if self.wait > 0:
            self.wait -= 1
            return False, None
        return True, self._reply

    def close(self):
        self.closed = True


def connect(win, daemon):
    """Wire the window to a daemon in-process: commands go to `daemon.apply`, as in the other smoke tests."""
    sent = []
    win.client.request = lambda cmd, timeout_ms=500: json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))
    win.client.request_async = lambda cmd, timeout_ms: sent.append(FakeAsync(daemon, cmd)) or sent[-1]
    win.client._sub = object()                 # `connected` is "has a SUB socket"
    win.pins._request = win.client.request
    win.pins.session.request = win.client.request
    win.client.disconnect = lambda: setattr(win.client, "_sub", None)
    assert win._sync_from_server()
    return sent


def finish(win):
    while win._selftest_req is not None:
        win._poll_selftest()


@pytest.fixture
def pl_daemon():
    cfg = config.load()
    cfg2 = config.load()
    cfg2["platform"] = {"name": "fake_pl"}
    d = Sweepd(cfg, build_hw_engine(cfg2))
    d.running = False
    return d


def test_the_box_exists_and_is_off_until_connected(app):
    win = MainWindow()
    try:
        assert not win.st_btn.isEnabled()
        assert win.st_sweeps.value() == 5 and not win.st_wrap.isChecked() and not win.st_fill.isChecked()
    finally:
        win.close()


def test_button_is_enabled_with_a_pl_engine_and_the_run_passes(app, pl_daemon):
    win = MainWindow()
    try:
        sent = connect(win, pl_daemon)
        assert win.st_btn.isEnabled()
        win.st_sweeps.setValue(3)
        win.st_wrap.setChecked(True)
        win._run_selftest()
        assert not win.st_btn.isEnabled() and not win.st_sweeps.isEnabled()        # busy: no second request
        assert "running" in win.st_label.text()
        win._run_selftest()
        assert len(sent) == 1
        finish(win)
        assert sent[0].cmd == {"cmd": "selftest", "sweeps": 3, "wrap": True, "fill": False}
        assert win.st_label.text().startswith("PASS:")
        assert "RESULT: PASS" in win.st_report.toPlainText() and "N_AVG 1, base 0xFFF0" in win.st_report.toPlainText()
        assert win.st_btn.isEnabled() and win.st_sweeps.isEnabled()
    finally:
        win.close()


def test_a_failing_engine_shows_fail_and_the_failed_check(app, pl_daemon):
    real = pl_daemon.engine.offload.offload.run

    def broken(n_avg, timeout_s=10.0):
        res = real(n_avg, timeout_s)
        res.sums[5] += 1
        return res

    pl_daemon.engine.offload.offload.run = broken
    win = MainWindow()
    try:
        connect(win, pl_daemon)
        win._run_selftest()
        finish(win)
        assert win.st_label.text().startswith("FAIL:")
        assert "FAIL" in win.st_report.toPlainText() and "index 5" in win.st_report.toPlainText()
    finally:
        win.close()


def test_without_a_pl_engine_the_button_stays_off_and_says_why(app):
    cfg = config.load()
    win = MainWindow()
    try:
        connect(win, Sweepd(cfg, build_sim_engine(cfg)))
        assert not win.st_btn.isEnabled()
        assert "not available" in win.st_label.text() and "PL engine" in win.st_label.text()
    finally:
        win.close()


def test_no_answer_is_reported_not_hidden(app, pl_daemon):
    win = MainWindow()
    try:
        connect(win, pl_daemon)
        win.client.request_async = lambda cmd, timeout_ms: None
        win._run_selftest()
        assert "no answer" in win.st_label.text() and win.st_btn.isEnabled()
    finally:
        win.close()


def test_disconnect_cancels_a_pending_test(app, pl_daemon):
    win = MainWindow()
    try:
        sent = connect(win, pl_daemon)
        win._run_selftest()
        win._toggle_connect()                                   # disconnect
        assert sent[0].closed and win._selftest_req is None and not win.st_btn.isEnabled()
    finally:
        win.close()
