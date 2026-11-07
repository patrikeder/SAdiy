"""Flags and sweep reports through sweepd: frame part, lock gating in the simulator, throttled warnings."""
import io
import logging

import numpy as np
import pytest

from sadiy import config, logs
from sadiy.core.sweep import FLAG_OVERRANGE, FLAG_UNLOCKED
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_sim_engine


@pytest.fixture
def ring():
    r = logs.setup("error", stream=io.StringIO())
    yield r
    for h in list(logging.getLogger("sadiy").handlers):
        if getattr(h, "_sadiy", False):
            logging.getLogger("sadiy").removeHandler(h)


def make(ring, unlock=(), tones=None):
    cfg = config.load()
    cfg["sim"] = dict(cfg.get("sim", {}), unlock_ranges_hz=[list(r) for r in unlock])
    if tones:
        cfg["sim"]["tones"] = tones
    d = Sweepd(cfg, build_sim_engine(cfg), ring=ring)
    d.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "points": 21, "auto_atten": False, "atten_db": 20.0})
    return d


def warnings(ring):
    return [e.msg for e in ring.entries(min_level=logging.WARNING)]


def test_frame_carries_flags_and_old_readers_ignore_them():
    parts = protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0, 3.0], [0, FLAG_UNLOCKED, 0])
    assert len(parts) == 4
    header, p, flags = protocol.decode_frame_flags(parts)
    assert header["flags"] is True and list(flags) == [0, 1, 0] and p.size == 3
    header, p = protocol.decode_frame(parts)                      # the two-value reader still works
    assert p.size == 3
    header, p, flags = protocol.decode_frame_flags(protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0]))
    assert flags is None and "flags" not in header
    with pytest.raises(ValueError):
        protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0], [0])
    bad = parts[:3] + [b"\x00"]
    with pytest.raises(ValueError):
        protocol.decode_frame_flags(bad)


def test_simulated_pll_that_does_not_lock_is_flagged_in_the_frame(ring):
    d = make(ring, unlock=[(98e6, 102e6)])
    header, p, flags = protocol.decode_frame_flags(d.run_step())
    f = header["f_start_hz"] + np.arange(header["n"]) * header["f_step_hz"]
    bad = (f >= 98e6) & (f <= 102e6)
    assert bad.any() and (flags[bad] & FLAG_UNLOCKED).all() and not (flags[~bad] & FLAG_UNLOCKED).any()
    assert d.apply({"cmd": "status"})["last_sweep"]["unlocked"] == int(bad.sum())
    msg = warnings(ring)[0]
    assert f"{int(bad.sum())} of 21 points read without PLL lock, the first at 98.000 MHz" in msg


def test_a_lasting_fault_is_reported_once_then_summarised_then_cleared(ring):
    d = make(ring, unlock=[(98e6, 102e6)])
    d.warn_every_s = 3600.0
    for _ in range(5):
        d.run_step()
    assert len(warnings(ring)) == 1                               # one report, not five
    d.warn_every_s = 0.0                                          # the window has passed
    d.run_step()
    assert "(also in 4 sweeps since the last report)" in warnings(ring)[-1]
    d.engine.synth.unlocked_rf_ranges = ()                        # the fault goes away
    d.run_step()
    assert "PLL lock is back on every point" in [e.msg for e in ring.entries(min_level=logging.INFO)]
    d.run_step()
    assert [e.msg for e in ring.entries(min_level=logging.INFO)].count("PLL lock is back on every point") == 1


def test_overload_is_a_warning_with_a_hint(ring):
    d = make(ring, tones=[[100e6, -15.0]])
    d.apply({"cmd": "set", "atten_db": 0.0})                      # -15 dBm tone + 22 dB gain: +7 dBm, overload
    _, _, flags = protocol.decode_frame_flags(d.run_step())
    assert (flags & FLAG_OVERRANGE).any()
    assert "detector overload" in warnings(ring)[0] and "raise the attenuation" in warnings(ring)[0]
    d.apply({"cmd": "set", "auto_atten": True})
    d.warn_every_s = 0.0
    d.run_step()
    assert "auto-ranging adds attenuation" in warnings(ring)[-1]


def test_no_lock_detect_is_noted_once(ring):
    d = make(ring)
    d.engine._lock = None                                         # a board without a lock detect wire
    d.run_step()
    d.run_step()
    notes = [e.msg for e in ring.entries() if "no lock detect" in e.msg]
    assert notes == ["no lock detect available: points are not gated on PLL lock"]


def test_a_clean_sweep_says_nothing_at_warning_level(ring):
    d = make(ring)
    d.apply({"cmd": "set", "atten_db": 30.0})
    d.run_step()
    assert warnings(ring) == []
