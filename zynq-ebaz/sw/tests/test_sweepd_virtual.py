"""The sweepd `virtual` command (virtual spectrum of the PL engine), with a stub for sadiy_ebaz.virtual_spectrum:
the sweepd side is the switching, the exclusion with the self-test, leaving on a failure and the sweep pace."""
import numpy as np
import pytest

from sadiy import config
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_hw_engine


class StubVirtual:
    """The interface of VirtualSweep that sweepd uses."""

    def __init__(self, detector, cal):
        self.detector, self.cal = detector, cal
        self.sweeps, self.closed, self.fail, self.fail_ideal = 0, 0, False, False

    def run_points(self, points, atten_db, n_avg):
        if self.fail:
            raise RuntimeError("generator not running")
        self.sweeps += 1
        return [1.0] * len(points), [False] * len(points), atten_db

    def state(self):
        return {"sweep": self.sweeps, "drift_points": 3}

    def ideal_dbm(self, points=None):
        if self.fail_ideal:
            raise RuntimeError("no ideal")
        return [-50.0 + i for i in range(len(points))]

    def close(self):
        self.closed += 1

    def safe_state(self):
        pass


@pytest.fixture
def daemon():
    cfg = config.load()
    cfg2 = config.load()
    cfg2["platform"] = {"name": "fake_pl"}
    d = Sweepd(cfg, build_hw_engine(cfg2))
    d.engine.offload.virtual = lambda det, cal: StubVirtual(det, cal)       # what OffloadSweep.virtual returns with the module
    return d


def test_status_says_whether_it_is_available_and_active(daemon):
    st = daemon.apply({"cmd": "status"})["virtual"]
    assert st == {"available": True, "active": False, "state": None}
    daemon.apply({"cmd": "virtual", "on": True})
    st = daemon.apply({"cmd": "status"})["virtual"]
    assert st["active"] and st["state"]["drift_points"] == 3


def test_not_available_without_the_module_or_the_pl_engine(daemon):
    daemon.engine.offload.virtual = lambda det, cal: None
    r = daemon.apply({"cmd": "virtual", "on": True})
    assert not r["ok"] and "no virtual spectrum module" in r["error"]
    from sadiy.server.sweepd import build_sim_engine
    sim = config.load()
    r = Sweepd(sim, build_sim_engine(sim)).apply({"cmd": "virtual", "on": True})
    assert not r["ok"] and "PL sweep engine" in r["error"]
    assert Sweepd(sim, build_sim_engine(sim)).apply({"cmd": "status"})["virtual"]["available"] is False


def test_on_replaces_the_offload_runs_sweeps_and_off_restores_it(daemon):
    real = daemon.engine.offload
    daemon.running = False
    assert daemon.apply({"cmd": "virtual", "on": True})["ok"]
    vs = daemon._virtual
    assert daemon.engine.offload is vs and daemon.running and daemon.min_period_s == 0.1
    frame = daemon.step()
    assert frame and vs.sweeps == 1
    assert daemon.apply({"cmd": "virtual", "on": True})["ok"] and daemon._virtual is vs      # again: nothing changes
    real._key = ("something",)
    assert daemon.apply({"cmd": "virtual", "on": False})["ok"]
    assert daemon.engine.offload is real and real._key is None and daemon._virtual is None
    assert vs.closed == 1 and daemon.min_period_s == 0.0
    assert daemon.step()                                       # real (model) sweeps again
    assert daemon.apply({"cmd": "virtual", "on": False})["ok"] and vs.closed == 1      # off when off: nothing


def test_the_self_test_is_refused_while_it_is_on(daemon):
    daemon.apply({"cmd": "virtual", "on": True})
    r = daemon.apply({"cmd": "selftest"})
    assert not r["ok"] and "virtual spectrum is on" in r["error"]
    daemon.apply({"cmd": "virtual", "on": False})
    assert daemon.apply({"cmd": "selftest", "sweeps": 2})["passed"]


def test_a_failed_sweep_leaves_the_mode_and_restores_the_engine(daemon):
    real = daemon.engine.offload
    daemon.apply({"cmd": "virtual", "on": True})
    vs = daemon._virtual
    vs.fail = True
    assert daemon.run_step() is None
    assert daemon.engine.offload is real and daemon._virtual is None and vs.closed == 1 and not daemon.running
    assert "generator not running" in daemon.last_error


def test_shutdown_closes_it(daemon):
    daemon.apply({"cmd": "virtual", "on": True})
    vs = daemon._virtual
    daemon.shutdown()
    assert vs.closed == 1 and daemon._virtual is None


def test_bench_mode_blocks_it():
    from sadiy.server.bench import Bench, fake_backend

    cfg = config.load()
    cfg2 = config.load()
    cfg2["platform"] = {"name": "fake_pl"}
    d = Sweepd(cfg, build_hw_engine(cfg2), Bench(fake_backend(__import__("sadiy.platforms", fromlist=["x"]).get("bbb")), cfg))
    d.engine.offload.virtual = lambda det, cal: StubVirtual(det, cal)
    d.apply({"cmd": "stop"})
    assert d.apply({"cmd": "bench_open"})["ok"] and d.bench_active
    r = d.apply({"cmd": "virtual", "on": True})
    assert not r["ok"] and "bench mode" in r["error"]


def test_frames_carry_the_expected_trace_only_while_virtual(daemon):
    header, p, flags, ideal = protocol.decode_frame_all(daemon.step())
    assert ideal is None and "ideal" not in header
    daemon.apply({"cmd": "virtual", "on": True})
    header, p, flags, ideal = protocol.decode_frame_all(daemon.step())
    assert header["ideal"] and ideal.size == p.size == header["n"] and ideal[3] == pytest.approx(-47.0)
    assert (flags is None) == (not header.get("flags"))                   # the flags part (if any) is still read first
    daemon.apply({"cmd": "virtual", "on": False})
    assert protocol.decode_frame_all(daemon.step())[3] is None


def test_a_failing_expected_trace_does_not_fail_the_sweep(daemon):
    daemon.apply({"cmd": "virtual", "on": True})
    daemon._virtual.fail_ideal = True
    header, p, flags, ideal = protocol.decode_frame_all(daemon.step())
    assert ideal is None and daemon._virtual is not None and p.size == header["n"]


def test_the_expected_part_follows_the_flags_part_and_old_readers_ignore_it():
    p = np.arange(5, dtype=np.float32)
    for flags in (None, np.array([0, 1, 0, 0, 2], dtype=np.uint8)):
        parts = protocol.encode_frame(1, 1e6, 1e3, 0.0, p, flags, ideal=p + 0.5)
        h, q, f, i = protocol.decode_frame_all(parts)
        assert h["ideal"] and np.array_equal(q, p) and np.array_equal(i, p + 0.5)
        assert (f is None) if flags is None else np.array_equal(f, flags)
        h, q, f = protocol.decode_frame_flags(parts)                  # a reader that knows nothing of it
        assert np.array_equal(q, p)
    with pytest.raises(ValueError):
        protocol.encode_frame(1, 1e6, 1e3, 0.0, p, ideal=[1.0])
    parts = protocol.encode_frame(1, 1e6, 1e3, 0.0, p, ideal=p)
    parts[3] = parts[3][:-4]
    with pytest.raises(ValueError):
        protocol.decode_frame_all(parts)
