"""Build identity: the line every program prints, BUILD_INFO, the git fallback, sweepd's status, the GUI note."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sadiy import buildinfo, config
from sadiy.server.sweepd import Sweepd, build_sim_engine

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")


@pytest.fixture(autouse=True)
def fresh_cache():
    buildinfo._info.cache_clear()
    yield
    buildinfo._info.cache_clear()


def test_describe_names_commit_branch_dirty_and_time():
    d = {"version": "0.1.0", "commit": "9b446a2", "branch": "main", "dirty": True, "built": "2026-11-16 00:12"}
    assert buildinfo.describe(d) == "sadiy 0.1.0, commit 9b446a2 (main, uncommitted changes), built 2026-11-16 00:12"
    assert buildinfo.describe({"version": "0.1.0", "commit": "abc", "branch": None, "dirty": False}) == "sadiy 0.1.0, commit abc"


def test_unknown_build_says_so():
    assert "build unknown" in buildinfo.describe({"version": "0.1.0", "commit": None})


def test_differ_only_when_both_commits_are_known():
    a = {"commit": "aaa", "dirty": False}
    assert not buildinfo.differ(a, {"commit": "aaa", "dirty": False})
    assert buildinfo.differ(a, {"commit": "bbb", "dirty": False})
    assert buildinfo.differ(a, {"commit": "aaa", "dirty": True})
    assert not buildinfo.differ(a, None) and not buildinfo.differ(a, {"commit": None})


def test_build_info_file_wins_over_git(tmp_path, monkeypatch):
    f = tmp_path / "BUILD_INFO"
    f.write_text(json.dumps({"version": "9.9", "commit": "cafe123", "branch": "linux", "dirty": False, "built": "now"}))
    monkeypatch.setattr(buildinfo, "SEARCH", (f,))
    d = buildinfo.info()
    assert d["commit"] == "cafe123" and d["source"] == "BUILD_INFO" and d["version"] == "9.9"


def test_broken_build_info_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / "BUILD_INFO"
    f.write_text("not json")
    monkeypatch.setattr(buildinfo, "SEARCH", (f,))
    monkeypatch.setattr(buildinfo, "from_git", lambda root=None: None)
    d = buildinfo.info()
    assert d["commit"] is None and d["source"] == "unknown"


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_write_records_the_checkout_and_info_reads_it_back(tmp_path, monkeypatch):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    run = lambda *a: subprocess.run([GIT, "-C", str(tmp_path), *a], check=True, capture_output=True, env=env)
    run("init", "-q", "-b", "work")
    (tmp_path / "x.txt").write_text("1")
    run("add", "x.txt")
    run("commit", "-q", "-m", "one")
    out = tmp_path / "BUILD_INFO"
    d = buildinfo.write(out, root=tmp_path)
    assert d["branch"] == "work" and d["dirty"] is False and len(d["commit"]) >= 7
    (tmp_path / "x.txt").write_text("2")                        # tracked file changed: dirty
    assert buildinfo.from_git(tmp_path)["dirty"] is True
    monkeypatch.setattr(buildinfo, "SEARCH", (out,))
    assert buildinfo.info()["commit"] == d["commit"]


def test_write_refuses_outside_a_checkout(tmp_path):
    with pytest.raises(SystemExit):
        buildinfo.write(tmp_path / "BUILD_INFO", root=tmp_path / "nowhere")


def test_module_prints_the_line():
    out = subprocess.run([sys.executable, "-m", "sadiy.buildinfo"], capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": os.environ.get("PATH", "")}, timeout=30)
    assert out.returncode == 0 and out.stdout.startswith("sadiy ")


def test_sweepd_status_carries_the_build():
    cfg = config.load()
    st = Sweepd(cfg, build_sim_engine(cfg)).apply({"cmd": "status"})
    assert st["build"]["version"] == buildinfo.info()["version"]
    assert "commit" in st["build"]


def test_tools_print_their_build_to_stderr():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "bringup.py"), "pll", "--mhz", "100"], capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": os.environ.get("PATH", "")}, timeout=30)
    assert out.returncode == 0 and out.stderr.startswith("bringup: sadiy ")
    assert "bringup:" not in out.stdout


def test_gui_notes_the_server_build_once_and_warns_on_a_different_one(monkeypatch):
    pytest.importorskip("zmq")
    pg = pytest.importorskip("pyqtgraph")
    pytest.importorskip("pyqtgraph.Qt.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from sadiy.ui.sa_gui import MainWindow

    pg.mkQApp("sadiy-test")
    win = MainWindow()
    try:
        texts = lambda: [e.msg for e in win.dev_log.entries]
        monkeypatch.setattr(buildinfo, "info", lambda: {"version": "0.1.0", "commit": "feed123", "branch": "linux", "dirty": False})
        other = {"version": "0.0.1", "commit": "deadbee", "branch": "main", "dirty": False, "built": "x"}
        win._note_server_build(other)
        win._note_server_build(other)                           # once only
        joined = "\n".join(texts())
        assert joined.count("sweepd build: sadiy 0.0.1, commit deadbee") == 1
        assert "different build" in joined
        win._build_noted = False
        win._note_server_build(None)
        assert "reports no build" in "\n".join(texts())
    finally:
        win.close()


def test_search_paths_depend_on_the_layout(tmp_path):
    deployed = tmp_path / "home" / "sadiy" / "src" / "sadiy" / "buildinfo.py"
    package = tmp_path / "home" / "sadiy" / "bringup-pkg" / "sadiy" / "buildinfo.py"
    for f in (deployed, package):
        f.parent.mkdir(parents=True)
        f.write_text("")
    d = [p.relative_to(tmp_path.resolve()).as_posix() for p in buildinfo.search_paths(deployed)]
    assert d == ["home/sadiy/src/BUILD_INFO", "home/sadiy/BUILD_INFO"]
    p = [x.relative_to(tmp_path.resolve()).as_posix() for x in buildinfo.search_paths(package)]
    assert p == ["home/sadiy/bringup-pkg/BUILD_INFO"]          # never the one of ~/sadiy around it
