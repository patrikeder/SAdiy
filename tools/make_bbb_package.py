#!/usr/bin/env python3
"""Build the BBB package from this checkout: dist/sadiy-bbb-<version>-<commit>.tar.gz, its .sha256, and
the unpacked tree in dist/sadiy-bbb.

    python tools/make_bbb_package.py [--out dist]

The name ends in -dirty when a packaged file has uncommitted changes, which are included. The package mirrors
the target file system and leaves out what the BBB does not need: the Qt GUI, tests, KiCad files, photos.
Older archives in the output folder are kept.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "sadiy-bbb"
UI_FILES = {"__init__.py", "cli_client.py", "sweep_client.py"}      # the rest of ui/ needs Qt and runs on the PC

# target path in the package -> source in the checkout
FILES = {
    "README-BBB.md": "deploy/README-BBB.md",
    "install.sh": "deploy/install.sh",
    "sadiy-update.sh": "deploy/sadiy-update.sh",
    "etc/sadiy/local.toml": "deploy/local.toml.example",
    "etc/systemd/system/sweepd.service": "deploy/sweepd.service",
    "etc/systemd/system/sadiy-pinmux.service": "deploy/sadiy-pinmux.service",
    "opt/sadiy/cal/.gitkeep": "cal/.gitkeep",
    "opt/sadiy/config/default.toml": "config/default.toml",
    "opt/sadiy/deploy/sadiy-pinmux.sh": "deploy/sadiy-pinmux.sh",
    "opt/sadiy/docs/architecture.md": "docs/architecture.md",
    "opt/sadiy/docs/bbb-setup.md": "deploy/bbb-setup.md",
    "opt/sadiy/docs/bringup.md": "docs/bringup.md",
    "opt/sadiy/docs/gui.md": "docs/gui.md",
    "opt/sadiy/hw/wiring-bbb.md": "hw/wiring-bbb.md",
    "opt/sadiy/tools/bringup.py": "tools/bringup.py",
    "opt/sadiy/tools/cal_run.py": "tools/cal_run.py",
}


def source_files():
    for path in sorted((ROOT / "src/sadiy").rglob("*.py")):
        rel = path.relative_to(ROOT)
        if path.parent.name != "ui" or path.name in UI_FILES:
            yield f"opt/sadiy/{rel.as_posix()}", rel.as_posix()


def is_executable(target: str) -> bool:
    return target.endswith(".sh") or target.startswith("opt/sadiy/tools/")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def version() -> str:
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def commit_label(sources: list) -> tuple:
    """(short name for the file, full id for the archive header). Dirty only if a packaged file differs."""
    dirty = "-dirty" if git("status", "--porcelain", "--", "pyproject.toml", *sources) else ""
    return git("rev-parse", "--short", "HEAD") + dirty, git("rev-parse", "HEAD") + dirty


def build(out: Path) -> Path:
    files = [*FILES.items(), *source_files()]
    short, full = commit_label([source for _target, source in files])
    stage = out / TOP
    shutil.rmtree(stage, ignore_errors=True)
    for target, source in files:
        dest = stage / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, dest)
        dest.chmod(0o755 if is_executable(target) else 0o644)

    def owned_by_root(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    archive = out / f"{TOP}-{version()}-{short}.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": full}) as tar:
        tar.add(stage, arcname=TOP, filter=owned_by_root)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(f"{archive}.sha256").write_text(f"{digest}  {archive.name}\n")
    return archive


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    archive = build(args.out)
    print(f"wrote {archive} ({archive.stat().st_size / 1024:.0f} kB) and its .sha256")


if __name__ == "__main__":
    main()
