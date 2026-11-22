"""Which build is this? One line at the start of every program, and the same facts in sweepd's `status`.

A copy of the code on a board does not say where it came from, so the scripts that make copies write a small JSON
file `BUILD_INFO` (commit, branch, dirty flag, time): `deploy_to_board.sh`, `tools/make_bbb_package.py` and
`make_bringup_pkg.sh` call `python -m sadiy.buildinfo write <file>`. Without that file the git checkout is asked,
and without both the build is "unknown".

    python -m sadiy.buildinfo                  print the line for this copy
    python -m sadiy.buildinfo write FILE       write BUILD_INFO from the git checkout this module lives in
"""
from __future__ import annotations

import functools
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import __version__

FILE = "BUILD_INFO"
_HERE = Path(__file__).resolve()


def search_paths(module_file: Path) -> tuple:
    """Where BUILD_INFO of the copy that `module_file` (sadiy/buildinfo.py) belongs to can be: next to the sadiy
    folder (bring-up package: bringup-pkg/BUILD_INFO), and, only when that folder is a `src` (checkout, ~/sadiy,
    /opt/sadiy), one level up. A package without the file must not borrow the one of the folder around it."""
    holder = Path(module_file).resolve().parents[1]
    paths = [holder / FILE]
    if holder.name == "src":
        paths.append(holder.parent / FILE)
    return tuple(paths)


SEARCH = search_paths(_HERE)


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def from_git(root: Optional[Path] = None) -> Optional[dict]:
    """Commit, branch and dirty flag (tracked files only) of the checkout at `root`, or None."""
    root = Path(root) if root else _HERE.parents[2]
    commit = _git(root, "rev-parse", "--short", "HEAD")
    if commit is None:
        return None
    return {"commit": commit, "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_git(root, "status", "--porcelain", "--untracked-files=no"))}


@functools.lru_cache(maxsize=None)
def _info() -> tuple:
    d = {"version": __version__, "commit": None, "branch": None, "dirty": None, "built": None, "source": "unknown"}
    for path in SEARCH:
        try:
            d.update(json.loads(path.read_text()))
            d["source"] = FILE
            return tuple(d.items())
        except (OSError, ValueError):
            continue
    g = from_git()
    if g:
        d.update(g)
        d["source"] = "git"
    return tuple(d.items())


def info() -> dict:
    return dict(_info())


def describe(d: Optional[dict] = None) -> str:
    """"sadiy 0.1.0, commit 9b446a2 (main, uncommitted changes), built 2026-11-16 00:12 from BUILD_INFO"."""
    d = d if d is not None else info()
    if not d.get("commit"):
        return f"sadiy {d.get('version', '?')}, build unknown (no {FILE}, not a git checkout)"
    extra = ", ".join(x for x in (d.get("branch"), "uncommitted changes" if d.get("dirty") else None) if x)
    built = f", built {d['built']}" if d.get("built") else ""
    return f"sadiy {d.get('version', '?')}, commit {d['commit']}{f' ({extra})' if extra else ''}{built}"


def differ(a: Optional[dict], b: Optional[dict]) -> bool:
    """True when both name a commit and the commits (or the dirty flags) are not the same build."""
    if not a or not b or not a.get("commit") or not b.get("commit"):
        return False
    return (a["commit"], bool(a.get("dirty"))) != (b["commit"], bool(b.get("dirty")))


def write(path, root: Optional[Path] = None) -> dict:
    g = from_git(root)
    if g is None:
        raise SystemExit("buildinfo: not a git checkout (or git is missing): no build info written")
    d = {"version": __version__, **g, "built": time.strftime("%Y-%m-%d %H:%M")}
    Path(path).write_text(json.dumps(d) + "\n")
    return d


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["write"] and len(argv) == 2:
        print(describe(write(argv[1])))
        return 0
    if argv:
        print(__doc__)
        return 2
    print(describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
