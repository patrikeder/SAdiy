"""The bench mode against the fake backend: protocol, safety rules, patterns. No hardware involved."""
import json

import pytest

from sadiy import config, pinmap
from sadiy.drivers.adf4351 import Output, Outputs, pack_r4, r4_enables_output, r4_with_outputs
from sadiy.hal.fake import FakeBackend
from sadiy.server.bench import Bench
from sadiy.server.sweepd import Sweepd, build_sim_engine

ATT_GPIO = [pinmap.BY_NET[n].gpio for n in pinmap.ATT_NETS]
LD_GPIO = pinmap.BY_NET["SYN_LD"].gpio
R4_OFF = 0x0080C004                # an R4 with no output enabled
R4_MAIN_ON = R4_OFF | (1 << 5)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Rig:
    """A daemon with fake hardware, a fake clock and a JSON round trip like the real socket."""

    def __init__(self, engine=True):
        self.cfg = config.load()
        self.clock = Clock()
        self.backend = FakeBackend(lock_gpio=LD_GPIO)
        self.bench = Bench(self.backend, self.cfg, self.clock, self.clock.sleep)
        self.daemon = Sweepd(self.cfg, build_sim_engine(self.cfg) if engine else None, self.bench)
        self.daemon.running = False
        self.token = None

    def cmd(self, name, **kw):
        if self.token and "token" not in kw:
            kw["token"] = self.token
        return json.loads(json.dumps(self.daemon.apply(json.loads(json.dumps({"cmd": f"bench_{name}", **kw})))))

    def open(self):
        r = self.cmd("open")
        assert r["ok"], r
        self.token = r["token"]
        return r

    def att_levels(self):
        return [self.backend.lines[n].level for n in ATT_GPIO]

    def r4_words(self):
        return [w for w in self.backend.spi_sent if w[3] & 7 == 4]

    def sent(self):
        return [int.from_bytes(w, "big") for w in self.backend.spi_sent]

    def lock(self):
        assert self.cmd("spi", word=0x00000000, confirm=True)["ok"]


@pytest.fixture
def rig():
    return Rig()


@pytest.fixture
def opened(rig):
    rig.open()
    return rig


# ---------------------------------------------------------------- exclusivity
def test_bench_is_refused_while_sweeping(rig):
    rig.daemon.running = True
    r = rig.cmd("open")
    assert not r["ok"] and r["sweep_running"]
    assert not rig.bench.active
    assert not rig.cmd("pin", pin="P8.7", action="read")["ok"]


def test_status_of_bench_is_allowed_while_sweeping(rig):
    rig.daemon.running = True
    r = rig.cmd("status")
    assert r["ok"] and r["active"] is False and r["owner"] is False


def test_run_is_refused_while_bench_is_open(opened):
    r = opened.daemon.apply({"cmd": "run"})
    assert not r["ok"] and "bench" in r["error"]
    assert not opened.daemon.running
    opened.cmd("close")
    assert opened.daemon.apply({"cmd": "run"})["ok"] and opened.daemon.running


def test_status_reports_bench_state(opened):
    assert opened.daemon.apply({"cmd": "status"})["bench"] == {"active": True}


def test_bench_only_daemon_has_no_sweeps():
    rig = Rig(engine=False)
    assert not rig.daemon.apply({"cmd": "run"})["ok"]
    assert Sweepd(rig.cfg, None).running is False
    rig.open()


def test_daemon_without_bench_backend_refuses_politely():
    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    d.running = False
    assert not d.apply({"cmd": "bench_open"})["ok"]


# ---------------------------------------------------------------- open, ownership, lease
def test_open_goes_to_the_safe_state(rig):
    r = rig.open()
    assert r["warnings"] == [] and r["limits"]["simulated"] is True
    assert rig.att_levels() == [1] * 6 and r["attenuation_db"] == 31.5
    first = int.from_bytes(rig.backend.spi_sent[0], "big")
    assert first & 7 == 4 and not r4_enables_output(first)        # outputs-off R4 before anything else
    assert rig.backend.lines[LD_GPIO].output is False


