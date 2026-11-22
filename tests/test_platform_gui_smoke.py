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


def test_ebaz_shows_the_adapter_picture_and_can_switch_to_the_connectors(app):
    win = MainWindow(platform="ebaz")
    try:
        tab = win.pins
        assert tab.adapter_view is not None and tab.adapter_view.renderer.isValid()
        assert not tab.view_cb.isHidden()
        assert tab.view_stack.currentWidget() is tab.adapter_view          # the default view
        tab.adapter_view.resize(900, 600)
        assert not tab.adapter_view.grab().isNull()                         # paints without an exception
        tab.view_cb.setCurrentIndex(tab.view_cb.findData("connectors"))
        assert tab.view_stack.currentWidget() is tab.canvas
        tab.set_view("adapter")
        assert tab.view_stack.currentWidget() is tab.adapter_view and tab.view_cb.currentData() == "adapter"
    finally:
        win.close()


def test_bbb_has_no_adapter_picture_and_no_view_selector(app):
    win = MainWindow(platform="bbb")
    try:
        tab = win.pins
        assert tab.adapter_view is None and tab.view_cb.isHidden()
        tab.set_view("adapter")
        assert tab.view_stack.currentWidget() is tab.canvas
    finally:
        win.close()


def test_the_view_choice_survives_a_platform_change(app):
    win = MainWindow()
    try:
        tab = win.pins
        tab.set_platform("ebaz")
        tab.set_view("connectors")
        tab.set_platform("bbb")
        tab.set_platform("ebaz")
        assert tab.view_stack.currentWidget() is tab.canvas
    finally:
        win.close()


def test_adapter_figure_lookup(tmp_path):
    from sadiy import pinmap
    from sadiy.ui import bench_core

    assert bench_core.adapter_figure(pinmap.BBB) is None
    assert bench_core.adapter_figure(pinmap_ebaz.EBAZ, tmp_path) is None            # file missing
    (tmp_path / "zynq-ebaz" / "docs").mkdir(parents=True)
    fig = tmp_path / "zynq-ebaz" / "docs" / "pinmap-adapter.svg"
    fig.write_text("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'/>")
    assert bench_core.adapter_figure(pinmap_ebaz.EBAZ, tmp_path) == fig
    assert bench_core.adapter_figure(pinmap_ebaz.EBAZ).name == "pinmap-adapter.svg"      # the real one in the repo


def test_without_qtsvg_the_adapter_picture_is_still_drawn_by_hand(app, monkeypatch):
    """A PyQt6 without QtSvg (Raspberry Pi OS): the import works, the first use raises ImportError."""
    from sadiy.ui import bench_tab

    class NoSvg:
        def __getattr__(self, name):
            raise ImportError("cannot import name 'QtSvg' from 'PyQt6'")

    monkeypatch.setattr(bench_tab, "QtSvg", NoSvg())
    assert not bench_tab.svg_available()
    win = MainWindow()
    try:
        tab = win.pins
        tab.set_platform("ebaz")
        assert tab.adapter_view is not None and not tab.adapter_view.uses_renderer
        assert tab.view_stack.currentWidget() is tab.adapter_view and not tab.view_cb.isHidden()
        view = tab.adapter_view
        view.resize(750, 450)
        assert view.grab().toImage().pixelColor(375, 225) != view.palette().color(view.backgroundRole())
        r = next(r for r in view.regions if r.pin_id == "DATA2.14")
        x, y, w, h = r.rect
        QtTest.QTest.mouseClick(view, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier,
                                view.to_widget(x + w / 2, y + h / 2))                # clicking works as with the renderer
        assert tab.selected == "DATA2.14"
    finally:
        win.close()


def test_hand_drawing_and_svg_renderer_agree_on_where_things_are(app):
    from pyqtgraph.Qt import QtGui
    from sadiy.ui.bench_tab import SvgView, svg_available

    if not svg_available():
        pytest.skip("no QtSvg here")
    pm = pinmap_ebaz.EBAZ
    path = bench_core.adapter_figure(pm)
    images = []
    for use in (True, False):
        v = SvgView(path, pm, lambda _pid: None, use_renderer=use)
        v.resize(1000, 600)
        pal = v.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#202124"))
        pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#e8eaed"))
        v.setPalette(pal)
        images.append(v.grab().toImage())
    a, b = images
    pts = [(x, y) for x in range(5, 1000, 11) for y in range(5, 600, 11)]
    differ = sum(1 for x, y in pts if (a.pixelColor(x, y) != QtGui.QColor("#202124")) != (b.pixelColor(x, y) != QtGui.QColor("#202124")))
    assert differ < len(pts) * 0.03, f"{differ} of {len(pts)} sample points differ in being drawn or not"


