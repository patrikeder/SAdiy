"""SweepClient against real ZeroMQ sockets on localhost: live log records, frames and `log` fetch."""
import json
import logging
import threading
import time

import pytest
import zmq

from sadiy import config, logs
from sadiy.server import protocol
from sadiy.server.sweepd import Sweepd, build_sim_engine
from sadiy.ui.sweep_client import SweepClient


@pytest.fixture
def rig():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    rep = ctx.socket(zmq.REP)
    pub_port = pub.bind_to_random_port("tcp://127.0.0.1")
    rep_port = rep.bind_to_random_port("tcp://127.0.0.1")
    ring = logs.RingLog(50)
    cfg = config.load()
    daemon = Sweepd(cfg, build_sim_engine(cfg), ring=ring)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            if rep.poll(20):
                rep.send_json(daemon.handle_raw(rep.recv()))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = SweepClient()
    client.connect("127.0.0.1", pub_port, rep_port)
    time.sleep(0.2)                                 # let the SUB socket attach before publishing
    yield pub, ring, client
    stop.set()
    thread.join()
    client.disconnect()
    pub.close(linger=0)
    rep.close(linger=0)
    ctx.term()


def wait_for(client, n_logs=0, frame=False, timeout=3.0):
    got_frame, logs_seen = None, []
    end = time.time() + timeout
    while time.time() < end:
        got_frame = client.poll_latest() or got_frame
        logs_seen += client.take_logs()
        if len(logs_seen) >= n_logs and (got_frame is not None or not frame):
            break
        time.sleep(0.01)
    return got_frame, logs_seen


def test_live_logs_and_frames_share_the_socket(rig):
    pub, ring, client = rig
    ring.add_listener(lambda e: pub.send_multipart(protocol.encode_log(e)))
    ring.log(logging.WARNING, "sadiy.x", "first")
    pub.send_multipart(protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0, 3.0]))
    ring.log(logging.ERROR, "sadiy.x", "second")
    frame, got = wait_for(client, n_logs=2, frame=True)
    assert [e.msg for e in got] == ["first", "second"] and [e.seq for e in got] == [1, 2]
    assert frame is not None and frame[0]["seq"] == 1
    assert client.bad_frames == 0                      # a log record is not a bad sweep frame
    assert client.take_logs() == []


def test_fetch_log_returns_what_the_daemon_kept(rig):
    _, ring, client = rig
    for i in range(3):
        ring.log(logging.INFO, "sadiy.x", f"line {i}")
    entries, boot, last_seq = client.fetch_log(since=1)
    assert [e.msg for e in entries] == ["line 1", "line 2"]
    assert boot == ring.boot and last_seq == 3


def test_fetch_log_is_none_without_a_daemon():
    client = SweepClient()
    client.connect("127.0.0.1", 59998, 59999)
    try:
        assert client.fetch_log(timeout_ms=100) is None
    finally:
        client.disconnect()


def test_malformed_log_record_is_counted_not_fatal(rig):
    pub, _, client = rig
    pub.send_multipart([protocol.LOG_TOPIC, b"not json"])
    pub.send_multipart(protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0]))
    frame, got = wait_for(client, frame=True)
    assert got == [] and client.bad_frames == 1 and frame is not None


def test_client_keeps_the_flags_of_the_last_frame(rig):
    pub, _, client = rig
    pub.send_multipart(protocol.encode_frame(1, 1e6, 1e3, 0.0, [1.0, 2.0, 3.0], [0, 1, 0]))
    frame, _ = wait_for(client, frame=True)
    assert list(client.last_flags) == [0, 1, 0]
    pub.send_multipart(protocol.encode_frame(2, 1e6, 1e3, 0.0, [1.0, 2.0, 3.0]))
    wait_for(client, frame=True)
    assert client.last_flags is None