def test_open_twice_is_refused(opened):
    assert not opened.cmd("open")["ok"]


def test_commands_need_the_token(opened):
    assert "another client" in opened.cmd("pin", pin="P8.7", token="wrong")["error"]
    assert opened.cmd("status", token="wrong")["owner"] is False


def test_commands_need_an_open_bench(rig):
    assert "not open" in rig.cmd("pin", pin="P8.7", action="read")["error"]


def test_unknown_bench_command(opened):
    assert "unknown" in opened.cmd("nope")["error"]


def test_lease_expiry_returns_to_safe(opened):
    opened.cmd("pin", pin="P8.7", action="write", value=0, confirm=True)
    assert opened.att_levels()[0] == 0
    opened.clock.t += 4.0
    opened.daemon.service_bench()
    assert opened.bench.active                                     # still inside the lease
    opened.cmd("status")                                           # renews it
    opened.clock.t += 4.0
    opened.daemon.service_bench()
    assert opened.bench.active
    opened.clock.t += 6.0
    opened.daemon.service_bench()
    assert not opened.bench.active and opened.att_levels() == [1] * 6
    r = opened.cmd("status")
    assert r["active"] is False and "no command" in r["closed_reason"]


def test_shutdown_returns_to_safe(opened):
    opened.cmd("atten", db=0.0, confirm=True)
    opened.daemon.shutdown()
    assert opened.att_levels() == [1] * 6 and not opened.bench.active


def test_close_closes_the_buses(opened):
    spi = opened.backend.spi_bus
    opened.cmd("close")
    assert spi.closed and opened.backend.ads.closed


# ---------------------------------------------------------------- pin rules
@pytest.mark.parametrize("pin", ["P9.1", "P9.3", "P9.5", "P8.3", "P8.27", "P9.32", "P9.34"])
def test_display_only_pins_cannot_be_touched(opened, pin):
    for kw in ({"action": "write", "value": 1, "confirm": True, "expert": True},
               {"action": "input", "expert": True}, {"action": "read", "expert": True}):
        r = opened.cmd("pin", pin=pin, **kw)
        assert not r["ok"], kw
    assert pinmap.PINS[pin].gpio not in opened.backend.lines or pin not in opened.bench._lines


def test_ain0_is_input_only(opened):
    r = opened.cmd("pin", pin="P9.39", action="write", value=1, confirm=True, expert=True)
    assert not r["ok"] and "input-only" in r["error"]


def test_lock_detect_is_input_only(opened):
    r = opened.cmd("pin", pin="P9.23", action="write", value=1, confirm=True, expert=True)
    assert not r["ok"] and "input-only" in r["error"]
    assert opened.cmd("pin", pin="P9.23", action="read")["level"] == 0


def test_free_gpio_needs_expert(opened):
    assert "Expert" in opened.cmd("pin", pin="P9.15", action="write", value=1)["error"]
    assert "Expert" in opened.cmd("pin", pin="P9.15", action="read")["error"]
    r = opened.cmd("pin", pin="P9.15", action="write", value=1, expert=True)
    assert r["ok"] and r["level"] == 1                           # not wired to a board: no confirm
    assert opened.backend.lines[pinmap.PINS["P9.15"].gpio].level == 1


def test_wired_pin_needs_a_confirm(opened):
    r = opened.cmd("pin", pin="P8.7", action="write", value=0)
    assert not r["ok"] and r["needs_confirm"] and "ATT_V1" in r["error"]
    assert opened.att_levels()[0] == 1                           # nothing happened
    assert opened.cmd("pin", pin="P8.7", action="write", value=0, confirm=True)["ok"]
    assert opened.att_levels()[0] == 0


def test_pin_write_keeps_the_attenuator_in_step(opened):
    r = opened.cmd("pin", pin="P8.12", action="write", value=0, confirm=True)
    assert r["attenuation_db"] == 15.5
    # the driver must see the new state: 15.5 -> 16 still has to go through make-before-break
    opened.backend.log.events.clear()
    opened.cmd("atten", db=16.0, confirm=True)
    assert opened.backend.log.events[0] == (f"gpio{ATT_GPIO[5]}", 1)


