"""The deploy folder has to agree with the code. Nothing here touches hardware: config-pin is a stub."""
import os
import re
import stat
import subprocess
import sys
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


# ---------------------------------------------------------------- sadiy-update.sh
UPDATE = DEPLOY / "sadiy-update.sh"
REPO = DEPLOY.parent


class UpdateRig:
    """An old install, an archive and stubs for systemctl, pgrep and config-pin, all under tmp_path.

    The stubs come first on PATH, so the script can not reach this machine's real services."""

    def __init__(self, tmp, package, active="yes", start_ok=True, stays_up=True, by_hand=False):
        self.tmp = tmp
        self.package = package
        self.dir = tmp / "opt" / "sadiy"
        self.old = tmp / "opt" / "sadiy.old"
        self.units = tmp / "units"
        self.bin = tmp / "bin"
        self.calls = tmp / "calls"
        self.state = tmp / "active"
        for d in (self.dir / "cal", self.units, self.bin):
            d.mkdir(parents=True)
        (self.dir / "marker").write_text("old install")
        (self.dir / "cal" / "gain.json").write_text("measured on this board")
        self.config = tmp / "local.toml"
        self.config.write_text("[bench]\ni2c_bus = 2\n")
        self.state.write_text(active)
        self._stub("systemctl", f'''
echo "systemctl $*" >> "{self.calls}"
case "$1" in
  is-active) [ "$(cat "{self.state}")" = yes ]; exit $? ;;
  stop) echo no > "{self.state}" ;;
  start) {"" if start_ok else "exit 1"}
         echo {"yes" if stays_up else "no"} > "{self.state}" ;;
esac
exit 0''')
        self._stub("pgrep", f'exit {0 if by_hand else 1}')
        self._stub("config-pin", f'echo "config-pin $*" >> "{self.calls}"')

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def archive(self, name="new.tar.gz", commit="abc1234", extra=()):
        """The real package with its commit id replaced and extra members added at the end."""
        import io
        import tarfile

        path = self.tmp / name
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}) as out, \
                tarfile.open(self.package) as base:
            for member in base.getmembers():
                out.addfile(member, base.extractfile(member) if member.isfile() else None)
            for member, text in extra:
                info = tarfile.TarInfo(member)
                info.size = len(text)
                out.addfile(info, io.BytesIO(text.encode()))
        return path

    def run(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", SADIY_DIR=str(self.dir),
                   SADIY_CONFIG=str(self.config), SADIY_UNIT_DIR=str(self.units), SADIY_PYTHON=sys.executable,
                   SADIY_SETTLE_S="0")
        return subprocess.run(["/bin/sh", str(UPDATE), *map(str, args)], env=env, capture_output=True, text=True)

    def log(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def untouched(self):
        return (self.dir / "marker").exists() and not self.old.exists() and not (self.tmp / "opt" / "sadiy.new").exists()


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    """The real package, built once by the real builder from this checkout."""
    out = tmp_path_factory.mktemp("dist")
    subprocess.run([sys.executable, str(REPO / "tools/make_bbb_package.py"), "--out", str(out)], check=True, capture_output=True)
    return next(out.glob("sadiy-bbb-*.tar.gz"))


@pytest.fixture
def make_rig(tmp_path, package):
    return lambda **kw: UpdateRig(tmp_path, package, **kw)


@pytest.fixture
def rig(make_rig):
    return make_rig()


def test_update_script_is_executable():
    assert UPDATE.stat().st_mode & stat.S_IXUSR


def test_update_swaps_the_code_and_restarts_the_service(rig):
    r = rig.run(rig.archive())
    assert r.returncode == 0, r.stderr
    assert (rig.dir / "src/sadiy/server/sweepd.py").exists() and not (rig.dir / "marker").exists()
    assert (rig.old / "marker").read_text() == "old install"
    assert (rig.dir / ".installed-commit").read_text().strip() == "abc1234"
    assert "abc1234" in r.stdout
    log = rig.log()
    assert log.index("systemctl stop sweepd") < log.index("systemctl start sweepd")
    assert "config-pin P9_22 spi_sclk" in log                       # pin modes set again, with sweepd stopped
    assert log.index("systemctl stop sweepd") < log.index("config-pin P9_22 spi_sclk") < log.index("systemctl start sweepd")
    assert rig.config.read_text() == "[bench]\ni2c_bus = 2\n"       # local config untouched


def test_update_keeps_one_previous_copy(rig):
    assert rig.run(rig.archive(commit="first")).returncode == 0
    assert rig.run(rig.archive(commit="second")).returncode == 0
    assert (rig.old / ".installed-commit").read_text().strip() == "first"
    assert not (rig.old / "marker").exists()


def test_update_without_a_service_tells_how_to_start(make_rig):
    rig = make_rig(active="no")
    r = rig.run(rig.archive())
    assert r.returncode == 0, r.stderr
    assert "--bench-only" in r.stdout
    assert not [c for c in rig.log() if "start" in c or "stop" in c]


def test_update_refuses_while_sweepd_runs_by_hand(make_rig):
    rig = make_rig(active="no", by_hand=True)
    r = rig.run(rig.archive())
    assert r.returncode == 1 and "by hand" in r.stderr and rig.untouched()


@pytest.mark.parametrize("make, message", [
    (lambda rig: rig.tmp / "missing.tar.gz", "no such file"),
    (lambda rig: (rig.tmp / "x.tar.gz").write_text("not a tar") and rig.tmp / "x.tar.gz", "not a readable"),
    (lambda rig: rig.archive(extra=[("evil/file", "x")]), "outside sadiy-bbb/"),
    (lambda rig: rig.archive(extra=[("sadiy-bbb/../../file", "x")]), "with .."),
])
def test_update_refuses_a_bad_archive_and_changes_nothing(rig, make, message):
    r = rig.run(make(rig))
    assert r.returncode == 1 and message in r.stderr and rig.untouched()
    assert "systemctl stop sweepd" not in rig.log()


def test_update_refuses_an_archive_of_something_else(rig):
    import tarfile

    path = rig.tmp / "other.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        tar.add(REPO / "README.md", arcname="sadiy-bbb/README.md")
    r = rig.run(path)
    assert r.returncode == 1 and "not a SAdiy package" in r.stderr and rig.untouched()


def test_update_refuses_code_that_does_not_load_before_stopping_anything(rig):
    path = rig.archive(extra=[("sadiy-bbb/opt/sadiy/src/sadiy/pinmap.py", "this is not python")])
    r = rig.run(path)
    assert r.returncode == 1 and "does not load" in r.stderr and rig.untouched()
    assert "systemctl stop sweepd" not in rig.log()


def test_update_refuses_a_bad_local_config_before_stopping_anything(rig):
    rig.config.write_text("this is not toml")
    r = rig.run(rig.archive())
    assert r.returncode == 1 and "does not load" in r.stderr and rig.untouched()
    assert "systemctl stop sweepd" not in rig.log()


def test_update_needs_write_access(rig):
    parent = rig.dir.parent
    parent.chmod(0o555)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("running as root")
        r = rig.run(rig.archive())
        assert r.returncode == 1 and "sudo" in r.stderr
    finally:
        parent.chmod(0o755)


def test_update_needs_an_existing_installation(rig):
    import shutil

    shutil.rmtree(rig.dir)
    r = rig.run(rig.archive())
    assert r.returncode == 1 and "first install" in r.stderr


def test_update_needs_exactly_one_argument(rig):
    assert "usage" in rig.run().stderr


@pytest.mark.parametrize("kw", [{"start_ok": False}, {"stays_up": False}])
def test_update_rolls_back_when_the_service_does_not_come_back(make_rig, kw):
    rig = make_rig(**kw)
    (rig.units / "sweepd.service").write_text("old unit")
    r = rig.run(rig.archive())
    assert r.returncode == 1 and "previous installation is back" in r.stderr
    assert (rig.dir / "marker").read_text() == "old install" and not rig.old.exists()
    assert (rig.units / "sweepd.service").read_text() == "old unit"
    assert rig.log().count("systemctl start sweepd") == 2
    assert (rig.dir / "cal/gain.json").read_text() == "measured on this board"


def test_update_replaces_installed_units_only_and_keeps_the_previous_one(rig):
    (rig.units / "sweepd.service").write_text("old unit")
    r = rig.run(rig.archive())
    assert r.returncode == 0, r.stderr
    assert (rig.units / "sweepd.service").read_text() == (DEPLOY / "sweepd.service").read_text()
    assert (rig.old / ".units/sweepd.service").read_text() == "old unit"
    assert not (rig.units / "sadiy-pinmux.service").exists()        # not installed: a decision for the notes
    assert "systemctl daemon-reload" in rig.log()


def test_update_leaves_identical_units_alone(rig):
    (rig.units / "sweepd.service").write_text((DEPLOY / "sweepd.service").read_text())
    assert rig.run(rig.archive()).returncode == 0
    assert "systemctl daemon-reload" not in rig.log()


def test_update_only_warns_when_pin_modes_fail(make_rig):
    rig = make_rig()
    rig._stub("config-pin", "exit 1")
    r = rig.run(rig.archive())
    assert r.returncode == 0 and "pin modes" in r.stdout
    assert (rig.dir / "src").exists()


def test_update_keeps_the_calibration_data(rig):
    assert rig.run(rig.archive()).returncode == 0
    assert (rig.dir / "cal/gain.json").read_text() == "measured on this board"
    assert (rig.old / "cal/gain.json").read_text() == "measured on this board"


def test_update_creates_a_missing_local_config_and_keeps_an_existing_one(rig):
    rig.config.unlink()
    assert rig.run(rig.archive()).returncode == 0
    assert "spi_bus" in rig.config.read_text()
    rig.config.write_text("[bench]\ni2c_bus = 1\n")
    assert rig.run(rig.archive()).returncode == 0
    assert rig.config.read_text() == "[bench]\ni2c_bus = 1\n"


def test_updated_install_runs_from_its_new_place(rig):
    assert rig.run(rig.archive()).returncode == 0
    env = dict(os.environ, PYTHONPATH=str(rig.dir / "src"))
    r = subprocess.run([sys.executable, str(rig.dir / "tools/bringup.py"), "pll", "--mhz", "110.7"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "PllPlan" in r.stdout
    assert os.access(rig.dir / "deploy/sadiy-pinmux.sh", os.X_OK)


def test_documented_bootstrap_extracts_only_the_script(rig):
    target = rig.tmp / "boot"
    target.mkdir()
    r = subprocess.run(["tar", "-xzf", rig.archive(), "-C", target, "sadiy-bbb/sadiy-update.sh"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert [p.name for p in target.rglob("*") if p.is_file()] == ["sadiy-update.sh"]
    assert "sadiy-bbb/sadiy-update.sh" in (DEPLOY / "bbb-setup.md").read_text()


# ---------------------------------------------------------------- the package
def members(package):
    import tarfile

    with tarfile.open(package) as tar:
        return {m.name: m for m in tar.getmembers()}


def test_package_layout_and_owner(package):
    found = members(package)
    for name in ("install.sh", "sadiy-update.sh", "README-BBB.md", "etc/sadiy/local.toml",
                 "etc/systemd/system/sweepd.service", "etc/systemd/system/sadiy-pinmux.service",
                 "opt/sadiy/cal/.gitkeep", "opt/sadiy/config/default.toml", "opt/sadiy/deploy/sadiy-pinmux.sh",
                 "opt/sadiy/docs/bbb-setup.md", "opt/sadiy/src/sadiy/pinmap.py", "opt/sadiy/src/sadiy/server/bench.py",
                 "opt/sadiy/tools/bringup.py"):
        assert f"sadiy-bbb/{name}" in found, name
    assert all(m.uid == 0 and m.gid == 0 for m in found.values())


def test_package_has_no_qt_code_tests_or_caches(package):
    names = list(members(package))
    assert not [n for n in names if "__pycache__" in n or "/tests/" in n or n.endswith(".pyc")]
    assert sorted(n.rsplit("/", 1)[1] for n in names if "/src/sadiy/ui/" in n) == ["__init__.py", "cli_client.py", "sweep_client.py"]
    assert not [n for n in names if "bench_tab" in n or "sa_gui" in n]


def test_package_scripts_are_executable(package):
    found = members(package)
    for name in ("install.sh", "sadiy-update.sh", "opt/sadiy/deploy/sadiy-pinmux.sh", "opt/sadiy/tools/bringup.py"):
        assert found[f"sadiy-bbb/{name}"].mode & 0o111 == 0o111, name
    assert found["sadiy-bbb/README-BBB.md"].mode & 0o111 == 0


def test_package_daemon_imports_without_qt(package, tmp_path):
    import tarfile

    with tarfile.open(package) as tar:
        tar.extractall(tmp_path, filter="data")
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "sadiy-bbb/opt/sadiy/src"))
    code = "import sys, sadiy.server.sweepd; sys.exit(any(m.startswith(('PyQt', 'pyqtgraph')) for m in sys.modules))"
    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0


def test_package_checksum_file_verifies(package):
    r = subprocess.run(["sha256sum", "-c", package.name + ".sha256"], cwd=package.parent, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_package_name_and_header_carry_the_commit(package):
    import tarfile

    short = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert short in package.name
    with tarfile.open(package) as tar:
        assert tar.pax_headers["comment"].startswith(short)


def test_install_script_stages_the_package(package, tmp_path):
    import tarfile

    with tarfile.open(package) as tar:
        tar.extractall(tmp_path, filter="data")
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "python3").symlink_to(sys.executable)
    dest = tmp_path / "stage"
    env = dict(os.environ, DESTDIR=str(dest), PATH=f"{tools}{os.pathsep}{os.environ['PATH']}")
    r = subprocess.run(["/bin/sh", str(tmp_path / "sadiy-bbb/install.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (dest / "etc/systemd/system/sadiy-pinmux.service").exists()
    assert os.access(dest / "opt/sadiy/deploy/sadiy-pinmux.sh", os.X_OK)
    assert (dest / "etc/sadiy/local.toml").exists()
