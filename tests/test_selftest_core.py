"""Qt-free parts of the Ramp self-test box: the command, the reply text, and the async request on a real REP socket."""
import threading

import pytest

from sadiy.ui import selftest_core as core


def test_command_is_clamped_and_complete():
    assert core.Options().command() == {"cmd": "selftest", "sweeps": 5, "wrap": False, "fill": False}
    assert core.Options(99, True, True).command() == {"cmd": "selftest", "sweeps": 20, "wrap": True, "fill": True}
    assert core.Options(0).command()["sweeps"] == 1


def test_timeout_covers_the_wait_for_the_sweep_and_the_longest_test():
    assert core.timeout_ms() >= (core.WAIT_FOR_SWEEP_S + core.TEST_LIMIT_S) * 1000


def test_reply_texts():
    ok = core.parse_reply({"ok": True, "passed": True, "checks": 120, "failed": [], "seconds": 0.43,
                           "lines": ["PASS ...", "RESULT: PASS"]})
    assert ok.passed is True and ok.summary == "PASS: 120 checks, 0.4 s" and ok.lines[-1] == "RESULT: PASS"
    bad = core.parse_reply({"ok": True, "passed": False, "checks": 120, "failed": ["a", "b"], "seconds": 1.0, "lines": []})
    assert bad.passed is False and "2 of 120" in bad.summary
    refused = core.parse_reply({"ok": False, "error": "no ramp self-test here"})
    assert refused.passed is None and "no ramp self-test here" in refused.summary
    assert core.parse_reply(None).passed is None


zmq = pytest.importorskip("zmq")


def _rep_server(delay_s: float, reply: dict):
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REP)
    port = sock.bind_to_random_port("tcp://127.0.0.1")

    def serve():
        if sock.poll(5000):
            sock.recv_json()
            threading.Event().wait(delay_s)
            sock.send_json(reply)
        sock.close(linger=0)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return port, t


def test_async_request_waits_without_blocking_and_returns_the_reply():
    from sadiy.ui.sweep_client import SweepClient

    port, t = _rep_server(0.3, {"ok": True, "passed": True})
    c = SweepClient()
    c.connect("127.0.0.1", port + 1, port)
    try:
        req = c.request_async({"cmd": "selftest"}, 5000)
        assert req.poll() == (False, None)                    # not there yet, and the call returned at once
        done, reply = False, None
        for _ in range(100):
            done, reply = req.poll()
            if done:
                break
            threading.Event().wait(0.05)
        assert done and reply == {"ok": True, "passed": True}
        assert req.poll() == (True, None)                     # closed: nothing more to read
    finally:
        c.disconnect()
        t.join(timeout=5)


def test_async_request_times_out_with_none():
    from sadiy.ui.sweep_client import SweepClient

    port, t = _rep_server(2.0, {"ok": True})
    c = SweepClient()
    c.connect("127.0.0.1", port + 1, port)
    try:
        req = c.request_async({"cmd": "selftest"}, 100)
        threading.Event().wait(0.25)
        assert req.poll() == (True, None)
    finally:
        c.disconnect()
        t.join(timeout=5)


def test_async_request_needs_a_connection():
    from sadiy.ui.sweep_client import SweepClient

    assert SweepClient().request_async({"cmd": "selftest"}, 1000) is None
