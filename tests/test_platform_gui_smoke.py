"""Platform choice in the GUI, offscreen: a selector in the Pins tab, or a fixed platform from `--platform`."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from pyqtgraph.Qt import QtCore, QtTest  # noqa: E402

from sadiy import config, pinmap_ebaz  # noqa: E402
from sadiy.server.bench import Bench, fake_backend  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_sim_engine  # noqa: E402
from sadiy.ui import bench_core  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402
from sadiy.ui.sim_runner import SimRunner  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


def daemon_for(platform):
    cfg = config.load()
    daemon = Sweepd(cfg, build_sim_engine(cfg), Bench(fake_backend(platform), cfg, platform=platform))
    daemon.running = False

    def request(cmd, timeout_ms=500):
        return json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))

    return daemon, request


def wire(win, request):
    win.client.request = request
    win.pins._request = request
    win.pins.session.request = request
    win.pins.ask_user = lambda text: True


def test_default_has_selector_with_both_platforms(app):
    win = MainWindow()
    try:
        tab = win.pins
        assert not tab.fixed and tab.platform() == "bbb"
        assert not tab.platform_cb.isHidden() and not tab.platform_lbl.isHidden()
        assert [tab.platform_cb.itemData(i) for i in range(tab.platform_cb.count())] == ["bbb", "ebaz"]
        assert tab.canvas.pm.name == "bbb"
    finally:
        win.close()


def test_fixed_platform_hides_the_selector_and_the_other_board(app):
    win = MainWindow(platform="ebaz")
    try:
        tab = win.pins
        assert tab.fixed and tab.platform() == "ebaz"
        assert tab.platform_cb.isHidden() and tab.platform_lbl.isHidden()
        assert tab.canvas.pm is pinmap_ebaz.EBAZ
        assert win.runner.platform == "ebaz"
        assert tab.set_platform("bbb") is False and tab.platform() == "ebaz"     # no way back to the other one
        tab.follow_server("bbb")
        assert tab.platform() == "ebaz"
        # nothing of the BeagleBone anywhere in the pin list
        tab._fill_pin_list()
        ids = [tab.pin_list.item(i).text() for i in range(tab.pin_list.count())]
        assert ids and all(t.startswith("DATA2.") for t in ids)
        assert not any(t.startswith(("P8", "P9")) for t in ids)
        assert tab.selected == "DATA2.14"
    finally:
        win.close()


def test_fixed_bbb_stays_bbb(app):
    win = MainWindow(platform="bbb")
    try:
        tab = win.pins
        assert tab.fixed and tab.platform_cb.isHidden()
        assert tab.set_platform("ebaz") is False
        assert tab.selected == "P8.7"
    finally:
        win.close()


def test_selector_switches_the_board(app):
    win = MainWindow()
    try:
        tab = win.pins
        before = tab.canvas
        tab.platform_cb.setCurrentIndex(tab.platform_cb.findData("ebaz"))
        assert tab.platform() == "ebaz" and tab.canvas is not before
        assert tab.canvas.pm is pinmap_ebaz.EBAZ and tab.session.pm is pinmap_ebaz.EBAZ
        assert tab.selected == "DATA2.14"
        # the pin list and the V check boxes follow the new pin map
        assert len(tab.v_checks) == 6
        assert tab.canvas.canvas_w == bench_core.canvas_size(pinmap_ebaz.EBAZ)[0]
        tab.platform_cb.setCurrentIndex(tab.platform_cb.findData("bbb"))
        assert tab.platform() == "bbb" and tab.selected == "P8.7"
        tab.canvas.resize(930, 640)
        tab.canvas.grab()                                       # paints without an exception
    finally:
        win.close()


def test_ebaz_canvas_paints_and_is_clickable(app):
    win = MainWindow(platform="ebaz")
    try:
        tab = win.pins
        tab.canvas.resize(850, 700)
        assert not tab.canvas.grab().isNull()
        pin = pinmap_ebaz.EBAZ.pins["DATA2.16"]
        x, y, w, h = bench_core.pin_rect(pin, pinmap_ebaz.EBAZ)
        QtTest.QTest.mouseClick(tab.canvas, QtCore.Qt.LeftButton, pos=tab.canvas.to_widget(x + w / 2, y + h / 2))
        assert tab.selected == "DATA2.16"
        # a board block row selects its pin too
        row = next(r for b in tab.canvas._blocks for r in b.rows if r.net == "SYN_LD")
        QtTest.QTest.mouseClick(tab.canvas, QtCore.Qt.LeftButton,
                                pos=tab.canvas.to_widget(row.rect[0] + 20, row.rect[1] + row.rect[3] / 2))
        assert tab.selected == "DATA2.9"
        # no AIN0 on this board: the cross-check row is hidden
        assert tab.ain_label.isHidden()
    finally:
        win.close()


def test_bbb_keeps_the_ain_row(app):
    win = MainWindow(platform="bbb")
    try:
        assert not win.pins.ain_label.isHidden() or win.pins.ain_label.isVisibleTo(win.pins.side)
    finally:
        win.close()


def test_bench_against_an_ebaz_daemon(app):
    daemon, request = daemon_for("ebaz")
    win = MainWindow(platform="ebaz")
    try:
        wire(win, request)
        tab = win.pins
        tab.enter()
        assert tab.session.active and "DATA2.14" in tab.session.status["pins"]
        assert not tab.platform_cb.isEnabled() or tab.fixed
        tab.select_pin("DATA2.14")
        tab.drive(1)
        assert tab.session.level("DATA2.14")[0] == 1
        tab.set_db(31.5)
        tab.leave()
        assert not tab.session.active
    finally:
        win.close()


def test_selector_follows_the_daemon_and_refuses_a_mismatch(app):
    daemon, request = daemon_for("ebaz")
    win = MainWindow()                          # not fixed: a BBB view at first
    try:
        wire(win, request)
        assert win._sync_from_server()
        assert win.pins.platform() == "ebaz"    # followed what sweepd says
        wire(win, request)
        assert win.pins.canvas.pm.name == "ebaz"
    finally:
        win.close()
    fixed = MainWindow(platform="bbb")          # fixed on the other board
    try:
        wire(fixed, request)
        fixed.pins.enter()
        assert not fixed.pins.session.active
    finally:
        fixed.close()


def test_a_platform_cannot_change_while_bench_mode_is_open(app):
    daemon, request = daemon_for("bbb")
    win = MainWindow()
    try:
        wire(win, request)
        win.pins.enter()
        assert win.pins.session.active
        win.pins.platform_cb.setCurrentIndex(win.pins.platform_cb.findData("ebaz"))
        assert win.pins.platform() == "bbb"
        assert win.pins.platform_cb.currentData() == "bbb"      # the selector went back
        win.pins.leave()
    finally:
        win.close()


def test_sim_runner_passes_the_platform():
    r = SimRunner()
    assert "--platform" not in r.build_command("x.toml", 0.1)
    r.platform = "ebaz"
    argv = r.build_command("x.toml", 0.1)
    assert argv[-2:] == ["--platform", "ebaz"]
