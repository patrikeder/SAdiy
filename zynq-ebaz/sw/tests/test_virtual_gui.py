"""The Virtual spectrum box in the GUI's Advanced tab (offscreen), against a Sweepd on the model-backed fake PL with a stub
for the virtual spectrum module."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy import config  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_hw_engine, build_sim_engine  # noqa: E402
from sadiy.ui import selftest_core  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402
from test_sweepd_virtual import StubVirtual  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


class FakeAsync:
    def __init__(self, daemon, cmd, wait=1):
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
    sent = []
    win.client.request = lambda cmd, timeout_ms=500: json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))
    win.client.request_async = lambda cmd, timeout_ms: sent.append(FakeAsync(daemon, cmd)) or sent[-1]
    win.client._sub = object()
    win.pins._request = win.client.request
    win.pins.session.request = win.client.request
    win.client.disconnect = lambda: setattr(win.client, "_sub", None)
    assert win._sync_from_server()
    return sent


def finish(win):
    while win._virtual_req is not None:
        win._poll_virtual()


@pytest.fixture
def pl_daemon():
    cfg, cfg2 = config.load(), config.load()
    cfg2["platform"] = {"name": "fake_pl"}
    d = Sweepd(cfg, build_hw_engine(cfg2))
    d.engine.offload.virtual = lambda det, cal: StubVirtual(det, cal)
    d.running = False
    return d


def test_info_from_status():
    assert selftest_core.VirtualInfo.from_status(None) == selftest_core.VirtualInfo()
    v = selftest_core.VirtualInfo.from_status({"available": True, "active": True, "state": {"sweep": 7, "drift_points": -3}})
    assert v.active and v.text == "VIRTUAL SPECTRUM, not RF: sweep 7, drift -3 points"
    assert selftest_core.VirtualInfo.from_status({"available": True, "active": False, "state": None}).text == ""
    assert selftest_core.virtual_command(True) == {"cmd": "virtual", "on": True}


def test_button_off_until_connected_then_on_when_available(app, pl_daemon):
    win = MainWindow()
    try:
        assert not win.vs_btn.isEnabled()
        connect(win, pl_daemon)
        assert win.vs_btn.isEnabled() and win.vs_btn.text() == "Start virtual spectrum"
    finally:
        win.close()


def test_start_and_stop_through_the_button(app, pl_daemon):
    win = MainWindow()
    try:
        sent = connect(win, pl_daemon)
        win._toggle_virtual()
        assert not win.vs_btn.isEnabled() and "switching" in win.vs_label.text()
        win._toggle_virtual()
        assert len(sent) == 1                                       # busy: no second request
        finish(win)
        assert sent[0].cmd == {"cmd": "virtual", "on": True}
        assert win.vs_btn.text() == "Stop virtual spectrum" and win.vs_btn.isEnabled()
        assert "VIRTUAL SPECTRUM" in win.vs_label.text()
        assert not win.st_btn.isEnabled()                           # the self-test is off while it is on
        win._toggle_virtual()
        finish(win)
        assert sent[1].cmd == {"cmd": "virtual", "on": False}
        assert win.vs_btn.text() == "Start virtual spectrum" and win.vs_label.text() == ""
        assert win.st_btn.isEnabled()
    finally:
        win.close()


def test_the_status_poll_keeps_the_label_current(app, pl_daemon):
    win = MainWindow()
    try:
        connect(win, pl_daemon)
        pl_daemon.apply({"cmd": "virtual", "on": True})
        pl_daemon._virtual.sweeps = 12
        win._synth_t = 0.0
        win._update_synth()
        assert "sweep 12" in win.vs_label.text()
    finally:
        win.close()


def test_without_the_engine_the_button_stays_off_and_says_why(app):
    cfg = config.load()
    win = MainWindow()
    try:
        connect(win, Sweepd(cfg, build_sim_engine(cfg)))
        assert not win.vs_btn.isEnabled() and "not available" in win.vs_label.text()
    finally:
        win.close()


def test_refusal_and_disconnect(app, pl_daemon):
    win = MainWindow()
    try:
        sent = connect(win, pl_daemon)
        pl_daemon.engine.offload.virtual = lambda det, cal: None
        win._toggle_virtual()
        finish(win)
        assert "not switched" in win.vs_label.text() and win.vs_btn.isEnabled()
        win._toggle_virtual()
        win._toggle_connect()                                       # disconnect with a request pending
        assert sent[-1].closed and win._virtual_req is None and not win.vs_btn.isEnabled()
    finally:
        win.close()


def test_the_expected_trace_is_drawn_only_when_the_frame_has_one(app, pl_daemon):
    import numpy as np
    from sadiy.server import protocol
    win = MainWindow()
    try:
        connect(win, pl_daemon)
        pl_daemon.apply({"cmd": "virtual", "on": True})
        header, p, flags, ideal = protocol.decode_frame_all(pl_daemon.step())
        win.handle_frame(header, p, flags=flags, ideal=ideal)
        x, y = win.view.ideal.getData()
        assert y is not None and len(y) == p.size and np.allclose(y, ideal)
        win.handle_frame(header, p, flags=flags)                    # a frame without one (virtual switched off)
        x, y = win.view.ideal.getData()
        assert y is None or len(y) == 0
    finally:
        win.close()
