"""Saved settings in the GUI (offscreen): default.json at start and exit, named settings, restore as delivered."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("zmq")
pg = pytest.importorskip("pyqtgraph")
pytest.importorskip("pyqtgraph.Qt.QtWidgets")

from sadiy import config  # noqa: E402
from sadiy.server.sweepd import Sweepd, build_sim_engine  # noqa: E402
from sadiy.ui import sa_core as core  # noqa: E402
from sadiy.ui import settings_core as sc  # noqa: E402
from sadiy.ui.sa_gui import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return pg.mkQApp("sadiy-test")


@pytest.fixture
def store(tmp_path):
    return sc.Store(tmp_path / "cfg")


SAVED = core.SaSettings(start_hz=88e6, stop_hz=108e6, points=801, averages=8, atten_db=6.0, auto_atten=False,
                        image_reject=True, ref_dbm=-50.0, db_per_div=5.0)


def write_default(store, **conn):
    store.save_default(sc.to_dict(SAVED, "max_hold", sc.Connection(**conn) if conn else None))


def connect(win, daemon):
    win.client.request = lambda cmd, timeout_ms=500: json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))
    win.client._sub = object()
    win.pins._request = win.client.request
    win.pins.session.request = win.client.request
    win.client.disconnect = lambda: setattr(win.client, "_sub", None)
    return win._sync_from_server()


@pytest.fixture
def daemon():
    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    d.running = False
    return d


def server_settings(daemon):
    return daemon.apply({"cmd": "status"})["settings"]


def test_without_a_store_nothing_is_read_or_written_and_the_menu_is_off(app, tmp_path, monkeypatch):
    monkeypatch.setenv("SADIY_CONFIG_DIR", str(tmp_path))
    win = MainWindow()
    try:
        assert not win.act_save_as.isEnabled() and not win.menu_load.isEnabled() and win.act_restore.isEnabled()
        assert win.save_default() is False and win.save_named("x") is False and win.load_named("x") is False
    finally:
        win.close()
    assert list(tmp_path.iterdir()) == []


def test_first_start_uses_the_settings_as_delivered_and_exit_writes_default_json(app, store):
    win = MainWindow(store=store)
    try:
        assert win.settings == core.SaSettings() and win.mode_cb.currentData() == "clear_write"
        assert not store.default_path.exists()
        win.ref_sb.setValue(-35.0)
        win.mode_cb.setCurrentIndex(win.mode_cb.findData("average"))
        win.host_edit.setText("10.0.0.5")
    finally:
        win.close()
    d = json.loads(store.default_path.read_text())
    assert d["display"] == {"ref_dbm": -35.0, "db_per_div": 10.0, "trace_mode": "average"}
    assert d["connection"] == {"host": "10.0.0.5", "pub_port": 5556, "rep_port": 5557}


def test_the_next_start_has_the_saved_settings_and_connection(app, store):
    write_default(store, host="192.168.88.244", pub_port=6000, rep_port=6001)
    win = MainWindow(None, None, None, store=store)
    try:
        assert win.settings == SAVED
        assert win.start_sb.value() == 88.0 and win.points_sb.value() == 801 and win.img_chk.isChecked()
        assert not win.auto_att_chk.isChecked() and win.att_sb.value() == 6.0 and win.ref_sb.value() == -50.0
        assert win.mode_cb.currentData() == "max_hold" and win.trace_a.mode == "max_hold"
        assert (win.host_edit.text(), win.pub_sb.value(), win.rep_sb.value()) == ("192.168.88.244", 6000, 6001)
    finally:
        win.close()
    win = MainWindow("1.2.3.4", None, None, store=store)           # a host given on the command line wins
    try:
        assert win.host_edit.text() == "1.2.3.4" and win.pub_sb.value() == 6000
    finally:
        win.close()


def test_the_saved_settings_go_to_sweepd_at_the_first_connection_only(app, store, daemon):
    write_default(store)
    win = MainWindow(store=store)
    try:
        assert server_settings(daemon)["start_hz"] == 30e6
        assert connect(win, daemon)
        s = server_settings(daemon)
        assert (s["start_hz"], s["stop_hz"], s["points"], s["averages"], s["atten_db"], s["auto_atten"],
                s["image_reject"]) == (88e6, 108e6, 801, 8, 6.0, False, True)
        assert win.settings == SAVED and "last session restored" in win.status_msg.text()
        win.settings.points = 201
        daemon.apply(win.settings.to_command())
        assert connect(win, daemon) and win.settings.points == 201           # a later sync adopts the server's again
    finally:
        win.close()


def test_a_first_start_does_not_push_anything_to_sweepd(app, store, daemon):
    daemon.apply(core.SaSettings(start_hz=200e6, stop_hz=300e6).to_command())
    win = MainWindow(store=store)
    try:
        connect(win, daemon)
        assert win.settings.start_hz == 200e6                                # sweepd's own settings are adopted
    finally:
        win.close()


def test_save_as_and_load_by_name(app, store, daemon):
    win = MainWindow(store=store)
    try:
        connect(win, daemon)
        win.settings.assign(SAVED)
        win.mode_cb.setCurrentIndex(win.mode_cb.findData("min_hold"))
        assert win.save_named("FM band") and store.names() == ["FM band"]
        assert "connection" not in json.loads(store.path_of("FM band").read_text())
        win.restore_as_delivered()
        assert win.settings == core.SaSettings() and server_settings(daemon)["points"] == 401
        win.menu_load.aboutToShow.emit()
        assert [a.text() for a in win.menu_load.actions()] == ["FM band"]
        win.menu_load.actions()[0].trigger()
        assert win.settings == SAVED and win.mode_cb.currentData() == "min_hold" and win.trace_a.mode == "min_hold"
        s = server_settings(daemon)
        assert (s["start_hz"], s["points"], s["image_reject"]) == (88e6, 801, True)        # pushed to sweepd
        assert win.start_sb.value() == 88.0 and "FM band" in win.status_msg.text()
    finally:
        win.close()


def test_loading_a_named_setup_does_not_change_the_connection(app, store):
    store.save("Other", sc.to_dict(SAVED, "view", sc.Connection("elsewhere", 1, 2)))
    win = MainWindow(store=store)
    try:
        assert win.load_named("Other") and win.host_edit.text() == "127.0.0.1" and win.pub_sb.value() == 5556
        assert win.settings == SAVED
    finally:
        win.close()


def test_restore_as_delivered_resets_the_controls_and_default_json_but_keeps_named_ones(app, store):
    write_default(store, host="rpi", pub_port=5556, rep_port=5557)
    store.save("Keep", sc.to_dict(SAVED, "clear_write"))
    win = MainWindow(None, None, None, store=store)
    try:
        assert win.settings == SAVED
        win.restore_as_delivered()
        assert win.settings == core.SaSettings() and win.mode_cb.currentData() == "clear_write"
        assert win.points_sb.value() == 401 and win.ref_sb.value() == -20.0 and win.host_edit.text() == "rpi"
    finally:
        win.close()
    assert sc.Store(store.dir).load_default().settings == core.SaSettings() and store.names() == ["Keep"]


def test_errors_go_to_the_status_bar_not_to_an_exception(app, store):
    win = MainWindow(store=store)
    try:
        assert win.load_named("missing") is False and "no saved settings" in win.status_msg.text()
        assert win.save_named("../evil") is False and "not a usable name" in win.status_msg.text()
        assert win.delete_named("missing") is False
        store.save("Odd", {"format": 1, "sweep": {"points": 5000, "averages": 0}})
        assert win.load_named("Odd") and win.settings.points == 4001 and win.settings.averages == 1
        assert "points 5000 set to 4001" in win.status_msg.text()
        assert win.delete_named("Odd") and store.names() == []
    finally:
        win.close()


def test_a_broken_default_json_is_reported_and_the_as_delivered_settings_used(app, store):
    store.dir.mkdir(parents=True)
    store.default_path.write_text("{broken")
    win = MainWindow(store=store)
    try:
        assert win.settings == core.SaSettings()
        assert any("not valid JSON" in e.msg for e in win.dev_log.entries)
    finally:
        win.close()
    assert json.loads(store.default_path.read_text())["format"] == 1          # and exit repaired it


def test_the_simulator_address_does_not_replace_the_saved_connection(app, store):
    class Running:
        running = True
        platform = None

        def stop(self):
            self.running = False

    write_default(store, host="rpi", pub_port=5556, rep_port=5557)
    win = MainWindow(None, None, None, store=store)
    win.runner = Running()                                          # the simulator is what the GUI is connected to
    win.host_edit.setText("127.0.0.1")
    win.close()                                                     # saves default.json
    d = json.loads(store.default_path.read_text())
    assert d["connection"]["host"] == "rpi" and d["sweep"]["points"] == 801