def test_bad_values_are_refused(opened):
    assert not opened.cmd("pin", pin="P8.7", action="write", value=2, confirm=True)["ok"]
    assert not opened.cmd("pin", pin="P99.1", action="read")["ok"]
    assert not opened.cmd("pin", pin="P8.7", action="fly")["ok"]
    assert not opened.cmd("pin", action="read")["ok"]


def test_input_releases_a_line_without_confirm(opened):
    r = opened.cmd("pin", pin="P8.7", action="input")
    assert r["ok"] and r["dir"] == "in"
    assert opened.backend.lines[ATT_GPIO[0]].output is False
    assert opened.cmd("atten", db=31.5, confirm=True)["ok"]       # driven again for the driver
    assert opened.backend.lines[ATT_GPIO[0]].output is True


# ---------------------------------------------------------------- bus pins as GPIO
def test_spi_pin_as_gpio_switches_the_mux_and_back(opened):
    r = opened.cmd("pin", pin="P9.22", action="write", value=1, confirm=True)
    assert r["ok"]
    assert opened.backend.mux_log == [("P9_22", "gpio")]
    assert opened.cmd("status")["pins"]["P9.22"] == {"level": 1, "dir": "out"}
    before = len(opened.r4_words())
    assert opened.cmd("pin", pin="P9.22", action="bus")["ok"]
    assert opened.backend.mux_log[-1] == ("P9_22", "spi_sclk")
    assert opened.cmd("status")["pins"]["P9.22"] == {"level": None, "dir": "bus"}
    assert len(opened.r4_words()) == before + 1                   # the chip may have latched junk


def test_spi_send_takes_the_pins_back(opened):
    opened.cmd("pin", pin="P9.18", action="write", value=1, confirm=True)
    assert opened.cmd("spi", word=0x00580005, confirm=True)["ok"]
    assert ("P9_18", "spi") in opened.backend.mux_log
    assert opened.sent()[-1] == 0x00580005


def test_i2c_read_takes_the_pins_back(opened):
    opened.cmd("pin", pin="P9.19", action="write", value=1, confirm=True)
    assert opened.cmd("adc", source="ads1115")["ok"]
    assert ("P9_19", "i2c") in opened.backend.mux_log


def test_close_restores_bus_and_expert_pins(opened):
    opened.cmd("pin", pin="P9.20", action="write", value=0, confirm=True)
    opened.cmd("pin", pin="P9.15", action="write", value=1, expert=True)
    opened.cmd("pin", pin="P9.27", action="write", value=1, confirm=True)
    opened.cmd("close")
    assert ("P9_20", "i2c") in opened.backend.mux_log
    assert opened.backend.lines[pinmap.PINS["P9.15"].gpio].output is False
    assert opened.backend.lines[pinmap.PINS["P9.27"].gpio].output is False


# ---------------------------------------------------------------- attenuator
def test_set_db_uses_make_before_break_and_reports_the_writes(opened):
    opened.cmd("atten", db=15.5, confirm=True)
    r = opened.cmd("atten", db=16.0, confirm=True)
    assert r["ok"] and r["attenuation_db"] == 16.0
    assert r["writes"][0] == ["ATT_V6", 1]                       # the stage turning on goes first


def test_atten_needs_a_confirm(opened):
    r = opened.cmd("atten", db=0.0)
    assert r["needs_confirm"] and opened.att_levels() == [1] * 6


def test_levels_ordered_vs_raw(opened):
    opened.cmd("atten", db=15.5, confirm=True)
    target = [0, 0, 0, 0, 0, 1]                                  # 16 dB
    ordered = opened.cmd("atten", levels=target, confirm=True)
    assert ordered["writes"][0] == ["ATT_V6", 1]
    opened.cmd("atten", db=15.5, confirm=True)
    raw = opened.cmd("atten", levels=target, raw=True, confirm=True)
    assert [w[0] for w in raw["writes"]] == list(pinmap.ATT_NETS)  # plain V1..V6 order, every line
    assert raw["attenuation_db"] == 16.0
    assert not opened.cmd("atten", levels=[1, 0], confirm=True)["ok"]


