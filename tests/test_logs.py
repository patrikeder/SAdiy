import io
import logging

import pytest

from sadiy import logs


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ring(clock):
    return logs.RingLog(capacity=5, dedup_s=5.0, clock=clock)


def test_parse_level_and_verbosity():
    assert logs.parse_level("INFO") == logging.INFO
    assert logs.parse_level("warn") == logging.WARNING
    assert logs.parse_level("trace") == logs.TRACE
    assert logs.parse_level(25) == 25
    with pytest.raises(ValueError):
        logs.parse_level("loud")
    assert logs.level_from_verbosity() == logging.INFO
    assert logs.level_from_verbosity(verbose=1) == logging.DEBUG
    assert logs.level_from_verbosity(verbose=2) == logs.TRACE
    assert logs.level_from_verbosity(verbose=9) == logs.TRACE        # clamped
    assert logs.level_from_verbosity(quiet=1) == logging.WARNING
    assert logs.level_from_verbosity(quiet=9) == logging.ERROR


def test_entries_are_numbered_filtered_and_bounded(ring):
    for i in range(7):
        ring.log(logging.INFO, "sadiy.x", f"m{i}")
    got = ring.entries()
    assert [e.msg for e in got] == ["m2", "m3", "m4", "m5", "m6"]        # capacity 5, oldest dropped
    assert [e.seq for e in got] == [3, 4, 5, 6, 7]
    assert ring.last_seq == 7
    assert [e.msg for e in ring.entries(since_seq=5)] == ["m5", "m6"]
    assert [e.msg for e in ring.entries(limit=2)] == ["m5", "m6"]
    ring.log(logging.ERROR, "sadiy.x", "bad")
    assert [e.msg for e in ring.entries(min_level=logging.WARNING)] == ["bad"]


def test_routine_lines_never_push_out_warnings(ring):
    ring.log(logging.ERROR, "sadiy.x", "first error")
    ring.log(logging.WARNING, "sadiy.x", "a warning")
    for i in range(20):
        ring.log(logging.INFO, "sadiy.x", f"routine {i}")
    msgs = [e.msg for e in ring.entries()]
    assert msgs[:2] == ["first error", "a warning"] and len(msgs) == 5
    for i in range(10):                                                  # only warnings left to drop
        ring.log(logging.WARNING, "sadiy.x", f"w{i}")
    assert [e.msg for e in ring.entries()] == ["w5", "w6", "w7", "w8", "w9"]


def test_trace_never_enters_the_ring(ring):
    ring.log(logs.TRACE, "sadiy.x", "per point")
    assert ring.entries() == [] and ring.last_seq == 0


def test_repeats_fold_into_one_summary(ring, clock):
    seen = []
    ring.add_listener(seen.append)
    for _ in range(50):
        ring.log(logging.WARNING, "sadiy.x", "PLL unlocked")
        clock.t += 0.01
    assert [e.msg for e in ring.entries()] == ["PLL unlocked"]           # 49 copies suppressed
    ring.log(logging.INFO, "sadiy.x", "next")                            # a different record closes the run
    got = ring.entries()
    assert [(e.msg, e.repeats) for e in got] == [("PLL unlocked", 0), ("PLL unlocked", 49), ("next", 0)]
    assert [e.seq for e in seen] == [1, 2, 3]                            # listeners see the same stream


def test_flush_closes_a_run_only_after_the_window(ring, clock):
    ring.log(logging.ERROR, "sadiy.x", "boom")
    ring.log(logging.ERROR, "sadiy.x", "boom")
    ring.flush()
    assert len(ring.entries()) == 1                                      # window still open
    clock.t += 5.0
    ring.flush()
    last = ring.entries()[-1]
    assert (last.msg, last.repeats) == ("boom", 1)
    ring.flush()
    assert len(ring.entries()) == 2                                      # nothing more to close


def test_same_message_after_the_window_logs_again(ring, clock):
    ring.log(logging.WARNING, "sadiy.x", "slow")
    clock.t += 6.0
    ring.log(logging.WARNING, "sadiy.x", "slow")
    assert [e.repeats for e in ring.entries()] == [0, 0]


def test_a_failing_listener_does_not_break_logging(ring):
    ring.add_listener(lambda e: 1 / 0)
    seen = []
    ring.add_listener(seen.append)
    ring.log(logging.INFO, "sadiy.x", "hello")
    assert len(seen) == 1 and ring.last_seq == 1


def test_entry_dict_roundtrip_and_format():
    e = logs.LogEntry(7, 0.0, logging.WARNING, "sadiy.server.sweepd", "lock lost", 3)
    assert logs.LogEntry.from_dict(e.to_dict()) == e
    text = logs.format_entry(e)
    assert "WARNING" in text and "server.sweepd: lock lost (repeated 3 more times)" in text
    assert "sadiy.server" not in text


def test_setup_routes_by_level():
    stream = io.StringIO()
    ring = logs.setup("warning", stream=stream)
    log = logging.getLogger("sadiy.test_logs")
    log.debug("quiet detail")
    log.warning("careful")
    try:
        raise OSError("spi gone")
    except OSError:
        log.error("write failed", exc_info=True)
    text = stream.getvalue()
    assert "careful" in text and "write failed" in text and "Traceback" in text
    assert "quiet detail" not in text                                    # stderr is at warning ...
    msgs = [e.msg for e in ring.entries()]
    assert "quiet detail" in msgs                                        # ... the ring still takes debug
    assert "write failed (OSError: spi gone)" in msgs                    # one line, no traceback
    assert not log.isEnabledFor(logs.TRACE)
    logs.setup("trace", stream=io.StringIO())
    assert log.isEnabledFor(logs.TRACE)
    logs.setup("info", stream=io.StringIO())                             # second call replaces the handlers
    assert sum(getattr(h, "_sadiy", False) for h in logging.getLogger("sadiy").handlers) == 2
