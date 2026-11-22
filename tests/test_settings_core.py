"""settings_core: the GUI's saved settings (as-delivered file, the user's default.json, named settings)."""
import json

import pytest

from sadiy.ui import sa_core as core
from sadiy.ui import settings_core as sc


def test_the_as_delivered_file_is_the_builtin_default():
    """config/default.json and SaSettings() must not drift apart."""
    loaded = sc.as_delivered()
    assert loaded.settings == core.SaSettings() and loaded.trace_mode == "clear_write" and not loaded.notes
    assert loaded.connection is None
    assert json.loads(sc.AS_DELIVERED_PATH.read_text()) == sc.to_dict(core.SaSettings(), "clear_write")


def test_a_missing_or_broken_as_delivered_file_falls_back_to_the_builtin_values(tmp_path):
    assert sc.as_delivered(path=tmp_path / "nope.json").settings == core.SaSettings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert sc.as_delivered(path=bad).settings == core.SaSettings()


def test_round_trip_with_and_without_connection():
    s = core.SaSettings(start_hz=100e6, stop_hz=200e6, points=801, averages=8, atten_db=5.5, auto_atten=False,
                        image_reject=True, ref_dbm=-40.0, db_per_div=5.0)
    d = sc.to_dict(s, "max_hold")
    assert "connection" not in d
    back = sc.parse(json.loads(json.dumps(d)))
    assert back.settings == s and back.trace_mode == "max_hold" and back.connection is None and not back.notes
    d = sc.to_dict(s, "average", sc.Connection("192.168.1.7", 6000, 6001))
    back = sc.parse(d)
    assert back.connection == sc.Connection("192.168.1.7", 6000, 6001) and back.trace_mode == "average"


def test_missing_values_keep_the_base_and_unknown_keys_are_ignored():
    base = core.SaSettings(points=1001, averages=2)
    got = sc.parse({"format": 1, "sweep": {"points": 201, "future_key": 1}, "extra": {}}, base=base)
    assert got.settings.points == 201 and got.settings.averages == 2 and not got.notes
    assert sc.parse({}).settings == core.SaSettings()


def test_bad_values_are_reported_and_replaced():
    got = sc.parse({"sweep": {"start_hz": "30 MHz", "points": True, "averages": 1000, "atten_db": 99,
                              "auto_atten": "yes", "stop_hz": 900e6},
                    "display": {"ref_dbm": 500, "db_per_div": 3, "trace_mode": "sparkle"}})
    s = got.settings
    assert s.stop_hz == 480e6 and s.start_hz == 30e6                   # clamped to the limits
    assert s.points == 401 and s.averages == 64 and s.atten_db == 31.5 and s.auto_atten is True
    assert s.ref_dbm == 30.0 and s.db_per_div == 10.0 and got.trace_mode == "clear_write"
    text = " | ".join(got.notes)
    for part in ("start_hz", "points", "averages 1000", "attenuation 99", "auto_atten", "reference level", "db_per_div",
                 "trace_mode"):
        assert part in text, (part, text)


def test_frequencies_are_clamped_to_the_limits_of_the_server():
    lim = core.Limits(rf_min_hz=100e6, rf_max_hz=300e6)
    got = sc.parse({"sweep": {"start_hz": 30e6, "stop_hz": 480e6}}, lim)
    assert (got.settings.start_hz, got.settings.stop_hz) == (100e6, 300e6) and got.notes


def test_connection_values_are_checked():
    got = sc.parse({"connection": {"host": " ", "pub_port": 70000, "rep_port": "x"}})
    assert got.connection == sc.Connection() and len(got.notes) == 3


@pytest.mark.parametrize("doc", [[], "text", 3, {"format": 2}, {"sweep": []}])
def test_not_a_settings_file_is_an_error(doc):
    with pytest.raises(sc.SettingsError):
        sc.parse(doc)


def test_names():
    assert sc.check_name("  Airband 2 ") == "Airband 2"
    assert sc.check_name("FM.json") == "FM"
    for bad in ("", "  ", "../x", "a/b", ".hidden", "x" * 65, "a\\b", "tab\tname", "-x"):
        with pytest.raises(sc.SettingsError):
            sc.check_name(bad)


def test_store_default_named_load_delete(tmp_path):
    st = sc.Store(tmp_path / "cfg")
    assert st.load_default() is None and st.names() == []
    s = core.SaSettings(start_hz=88e6, stop_hz=108e6, points=1001)
    st.save_default(sc.to_dict(s, "min_hold", sc.Connection("rpi.local", 5556, 5557)))
    d = st.load_default()
    assert d.settings == s and d.trace_mode == "min_hold" and d.connection.host == "rpi.local"
    # named settings never carry the connection, even when the document given has one
    st.save("FM band", sc.to_dict(s, "average", sc.Connection("elsewhere", 1, 2)))
    st.save("Air", sc.to_dict(core.SaSettings(start_hz=118e6, stop_hz=137e6), "clear_write"))
    assert st.names() == ["Air", "FM band"]
    assert "connection" not in json.loads(st.path_of("FM band").read_text())
    got = st.load("FM band")
    assert got.settings == s and got.trace_mode == "average" and got.connection is None
    st.delete("Air")
    assert st.names() == ["FM band"]
    for fn in (st.load, st.delete):
        with pytest.raises(sc.SettingsError, match="no saved settings"):
            fn("Air")
    assert not list((tmp_path / "cfg").rglob("*.tmp"))                  # the temporary file is gone


def test_store_reports_unreadable_files(tmp_path):
    st = sc.Store(tmp_path)
    st.default_path.write_text("{oops")
    with pytest.raises(sc.SettingsError, match="not valid JSON"):
        st.load_default()
    (tmp_path / sc.NAMES_DIR).mkdir()
    (tmp_path / sc.NAMES_DIR / "old.json").write_text(json.dumps({"format": 9}))
    with pytest.raises(sc.SettingsError, match="not supported"):
        st.load("old")
    blocked = tmp_path / "file"
    blocked.write_text("x")
    with pytest.raises(sc.SettingsError, match="could not write"):
        sc.Store(blocked / "sub").save_default({})


def test_the_folder_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SADIY_CONFIG_DIR", str(tmp_path / "a"))
    assert sc.config_dir() == tmp_path / "a"
    monkeypatch.delenv("SADIY_CONFIG_DIR")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "x"))
    assert sc.config_dir() == tmp_path / "x" / "sadiy"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert sc.config_dir().parts[-2:] == (".config", "sadiy")
