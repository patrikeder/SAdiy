"""The sweepd `selftest` command (ramp self-test of the PL engine) on the model-backed fake platform."""
import pytest

from sadiy import config
from sadiy.server.sweepd import Sweepd, build_hw_engine, build_sim_engine


def _cfg():
    c = config.load()
    c["platform"] = {"name": "fake_pl"}
    return c


@pytest.fixture
def daemon():
    return Sweepd(config.load(), build_hw_engine(_cfg()))      # the daemon's own platform is not the engine's fake


def test_status_says_whether_a_self_test_exists(daemon):
    assert daemon.apply({"cmd": "status"})["selftest_available"] is True
    sim = config.load()
    assert Sweepd(sim, build_sim_engine(sim)).apply({"cmd": "status"})["selftest_available"] is False
    assert Sweepd(sim, None).apply({"cmd": "status"})["selftest_available"] is False


def test_without_the_pl_engine_the_command_is_refused_with_the_reason():
    sim = config.load()
    r = Sweepd(sim, build_sim_engine(sim)).apply({"cmd": "selftest"})
    assert not r["ok"] and "PL sweep engine" in r["error"]


def test_selftest_passes_and_sweeping_goes_on(daemon):
    daemon.step()
    off = daemon.engine.offload
    uploads = off.uploads
    r = daemon.apply({"cmd": "selftest", "sweeps": 3})
    assert r["ok"] and r["passed"], r["lines"]
    assert r["checks"] > 20 and r["failed"] == [] and r["lines"][-1].startswith("RESULT: PASS")
    assert r["params"]["points"] == 401 and r["params"]["sweeps"] == 3
    frame = daemon.step()                       # the sweep table is uploaded again, results are the sweep's
    assert frame and off.uploads == uploads + 1


def test_selftest_leaves_the_engine_configuration_alone(daemon):
    from sadiy_ebaz import regmap_toml

    daemon.step()
    m = daemon.engine.offload.offload._rd.__self__.model          # PlModel behind the fake platform
    names = ("N_AVG", "DET_CFG", "DET_TEST", "T_MIN_US", "T_SETTLE_US")
    before = {n: m.read(regmap_toml.REGS[n].offset) for n in names}
    assert daemon.apply({"cmd": "selftest"})["passed"]
    assert {n: m.read(regmap_toml.REGS[n].offset) for n in names} == before
    assert daemon.engine.offload.offload.status()["pin_owner_act"]


def test_a_failing_engine_gives_passed_false_with_the_failed_checks(daemon, caplog):
    real = daemon.engine.offload.offload.run

    def broken(n_avg, timeout_s=10.0):
        res = real(n_avg, timeout_s)
        res.sums[7] += 1
        return res

    daemon.engine.offload.offload.run = broken
    with caplog.at_level("WARNING"):
        r = daemon.apply({"cmd": "selftest", "sweeps": 2})
    assert r["ok"] and not r["passed"] and r["failed"]
    assert any("index 7" in line for line in r["failed"]) and r["lines"][-1].startswith("RESULT: FAIL")
    assert "self-test FAIL" in caplog.text


@pytest.mark.parametrize("bad", [{"points": 1}, {"points": 5000}, {"n_avg": 0}, {"base": 70000}, {"sweeps": 0},
                                 {"points": "many"}, {"fill": True, "n_avg": 4095, "sweeps": 20}])
def test_bad_parameters_are_refused_before_anything_runs(daemon, bad):
    r = daemon.apply({"cmd": "selftest", **bad})
    assert not r["ok"] and "selftest" in r["error"]


def test_wrap_and_fill_options(daemon):
    r = daemon.apply({"cmd": "selftest", "sweeps": 2, "wrap": True, "fill": True})
    assert r["passed"], r["lines"]
    assert r["params"]["points"] == 4096 and r["params"]["wrap"] is True
    assert any("N_AVG 1, base 0xFFF0" in line for line in r["lines"])