# ---------------------------------------------------------------- ADF4351
def test_r4_helpers():
    word = pack_r4(8, Outputs(), 200)
    on = r4_with_outputs(word, Outputs(main=Output(True, 5)))
    assert r4_enables_output(on) and not r4_enables_output(word)
    assert on == pack_r4(8, Outputs(main=Output(True, 5)), 200)
    assert r4_with_outputs(on, Outputs()) == word
    assert not r4_enables_output(0x00000020)                     # bit 5 of a non-R4 word is something else
    with pytest.raises(ValueError):
        r4_with_outputs(0x00000000, Outputs())


def test_raw_word_goes_out_big_endian(opened):
    r = opened.cmd("spi", word=0x00580005, confirm=True)
    assert r["ok"] and r["sent"] == ["0x00580005"]
    assert opened.backend.spi_sent[-1] == bytes.fromhex("00580005")


def test_raw_spi_needs_a_confirm_and_checks_the_range(opened):
    assert opened.cmd("spi", word=5)["needs_confirm"]
    assert not opened.cmd("spi", word=1 << 32, confirm=True)["ok"]
    assert not opened.cmd("spi", word="x", confirm=True)["ok"]


def test_init_sequence_keeps_its_order(opened):
    words = [0x00580005, R4_OFF, 0x000004B3, 0x00004E42, 0x08008011, 0x00320000]
    assert opened.cmd("spi", words=words, confirm=True)["ok"]
    assert opened.sent()[-6:] == words


def test_raw_r4_that_enables_an_output_is_refused(opened):
    before = len(opened.backend.spi_sent)
    r = opened.cmd("spi", word=R4_MAIN_ON, confirm=True)
    assert not r["ok"] and "RF output" in r["error"]
    r = opened.cmd("spi", words=[0x00580005, R4_MAIN_ON], confirm=True)      # nothing of the list goes out
    assert not r["ok"] and len(opened.backend.spi_sent) == before


def test_outputs_need_r0_then_lock_then_confirm(opened):
    assert "R0" in opened.cmd("rf", main=True, confirm=True)["error"]
    opened.lock()
    opened.backend.lines[LD_GPIO].external = 0                   # R0 sent but not locked
    assert "not locked" in opened.cmd("rf", main=True, confirm=True)["error"]
    opened.backend.lines[LD_GPIO].external = 1
    assert opened.cmd("rf", main=True)["needs_confirm"]
    r = opened.cmd("rf", main=True, power_dbm=-1, confirm=True)
    assert r["ok"] and r["rf"] == {"main": True, "aux": False}
    assert r4_enables_output(opened.sent()[-1])
    assert opened.cmd("status")["rf"]["main"] is True


def test_turning_outputs_off_needs_nothing(opened):
    assert opened.cmd("rf", main=False, aux=False)["ok"]
    assert not r4_enables_output(opened.sent()[-1])


def test_rf_keeps_the_divider_of_the_last_raw_r4(opened):
    r4 = pack_r4(16, Outputs(), 100)
    opened.cmd("spi", word=r4, confirm=True)
    opened.lock()
    opened.cmd("rf", main=True, power_dbm=5, confirm=True)
    assert opened.sent()[-1] == pack_r4(16, Outputs(main=Output(True, 5)), 100)


def test_while_rf_is_on_raw_words_and_spi_gpio_are_refused(opened):
    opened.lock()
    opened.cmd("rf", main=True, confirm=True)
    assert "RF output is on" in opened.cmd("spi", word=0x00580005, confirm=True)["error"]
    assert "RF output is on" in opened.cmd("pin", pin="P9.22", action="write", value=1, confirm=True)["error"]
    assert "RF output is on" in opened.cmd("pin", pin="P9.22", action="input")["error"]
    # an R4 that turns it off is the one raw word that is allowed, and the state follows
    assert opened.cmd("spi", word=R4_OFF, confirm=True)["ok"]
    assert opened.cmd("status")["rf"]["main"] is False


