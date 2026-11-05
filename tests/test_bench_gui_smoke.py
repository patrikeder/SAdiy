"""The Pins tab, offscreen, against the fake backend. Skipped without PyQt / pyqtgraph / pyzmq."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from pyqtgraph.Qt import QtCore, QtTest  # noqa: E402

from sadiy import config, pinmap  # noqa: E402
from sadiy.server.bench import Bench, fake_backend  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_sim_engine  # noqa: E402
from sadiy.ui import bench_core  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402

from test_sa_gui_smoke import _free_port, _spin  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


@pytest.fixture
def rig(app):
    cfg = config.load()
    backend = fake_backend()
    daemon = Sweepd(cfg, build_sim_engine(cfg), Bench(backend, cfg))
    win = MainWindow()
    tab = win.pins

    def request(cmd):
        return json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))

    tab.session.request = request
    win.client.request = lambda cmd, timeout_ms=500: request(cmd)
    tab.ask_user = lambda text: True
    yield win, tab, daemon, backend
    win.close()


def enter(tab, daemon):
    daemon.running = False
    tab.enter()
    assert tab.session.active


def click_canvas(tab, x, y):
    tab.canvas.resize(930, 640)
    QtTest.QTest.mouseClick(tab.canvas, QtCore.Qt.LeftButton, pos=tab.canvas.to_widget(x, y))


def test_tabs(rig):
    win, *_ = rig
    tabs = win.centralWidget()
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Spectrum", "Pins", "Advanced"]


def test_board_paints(rig):
    win, tab, daemon, _ = rig
    enter(tab, daemon)
    tab.canvas.resize(930, 640)
    tab.poll()
    assert not tab.canvas.grab().isNull()
    tab.leave()


def test_clicking_a_pin_shows_its_details(rig):
    _, tab, *_ = rig
    x, y, w, h = bench_core.pin_rect(pinmap.PINS["P9.23"])
    click_canvas(tab, x + w / 2, y + h / 2)
    assert tab.selected == "P9.23"
    assert "SYN_LD" in tab.pin_info.text() and "49" in tab.pin_info.text()


def test_clicking_a_board_row_selects_its_pin(rig):
    _, tab, *_ = rig
    block = next(b for b in bench_core.blocks() if b.board.title == "PE4302")
    x, y, w, h = block.rows[2].rect
    click_canvas(tab, x + w / 2, y + h / 2)
    assert tab.selected == "P8.9"


def test_controls_follow_the_pin_kind_and_the_mode(rig):
    _, tab, daemon, _ = rig
    tab.select_pin("P8.7")
    assert not tab.drive1_btn.isEnabled()                           # bench mode off
    enter(tab, daemon)
    assert tab.drive1_btn.isEnabled() and not tab.bus_btn.isEnabled()
    tab.select_pin("P9.22")
    assert tab.bus_btn.isEnabled()
    for display in ("P9.1", "P9.39"):
        tab.select_pin(display)
        assert not tab.drive1_btn.isEnabled() and not tab.read_btn.isEnabled()
    tab.select_pin("P9.23")
    assert not tab.drive1_btn.isEnabled() and tab.read_btn.isEnabled()
    tab.select_pin("P9.15")
    assert not tab.drive1_btn.isEnabled()
    tab.expert_chk.setChecked(True)
    assert tab.drive1_btn.isEnabled()
    tab.leave()
    assert not tab.drive1_btn.isEnabled()


def test_enter_stops_the_sweep_after_asking(rig):
    win, tab, daemon, _ = rig
    assert daemon.running
    asked = []
    tab.ask_user = lambda text: asked.append(text) or True
    win._remote_running = True
    tab.enter()
    assert asked and "sweep" in asked[0]
    assert tab.session.active and not daemon.running and not win._remote_running
    tab.leave()
    assert not daemon.bench_active


def test_enter_refused_keeps_the_sweep(rig):
    _, tab, daemon, _ = rig
    tab.ask_user = lambda text: False
    tab.enter()
    assert not tab.session.active and daemon.running


def test_drive_pin_end_to_end(rig):
    _, tab, daemon, backend = rig
    enter(tab, daemon)
    tab.select_pin("P8.7")
    tab.drive(0)
    assert backend.lines[66].level == 0
    assert "Level: 0" in tab.pin_level.text() and "out" in tab.pin_level.text()
    tab.read_pin()
    tab.release()
    assert backend.lines[66].output is False
    tab.leave()
    assert backend.lines[66].output is True and backend.lines[66].level == 1     # safe state


def test_raw_access_page(rig):
    _, tab, daemon, backend = rig
    enter(tab, daemon)
    tab.word_edit.setText("0x00580005")
    tab.send_word()
    assert backend.spi_sent[-1] == bytes.fromhex("00580005")
    tab.word_edit.setText("nonsense")
    tab.send_word()                                                 # a message, no crash

    for edit, word in zip(tab.init_edits, ("00580005", "0080C004", "000004B3", "00004E42", "08008011", "00320000")):
        edit.setText(word)
    tab.send_init()
    assert backend.spi_sent[-1] == bytes.fromhex("00320000")
    assert tab.ld_label.text() == "LD: 1"                           # the fake locks on R0

    tab.rf_main_chk.setChecked(True)
    tab.apply_rf()
    assert daemon.bench._outputs.main.enabled
    assert "main ON" in tab.raw_note.text()
    tab.rf_main_chk.setChecked(False)
    tab.apply_rf()
    assert not daemon.bench._outputs.main.enabled

    tab.db_sb.setValue(10.5)
    tab.set_db(tab.db_sb.value())
    assert "10.5 dB" in tab.att_label.text() and "V2=0" in tab.writes_label.text()
    tab.poll()
    assert "V2=0" in tab.writes_label.text()                        # the live refresh keeps the write order
    tab.raw_order_chk.setChecked(True)
    for chk, on in zip(tab.v_checks, (1, 0, 0, 0, 0, 1)):
        chk.setChecked(bool(on))
    tab.apply_levels()
    assert "16.5 dB" in tab.att_label.text()

    tab.read_ads()
    assert "1.13" in tab.ads_label.text() and "config 0x" in tab.ads_label.text()
    tab.read_ads_regs()
    assert "conversion 0x" in tab.ads_label.text()
    tab.read_ain()
    assert "raw 1500.0" in tab.ain_label.text()
    tab.leave()


def test_refused_rf_clears_the_checkbox(rig):
    _, tab, daemon, _ = rig
    enter(tab, daemon)
    tab.rf_main_chk.setChecked(True)
    tab.apply_rf()                                                  # no R0 sent, so no lock
    assert not tab.rf_main_chk.isChecked() and not daemon.bench._outputs.main.enabled
    tab.leave()


def test_pattern_page_preview_run_stop_and_csv(rig, tmp_path):
    _, tab, daemon, backend = rig
    enter(tab, daemon)
    assert tab.checked_pins() == list(pinmap.ATT_NETS)              # default selection: the PE4302 lines
    tab.refresh_preview()
    text = tab.preview.toPlainText()
    assert "Walking one" in text and "steps/s" in text and "keep RF off" in text and "ATT_V6" in text

    csv = tmp_path / "p.csv"
    tab.export_csv(str(csv))
    assert csv.read_text().splitlines()[0] == "step,ATT_V1,ATT_V2,ATT_V3,ATT_V4,ATT_V5,ATT_V6"

    tab.rate_sb.setValue(1000.0)
    tab.loop_chk.setChecked(True)
    tab.run_pattern()
    assert daemon.bench.pattern_running
    daemon.bench.service(0.02)
    tab.poll()
    assert "measured" in tab.run_label.text() and "Running" in tab.run_label.text()
    tab.stop_pattern()
    assert not daemon.bench.pattern_running
    assert "Stopped" in tab.run_label.text()
    assert [backend.lines[n].level for n in (66, 67, 69, 68, 45, 44)] == [1] * 6
    tab.leave()


@pytest.mark.parametrize("index", range(7))
def test_every_pattern_kind_previews(rig, index):
    _, tab, *_ = rig
    tab.kind_cb.setCurrentIndex(index)
    tab.refresh_preview()
    assert tab.pattern is not None, tab.preview.toPlainText()


def test_bad_pattern_shows_why_and_does_not_run(rig):
    _, tab, daemon, _ = rig
    enter(tab, daemon)
    for i in range(tab.pin_list.count()):
        tab.pin_list.item(i).setCheckState(QtCore.Qt.Unchecked)
    assert tab.pattern is None and "pick at least one" in tab.preview.toPlainText()
    tab.run_pattern()
    assert not daemon.bench.pattern_running
    tab.leave()


def test_expert_adds_free_pins_to_the_pattern_list(rig):
    _, tab, *_ = rig
    count = tab.pin_list.count()
    tab.expert_chk.setChecked(True)
    assert tab.pin_list.count() > count
    tab.expert_chk.setChecked(False)
    assert tab.pin_list.count() == count


def test_run_button_shows_the_refusal_while_in_bench_mode(rig):
    win, tab, daemon, _ = rig
    enter(tab, daemon)
    win._remote_running = False
    win._run()
    assert "bench" in win.status_msg.text() and not win._remote_running
    tab.leave()


def test_server_side_close_is_noticed(rig):
    win, tab, daemon, _ = rig
    enter(tab, daemon)
    daemon.bench.close("no command from the client for 5 s")
    tab.poll()
    assert not tab.session.active and tab.mode_btn.text() == "Enter bench mode"
    assert "no command" in win.status_msg.text()


def test_closing_the_window_returns_to_safe(rig):
    win, tab, daemon, backend = rig
    enter(tab, daemon)
    tab.set_db(0.0)
    win.close()
    assert not daemon.bench_active and backend.lines[66].level == 1


def test_bench_end_to_end_through_sweepd_sim(app):
    """The real path: GUI, ZeroMQ, a separate `sweepd --sim` process with the fake backend."""
    w = MainWindow(pub_port=_free_port(), rep_port=_free_port())
    try:
        w.pins.ask_user = lambda text: True
        w.start_sim()
        _spin(app, 15, lambda: w.synced)
        assert w.synced
        w.pins.enter()
        assert w.pins.session.active and w.pins.session.limits["simulated"]
        assert "SIMULATED" in w.pins.mode_label.text()
        n = w._frames
        w.pins.select_pin("P8.7")
        w.pins.drive(0)
        assert w.pins.session.level("P8.7") == (0, "out")
        w._run()
        assert "bench" in w.status_msg.text()
        w.pins.rate_sb.setValue(500.0)
        w.pins.loop_chk.setChecked(True)
        w.pins.kind_cb.setCurrentIndex(0)
        w.pins.run_pattern()
        _spin(app, 1.0)
        status = w.pins.session.poll()
        assert status["pattern"]["running"] and status["pattern"]["measured_hz"] > 50
        w.pins.stop_pattern()
        w.pins.read_ads()
        assert "1.13" in w.pins.ads_label.text()
        w.pins.leave()
        assert not w.pins.session.active
        w._run()
        _spin(app, 15, lambda: w._frames > n)                       # sweeping again
        assert w._frames > n
    finally:
        w.close()
