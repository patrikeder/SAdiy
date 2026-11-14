"""pins.toml / gen_xdc.py checks (lane L). Runs without Vivado."""
import importlib.util
import tomllib
from pathlib import Path

VIVADO = Path(__file__).resolve().parents[2] / "rtl" / "vivado"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_xdc", VIVADO / "gen_xdc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg():
    return tomllib.loads((VIVADO / "pins.toml").read_text())


def test_committed_xdc_is_current():
    gen = _gen()
    assert (VIVADO / "constraints" / "ebaz4205.xdc").read_text() == gen.render(_cfg())


def test_phase1_signal_names_follow_the_contract():
    names = {s["name"] for s in _cfg()["signal"] if s.get("active")}
    expected = {f"pe4302_v[{i}]" for i in range(6)} | {
        "adf4351_clk", "adf4351_dat", "adf4351_le", "adf4351_ce", "adf4351_ld",
        "i2c_scl", "i2c_sda",
    }
    assert names == expected


def test_pe4302_bit_order_matches_weights():
    # V1..V6 = 0.5, 1, 2, 4, 8, 16 dB -> pe4302_v[0..5]
    notes = {s["name"]: s["note"] for s in _cfg()["signal"] if s["name"].startswith("pe4302")}
    for i, w in enumerate(["0.5", "1", "2", "4", "8", "16"]):
        assert notes[f"pe4302_v[{i}]"] == f"V{i+1} = {w} dB"


def test_no_duplicate_balls_or_pins():
    sigs = _cfg()["signal"]
    assert len({s["ball"] for s in sigs}) == len(sigs)
    assert len({(s["connector"], s["pin"]) for s in sigs}) == len(sigs)


def test_top_level_uses_every_active_port():
    top = (VIVADO / "phase1_top.v").read_text()
    for s in _cfg()["signal"]:
        if s.get("active"):
            base = s["name"].split("[")[0]
            assert base in top, base