def test_close_turns_outputs_off(opened):
    opened.lock()
    opened.cmd("rf", aux=True, confirm=True)
    opened.cmd("close")
    assert not r4_enables_output(opened.sent()[-1]) and opened.sent()[-1] & 7 == 4


# ---------------------------------------------------------------- ADCs
def test_ads1115_single_shot_and_registers(opened):
    opened.backend.ads.volts[1] = 2.0
    r = opened.cmd("adc", source="ads1115", channel=1)
    assert r["ok"] and r["volts"] == pytest.approx(2.0, abs=2e-4) and r["code"] == 16000
    assert r["conversion"] == 16000 and r["config"] >> 15 == 1
    assert (r["config"] >> 12) & 7 == 0b101
    r = opened.cmd("adc", source="ads1115", read="regs")
    assert r["conversion"] == 16000 and "volts" not in r


def test_ads1115_is_the_default_adc(opened):
    assert opened.cmd("adc")["source"] == "ads1115"


def test_ain_raw_and_volts(opened):
    opened.backend.analog[0].raw = 2048
    r = opened.cmd("adc", source="ain", channel=0, n=4)
    assert r["raw"] == 2048 and r["volts"] == pytest.approx(2048 * 1.8 / 4095)
    assert r["volts_detector"] == pytest.approx(r["volts"] / 0.751)   # AIN0 has its own divider
    assert not opened.cmd("adc", source="ain", channel=7)["ok"]
    assert not opened.cmd("adc", source="dmm")["ok"]


def test_ads1115_missing_is_a_warning_not_a_failure():
    rig = Rig()

    def no_bus():
        raise OSError("no /dev/i2c-2")

    rig.backend.i2c = no_bus
    r = rig.open()
    assert r["ok"] and any("ADS1115" in w for w in r["warnings"])
    assert "not available" in rig.cmd("adc")["error"]
    assert rig.cmd("atten", db=3.0, confirm=True)["ok"]           # the rest still works


def test_spi_missing_is_a_warning_that_says_rf_state_is_unknown():
    rig = Rig()

    def no_bus():
        raise ImportError("no spidev")

    rig.backend.spi = no_bus
    r = rig.open()
    assert r["ok"] and any("RF output state is unknown" in w for w in r["warnings"])
    assert "not available" in rig.cmd("spi", word=5, confirm=True)["error"]
    assert rig.cmd("close")["ok"]


# ---------------------------------------------------------------- errors go to the safe state
def test_hardware_error_returns_everything_to_safe(opened):
    opened.cmd("atten", db=0.0, confirm=True)
    assert opened.att_levels() == [0] * 6

    def boom(_data):
        raise OSError("SPI went away")

    opened.backend.spi_bus.on_xfer = boom
    r = opened.cmd("spi", word=0x00580005, confirm=True)
    assert not r["ok"] and "safe state" in r["error"] and "SPI went away" in r["error"]
    assert opened.att_levels() == [1] * 6
    assert "SPI went away" in opened.cmd("status")["last_error"]
    assert opened.bench.active                                    # still open: the operator sees what happened


def test_failing_mux_changes_nothing(opened):
    def boom(_name, _mode):
        raise OSError("config-pin: not found")

    opened.backend.set_mux = boom
    r = opened.cmd("pin", pin="P9.22", action="write", value=1, confirm=True)
    assert not r["ok"] and "config-pin" in r["error"]
    assert opened.att_levels() == [1] * 6


# ---------------------------------------------------------------- patterns
def start(rig, spec, rate=100.0, loop=False, **kw):
    kw.setdefault("confirm", True)
    return rig.cmd("pattern", action="start", spec=spec, rate_hz=rate, loop=loop, **kw)


def run_for(rig, seconds):
    end = rig.clock.t + seconds
    while rig.clock.t < end and rig.bench.pattern_running:
        rig.bench.service(0.01)


