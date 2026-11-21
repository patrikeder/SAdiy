"""The day-to-day scripts on the board (~/sadiy: fpga.sh, bench.sh, sweep.sh, ...) and the probe they use.
The board is a temp directory unpacked by deploy_to_board.sh with a stub `ssh`; the PL is a fake /sys state file and a
fake register file (SADIY_NO_SUDO and PROBE_ARGS are the test hooks of common.sh)."""
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

SW = Path(__file__).resolve().parents[1]
ROOT = SW.parents[1]
sys.path.insert(0, str(SW))
from sadiy_ebaz import regmap_toml  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS  # noqa: E402

sys.path.insert(0, str(SW / "tools"))
import ebaz_pl_probe  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "posix", reason="shell scripts")


def fake_pl(tmp_path, state="operating", ident=None, version=None, owner_act=0):
    st = tmp_path / "state"
    st.write_text(state + "\n")
    mem = tmp_path / "mem"
    words = [0] * 0x400
    words[REGS["ID"].offset >> 2] = REGS["ID"].reset_value() if ident is None else ident
    words[REGS["VERSION"].offset >> 2] = regmap_toml.map_version() if version is None else version
    words[REGS["STATUS"].offset >> 2] = REGS["STATUS"].fields["pin_owner_act"].put(owner_act)
    mem.write_bytes(struct.pack(f"<{len(words)}I", *words))
    return st, mem


# ------------------------------------------------------------------ the probe
def run_probe(st, mem):
    lines = []
    rc = ebaz_pl_probe.probe(0, st, str(mem), lines)
    return rc, "\n".join(lines)


def test_probe_ok(tmp_path):
    rc, text = run_probe(*fake_pl(tmp_path))
    assert rc == 0 and "register map" in text and "owned by Linux" in text


def test_probe_reports_the_engine_as_pin_owner(tmp_path):
    rc, text = run_probe(*fake_pl(tmp_path, owner_act=1))
    assert rc == 0 and "owned by the sweep engine" in text


def test_probe_map_differs_from_the_software(tmp_path):
    rc, text = run_probe(*fake_pl(tmp_path, version=0x00010000))
    assert rc == 1 and "register map 1.0" in text and "--force" in text


def test_probe_wrong_core(tmp_path):
    rc, text = run_probe(*fake_pl(tmp_path, ident=0x12345678))
    assert rc == 2 and "no sweep core" in text


def test_probe_pl_not_configured_never_reads_the_registers(tmp_path):
    st, _mem = fake_pl(tmp_path, state="unknown")
    rc, text = run_probe(st, tmp_path / "does-not-exist")          # a read would raise: it must not get that far
    assert rc == 3 and "no bitstream" in text


def test_probe_without_fpga_manager_and_without_registers(tmp_path):
    assert run_probe(tmp_path / "missing", tmp_path / "mem")[0] == 3
    st, _ = fake_pl(tmp_path)
    assert run_probe(st, tmp_path / "no-such-file")[0] == 4


