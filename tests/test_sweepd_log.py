"""What sweepd says: the `log` command, events, a failing sweep, bad commands, bench events."""
import io
import json
import logging

import pytest

from sadiy import config, logs
from sadiy.hal.fake import FakeBackend
from sadiy.server import protocol
from sadiy.server.bench import Bench
from sadiy.server.sweepd import Sweepd, build_sim_engine
from test_bench import LD_GPIO, Clock


@pytest.fixture
def ring():
    r = logs.setup("error", stream=io.StringIO())      # quiet stderr; the ring still takes DEBUG up
    yield r
    for h in list(logging.getLogger("sadiy").handlers):
        if getattr(h, "_sadiy", False):
            logging.getLogger("sadiy").removeHandler(h)


@pytest.fixture
def daemon(ring):
    cfg = config.load()
    return Sweepd(cfg, build_sim_engine(cfg), ring=ring)


def msgs(ring, min_level=0):
    return [e.msg for e in ring.entries(min_level=min_level)]


def test_log_command_filters_and_reports_last_seq(daemon, ring):
    daemon.apply({"cmd": "set", "points": 11})
    daemon.apply({"cmd": "set", "points": 5000})                   # rejected: a warning
    r = daemon.apply({"cmd": "log"})
    assert r["ok"] and r["last_seq"] == ring.last_seq
    assert [e["level"] for e in r["entries"]] == [logging.INFO, logging.WARNING]
    warn = daemon.apply({"cmd": "log", "level": "warning"})["entries"]
    assert len(warn) == 1 and "points must be 2..4001" in warn[0]["msg"]
    assert daemon.apply({"cmd": "log", "since": r["last_seq"]})["entries"] == []
    assert not daemon.apply({"cmd": "log", "level": "loud"})["ok"]
    assert daemon.apply({"cmd": "log", "limit": 1})["entries"][0]["seq"] == ring.last_seq   # the refusal above
    assert daemon.apply({"cmd": "status"})["log_seq"] >= r["last_seq"]


def test_log_command_without_a_ring_is_empty():
    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    assert d.apply({"cmd": "log"}) == {"ok": True, "entries": [], "last_seq": 0, "boot": ""}


def test_settings_run_and_stop_are_logged(daemon, ring):
    daemon.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "atten_db": 12.0})
    daemon.apply({"cmd": "set", "start_hz": 90e6})                 # nothing changed: nothing logged
    daemon.apply({"cmd": "stop"})
    daemon.apply({"cmd": "run"})
    got = msgs(ring)
    assert got[0] == "settings: start_hz=9e+07, stop_hz=1.1e+08, atten_db=12"
    assert got[1:] == ["sweep stopped by a client", "sweep started"]


def test_first_sweep_is_info_and_later_ones_are_not(daemon, ring):
    daemon.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "points": 11})
    for _ in range(3):
        assert daemon.run_step() is not None
    info = [m for m in msgs(ring, logging.INFO) if m.startswith("sweeping")]
    assert len(info) == 1 and "11 points" in info[0] and "90.000 to 110.000 MHz" in info[0]
    daemon.apply({"cmd": "set", "points": 21})                     # a new range is announced again
    daemon.run_step()
    assert len([m for m in msgs(ring) if m.startswith("sweeping")]) == 2


def test_failed_sweep_stops_sweeping_and_reports(daemon, ring):
    calls = []
    daemon.engine.safe_state = lambda: calls.append("safe") or ["synth: SPI is gone"]

    def boom(points, atten_db):
        raise OSError("SPI write failed on /dev/spidev1.0")

    daemon.engine.run = boom
    assert daemon.run_step() is None
    assert not daemon.running and calls == ["safe"]
    assert daemon.apply({"cmd": "status"})["last_error"] == "sweep failed: SPI write failed on /dev/spidev1.0"
    errors = msgs(ring, logging.ERROR)
    assert errors == ["sweep failed, sweeping stopped: SPI write failed on /dev/spidev1.0 (OSError: SPI write failed on /dev/spidev1.0)"]
    assert any("SPI is gone" in m for m in msgs(ring, logging.WARNING))
    assert daemon.apply({"cmd": "run"})["ok"]                      # the daemon still answers and can retry


def test_real_engine_safe_state_goes_to_max_attenuation(daemon):
    daemon.engine.atten.set_attenuation(3.0)
    assert daemon.engine.safe_state() == []
    assert daemon.engine.atten.chain.atten_db == 31.5


