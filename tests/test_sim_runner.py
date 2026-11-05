import sys
import time
import tomllib

import pytest

from sadiy import config
from sadiy.ui.sim_runner import SimRunner, render_override


def test_override_is_valid_toml_and_merges_over_defaults(tmp_path):
    text = render_override(6000, 6001, [(100e6, -30.0), (250.5e6, -45.0)], -95.0, 100e3)
    path = tmp_path / "o.toml"
    path.write_text(text)
    cfg = config.load(path)
    assert cfg["server"]["pub"] == "tcp://127.0.0.1:6000" and cfg["server"]["rep"] == "tcp://127.0.0.1:6001"
    assert cfg["sim"]["tones"] == [[100e6, -30.0], [250.5e6, -45.0]]
    assert cfg["sim"]["noise_dbm_in"] == -95.0 and cfg["sim"]["rbw_hz"] == 100e3
    assert cfg["rf"]["if_hz"] == 10.7e6                    # untouched sections survive the merge


def test_override_without_tones_parses():
    cfg = tomllib.loads(render_override(1, 2, []))
    assert cfg["sim"]["tones"] == []


def test_sim_engine_uses_the_sim_section():
    from sadiy.server.sweepd import Sweepd, build_sim_engine

    cfg = config.load()
    cfg["sim"] = {"tones": [[60e6, -20.0]], "noise_dbm_in": -90.0, "rbw_hz": 100e3}
    d = Sweepd(cfg, build_sim_engine(cfg))
    chain = d.engine.synth.chain
    assert chain.tones == ((60e6, -20.0),) and chain.noise_dbm_in == -90.0 and chain.rbw_hz == 100e3
    d.apply({"cmd": "set", "start_hz": 40e6, "stop_hz": 80e6, "points": 201})
    import numpy as np
    from sadiy.server import protocol

    header, p = protocol.decode_frame(d.step())
    f = header["f_start_hz"] + np.arange(header["n"]) * header["f_step_hz"]
    assert abs(f[int(np.argmax(p))] - 60e6) < 0.5e6


def test_default_config_reproduces_the_old_hardcoded_tones():
    from sadiy.server.sweepd import build_sim_engine

    chain = build_sim_engine(config.load()).synth.chain
    assert chain.tones == ((100e6, -30.0), (250e6, -45.0)) and chain.rbw_hz == 230e3


def test_start_stop_log_and_cleanup():
    r = SimRunner()
    script = "import time; print('hello from sim', flush=True); time.sleep(30)"
    r.start(5556, 5557, 0.1, [(100e6, -30.0)], command=[sys.executable, "-u", "-c", script])
    assert r.running and r.pid
    cfg_path = r._cfg_path
    for _ in range(100):
        if any("hello from sim" in line for line in r.drain_log()):
            break
        time.sleep(0.05)
    assert any("hello from sim" in line for line in r.drain_log())
    with pytest.raises(RuntimeError):
        r.start(5556, 5557, 0.1, [], command=[sys.executable, "-c", "pass"])
    r.stop()
    assert not r.running and r.returncode is not None
    assert r.drain_log()[-1].startswith("[exited with code")
    import os
    assert not os.path.exists(cfg_path)


def test_process_that_dies_is_reported():
    r = SimRunner()
    r.start(1, 2, 0.1, [], command=[sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"])
    for _ in range(100):
        if not r.running:
            break
        time.sleep(0.05)
    assert not r.running and r.returncode == 3
    r.stop()
    assert any("boom" in line for line in r.drain_log())


def test_default_command_runs_sweepd_sim_with_the_override():
    r = SimRunner()
    cmd = r.build_command("/tmp/x.toml", 0.25)
    assert cmd[1:] == ["-u", "-m", "sadiy.server.sweepd", "--sim", "--period", "0.25", "--config", "/tmp/x.toml"] or \
        cmd[2:] == ["-m", "sadiy.server.sweepd", "--sim", "--period", "0.25", "--config", "/tmp/x.toml"]