def test_pattern_needs_a_confirm_and_checks_every_pin(opened):
    spec = {"kind": "walking", "signals": ["ATT_V1", "ATT_V2"]}
    assert start(opened, spec, confirm=False)["needs_confirm"]
    assert not start(opened, {"kind": "walking", "signals": ["SYN_LD"]})["ok"]
    assert not start(opened, {"kind": "walking", "signals": ["P9.1"]})["ok"]
    assert not start(opened, {"kind": "walking", "signals": ["P9.39"]})["ok"]
    assert "Expert" in start(opened, {"kind": "walking", "signals": ["P9.15"]})["error"]
    assert not opened.bench.pattern_running


def test_pattern_runs_on_schedule_and_writes_what_was_previewed(opened):
    from sadiy import patterns

    spec = {"kind": "walking", "signals": ["ATT_V1", "ATT_V2", "ATT_V3"]}
    expected = patterns.from_spec(spec, pinmap.ATT_NETS)
    assert start(opened, spec, rate=100.0)["ok"]
    t0 = opened.clock.t
    opened.backend.log.events.clear()
    r = opened.cmd("status")["pattern"]
    assert r["running"] and r["total"] == 4
    run_for(opened, 10.0)
    written = opened.backend.log.events[:len(expected.edges)]
    name = {f"gpio{pinmap.find(s).gpio}": s for s in expected.idle}
    assert [(name[n], v) for n, v in written] == [(e.signal, e.level) for e in expected.edges]
    assert opened.clock.t - t0 == pytest.approx(0.03, abs=0.015)  # 4 steps at 100 per s, the first at once
    done = opened.cmd("status")["pattern"]
    assert done["running"] is False and done["end"] == "finished" and done["steps"] == 4


def test_lines_go_back_to_safe_after_a_pattern(opened):
    assert start(opened, {"kind": "walking", "signals": list(pinmap.ATT_NETS)})["ok"]
    assert opened.att_levels() == [0] * 6                         # idle of a walking one
    run_for(opened, 10.0)
    assert opened.att_levels() == [1] * 6


def test_loop_runs_until_stopped(opened):
    assert start(opened, {"kind": "square", "signals": ["ATT_V1"]}, rate=1000.0, loop=True)["ok"]
    run_for(opened, 0.1)
    st = opened.cmd("status")["pattern"]
    assert st["running"] and st["loops"] >= 10
    assert st["measured_hz"] == pytest.approx(1000.0, rel=0.2)
    r = opened.cmd("pattern", action="stop")
    assert r["pattern"]["end"] == "stopped" and not opened.bench.pattern_running
    assert opened.att_levels() == [1] * 6


def test_other_commands_are_refused_during_a_pattern(opened):
    start(opened, {"kind": "square", "signals": ["ATT_V1"]}, loop=True)
    for reply in (opened.cmd("atten", db=1.0, confirm=True), opened.cmd("spi", word=5, confirm=True),
                  opened.cmd("pin", pin="P8.8", action="read"), opened.cmd("adc"),
                  start(opened, {"kind": "square", "signals": ["ATT_V2"]})):
        assert not reply["ok"] and "running" in reply["error"]
    assert opened.cmd("status")["ok"]


def test_lease_expiry_stops_a_looping_pattern(opened):
    start(opened, {"kind": "square", "signals": ["ATT_V1"]}, loop=True)
    opened.clock.t += 6.0
    opened.daemon.service_bench()
    assert not opened.bench.active and not opened.bench.pattern_running
    assert opened.att_levels() == [1] * 6


def test_close_during_a_pattern(opened):
    start(opened, {"kind": "square", "signals": ["ATT_V1"]}, loop=True)
    assert opened.cmd("close")["ok"]
    assert opened.att_levels() == [1] * 6 and not opened.bench.pattern_running


def test_hardware_error_during_a_pattern_stops_it_safely(opened):
    start(opened, {"kind": "square", "signals": ["ATT_V1"]}, loop=True)

    def boom(_value):
        raise OSError("gpio went away")

    line = opened.backend.lines[ATT_GPIO[0]]
    original = line.write
    line.write = boom
    opened.bench.service(0.01)
    line.write = original
    assert not opened.bench.pattern_running
    st = opened.cmd("status")
    assert "gpio went away" in st["last_error"] and st["pattern"]["end"] == "error"


