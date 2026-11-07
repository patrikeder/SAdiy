import logging

from sadiy import logs
from sadiy.ui.log_core import LogBuffer, entry_html


def E(seq, level=logging.INFO, msg=None, boot="b1", repeats=0):
    return logs.LogEntry(seq, 1000.0 + seq, level, "sadiy.server.sweepd", msg or f"m{seq}", repeats, boot)


def test_live_feed_is_ignored_until_the_first_fetch():
    b = LogBuffer()
    assert b.gap
    assert b.add_live([E(5)]) == [] and b.gap
    b.add_fetched([E(3), E(4), E(5)], boot="b1", last_seq=5)     # the daemon's ring starts at 3: not a gap
    assert not b.gap and b.last_seq == 5
    assert [e.seq for e in b.add_live([E(5), E(6), E(7)])] == [6, 7]       # 5 was a duplicate


def test_a_skipped_number_sets_gap_and_drops_the_rest_until_fetched():
    b = LogBuffer()
    b.add_fetched([E(1), E(2)], boot="b1", last_seq=2)
    assert [e.seq for e in b.add_live([E(3), E(5), E(6)])] == [3]
    assert b.gap and b.last_seq == 3
    assert b.add_live([E(7)]) == []                                       # still waiting for the fetch
    b.add_fetched([E(4), E(5), E(6), E(7)], boot="b1", last_seq=7)
    assert not b.gap and [e.seq for e in b.entries] == [1, 2, 3, 4, 5, 6, 7]


def test_empty_fetch_still_sets_the_state():
    b = LogBuffer()
    b.add_fetched([], boot="b1", last_seq=0)
    assert not b.gap and b.boot == "b1"
    assert [e.seq for e in b.add_live([E(1)])] == [1]


def test_restart_adds_a_marker_and_renumbers():
    b = LogBuffer()
    b.add_fetched([E(1), E(2), E(3)], boot="b1", last_seq=3)
    added = b.add_live([E(1, boot="b2"), E(2, boot="b2")])
    assert [e.name for e in added[:1]] == ["gui"] and "restarted" in added[0].msg
    assert [e.seq for e in added[1:]] == [1, 2] and b.boot == "b2" and not b.gap
    assert b.unseen_warnings == 1                                          # the marker is a warning
    b2 = LogBuffer()
    b2.add_fetched([E(1), E(2), E(3)], boot="b1", last_seq=3)
    b2.add_fetched([E(1, boot="b2")], boot="b2", last_seq=1)               # same, found by a fetch
    assert b2.last_seq == 1 and b2.boot == "b2"


def test_restart_that_skips_the_start_is_a_gap():
    b = LogBuffer()
    b.add_fetched([E(1)], boot="b1", last_seq=1)
    b.add_live([E(40, boot="b2")])
    assert b.gap


def test_unseen_counters_badge_and_repeats():
    b = LogBuffer()
    b.add_fetched([], boot="b1", last_seq=0)
    b.add_live([E(1, logging.INFO), E(2, logging.WARNING), E(3, logging.ERROR), E(4, logging.ERROR, repeats=9)])
    assert (b.unseen_warnings, b.unseen_errors) == (1, 1)                  # a folded summary is not new
    assert b.badge == " (1 error, 1 warning)"
    b.mark_seen()
    assert b.badge == ""
    b.note(logging.ERROR, "connection lost")
    assert b.badge == " (1 error)"


def test_visible_text_and_clear():
    b = LogBuffer()
    b.add_fetched([E(1, logging.DEBUG), E(2, logging.INFO), E(3, logging.WARNING)], boot="b1", last_seq=3)
    assert [e.seq for e in b.visible(logging.WARNING)] == [3]
    assert [e.seq for e in b.visible()] == [2, 3]                          # default level is info
    assert [e.seq for e in b.visible(logging.DEBUG)] == [1, 2, 3]
    assert "m3" in b.text(logging.WARNING) and "m2" not in b.text(logging.WARNING)
    b.clear()
    assert b.entries == type(b.entries)([], maxlen=b.entries.maxlen) and b.last_seq == 3
    assert b.add_live([E(3)]) == []                                        # nothing shown comes back


def test_buffer_is_bounded():
    b = LogBuffer(max_lines=3)
    b.add_fetched([E(i) for i in range(1, 9)], boot="b1", last_seq=8)
    assert [e.seq for e in b.entries] == [6, 7, 8]


def test_html_is_escaped_and_coloured():
    h = entry_html(E(1, logging.ERROR, "<b>&"))
    assert "&lt;b&gt;&amp;" in h and "<b>" not in h and "color" in h
    assert "color" not in entry_html(E(1, logging.INFO))
