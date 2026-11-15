"""Bench mode on the EBAZ4205 with Linux owning the pins: EbazPsBackend on a fake /sys tree, and through the bench."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sadiy import config, pinmap_ebaz  # noqa: E402
from sadiy.hal.linux import SysfsGpio  # noqa: E402
from sadiy.server.bench import Bench  # noqa: E402
from sadiy.server.sweepd import Sweepd, hardware_backend  # noqa: E402
from sadiy_ebaz.platforms import ebaz as ebaz_platform  # noqa: E402
from sadiy_ebaz.ps_backend import EbazPsBackend, release_pl_pins  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BASE = 512                                            # sysfs number of the first line of the PS GPIO chip


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    """A /sys/class/gpio with the Zynq chip (118 lines at base 512) and the EMIO lines 54..71 already exported."""
    monkeypatch.setattr(SysfsGpio, "ROOT", tmp_path)
    chip = tmp_path / "gpiochip0"
    chip.mkdir()
    (chip / "base").write_text(str(BASE))
    (chip / "ngpio").write_text("118")
    for line in range(54, 72):
        d = tmp_path / f"gpio{BASE + line}"
        d.mkdir()
        (d / "direction").write_text("in")
        (d / "value").write_text("0")
    return tmp_path


class FakeCore:
    """The register file as far as the pin owner goes: STATUS.pin_owner_act follows CTRL.pin_owner."""

    def __init__(self, owner=1, magic=None):
        self.mem = {REGS["ID"].offset: REGS["ID"].reset_value() if magic is None else magic}
        self.owner = owner
        self.writes = []
        self.closed = False

    def read(self, offset):
        if offset == REGS["STATUS"].offset:
            return REGS["STATUS"].fields["pin_owner_act"].put(self.owner)
        if offset == REGS["CTRL"].offset:
            return REGS["CTRL"].fields["pin_owner"].put(self.owner) | REGS["CTRL"].fields["irq_en"].put(1)
        return self.mem.get(offset, 0)

    def write(self, offset, value):
        self.writes.append((offset, value))
        if offset == REGS["CTRL"].offset:
            self.owner = REGS["CTRL"].fields["pin_owner"].get(value)

    def close(self):
        self.closed = True


# ---------------------------------------------------------------- the backend
def test_gpio_numbers_are_emio_lines_on_the_ps_chip(sysfs):
    b = EbazPsBackend(gpio_root=sysfs)
    line = b.gpio(54, output=True, initial=1)                         # ATT_V1 = EMIO 0 = line 54
    assert (sysfs / f"gpio{BASE + 54}" / "direction").read_text() == "high"
    line.write(0)
    assert (sysfs / f"gpio{BASE + 54}" / "value").read_text() == "0"
    b.gpio(61)                                                        # LD, input
    assert (sysfs / f"gpio{BASE + 61}" / "direction").read_text() == "in"


def test_no_ps_gpio_chip_is_an_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(SysfsGpio, "ROOT", tmp_path)
    with pytest.raises(OSError, match="PS GPIO chip"):
        EbazPsBackend().gpio(54)


def test_no_mux_and_no_ain():
    b = EbazPsBackend()
    assert b.can_mux is False and not b.simulated
    with pytest.raises(OSError, match="no on-chip ADC"):
        b.ain(0)
    with pytest.raises(OSError, match="no pin mux"):
        b.set_mux("P9_22", "gpio")


# ---------------------------------------------------------------- handing the pins to Linux
def test_release_when_the_engine_owns_the_pins():
    core = FakeCore(owner=1)
    note = release_pl_pins(core, sleep=lambda _s: None)
    assert "handed back to Linux" in note and core.owner == 0
    (offset, value), = core.writes
    assert offset == REGS["CTRL"].offset
    assert REGS["CTRL"].fields["abort"].get(value) == 1 and REGS["CTRL"].fields["irq_en"].get(value) == 1   # rw bits kept
    assert REGS["CTRL"].fields["start"].get(value) == 0 and REGS["CTRL"].fields["pin_owner"].get(value) == 0


def test_nothing_to_do_when_linux_already_owns_them():
    core = FakeCore(owner=0)
    assert release_pl_pins(core) == "" and core.writes == []


def test_no_core_no_write():
    core = FakeCore(owner=1, magic=0xDEADBEEF)
    assert "no sweep core" in release_pl_pins(core) and core.writes == []


def test_a_stuck_engine_is_reported():
    class Stuck(FakeCore):
        def write(self, offset, value):
            self.writes.append((offset, value))                      # the owner does not change

    t = [0.0]

    def clock():
        t[0] += 0.2
        return t[0]

    note = release_pl_pins(Stuck(owner=1), sleep=lambda _s: None, clock=clock)
    assert "still owns the pins" in note


def test_prepare_skips_an_unconfigured_pl_and_never_opens_the_registers(tmp_path):
    state = tmp_path / "state"
    state.write_text("unknown\n")
    opened = []
    b = EbazPsBackend(state_path=state, open_regs=lambda: opened.append(1))
    assert "PL is unknown" in b.prepare()[0] and opened == []         # an AXI access to an empty PL stalls the CPU


def test_prepare_releases_and_closes(tmp_path):
    state = tmp_path / "state"
    state.write_text("operating\n")
    core = FakeCore(owner=1)
    notes = EbazPsBackend(state_path=state, open_regs=lambda: core).prepare()
    assert core.owner == 0 and core.closed and "handed back" in notes[0]


def test_prepare_without_devmem_is_a_warning_not_an_error(tmp_path):
    def nope():
        raise PermissionError("/dev/mem")
    notes = EbazPsBackend(state_path=tmp_path / "missing", open_regs=nope).prepare()
    assert "not reachable" in notes[0]


# ---------------------------------------------------------------- through the bench
def rig(sysfs, tmp_path):
    cfg = config.load()
    state = tmp_path / "state"
    state.write_text("operating\n")
    core = FakeCore(owner=1)
    backend = EbazPsBackend(gpio_root=sysfs, state_path=state, open_regs=lambda: core)
    daemon = Sweepd(cfg, None, Bench(backend, cfg, platform="ebaz"))
    daemon.running = False
    return daemon, core, (lambda cmd: json.loads(json.dumps(daemon.apply(json.loads(json.dumps(cmd))))))


def test_bench_opens_on_the_ps_path_and_drives_the_attenuator(sysfs, tmp_path):
    daemon, core, call = rig(sysfs, tmp_path)
    opened = call({"cmd": "bench_open"})
    assert opened["ok"] and opened["platform"] == "ebaz" and opened["limits"]["can_mux"] is False
    assert core.owner == 0 and any("handed back" in w for w in opened["warnings"])
    for n in range(54, 60):                                         # the six PE4302 lines are outputs now, all "in" (31.5 dB)
        d = sysfs / f"gpio{BASE + n}"
        assert d.joinpath("direction").read_text() == "high", n
    tok = opened["token"]
    reply = call({"cmd": "bench_atten", "token": tok, "db": 16.0, "confirm": True})
    assert reply["ok"] and reply["attenuation_db"] == 16.0
    assert (sysfs / f"gpio{BASE + 59}" / "value").read_text() == "1"        # V6 (16 dB) in
    assert (sysfs / f"gpio{BASE + 54}" / "value").read_text() == "0"
    ce = call({"cmd": "bench_pin", "token": tok, "pin": "SYN_CE", "action": "write", "value": 1, "confirm": True})
    assert ce["ok"] and (sysfs / f"gpio{BASE + 60}" / "direction").read_text() == "high"
    adc = call({"cmd": "bench_adc", "token": tok, "source": "ain", "channel": 0})
    assert not adc["ok"] and "no on-chip ADC" in adc["error"]
    call({"cmd": "bench_close", "token": tok})
    assert (sysfs / f"gpio{BASE + 59}" / "value").read_text() == "1"        # back to the safe state, 31.5 dB


def test_hook_builds_the_ps_backend_from_the_config():
    cfg = config.load()
    cfg["platform"] = {"name": "ebaz", "i2c_bus": 1, "base": 0x43C10000}
    b = ebaz_platform.build_bench_backend(cfg)
    assert isinstance(b, EbazPsBackend) and b._i2c_args == (1, 0x48) and b._regs_base == 0x43C10000
    assert isinstance(hardware_backend(config.load(), pinmap_ebaz.EBAZ), EbazPsBackend)


def test_sweepd_bench_only_starts_on_ebaz_hardware_mode(tmp_path):
    """No board here: the daemon must still come up (the backend only touches hardware when bench mode opens)."""
    def free():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p
    cfgfile = tmp_path / "t.toml"
    cfgfile.write_text(f'[server]\npub = "tcp://127.0.0.1:{free()}"\nrep = "tcp://127.0.0.1:{free()}"\n')
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'zynq-ebaz' / 'sw'}"}
    p = subprocess.Popen([sys.executable, "-m", "sadiy.server.sweepd", "--platform", "ebaz", "--bench-only",
                          "--config", str(cfgfile)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.0)
        assert p.poll() is None, p.stdout.read()
    finally:
        p.terminate()
        out = p.communicate(timeout=10)[0]
    assert "bench-only on EBAZ4205" in out and "Traceback" not in out
