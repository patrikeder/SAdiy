"""The terminal client against a live sweepd (simulated chain) in this process."""
import io
import logging
import threading
import time

import pytest
import zmq

from sadiy import config, logs
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_sim_engine
from sadiy.ui import cli_client


def test_cli_prints_history_live_log_and_flag_counts(capsys):
    ring = logs.setup("error", stream=io.StringIO())
    try:
        cfg = config.load()
        cfg["sim"] = dict(cfg.get("sim", {}), unlock_ranges_hz=[[98e6, 102e6]])
        daemon = Sweepd(cfg, build_sim_engine(cfg), ring=ring)
        daemon.apply({"cmd": "set", "start_hz": 90e6, "stop_hz": 110e6, "points": 21})
        logging.getLogger("sadiy.test").warning("before the client")
        ctx = zmq.Context()
        pub, rep = ctx.socket(zmq.PUB), ctx.socket(zmq.REP)
        pub_port, rep_port = pub.bind_to_random_port("tcp://127.0.0.1"), rep.bind_to_random_port("tcp://127.0.0.1")
        ring.add_listener(lambda e: pub.send_multipart(protocol.encode_log(e)))
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                if rep.poll(20):
                    rep.send_json(daemon.handle_raw(rep.recv()))

        def publish():
            while not stop.is_set():
                frame = daemon.run_step()
                if frame:
                    pub.send_multipart(frame)
                time.sleep(0.05)

        threads = [threading.Thread(target=f, daemon=True) for f in (serve, publish)]
        for t in threads:
            t.start()
        cli_client.main(["--pub-port", str(pub_port), "--rep-port", str(rep_port), "--count", "2",
                         "--log-level", "warning"])
        stop.set()
        for t in threads:
            t.join()
        pub.close(linger=0)
        rep.close(linger=0)
        ctx.term()
    finally:
        for h in list(logging.getLogger("sadiy").handlers):
            if getattr(h, "_sadiy", False):
                logging.getLogger("sadiy").removeHandler(h)
    out = capsys.readouterr().out
    assert "WARNING" in out and "before the client" in out                      # from the history
    assert "points read without PLL lock" in out                                # live, from the sweeps
    assert out.count("seq ") == 2 and "flagged)" in out
    assert "settings:" not in out                                               # info is below warning
