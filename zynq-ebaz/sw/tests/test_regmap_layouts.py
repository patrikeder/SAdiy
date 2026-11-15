"""regmap.toml is found in the repository layout and in the bring-up package layout without SADIY_REGMAP_TOML."""
import shutil
import subprocess
import sys
from pathlib import Path

SW = Path(__file__).resolve().parents[1]
ROOT = SW.parents[1]
TOML = ROOT / "zynq-ebaz" / "rtl" / "regmap" / "regmap.toml"
CODE = "import sadiy_ebaz.regmap_toml as m; print(len(m.REGS), m.DEFAULT_PATH)"


def _run(cwd, pythonpath, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(pythonpath)}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-c", CODE], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def test_package_layout_finds_the_file_next_to_the_package(tmp_path):
    """make_bringup_pkg.sh puts regmap.toml beside sadiy_ebaz/: `python pl_bringup.py` without run.sh must work."""
    pkg = tmp_path / "bringup-pkg"
    shutil.copytree(SW / "sadiy_ebaz", pkg / "sadiy_ebaz", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(TOML, pkg / "regmap.toml")
    out = _run(pkg, pkg)
    assert out.returncode == 0, out.stderr
    assert str(pkg / "regmap.toml") in out.stdout


def test_repository_layout_still_works():
    out = _run(ROOT, SW)
    assert out.returncode == 0, out.stderr
    assert str(TOML) in out.stdout


def test_missing_file_names_every_place_that_was_tried(tmp_path):
    pkg = tmp_path / "pkg"
    shutil.copytree(SW / "sadiy_ebaz", pkg / "sadiy_ebaz", ignore=shutil.ignore_patterns("__pycache__"))
    out = _run(pkg, pkg)
    assert out.returncode != 0
    assert "SADIY_REGMAP_TOML" in out.stderr and str(pkg / "regmap.toml") in out.stderr


def test_environment_variable_wins(tmp_path):
    pkg = tmp_path / "pkg"
    shutil.copytree(SW / "sadiy_ebaz", pkg / "sadiy_ebaz", ignore=shutil.ignore_patterns("__pycache__"))
    other = tmp_path / "elsewhere.toml"
    shutil.copy(TOML, other)
    out = _run(pkg, pkg, {"SADIY_REGMAP_TOML": str(other)})
    assert out.returncode == 0, out.stderr
