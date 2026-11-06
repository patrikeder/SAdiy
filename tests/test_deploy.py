"""The deploy folder has to agree with the code. Nothing here touches hardware: config-pin is a stub."""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from sadiy import config, pinmap

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SCRIPT = DEPLOY / "sadiy-pinmux.sh"


def stub(tmp_path, exit_code=0):
    log = tmp_path / "calls"
    tool = tmp_path / "config-pin"
    tool.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit {exit_code}\n')
    tool.chmod(0o755)
    return log


def run_script(path_dir):
    env = dict(os.environ, PATH=str(path_dir))
    return subprocess.run(["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True)


def expected_modes():
    return {
        (p.config_pin_name, p.mux or "gpio")
        for p in pinmap.PINS.values() if p.access in (pinmap.WIRED, pinmap.INPUT_ONLY)
    }


def test_pinmux_script_matches_the_pin_map():
    modes = re.findall(r"^set_mode (\S+) (\S+)$", SCRIPT.read_text(), re.M)
    assert len(modes) == len(set(modes))
    assert set(modes) == expected_modes()


def test_pinmux_script_is_executable():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_pinmux_script_sets_every_mode(tmp_path):
    log = stub(tmp_path)
    assert run_script(tmp_path).returncode == 0
    calls = {tuple(line.split()) for line in log.read_text().splitlines()}
    assert calls == expected_modes()


def test_pinmux_script_tries_every_pin_and_reports_a_failure(tmp_path):
    log = stub(tmp_path, exit_code=1)
    result = run_script(tmp_path)
    assert result.returncode == 1 and "P8_12" in result.stderr
    assert len(log.read_text().splitlines()) == len(expected_modes())


def test_pinmux_script_says_when_config_pin_is_missing(tmp_path):
    result = run_script(tmp_path)
    assert result.returncode == 1 and "not found" in result.stderr


def test_service_uses_bench_only_until_the_hardware_engine_exists():
    from sadiy.server.sweepd import build_hw_engine

    with pytest.raises(NotImplementedError):
        build_hw_engine({})
    text = (DEPLOY / "sweepd.service").read_text()
    assert re.search(r"^ExecStart=.*--bench-only", text, re.M)
    assert re.search(r"^Wants=sadiy-pinmux\.service", text, re.M)


def test_pinmux_service_runs_the_script():
    text = (DEPLOY / "sadiy-pinmux.service").read_text()
    assert "ExecStart=/opt/sadiy/deploy/sadiy-pinmux.sh\n" in text


def test_config_example_loads_over_the_defaults():
    cfg = config.load(DEPLOY / "local.toml.example")
    assert cfg["bench"]["spi_bus"] == 1 and cfg["bench"]["i2c_bus"] == 2
    assert cfg["bench"]["lease_s"] == 5.0                  # the rest of the section stays
    assert cfg["server"]["rep"] == "tcp://*:5557"          # the [server] example is commented out


def test_setup_notes_name_files_that_exist():
    text = (DEPLOY / "bbb-setup.md").read_text()
    for name in set(re.findall(r"/opt/sadiy/deploy/([\w.-]+)", text)):
        assert (DEPLOY / name).exists(), name