# ------------------------------------------------------------------ deploy and scripts
@pytest.fixture
def board(tmp_path):
    """deploy_to_board.sh into tmp_path/home/sadiy through a stub ssh."""
    home = tmp_path / "home"
    home.mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "ssh").write_text(f'#!/bin/sh\ncd "{home}" && mkdir -p sadiy && cd sadiy && tar -xzf - && ls >/dev/null\n')
    (stub / "ssh").chmod(0o755)
    bit = tmp_path / "ebaz_sadiy.bit.bin"
    bit.write_bytes(b"\x00bitstream")
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}", "BITSTREAM": str(bit)}
    out = subprocess.run(["sh", str(SW / "deploy" / "deploy_to_board.sh"), "1.2.3.4"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return home / "sadiy", out.stdout


def sh(board_dir, script, tmp_path, *args, **plenv):
    st, mem = plenv.pop("pl", (tmp_path / "state", tmp_path / "mem"))
    env = {"PATH": os.environ["PATH"], "HOME": str(board_dir.parent), "SADIY_NO_SUDO": "1",
           "PROBE_ARGS": f"--base 0 --state {st} --mem {mem}",
           "SADIY_PROC_PATTERN": "sadiy-test-no-such-process", **plenv}      # a real sweepd on this machine is none of our business
    return subprocess.run(["sh", str(board_dir / script), *args], cwd=board_dir, env=env, capture_output=True,
                          text=True, timeout=60)


def test_deploy_puts_scripts_and_bitstream_in_the_base_directory(board):
    base, out = board
    for name in ("fpga.sh", "bench.sh", "sweep.sh", "sim.sh", "status.sh", "stop.sh", "selftest.sh", "common.sh"):
        assert (base / name).is_file(), name
    for name in ("fpga.sh", "bench.sh", "sweep.sh", "sim.sh", "status.sh", "stop.sh", "selftest.sh"):
        assert os.access(base / name, os.X_OK), name
    assert (base / "fpga" / "ebaz_sadiy.bit.bin").read_bytes() == b"\x00bitstream"
    assert (base / "fpga" / "sadiy_pl_load.sh").is_file()
    assert (base / "zynq-ebaz" / "sw" / "tools" / "ebaz_pl_probe.py").is_file()
    assert "bitstream:" in out and "./status.sh" in out


def test_fpga_sh_does_nothing_when_the_right_bitstream_is_in(board, tmp_path):
    base, _ = board
    out = sh(base, "fpga.sh", tmp_path, pl=fake_pl(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "PL state: operating" in out.stdout and "loading" not in out.stdout
    assert out.stdout.startswith("software: sadiy ")


def test_fpga_sh_status_never_loads(board, tmp_path):
    base, _ = board
    out = sh(base, "fpga.sh", tmp_path, "status", pl=fake_pl(tmp_path, state="unknown"))
    assert out.returncode == 3 and "loading" not in out.stdout and "./fpga.sh" in out.stdout


def test_fpga_sh_tries_to_load_when_the_pl_is_empty(board, tmp_path):
    base, _ = board
    out = sh(base, "fpga.sh", tmp_path, pl=fake_pl(tmp_path, state="unknown"))
    # no fpga_manager on this PC: the loader stops before it writes anything
    assert out.returncode != 0 and "loading" in out.stdout and "fpga_manager" in out.stderr + out.stdout


def test_fpga_sh_without_a_bitstream_says_how_to_deploy_one(board, tmp_path):
    base, _ = board
    (base / "fpga" / "ebaz_sadiy.bit.bin").unlink()
    out = sh(base, "fpga.sh", tmp_path, "--force", pl=fake_pl(tmp_path))
    assert out.returncode != 0 and "no bitstream" in out.stderr and "BITSTREAM=" in out.stderr


def test_bench_and_sweep_stop_before_sweepd_when_the_pl_is_not_ready(board, tmp_path):
    base, _ = board
    (base / "fpga" / "ebaz_sadiy.bit.bin").unlink()
    for script in ("bench.sh", "sweep.sh"):
        out = sh(base, script, tmp_path, pl=fake_pl(tmp_path, state="unknown"))
        assert out.returncode != 0 and "starting sweepd" not in out.stdout, script


def test_selftest_sh_stops_when_the_pl_is_not_ready(board, tmp_path):
    base, _ = board
    (base / "fpga" / "ebaz_sadiy.bit.bin").unlink()
    out = sh(base, "selftest.sh", tmp_path, pl=fake_pl(tmp_path, state="unknown"))
    assert out.returncode == 2 and "PASS" not in out.stdout


def test_selftest_sh_refuses_while_sweepd_runs(board, tmp_path):
    base, _ = board
    token = "sadiy-selftest-token-4712"
    py = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep(30)  # {token}"])
    try:
        out = sh(base, "selftest.sh", tmp_path, pl=fake_pl(tmp_path), SADIY_PROC_PATTERN=token)
        assert out.returncode != 0 and "sweepd is already running" in out.stderr and "PASS" not in out.stdout
    finally:
        py.kill()
        py.wait()


def test_status_sh_is_read_only_and_reports(board, tmp_path):
    base, _ = board
    out = sh(base, "status.sh", tmp_path, pl=fake_pl(tmp_path))
    assert out.returncode == 0, out.stderr
    for part in ("--- PL", "--- devices", "--- sweepd", "not running", "--- network"):
        assert part in out.stdout, part


def test_stop_sh_with_nothing_running(board, tmp_path):
    base, _ = board
    out = sh(base, "stop.sh", tmp_path)
    assert out.returncode == 0 and "not running" in out.stdout


def test_sim_sh_runs_a_simulated_sweepd(board, tmp_path):
    base, _ = board
    cfg = tmp_path / "ports.toml"                                # other ports than a real sweepd on this machine
    cfg.write_text('[server]\npub = "tcp://127.0.0.1:25556"\nrep = "tcp://127.0.0.1:25557"\n')
    out = sh(base, "sim.sh", tmp_path, "--sweeps", "2", SADIY_CONFIG=str(cfg))
    assert out.returncode == 0, out.stderr
    assert "simulated chain on EBAZ4205" in out.stdout + out.stderr


def test_pc_gui_script_needs_an_argument():
    out = subprocess.run(["sh", str(SW / "pc" / "gui.sh")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 2 and "usage" in out.stderr


def test_process_check_matches_python_and_sudo_never_a_shell_that_mentions_it(board, tmp_path):
    """stop.sh kills what it finds: it must not find a shell or editor whose command line merely contains the name."""
    base, _ = board
    token = "sadiy-test-token-4711"
    shell = subprocess.Popen(["sh", "-c", f"sleep 30 # {token}"])
    py = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep(30)  # {token}"])
    try:
        out = sh(base, "status.sh", tmp_path, pl=fake_pl(tmp_path), SADIY_PROC_PATTERN=token)
        assert f"pid {py.pid}" in out.stdout and f"pid {shell.pid}" not in out.stdout
        out = sh(base, "stop.sh", tmp_path, SADIY_PROC_PATTERN=token)
        assert f"stopped sweepd pid {py.pid}" in out.stdout
        py.wait(timeout=10)
        assert shell.poll() is None                      # the shell was left alone
    finally:
        for p in (shell, py):
            if p.poll() is None:
                p.kill()
            p.wait()


def test_status_lists_the_copies_of_the_software_and_marks_the_one_in_use(board, tmp_path):
    """A bring-up package with its own old copy of sadiy was the surprise on the board: status.sh must show it."""
    base, _ = board
    old = base / "bringup-pkg" / "sadiy" / "server"
    old.mkdir(parents=True)
    (old / "sweepd.py").write_text("# old copy\n")
    out = sh(base, "status.sh", tmp_path, pl=fake_pl(tmp_path))
    lines = [l for l in out.stdout.splitlines() if l.endswith(("BUILD_INFO (made before build info, or copied by hand)",)) or " commit " in l]
    assert any(l.startswith("* ") and str(base / "src") in l for l in out.stdout.splitlines()), out.stdout
    assert any(l.startswith("  ") and str(base / "bringup-pkg") in l and "no BUILD_INFO" in l for l in out.stdout.splitlines()), out.stdout


def test_readme_is_deployed_and_names_the_namespace_package_trap(board):
    base, _ = board
    text = (base / "README.txt").read_text()
    assert "./bench.sh" in text and "env.sh" in text and "No module named 'sadiy.server'" in text


def test_python_module_run_fails_the_way_the_user_saw_without_pythonpath(board, tmp_path):
    """Documented trap: from the folder that holds ~/sadiy, without PYTHONPATH, `python3 -m sadiy.server.sweepd` finds
    the plain folder ~/sadiy and says No module named 'sadiy.server'. The scripts set PYTHONPATH themselves."""
    base, _ = board
    out = subprocess.run([sys.executable, "-S", "-m", "sadiy.server.sweepd", "--help"], cwd=base.parent,
                         env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=30)
    assert out.returncode != 0 and "No module named 'sadiy.server'" in out.stderr
    ok = subprocess.run(["sh", str(base / "status.sh")], cwd=tmp_path, env={"PATH": os.environ["PATH"], "HOME": str(base.parent),
                        "SADIY_NO_SUDO": "1", "SADIY_PROC_PATTERN": "sadiy-test-no-such-process",
                        "PROBE_ARGS": f"--base 0 --state {tmp_path}/s --mem {tmp_path}/m"}, capture_output=True, text=True, timeout=30)
    assert ok.returncode == 0 and ok.stdout.startswith("software: sadiy ")       # from another directory, by full path
