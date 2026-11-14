"""The platform layer: BBB and EBAZ4205 pin maps, `platforms`, the bench on the EBAZ map, the pin list of pins.toml."""
import json
import tomllib
from pathlib import Path

import pytest

from sadiy import config, pinmap, pinmap_ebaz, platforms
from sadiy.hal.fake import FakeBackend
from sadiy.server.bench import Bench, fake_backend
from sadiy.server.sweepd import Sweepd, build_sim_engine
from sadiy.ui import bench_core

PINS_TOML = Path(__file__).resolve().parents[1] / "zynq-ebaz" / "rtl" / "vivado" / "pins.toml"


# ---------------------------------------------------------------- platforms
def test_names_and_default():
    assert platforms.NAMES == ("bbb", "ebaz")
    assert platforms.DEFAULT == "bbb"
    assert platforms.get() is pinmap.BBB
    assert platforms.get("ebaz") is pinmap_ebaz.EBAZ


@pytest.mark.parametrize("name,want", [("BBB", "bbb"), (" ebaz ", "ebaz"), ("ebaz-ps", "ebaz"), ("ebaz-pl", "ebaz"), (None, "bbb")])
def test_normalize(name, want):
    assert platforms.normalize(name) == want


def test_unknown_platform_is_an_error():
    with pytest.raises(ValueError, match="unknown platform"):
        platforms.get("rpi")


def test_from_config():
    assert platforms.from_config({}).name == "bbb"
    assert platforms.from_config({"platform": {"name": "ebaz-pl"}}).name == "ebaz"
    assert config.load()["platform"]["name"] == "bbb"


def test_bbb_map_is_the_module_level_one():
    assert pinmap.BBB.pins is pinmap.PINS
    assert pinmap.BBB.by_net is pinmap.BY_NET
    assert len(pinmap.BBB.pins) == 92


# ---------------------------------------------------------------- the EBAZ map
def test_ebaz_pins():
    pm = pinmap_ebaz.EBAZ
    assert len(pm.pins) == 60
    assert {p.header for p in pm.pins.values()} == {"DATA1", "DATA2", "DATA3"}
    assert pm.ids(pm.att_nets) == tuple(f"DATA2.{n}" for n in range(14, 20))
    assert pm.ids(pm.spi_nets) == ("DATA2.5", "DATA2.7", "DATA2.8")
    assert pm.ids(pm.i2c_nets) == ("DATA2.20", "DATA2.11")          # SCL, SDA
    assert pm.by_net[pm.lock_net].access == pinmap.INPUT_ONLY
    assert pm.by_net[pm.ce_net].access == pinmap.WIRED
    assert [pm.by_net[n].gpio for n in pm.att_nets] == [54, 55, 56, 57, 58, 59]       # EMIO n is 54 + n
    assert (pm.by_net["SYN_CE"].gpio, pm.by_net["SYN_LD"].gpio) == (60, 61)
    assert pm.find("ATT_V1") is pm.pins["DATA2.14"] and pm.find("DATA2.14").net == "ATT_V1"
    with pytest.raises(KeyError):
        pm.find("P8.7")


def test_ebaz_has_every_net_but_the_bbb_adc():
    missing = {n["id"] for n in pinmap.NETS if not n.get("ebaz")}
    assert missing == {"DET_ADC", "ADC_GND"}
    assert set(pinmap_ebaz.BY_NET) == {n["id"] for n in pinmap.NETS} - missing


def test_ebaz_display_pins_cannot_be_driven():
    pm = pinmap_ebaz.EBAZ
    for pin in pm.pins.values():
        if pin.net is None:
            assert pin.access == pinmap.DISPLAY, pin.id
    assert not any(p.ain is not None for p in pm.pins.values())


def test_ebaz_boards_have_no_ain_block():
    assert [b.title for b in pinmap_ebaz.EBAZ.boards] == ["PE4302", "ADF4351", "ADS1115"]
    assert "AIN0" in [b.title for b in pinmap.BBB.boards]


def _toml_signals():
    return {s["name"]: s for s in tomllib.loads(PINS_TOML.read_text())["signal"]}


def test_ebaz_pin_map_agrees_with_pins_toml():
    """pins.toml is the master list of the PCB and the XDC; pinmap_ebaz copies balls and port names."""
    by_pin = {(s["connector"], s["pin"]): s for s in _toml_signals().values()}
    for header, balls in pinmap_ebaz.BALLS.items():
        for number, ball in balls.items():
            if header == "DATA3" and (header, number) not in by_pin:      # DATA3 is not in pins.toml yet
                continue
            assert by_pin[(header, number)]["ball"] == ball, f"{header}.{number}"
    for number, signal in pinmap_ebaz.DATA2_SIGNALS.items():
        sig = by_pin[("DATA2", number)]
        assert sig["name"] == signal and sig.get("active", True)
    for number, role in pinmap_ebaz.DATA1_ROLES.items():
        assert by_pin[("DATA1", number)]["name"] == role


# ---------------------------------------------------------------- bench on the EBAZ map
def _ebaz_rig(sim=True):
    cfg = config.load()
    bench = Bench(fake_backend("ebaz"), cfg, platform="ebaz")
    daemon = Sweepd(cfg, build_sim_engine(cfg), bench)
    daemon.running = False

    def call(cmd):
        return json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd)))))

    return daemon, bench, call


