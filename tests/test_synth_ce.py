"""ADF4351 CE from Linux: the driver, the sysfs line it sits on, and `tools/bringup.py synth-ce` (BBB and EBAZ)."""
import subprocess
import sys
from pathlib import Path

import pytest

from sadiy.drivers.synth_ce import SynthCe
from sadiy.hal.fake import FakeGpio, PinLog
from sadiy.hal.linux import SysfsGpio, zynq_gpio_base

ROOT = Path(__file__).resolve().parents[1]


def line(external=1):
    ln = FakeGpio("CE", PinLog(), output=False)
    ln.external = external              # the adapter holds CE high while it is released
    return ln


def test_enable_disable_release():
    ce = SynthCe(line(), sleep=lambda _s: None)
    assert ce.status()["requested"] is None and ce.level() == 1 and ce.status()["direction"] == "in"
    assert ce.disable() and ce.level() == 0 and ce.status()["direction"] == "out"
    assert ce.enable() and ce.level() == 1
    assert ce.release() and ce.status()["direction"] == "in" and ce.level() == 1 and ce.requested is None


def test_reprogram_is_flagged_only_after_a_real_power_down():
    waits = []
    ce = SynthCe(line(), settle_s=0.01, sleep=waits.append)
    ce.enable()                                       # was never low
    assert not ce.needs_reprogram and waits == []
    ce.disable()
    ce.enable()
    assert ce.needs_reprogram and waits == [0.01]     # the chip lost its registers


def test_the_engine_owning_ce_ignores_linux():
    owned = [True]
    ln = line()
    ce = SynthCe(ln, owner_active=lambda: owned[0], sleep=lambda _s: None)
    assert ce.status()["owner"] == "engine"
    assert ce.disable() is False and ce.requested == 0
    assert ln.log.directions == [] and ln.output is False       # the line was not touched
    assert ce.release() is False
    owned[0] = False
    assert ce.status()["owner"] == "linux"
    assert ce.enable() is True and ln.output and ln.level == 1


# ---------------------------------------------------------------- sysfs
def test_sysfs_open_without_direction_leaves_the_line_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(SysfsGpio, "ROOT", tmp_path)
    (tmp_path / "gpio5").mkdir()
    (tmp_path / "gpio5" / "direction").write_text("high")
    (tmp_path / "gpio5" / "value").write_text("1")
    seen = SysfsGpio(5, output=None)
    assert (tmp_path / "gpio5" / "direction").read_text() == "high"      # an input open would have released it
    assert seen.direction() == "high" and seen.read() == 1


def test_sysfs_unexported_line_is_exported_by_a_look(tmp_path, monkeypatch):
    monkeypatch.setattr(SysfsGpio, "ROOT", tmp_path)
    SysfsGpio(7, output=None)
    assert (tmp_path / "export").read_text() == "7"


def test_zynq_gpio_base_finds_the_118_line_chip(tmp_path):
    for name, base, n in (("gpiochip0", 512, 118), ("gpiochip1", 700, 8)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "base").write_text(str(base))
        (tmp_path / name / "ngpio").write_text(str(n))
    assert zynq_gpio_base(tmp_path) == 512
    (tmp_path / "gpiochip0" / "ngpio").write_text("32")
    assert zynq_gpio_base(tmp_path) is None
    assert zynq_gpio_base(tmp_path / "nothing") is None


# ---------------------------------------------------------------- the command
def run(platform, action, *extra):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "bringup.py"), "--platform", platform, "synth-ce", action, *extra],
                          capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")}, timeout=30)


@pytest.mark.parametrize("platform,pin", [("bbb", "P9.27"), ("ebaz", "DATA2.13")])
def test_command_dry_run_on_both_boards(platform, pin):
    out = run(platform, "off", "--dry-run")
    assert out.returncode == 0, out.stderr
    assert f"CE ({pin}, {platform})" in out.stdout and "pad 0" in out.stdout and "powered down" in out.stdout
    assert "dry run" in out.stdout
    assert "pad 1" in run(platform, "read", "--dry-run").stdout
    assert "direction in" in run(platform, "release", "--dry-run").stdout


def test_command_names_the_other_board_nowhere():
    assert "DATA2" not in run("bbb", "on", "--dry-run").stdout
    assert "P9" not in run("ebaz", "on", "--dry-run").stdout


def test_pl_owner_is_ebaz_only():
    out = run("bbb", "read", "--dry-run", "--pl-owner")
    assert out.returncode != 0 and "only applies to --platform ebaz" in out.stderr


def test_bringup_finds_sadiy_without_pythonpath():
    """On the boards the checkout is ~/sadiy (src/sadiy next to tools/): no PYTHONPATH should be needed."""
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "bringup.py"), "--platform", "ebaz", "synth-ce", "read", "--dry-run"],
                         capture_output=True, text=True, env={"PATH": "/usr/bin"}, cwd="/", timeout=30)
    assert out.returncode == 0, out.stderr
    assert "CE (DATA2.13, ebaz)" in out.stdout
