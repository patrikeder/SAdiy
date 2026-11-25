"""tools/gen_diagrams.py with --platform: only the selected platform appears in what it writes."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_diagrams", ROOT / "tools" / "gen_diagrams.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(gen, tmp_path, platform):
    args = ["--no-png", "--out", str(tmp_path)]
    if platform:
        args += ["--platform", platform]
    gen.main(args)
    return {p.name: p.read_text() for p in list(tmp_path.glob("diagrams/*.svg")) + list(tmp_path.glob("*.md"))}


OTHER_BBB = re.compile(r"\b(BBB|BeagleBone|RPi|Raspberry)\b|\bP[89]\.\d+")
OTHER_EBAZ = re.compile(r"EBAZ|\bDATA[123]\b")


def test_ebaz_only(gen, tmp_path):
    files = run(gen, tmp_path, "ebaz")
    assert sorted(files) == ["ebaz-data1-pinout.svg", "ebaz-data2-pinout.svg", "ebaz-data3-pinout.svg", "ebaz-wiring.svg",
                             "netlist-ebaz.md"]
    for name, text in files.items():
        assert not OTHER_BBB.search(text), (name, OTHER_BBB.search(text).group(0))
    net = files["netlist-ebaz.md"]
    assert "DET_ADC" not in net and "ADC_GND" not in net          # nets this board does not have
    assert "| SYN_CLK | ADF4351 | CLK | SBC to board | DATA2.5 G20  adf4351_clk |" in net


def test_bbb_only(gen, tmp_path):
    files = run(gen, tmp_path, "bbb")
    assert sorted(files) == ["bbb-p8-pinout.svg", "bbb-p9-pinout.svg", "bbb-wiring.svg", "netlist-bbb.md"]
    for name, text in files.items():
        assert not OTHER_EBAZ.search(text), (name, OTHER_EBAZ.search(text).group(0))
        assert "RPi" not in text and "Raspberry" not in text, name
    assert "DET_ADC" in files["netlist-bbb.md"]


def test_default_writes_everything_and_keeps_the_old_figures(gen, tmp_path):
    files = run(gen, tmp_path, None)
    for name in ("bbb-wiring.svg", "rpi-wiring.svg", "ebaz-wiring.svg", "ebaz-data2-pinout.svg", "netlist.md"):
        assert name in files
    net = files["netlist.md"]
    assert "| Net | Board | Board pin | Direction | BBB | RPi | EBAZ | Notes |" in net
    # the committed figures of the BBB and RPi set come out as before (their first line holds metadata)
    for name in ("bbb-p9-pinout.svg", "bbb-p8-pinout.svg", "bbb-wiring.svg", "rpi-wiring.svg", "power-tree.svg"):
        committed = (ROOT / "hw" / "diagrams" / name).read_text().split("\n", 1)[1]
        assert files[name].split("\n", 1)[1] == committed, name


def test_committed_ebaz_outputs_are_current(gen, tmp_path):
    """hw/netlist.md and the ebaz-*.svg in the repo are the generator's output (never edited by hand)."""
    files = run(gen, tmp_path, None)
    assert (ROOT / "hw" / "netlist.md").read_text() == files["netlist.md"]
    for name in ("ebaz-wiring.svg", "ebaz-data1-pinout.svg", "ebaz-data2-pinout.svg", "ebaz-data3-pinout.svg"):
        assert (ROOT / "hw" / "diagrams" / name).read_text() == files[name], name


def test_other_tools_take_the_platform():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "bringup.py"), "--platform", "ebaz", "gpio-map"],
                         capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")})
    assert out.returncode == 0, out.stderr
    assert "DATA2.13" in out.stdout and "SYN_CE" in out.stdout and "ATT_V1" not in out.stdout and "P9." not in out.stdout


def test_sweepd_ebaz_hardware_fails_cleanly_without_the_board():
    """On a PC there is no PL engine: without the sadiy_ebaz package, or without access to /dev/mem, sweepd must
    stop with one clear line, not a traceback."""
    out = subprocess.run([sys.executable, "-m", "sadiy.server.sweepd", "--platform", "ebaz"],
                         capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")}, timeout=30)
    assert out.returncode != 0
    assert "cannot start the EBAZ4205 hardware backend" in out.stderr and "Traceback" not in out.stderr
    both = f"{ROOT / 'src'}:{ROOT / 'zynq-ebaz' / 'sw'}"
    out = subprocess.run([sys.executable, "-m", "sadiy.server.sweepd", "--platform", "ebaz"],
                         capture_output=True, text=True, env={"PYTHONPATH": both}, timeout=30)
    assert out.returncode != 0 and "Traceback" not in out.stderr      # no /dev/mem access (or no core) on a PC
    out = subprocess.run([sys.executable, "-m", "sadiy.server.sweepd", "--platform", "ebaz", "--bench-only"],
                         capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src")}, timeout=30)
    assert out.returncode != 0 and "cannot start the EBAZ4205 bench backend" in out.stderr and "Traceback" not in out.stderr
