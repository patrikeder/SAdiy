import pytest

from sadiy import config
from sadiy.server.sweepd import Sweepd, build_sim_engine


@pytest.fixture
def daemon():
    cfg = config.load()
    return Sweepd(cfg, build_sim_engine(cfg))


def test_range_outside_rf_limits_is_rejected_not_fatal(daemon):
    # 5 MHz + 10.7 MHz IF is below the ADF4351 minimum: plan_pll would raise inside step()
    r = daemon.apply({"cmd": "set", "start_hz": 5e6, "stop_hz": 100e6})
    assert not r["ok"] and "MHz" in r["error"]
    assert not daemon.apply({"cmd": "set", "start_hz": 100e6, "stop_hz": 600e6})["ok"]
    assert daemon.settings["start_hz"] == 30e6               # unchanged
    daemon.step()                                            # still runs


def test_edges_of_the_range_are_accepted(daemon):
    assert daemon.apply({"cmd": "set", "start_hz": 30e6, "stop_hz": 480e6, "points": 11})["ok"]
    daemon.step()


def test_status_reports_limits(daemon):
    st = daemon.apply({"cmd": "status"})
    assert st["limits"] == {"rf_min_hz": 30e6, "rf_max_hz": 480e6, "points_max": 4001}
    assert st["settings"]["points"] == 401