def test_bad_commands_always_get_a_reply(daemon, ring):
    assert daemon.handle_raw(b"not json")["error"] == "command is not JSON"
    assert daemon.handle_raw(b"[1, 2]")["error"] == "command must be a JSON object"
    assert not daemon.handle_raw(b'{"cmd": "bogus"}')["ok"]
    daemon._apply = lambda cmd: 1 / 0
    r = daemon.handle_raw(b'{"cmd": "set"}')
    assert not r["ok"] and "division by zero" in r["error"]
    assert daemon.last_error == r["error"]
    assert any("division by zero" in m for m in msgs(ring, logging.ERROR))


def test_refused_run_is_a_warning(ring):
    cfg = config.load()
    d = Sweepd(cfg, None, ring=ring)                               # --bench-only: no engine
    assert not d.apply({"cmd": "run"})["ok"]
    assert any("no sweep hardware" in m for m in msgs(ring, logging.WARNING))


# ---------------------------------------------------------------- the wire

def test_log_record_roundtrip_and_rejects_garbage():
    e = logs.LogEntry(3, 12.5, logging.WARNING, "sadiy.server.sweepd", "careful", 2, "ab12")
    parts = protocol.encode_log(e)
    assert parts[0] == protocol.LOG_TOPIC
    assert protocol.decode_log(parts) == e
    with pytest.raises(ValueError):
        protocol.decode_log([protocol.TOPIC, b"{}"])
    with pytest.raises(ValueError):
        protocol.decode_log([protocol.LOG_TOPIC, b'{"seq": 1}'])
    with pytest.raises(ValueError):
        protocol.decode_log([protocol.LOG_TOPIC, b"nope"])


# ---------------------------------------------------------------- bench events

def bench_rig(ring):
    cfg = config.load()
    clock = Clock()
    bench = Bench(FakeBackend(lock_gpio=LD_GPIO), cfg, clock, clock.sleep)
    daemon = Sweepd(cfg, None, bench, ring)
    return daemon, clock


def test_bench_open_close_and_lease_are_logged(ring):
    daemon, clock = bench_rig(ring)
    token = daemon.apply({"cmd": "bench_open"})["token"]
    assert any(m.startswith("bench mode opened") for m in msgs(ring, logging.INFO))
    daemon.apply({"cmd": "bench_close", "token": token})
    assert "bench mode closed: closed by the client" in msgs(ring, logging.INFO)
    token = daemon.apply({"cmd": "bench_open"})["token"]
    clock.t += daemon.bench.lease_s + 1
    daemon.service_bench()
    warn = msgs(ring, logging.WARNING)
    assert any("bench client silent" in m for m in warn)
    assert any("no command from the client" in m for m in msgs(ring, logging.INFO))


def test_bench_refusals_are_debug_and_hardware_errors_are_errors(ring):
    daemon, _ = bench_rig(ring)
    token = daemon.apply({"cmd": "bench_open"})["token"]
    daemon.apply({"cmd": "bench_pin", "token": token, "pin": "P8.7", "action": "write", "value": 1})
    refused = [e for e in ring.entries() if "needs the operator's confirm" in e.msg]
    assert refused and refused[0].level == logging.DEBUG
    r = daemon.apply({"cmd": "bench_spi", "token": token, "word": 0x0080C004, "confirm": True})
    assert r["ok"]
    daemon.bench._adf.write_word = lambda w: (_ for _ in ()).throw(OSError("SPI gone"))
    r = daemon.apply({"cmd": "bench_spi", "token": token, "word": 0x0080C004, "confirm": True})
    assert not r["ok"]
    assert any("SPI gone" in m for m in msgs(ring, logging.ERROR))


def test_rf_output_changes_are_info(ring):
    daemon, _ = bench_rig(ring)
    token = daemon.apply({"cmd": "bench_open"})["token"]
    daemon.apply({"cmd": "bench_spi", "token": token, "word": 0x00000000, "confirm": True})   # an R0
    daemon.bench.backend.lines[LD_GPIO].level = 1
    r = daemon.apply({"cmd": "bench_rf", "token": token, "main": True, "confirm": True})
    assert r["ok"], r
    daemon.apply({"cmd": "bench_rf", "token": token, "main": False})
    got = msgs(ring, logging.INFO)
    assert "RF output main=on aux=off at -4 dBm" in got and "RF output main=off aux=off" in got
