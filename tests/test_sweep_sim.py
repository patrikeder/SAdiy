import numpy as np
import pytest

from sadiy import config
from sadiy.core.freqplan import build_sweep
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_sim_engine

IF = 10.7e6


@pytest.fixture
def daemon():
    cfg = config.load()
    return Sweepd(cfg, build_sim_engine(cfg))


def test_sim_finds_tone_and_low_if_image(daemon):
    pts = build_sweep(60e6, 140e6, 401, IF, "high", 25e6)       # 200 kHz steps
    p = daemon.engine.run(pts, 0.0)
    f = np.array([pt.f_rf_hz for pt in pts])
    real = (f > 100e6 - 1e6) & (f < 100e6 + 1e6)
    ghost = (f > 100e6 - 2 * IF - 1e6) & (f < 100e6 - 2 * IF + 1e6)
    # the sim has no image rejection, so the real tone and its image appear at the same level
    assert abs(f[real][p[real].argmax()] - 100e6) <= 0.2e6
    assert abs(f[ghost][p[ghost].argmax()] - (100e6 - 2 * IF)) <= 0.2e6
    assert p[real].max() == pytest.approx(-30.0, abs=1.5)        # tone is -30 dBm
    assert p[ghost].max() == pytest.approx(p[real].max(), abs=1.0)
    # everything else stays near the noise floor (-100 dBm input-referred)
    other = ~real & ~ghost & ~((f > 250e6 - 1e6) & (f < 250e6 + 1e6))
    assert p[other].max() < -80.0


def test_step_and_command_roundtrip(daemon):
    assert daemon.apply({"cmd": "set", "start_hz": 60e6, "stop_hz": 140e6, "points": 101})["ok"]
    assert not daemon.apply({"cmd": "set", "start_hz": 200e6, "stop_hz": 100e6})["ok"]
    assert not daemon.apply({"cmd": "set", "points": 1})["ok"]
    assert not daemon.apply({"cmd": "bogus"})["ok"]
    header, p = protocol.decode_frame(daemon.step())
    assert header["n"] == 101 and header["seq"] == 0
    assert header["f_start_hz"] == 60e6
    assert p.dtype == np.dtype("<f4") and p.size == 101
    daemon.apply({"cmd": "stop"})
    assert daemon.apply({"cmd": "status"})["running"] is False


def test_auto_atten_moves_into_window(daemon):
    daemon.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "points": 101, "atten_db": 0.0})
    for _ in range(3):
        daemon.step()
    # strong -30 dBm tone + 22 dB gain = -8 dBm at the detector: auto-range must add attenuation
    assert daemon.settings["atten_db"] > 0.0


def test_protocol_rejects_garbage():
    with pytest.raises(ValueError):
        protocol.decode_frame([b"nope", b"{}", b""])
    parts = protocol.encode_frame(1, 0.0, 1.0, 0.0, [1.0, 2.0])
    with pytest.raises(ValueError):
        protocol.decode_frame([parts[0], parts[1], parts[2][:-4]])


def test_zmq_pub_sub_roundtrip(daemon):
    zmq = pytest.importorskip("zmq")
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    port = pub.bind_to_random_port("tcp://127.0.0.1")
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://127.0.0.1:{port}")
    sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)
    sub.setsockopt(zmq.RCVTIMEO, 2000)
    import time

    got = None
    for _ in range(40):                      # PUB/SUB needs a moment to connect
        pub.send_multipart(daemon.step())
        time.sleep(0.05)
        try:
            got = sub.recv_multipart()
            break
        except zmq.Again:
            continue
    ctx.destroy(linger=0)
    assert got is not None
    header, p = protocol.decode_frame(got)
    assert header["n"] == p.size