def test_spi_pin_pattern_restores_the_bus_and_rewrites_r4(opened):
    before = len(opened.r4_words())
    assert start(opened, {"kind": "walking", "signals": ["SYN_CLK", "SYN_DATA", "SYN_LE"]})["ok"]
    assert ("P9_22", "gpio") in opened.backend.mux_log
    run_for(opened, 10.0)
    assert opened.backend.mux_log[-1] in (("P9_22", "spi_sclk"), ("P9_18", "spi"), ("P9_17", "spi_cs"))
    assert {"P9_22", "P9_18", "P9_17"} == {n for n, m in opened.backend.mux_log if m != "gpio"}
    assert len(opened.r4_words()) == before + 1


def test_expert_pin_pattern_releases_the_line(opened):
    assert start(opened, {"kind": "square", "signals": ["P9.15"]}, expert=True, confirm=False)["ok"]
    run_for(opened, 10.0)
    assert opened.backend.lines[pinmap.PINS["P9.15"].gpio].output is False


def test_adf4351_frame_pattern_goes_through_spi(opened):
    assert start(opened, {"kind": "adf4351_frame", "words": [0x00580005], "repeat": 3})["ok"]
    run_for(opened, 10.0)
    assert opened.sent()[-3:] == [0x00580005] * 3
    assert opened.cmd("status")["pattern"]["steps"] == 3


def test_adf4351_frame_pattern_cannot_enable_outputs(opened):
    r = start(opened, {"kind": "adf4351_frame", "words": [R4_MAIN_ON]})
    assert not r["ok"] and "RF output" in r["error"]


def test_pattern_bad_arguments(opened):
    assert not start(opened, {"kind": "square", "signals": ["ATT_V1"]}, rate=0)["ok"]
    assert not start(opened, {"kind": "nope"})["ok"]
    assert not opened.cmd("pattern", action="pause")["ok"]
    assert not opened.cmd("pattern", action="start")["ok"]        # no spec


def test_stop_without_a_pattern_is_harmless(opened):
    assert opened.cmd("pattern", action="stop")["ok"]


# ---------------------------------------------------------------- Linux backend, without touching any hardware
def test_sysfs_direction_and_level(tmp_path, monkeypatch):
    from sadiy.hal.linux import SysfsGpio

    monkeypatch.setattr(SysfsGpio, "ROOT", tmp_path)
    (tmp_path / "gpio66").mkdir()
    line = SysfsGpio(66, output=True, initial=1)
    assert (tmp_path / "gpio66" / "direction").read_text() == "high"
    line.set_direction(True, 0)
    assert (tmp_path / "gpio66" / "direction").read_text() == "low"
    line.set_direction(False)
    assert (tmp_path / "gpio66" / "direction").read_text() == "in"
    line.write(1)
    assert line.read() == 1


def test_mux_failure_is_an_oserror(monkeypatch):
    import subprocess

    from sadiy.hal.linux import LinuxBackend

    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        raise FileNotFoundError("config-pin")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OSError, match="config-pin P9_22 gpio"):
        LinuxBackend().set_mux("P9_22", "gpio")
    assert calls == [["config-pin", "P9_22", "gpio"]]


def test_linux_i2c_uses_the_device_address(monkeypatch):
    import fcntl
    import os

    from sadiy.hal.linux import LinuxI2c

    r, w = os.pipe()
    seen = {}
    monkeypatch.setattr(os, "open", lambda path, flags: seen.setdefault("path", path) and w)
    monkeypatch.setattr(fcntl, "ioctl", lambda fd, req, arg: seen.update(req=req, addr=arg))
    bus = LinuxI2c(2, 0x48)
    assert seen == {"path": "/dev/i2c-2", "req": LinuxI2c.I2C_SLAVE, "addr": 0x48}
    bus.write(b"\x01")
    assert os.read(r, 1) == b"\x01"
    bus.close()
    os.close(r)