def test_fake_backend_for_ebaz_has_no_pin_mux():
    assert fake_backend("ebaz").can_mux is False
    assert fake_backend("bbb").can_mux is True
    assert fake_backend(pinmap_ebaz.EBAZ).can_mux is False


def test_bench_defaults_to_the_config_platform():
    cfg = config.load()
    assert Bench(FakeBackend(lock_gpio=pinmap.BY_NET["SYN_LD"].gpio), cfg).pm.name == "bbb"
    assert Bench(FakeBackend(lock_gpio=61), dict(cfg, platform={"name": "ebaz"})).pm.name == "ebaz"


def test_sweepd_status_and_bench_open_name_the_platform():
    daemon, _bench, call = _ebaz_rig()
    assert call({"cmd": "status"})["platform"] == "ebaz"
    opened = call({"cmd": "bench_open"})
    assert opened["ok"] and opened["platform"] == "ebaz"
    assert opened["limits"]["can_mux"] is False
    assert set(opened["pins"]) >= {"DATA2.14", "DATA2.9", "DATA2.13"}
    assert not any(pid.startswith(("P8", "P9")) for pid in opened["pins"])


def test_ebaz_bench_rejects_bbb_pins_and_bus_pins():
    _daemon, _bench, call = _ebaz_rig()
    tok = call({"cmd": "bench_open"})["token"]
    wrong = call({"cmd": "bench_pin", "token": tok, "pin": "P8.7", "action": "read"})
    assert not wrong["ok"] and "EBAZ4205" in wrong["error"]
    assert call({"cmd": "bench_pin", "token": tok, "pin": "ATT_V1", "action": "read"})["ok"]
    # DATA2.5 is the SPI clock, wired to the PS in the bitstream: it can not become a GPIO
    gpio = call({"cmd": "bench_pin", "token": tok, "pin": "DATA2.5", "action": "read"})
    assert not gpio["ok"] or gpio.get("dir") != "out"
    atten = call({"cmd": "bench_atten", "token": tok, "db": 31.5, "confirm": True})
    assert atten["ok"] and atten["attenuation_db"] == 31.5


def test_bbb_bench_rejects_ebaz_pins():
    cfg = config.load()
    daemon = Sweepd(cfg, build_sim_engine(cfg), Bench(fake_backend(), cfg))
    daemon.running = False
    tok = daemon.apply({"cmd": "bench_open"})["token"]
    reply = daemon.apply({"cmd": "bench_pin", "token": tok, "pin": "DATA2.14", "action": "read"})
    assert not reply["ok"] and "BeagleBone" in reply["error"]


def test_attenuator_pattern_uses_the_ebaz_pins():
    _daemon, _bench, call = _ebaz_rig()
    tok = call({"cmd": "bench_open"})["token"]
    reply = call({"cmd": "bench_pattern", "token": tok, "action": "start", "confirm": True,
                  "spec": {"kind": "pe4302_stages", "mode": "one_out"}, "rate_hz": 5.0, "loop": False})
    assert reply["ok"], reply
    call({"cmd": "bench_pattern", "token": tok, "action": "stop"})


# ---------------------------------------------------------------- the session refuses a platform mismatch
def test_session_refuses_a_daemon_of_the_other_platform():
    daemon, _bench, call = _ebaz_rig()
    daemon.bench.pm  # ebaz daemon, BBB session (the default)
    session = bench_core.BenchSession(call, lambda _t: True)
    reply = session.open(lambda: True)
    assert not reply["ok"] and "ebaz" in reply["error"] and not session.active
    assert not daemon.bench_active                      # the daemon side was closed again
    ok = bench_core.BenchSession(call, lambda _t: True, pm=pinmap_ebaz.EBAZ)
    assert ok.open(lambda: True)["ok"] and ok.active
    ok.close()


# ---------------------------------------------------------------- the drawn board
@pytest.mark.parametrize("pm", [pinmap.BBB, pinmap_ebaz.EBAZ], ids=lambda p: p.name)
def test_board_geometry(pm):
    w, h = bench_core.canvas_size(pm)
    blocks = bench_core.blocks(pm)
    assert [b.board.title for b in blocks] == [t for t, *_ in pm.layout.blocks]
    rows = [r for b in blocks for r in b.rows]
    assert {r.net for r in rows} >= set(pm.att_nets) | set(pm.spi_nets) | set(pm.i2c_nets)
    for pin in pm.pins.values():
        x, y, pw, ph = bench_core.pin_rect(pin, pm)
        assert 0 <= x and x + pw <= w and 0 <= y and y + ph <= h, pin.id
        assert bench_core.hit_test(x + pw / 2, y + ph / 2, pm) == pin.id
    for wire in bench_core.wires(pm):
        for px, py in wire.points:
            assert 0 <= px <= w and 0 <= py <= h
    assert {k for k, _ in pm.layout.legend} <= set(bench_core.CATEGORY_COLOURS)
    assert {p.category for p in pm.pins.values()} <= set(bench_core.CATEGORY_COLOURS)


def test_ebaz_connectors_do_not_overlap():
    rects = [bench_core.pin_rect(p, pinmap_ebaz.EBAZ) for p in pinmap_ebaz.EBAZ.pins.values()]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
