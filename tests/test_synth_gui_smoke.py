"""The Synth tab and the status-bar readback, offscreen, against the fake backend."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy import config  # noqa: E402
from sadiy.drivers.adf4351 import r4_enables_output  # noqa: E402
from sadiy.server.bench import Bench, fake_backend  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_sim_engine  # noqa: E402
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
    daemon.running = False
    win = MainWindow()

    def request(cmd, timeout_ms=500):
        return json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))

    win.pins.session.request = request
    win.client.request = request
    win.client._sub = object()                      # "connected" without sockets: the fake daemon answers
    win.synced = True
    asked = []
    win.pins.ask_user = lambda text: asked.append(text) or True
    yield win, win.synth_tab, daemon, backend, asked
    win.client._sub = None
    win.close()


def words(backend):
    return [int.from_bytes(w, "big") for w in backend.spi_sent]


def test_presets_are_listed_and_fill_the_settings(rig):
    win, tab, *_ = rig
    assert tab.preset_list.count() >= 6
    tab.preset_list.setCurrentRow(1)
    assert tab.freq_sb.value() == pytest.approx(110.7) and "fractional-N" in tab.plan_label.text()
    assert tab.preset_note.text()
    tab.preset_list.setCurrentRow(0)
    assert tab.freq_sb.value() == 100.0 and "integer-N" in tab.plan_label.text()


def test_the_buttons_wait_for_bench_mode(rig):
    win, tab, daemon, backend, _ = rig
    tab.refresh()
    assert not tab.apply_btn.isEnabled() and not tab.off_btn.isEnabled()
    tab.apply()
    assert "bench mode" in win.status_msg.text().lower() and not backend.spi_sent
    tab.mode_btn.click()
    assert win.pins.session.active and tab.apply_btn.isEnabled() and tab.mode_btn.text() == "Leave bench mode"
    tab.mode_btn.click()
    assert not win.pins.session.active and not tab.apply_btn.isEnabled()


def test_apply_a_preset_with_the_output_off_and_read_it_back(rig):
    win, tab, daemon, backend, asked = rig
    tab.mode_btn.click()
    tab.preset_list.setCurrentRow(1)                                   # LO for a 100 MHz signal
    tab.apply()
    assert "110.7" in win.status_msg.text() and "locked" in win.status_msg.text()
    assert len(asked) == 1 and "wired to board inputs" in asked[0]      # the SPI confirm, asked once
    assert not any(r4_enables_output(w) for w in words(backend))
    text = tab.readback.text()
    assert "110.7" in text and "fractional-N" in text and "Lock detect: 1" in text and "R0 0x" in text
    win._update_synth()
    assert win.status_synth.text().startswith("LO 110.7") and "LD 1" in win.status_synth.text()
    assert "RF main off" in win.status_synth.text()


def test_output_on_asks_every_time_and_rf_off_turns_it_off(rig):
    win, tab, daemon, backend, asked = rig
    tab.mode_btn.click()
    tab.rf_chk.setChecked(True)
    tab.apply()
    n = len(asked)
    assert n >= 2 and any("RF output on" in a for a in asked)           # SPI confirm, then the RF one
    assert "RF main ON" in win.status_msg.text() and r4_enables_output(words(backend)[-1])
    win._update_synth()
    assert "RF main -4 dBm" in win.status_synth.text()
    tab.apply()                                                         # again: the RF confirm again, the SPI one not
    assert len(asked) == n + 1
    tab.rf_off()
    assert "off" in win.status_msg.text() and not r4_enables_output(words(backend)[-1])
    win._update_synth()
    assert "RF main off" in win.status_synth.text()


def test_cancelling_the_confirm_writes_nothing(rig):
    win, tab, daemon, backend, asked = rig
    tab.mode_btn.click()
    before = len(backend.spi_sent)
    win.pins.ask_user = lambda text: False
    tab.apply()
    assert len(backend.spi_sent) == before


def test_a_pll_that_does_not_lock_is_reported(rig):
    win, tab, daemon, backend, _ = rig
    tab.mode_btn.click()
    backend.lock_gpio = None
    tab.rf_chk.setChecked(True)
    tab.apply()
    assert "NOT locked" in win.status_msg.text() and "did not lock" in win.status_msg.text()
    assert not any(r4_enables_output(w) for w in words(backend))


def test_status_bar_shows_the_sweep_readback_without_bench_mode(rig):
    win, tab, daemon, backend, _ = rig
    daemon.running = True
    daemon.step()
    win._synth_t = 0.0
    win._update_synth()
    assert "(sweeping)" in win.status_synth.text() and "LD 1" in win.status_synth.text()
    assert "Sweeping" in tab.readback.text()
    win.client._sub = None                                              # disconnected: nothing to show
    win._update_synth()
    assert win.status_synth.text() == ""


def test_presets_adopt_the_receiver_from_sweepd(rig):
    win, tab, daemon, *_ = rig
    daemon.cfg["rf"]["if_hz"] = 21.4e6
    assert win._sync_from_server()
    assert any("78.600 MHz" in tab.preset_list.item(i).text() for i in range(tab.preset_list.count()))


def test_end_to_end_through_sweepd_sim(app):
    """GUI, ZeroMQ and a separate `sweepd --sim` process: status bar readback while sweeping, then a preset."""
    w = MainWindow(pub_port=_free_port(), rep_port=_free_port())
    try:
        w.pins.ask_user = lambda text: True
        w.start_sim()
        _spin(app, 15, lambda: w.synced)
        w._synth_every_s = 0.0
        _spin(app, 15, lambda: "(sweeping)" in w.status_synth.text())
        assert "(sweeping)" in w.status_synth.text()
        w._stop()
        t = w.synth_tab
        t.mode_btn.click()
        assert w.pins.session.active
        t.preset_list.setCurrentRow(0)
        t.apply()
        assert "100.000000 MHz" in w.status_msg.text()
        w._update_synth()
        assert w.status_synth.text().startswith("LO 100.000000 MHz")
    finally:
        w.close()
