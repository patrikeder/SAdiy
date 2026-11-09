"""The Synth tab's logic without Qt: presets, plan preview, readback texts."""
import pytest

from sadiy import config
from sadiy.core import freqplan
from sadiy.ui import synth_core as core

INFO = core.LoInfo()


def test_defaults_match_the_default_config():
    cfg = config.load()
    assert INFO == core.LoInfo(cfg["rf"]["rf_min_hz"], cfg["rf"]["rf_max_hz"], cfg["rf"]["if_hz"], cfg["rf"]["injection"],
                               cfg["synth"]["pfd_hz"], cfg["synth"]["mod_max"])


def test_info_from_status_and_from_an_older_sweepd():
    st = {"limits": {"rf_min_hz": 50e6, "rf_max_hz": 400e6}, "lo": {"if_hz": 21.4e6, "injection": "low", "pfd_hz": 10e6, "mod_max": 100}}
    assert core.LoInfo.from_status(st) == core.LoInfo(50e6, 400e6, 21.4e6, "low", 10e6, 100)
    assert core.LoInfo.from_status({"limits": {"rf_min_hz": 30e6}}) == INFO       # no "lo": defaults
    assert core.LoInfo.from_status({"lo": {"if_hz": "x"}}) == INFO                # garbage: defaults


def test_presets_are_the_lo_for_the_sweep_not_the_rf():
    by_name = {p.name: p for p in core.presets(INFO)}
    start = next(p for n, p in by_name.items() if n.startswith("Sweep start"))
    stop = next(p for n, p in by_name.items() if n.startswith("Sweep stop"))
    assert start.f_lo_hz == pytest.approx(40.7e6) and stop.f_lo_hz == pytest.approx(490.7e6)
    assert by_name["100 MHz CW (first light)"].f_lo_hz == 100e6
    image = next(p for n, p in by_name.items() if n.startswith("Image check"))
    assert image.f_lo_hz == pytest.approx(89.3e6)
    for p in by_name.values():
        assert freqplan.OUT_MIN_HZ <= p.f_lo_hz <= freqplan.LO_MAX_HZ and p.power_dbm in core.POWER_CHOICES_DBM and p.note


def test_presets_follow_the_if_and_the_injection_and_drop_what_the_hardware_can_not_do():
    low = core.LoInfo(if_hz=21.4e6, injection="low")
    names = {p.name: p.f_lo_hz for p in core.presets(low)}
    assert next(v for n, v in names.items() if n.startswith("LO for a 100 MHz")) == pytest.approx(78.6e6)
    assert all(freqplan.OUT_MIN_HZ <= f <= freqplan.LO_MAX_HZ for f in names.values())      # 8.6 MHz start LO is dropped
    assert not any(n.startswith("Sweep start") for n in names)


def test_plan_text_says_integer_or_fractional_and_why_not():
    assert "integer-N" in core.plan_text(100e6, INFO) and "INT 128" in core.plan_text(100e6, INFO)
    frac = core.plan_text(110.7e6, INFO)
    assert "fractional-N" in frac and "MOD" in frac
    assert "outside the ADF4351 range" in core.plan_text(10e6, INFO)
    assert "AD831" in core.plan_text(800e6, INFO)


def test_status_text_and_readback_text():
    assert core.status_text(None) == "" and "No readback" in core.readback_text(None)
    fresh = {"source": "bench", "f_out_hz": None, "ld": 0, "main": {"enabled": False, "power_dbm": -4},
             "aux": {"enabled": False, "power_dbm": -4}, "words": {"R4": "0x0080C004"}}
    assert core.status_text(fresh) == "LO not programmed   LD 0   RF main off, aux off"
    assert "not programmed" in core.readback_text(fresh) and "R4 0x0080C004" in core.readback_text(fresh)
    on = dict(fresh, f_out_hz=110.7e6, f_vco_hz=3542.4e6, rf_div=32, mode="fractional-N", int_n=141, frac=2423, mod=3500,
              prescaler="4/5", ld=1, main={"enabled": True, "power_dbm": 2})
    assert core.status_text(on) == "LO 110.700000 MHz   LD 1   RF main +2 dBm, aux off"
    text = core.readback_text(on)
    assert "fractional-N, INT 141, FRAC 2423, MOD 3500" in text and "/ 32" in text and "Lock detect: 1" in text
    sweep = {"source": "sweep", "f_out_hz": 150.7e6, "ld": 1}
    assert core.status_text(sweep) == "LO 150.700 MHz (sweeping)   LD 1" and "Sweeping" in core.readback_text(sweep)
    assert core.status_text({"source": "sweep", "f_out_hz": None, "ld": None}) == "LO - (sweeping)   LD ?"