def test_adapter_shapes_read_the_picture():
    (w, h), shapes = bench_core.adapter_shapes(bench_core.adapter_figure(pinmap_ebaz.EBAZ))
    assert (w, h) == (1500, 900)
    kinds = [s.kind for s in shapes]
    assert kinds.count("text") == 173 and kinds.count("circle") == 29 and kinds.count("rect") == 14     # page left out
    assert any(s.kind == "circle" and s.dash for s in shapes) and any(s.kind == "text" and s.italic for s in shapes)
    assert any(s.kind == "text" and s.anchor == "end" for s in shapes)


def test_adapter_svg_drops_the_white_page_and_takes_the_text_colour():
    pm = pinmap_ebaz.EBAZ
    path = bench_core.adapter_figure(pm)
    raw = path.read_text(encoding="utf-8")
    assert '<rect width="1500" height="900" fill="#fff"/>' in raw
    data = bench_core.adapter_svg_data(path, "#abcdef").decode()
    assert '<rect width="1500" height="900" fill="#fff"/>' not in data
    assert data.count("<rect") == raw.count("<rect") - 1 and data.count("<text") == raw.count("<text")
    assert '<svg fill="#abcdef"' in data
    other = path.parent / "no-such-page.svg"                                 # a file without the white page is kept as it is
    other.write_text("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><rect width='4' height='4'/></svg>")
    try:
        assert "<rect width='4' height='4'/>" in bench_core.adapter_svg_data(other, "#000").decode()
    finally:
        other.unlink()


def test_adapter_view_paints_on_the_palette_colours(app):
    from pyqtgraph.Qt import QtGui
    from sadiy.ui.bench_tab import SvgView

    pm = pinmap_ebaz.EBAZ
    view = SvgView(bench_core.adapter_figure(pm), pm, lambda _pid: None)
    view.resize(750, 450)
    for window, text in (("#202124", "#e8eaed"), ("#f0f0f0", "#202020")):
        pal = view.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(window))
        pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(text))
        view.setPalette(pal)
        img = view.grab().toImage()
        assert img.pixelColor(3, 3) == QtGui.QColor(window)                 # no white page: the corner is the window colour
        assert img.pixelColor(375, 225) != QtGui.QColor(window)             # and the picture is drawn


def test_adapter_regions_cover_every_signal_pin_of_the_picture():
    from sadiy.ui import bench_core

    pm = pinmap_ebaz.EBAZ
    regions = bench_core.adapter_regions(bench_core.adapter_figure(pm), pm)
    ids = {r.pin_id for r in regions}
    signals = {p.id for p in pm.pins.values() if p.id.startswith("DATA2.") and p.kind not in ("power", "gnd")
               and p.name not in ("NC",)}
    assert signals <= ids, sorted(signals - ids)
    assert {"DATA1.15", "DATA1.18", "DATA1.20", "DATA3.18", "DATA3.15", "DATA3.17", "DATA3.19", "DATA3.20",
            "DATA3.16", "DATA3.13", "DATA3.14", "DATA3.11"} <= ids              # LEDs, keys and the LCD pins
    # points taken from the picture: the circle of adf4351_dat, the circle of adf4351_le, LED1, KEY1, "CS lcd_cs", empty
    assert bench_core.adapter_hit(regions, 790, 472) == "DATA2.7"
    assert bench_core.adapter_hit(regions, 830, 516) == "DATA2.8"
    assert bench_core.adapter_hit(regions, 900, 262) == "DATA1.15"
    assert bench_core.adapter_hit(regions, 470, 700) == "DATA3.18"
    assert bench_core.adapter_hit(regions, 250, 424) == "DATA3.16"
    assert bench_core.adapter_hit(regions, 5, 5) is None


def test_clicking_the_adapter_picture_selects_the_pin(app):
    win = MainWindow(platform="ebaz")
    try:
        tab = win.pins
        view = tab.adapter_view
        view.resize(900, 560)
        QtTest.QTest.mouseClick(view, QtCore.Qt.LeftButton, pos=view.to_widget(790, 472))      # adf4351_dat
        assert tab.selected == "DATA2.7" and view.selected == "DATA2.7" and tab.canvas.selected == "DATA2.7"
        QtTest.QTest.mouseClick(view, QtCore.Qt.LeftButton, pos=view.to_widget(470, 700))      # KEY1
        assert tab.selected == "DATA3.18"
        QtTest.QTest.mouseClick(view, QtCore.Qt.LeftButton, pos=view.to_widget(1200, 800))     # nothing there
        assert tab.selected == "DATA3.18"
        assert not view.grab().isNull()                                                        # paints with the red frame
        QtTest.QTest.mouseMove(view, view.to_widget(790, 472))
        assert view.pin_at(view.to_widget(790, 472)) == "DATA2.7"
    finally:
        win.close()
