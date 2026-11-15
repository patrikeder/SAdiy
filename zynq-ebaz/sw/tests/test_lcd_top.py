"""ebaz_lcd_top.sh: the compact frame from `top -b` (old KiB and new MiB layouts) and the inittab edit, no board needed."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "ebaz_lcd_top.sh"

TOP_KIB = """top - 16:28:57 up 8 min,  2 users,  load average: 0.00, 0.04, 0.05
Tasks:  71 total,   1 running,  70 sleeping,   0 stopped,   0 zombie
%Cpu(s):  1.0 us,  2.0 sy,  0.0 ni, 96.9 id,  0.0 wa,  0.0 hi,  0.1 si,  0.0 st
KiB Mem :   248528 total,   201224 free,    27000 used,    20304 buff/cache
KiB Swap:        0 total,        0 free,        0 used.   215000 avail Mem

  PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
  900 root      20   0   12000   3000   2000 S  99.0  1.2   0:00.10 averages-only
    1 root      20   0    4000   1000    800 S   0.0  0.4   0:01.00 init
top - 16:29:00 up 8 min,  2 users,  load average: 0.10, 0.05, 0.05
Tasks:  71 total,   2 running,  69 sleeping,   0 stopped,   0 zombie
%Cpu(s): 12.5 us,  3.0 sy,  0.0 ni, 84.5 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
KiB Mem :   248528 total,   200000 free,    28224 used,    20304 buff/cache
KiB Swap:        0 total,        0 free,        0 used.   215000 avail Mem

  PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
 1234 petalinux 20   0   30000   9000   4000 R  12.5  3.6   0:01.20 python3
    1 root      20   0    4000   1000    800 S   0.3  0.4   0:01.00 init
  222 root      20   0    2000    500    400 S   0.0  0.2   0:00.01 a-very-long-command-name
"""

TOP_MIB = TOP_KIB.replace("KiB Mem :   248528 total,   201224 free,    27000 used", "MiB Mem :    242.7 total,    196.5 free,     26.4 used").replace(
    "KiB Mem :   248528 total,   200000 free,    28224 used", "MiB Mem :    242.7 total,    195.3 free,     27.6 used")


@pytest.fixture
def fake_top(tmp_path):
    def make(text):
        data = tmp_path / "top.out"
        data.write_text(text)
        prog = tmp_path / "faketop"
        prog.write_text(f"#!/bin/sh\ncat {data}\n")
        prog.chmod(prog.stat().st_mode | stat.S_IEXEC)
        return str(prog)
    return make


def frame(top, size="30,15"):
    env = {**os.environ, "TOP": top, "LCD_TOP_SIZE": size, "LCD_TOP_DELAY": "1"}
    out = subprocess.run(["sh", str(SCRIPT), "frame"], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.rstrip("\n").split("\n")


@pytest.mark.parametrize("layout", [TOP_KIB, TOP_MIB], ids=["kib", "mib"])
def test_frame_is_compact_and_uses_the_last_frame(fake_top, layout):
    lines = frame(fake_top(layout))
    assert lines[0] == "16:29:00 ld 0.10 0.05 0.05"
    assert lines[1] == "Tasks 71 run 2"
    assert lines[2] == "CPU us 12.5 sy 3.0 id 84.5"
    assert lines[3] == "Mem 27/242M"                                         # used / total in MB, last frame
    assert lines[4] == "  PID  %CPU %MEM COMMAND"
    assert lines[5].split() == ["1234", "12.5", "3.6", "python3"]
    assert "averages-only" not in "\n".join(lines)                           # the first top frame is not shown


def test_nothing_is_wider_or_taller_than_the_console(fake_top):
    for size, (cols, rows) in (("30,15", (30, 15)), ("30,8", (30, 8)), ("40,30", (40, 30))):
        lines = frame(fake_top(TOP_KIB), size)
        assert len(lines) <= rows and all(len(x) <= cols for x in lines), (size, lines)
    assert len(frame(fake_top(TOP_KIB), "30,8")) == 8                       # header (5) + 3 processes, no more
    long_name = [x for x in frame(fake_top(TOP_KIB)) if "a-very" in x]
    assert long_name and len(long_name[0]) == 30                            # a long command name is cut to the width


def test_a_top_without_output_gives_no_frame(fake_top):
    env = {**os.environ, "TOP": fake_top(""), "LCD_TOP_SIZE": "30,15", "LCD_TOP_DELAY": "1"}
    out = subprocess.run(["sh", str(SCRIPT), "frame"], capture_output=True, text=True, env=env, timeout=30)
    assert out.stdout.strip() == ""


# ---------------------------------------------------------------- install / remove on a copy of inittab
INITTAB = """id:5:initdefault:
si::sysinit:/etc/init.d/rcS
PS0:12345:respawn:/usr/sbin/ttyrun ttyPS0 /bin/start_getty 115200 ttyPS0 vt102
1:12345:respawn:/sbin/getty 38400 tty1
"""


def run(tmp_path, action):
    env = {**os.environ, "SKIP_SYSTEM": "1", "INITTAB": str(tmp_path / "inittab"), "DEST": str(tmp_path / "bin" / "ebaz_lcd_top"),
           "LCD_TOP_SIZE": "30,15"}
    return subprocess.run(["sh", str(SCRIPT), action], capture_output=True, text=True, env=env, timeout=30)


def test_install_replaces_only_the_tty1_getty(tmp_path):
    (tmp_path / "inittab").write_text(INITTAB)
    out = run(tmp_path, "install")
    assert out.returncode == 0, out.stderr
    new = (tmp_path / "inittab").read_text().splitlines()
    assert new[:3] == INITTAB.splitlines()[:3]                                   # serial console login untouched
    assert new[3] == f"1:12345:respawn:{tmp_path}/bin/ebaz_lcd_top run"
    assert (tmp_path / "inittab.sadiy-orig").read_text() == INITTAB
    assert os.access(tmp_path / "bin" / "ebaz_lcd_top", os.X_OK)


def test_install_twice_and_remove(tmp_path):
    (tmp_path / "inittab").write_text(INITTAB)
    run(tmp_path, "install")
    again = run(tmp_path, "install")
    assert "already installed" in again.stdout
    assert (tmp_path / "inittab.sadiy-orig").read_text() == INITTAB             # the backup is the first original
    assert "top on tty1" in run(tmp_path, "status").stdout
    out = run(tmp_path, "remove")
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "inittab").read_text() == INITTAB
    assert not (tmp_path / "bin" / "ebaz_lcd_top").exists()
    assert "not installed" in run(tmp_path, "status").stdout


def test_install_refuses_an_inittab_without_a_tty1_getty(tmp_path):
    (tmp_path / "inittab").write_text("id:5:initdefault:\n")
    out = run(tmp_path, "install")
    assert out.returncode != 0 and "tty1" in out.stderr
    assert (tmp_path / "inittab").read_text() == "id:5:initdefault:\n"


def test_usage(tmp_path):
    out = run(tmp_path, "nonsense")
    assert out.returncode == 2 and "install" in out.stdout
