import json

import pytest

from sadiy import config, patterns, pinmap
from sadiy.server.bench import Bench, fake_backend
from sadiy.server.sweepd import Sweepd
from sadiy.ui import bench_core as core

LIMITS = {"max_writes_per_s": 3000.0, "max_spi_words_per_s": 1000.0}


class Harness:
    def __init__(self, answer=True, running=False):
        cfg = config.load()
        self.backend = fake_backend()
        self.daemon = Sweepd(cfg, None, Bench(self.backend, cfg))
        self.daemon.running = running
        self.asked = []
        self.answer = answer
        self.session = core.BenchSession(self._request, self._ask)

    def _request(self, cmd):
        return json.loads(json.dumps(self.daemon.apply(json.loads(json.dumps(cmd)))))

    def _ask(self, text):
        self.asked.append(text)
        return self.answer


@pytest.fixture
def h():
    harness = Harness()
    assert harness.session.open(lambda: pytest.fail("no sweep is running"))["ok"]
    return harness


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("text, word", [("0x00580005", 0x00580005), ("580005", 0x580005), (" 0058_0005 ", 0x580005), ("FFFFFFFF", 0xFFFFFFFF)])
def test_parse_word(text, word):
    assert core.parse_word(text) == word


@pytest.mark.parametrize("text", ["", "zz", "100000000"])
def test_parse_word_rejects(text):
    with pytest.raises(ValueError):
        core.parse_word(text)


def test_init_sequence_checks_the_address_bits():
    good = ["5", "4", "3", "2", "1", "0"]
    assert core.init_sequence(good) == [5, 4, 3, 2, 1, 0]
    with pytest.raises(ValueError, match="R4"):
        core.init_sequence(["5", "3", "3", "2", "1", "0"])
    with pytest.raises(ValueError):
        core.init_sequence(good[:5])


# ---------------------------------------------------------------- pin text
def test_describe_pin_has_net_board_pin_gpio_and_notes():
    text = core.describe_pin(pinmap.PINS["P8.7"])
    assert all(s in text for s in ("P8.7", "ATT_V1", "PE4302 V1", "66", "confirm", "pe4302-walk"))
    assert "display-only" in core.describe_pin(pinmap.PINS["P9.1"])
    assert "AIN0" in core.describe_pin(pinmap.PINS["P9.39"])
    assert "Expert" in core.describe_pin(pinmap.PINS["P9.15"])


# ---------------------------------------------------------------- preview
def test_waveform_one_line_per_signal():
    lines = core.waveform(patterns.walking(["A", "B"]))
    assert lines == ["A _‾__", "B __‾_"]


def test_waveform_is_cut_off_with_a_note():
    lines = core.waveform(patterns.square_wave("A", cycles=100), max_steps=8)
    assert lines[0].count("‾") == 4 and "first 8 of 200" in lines[-1]


def test_max_rate_is_lower_when_a_step_writes_more_lines():
    assert core.max_rate_hz(patterns.square_wave("A"), LIMITS) == 3000.0
    walk = patterns.walking(["A", "B", "C", "D"])          # about two writes per step
    assert core.max_rate_hz(walk, LIMITS) < 2000.0
    spi = patterns.from_spec({"kind": "adf4351_frame", "words": [5]})
    assert core.max_rate_hz(spi, LIMITS) == 1000.0
    assert core.max_rate_hz(walk, None) is None


def test_preview_states_the_rate_honestly():
    p = patterns.square_wave("A")
    text = core.preview_text(p, 100.0, LIMITS)
    assert "about 3000 steps/s" in text and "estimate" in text and "WARNING" not in text
    assert "WARNING" in core.preview_text(p, 50000.0, LIMITS)
    assert "looping" in core.preview_text(p, 100.0, LIMITS, loop=True)


def test_preview_of_a_spi_frame_lists_the_words():
    p = patterns.from_spec({"kind": "adf4351_frame", "words": [0x00580005]})
    assert "0x00580005  (R5)" in core.preview_text(p, 10.0)


# ---------------------------------------------------------------- session
def test_open_asks_before_stopping_a_sweep():
    h = Harness(running=True)
    r = h.session.open(lambda: False)
    assert not r["ok"] and r["cancelled"] and not h.session.active and h.daemon.running

    def stop():
        h.daemon.apply({"cmd": "stop"})
        return True

    assert h.session.open(stop)["ok"] and h.session.active


def test_no_reply_is_an_error_not_a_crash():
    session = core.BenchSession(lambda cmd: None, lambda text: True)
    assert not session.open(lambda: True)["ok"]
    assert "No reply" in session.poll()["error"]


def test_confirm_is_asked_once_per_pin(h):
    assert h.session.drive("P8.7", 0)["ok"]
    assert h.session.drive("P8.7", 1)["ok"]
    assert len(h.asked) == 1
    assert h.session.drive("P8.8", 0)["ok"]
    assert len(h.asked) == 2


def test_refused_confirm_leaves_the_pin_alone():
    h = Harness(answer=False)
    h.session.open(lambda: True)
    r = h.session.drive("P8.7", 0)
    assert not r["ok"] and r["cancelled"]
    assert h.daemon.bench._lines["P8.7"].read() == 1


def test_confirm_is_forgotten_when_the_mode_closes(h):
    h.session.drive("P8.7", 0)
    h.session.close()
    h.session.open(lambda: True)
    h.session.drive("P8.7", 0)
    assert len(h.asked) == 2


def test_rf_confirm_is_never_remembered(h):
    h.session.send_words([0])                              # R0: the fake locks
    assert h.session.set_rf(True, False, -4)["ok"]
    assert h.session.set_rf(True, False, -1)["ok"]
    assert sum("RF output" in q for q in h.asked) == 2


def test_expert_flag_follows_the_checkbox(h):
    assert not h.session.drive("P9.15", 1)["ok"]
    h.session.expert = True
    assert h.session.drive("P9.15", 1)["ok"]


def test_poll_sees_levels_and_notices_a_closed_mode(h):
    h.session.drive("P8.7", 0)
    assert h.session.poll()["ok"]
    assert h.session.level("P8.7") == (0, "out")
    assert h.session.level("P9.22") == (None, "bus")
    assert h.session.level("P9.1") == (None, None)
    h.daemon.bench.close("no command from the client for 5 s")
    r = h.session.poll()
    assert r["closed"] and "no command" in r["error"] and not h.session.active
    assert h.session.level("P8.7") == (None, None)


def test_close_when_not_open_sends_nothing():
    session = core.BenchSession(lambda cmd: pytest.fail("nothing to send"), lambda text: True)
    assert session.close()["ok"]


def test_pattern_through_the_session_uses_one_confirm(h):
    spec = {"kind": "walking", "signals": ["ATT_V1", "ATT_V2"]}
    assert h.session.start_pattern(spec, 100.0, False)["ok"]
    assert h.session.stop_pattern()["ok"]
    assert h.session.start_pattern(spec, 100.0, False)["ok"]
    assert len(h.asked) == 1


def test_session_preview_equals_daemon_pattern(h):
    spec = {"kind": "pe4302_stages", "mode": "one_out"}
    p = h.session.build_pattern(spec)
    assert h.session.start_pattern(spec, 100.0, False)["ok"]
    assert h.daemon.bench._run.pattern.edges == p.edges


# ---------------------------------------------------------------- board layout
def test_pins_are_laid_out_like_the_diagrams():
    x1, y1, _, _ = core.pin_rect(pinmap.PINS["P8.1"])
    x2, y2, _, _ = core.pin_rect(pinmap.PINS["P8.2"])
    x45, y45, _, _ = core.pin_rect(pinmap.PINS["P8.45"])
    assert y1 == y2 and x1 < x2                            # odd left, even right, same row
    assert y45 > y1 and x45 == x1                          # pin 1 at the top
    assert core.pin_rect(pinmap.PINS["P9.1"])[0] > x2      # P8 left, P9 right


def test_every_pin_is_hit_at_its_centre_and_nothing_overlaps():
    for pin in pinmap.PINS.values():
        x, y, w, h = core.pin_rect(pin)
        assert core.hit_test(x + w / 2, y + h / 2) == pin.id
        assert 0 <= x and x + w <= core.CANVAS_W and 0 <= y and y + h <= core.CANVAS_H


def test_block_rows_select_their_pin():
    for block in core.blocks():
        for row in block.rows:
            x, y, w, h = row.rect
            assert core.hit_test(x + w / 2, y + h / 2) == row.pin_id


def test_empty_space_hits_nothing():
    assert core.hit_test(1, 1) is None


def test_blocks_fit_and_every_net_has_a_wire():
    for block in core.blocks():
        x, y, w, h = block.rect
        assert x >= 0 and x + w <= core.CANVAS_W and y + h <= core.CANVAS_H - 40
    assert {w.net for w in core.wires()} == {n for b in pinmap.BOARDS for n in b.nets}


def test_inner_column_wires_run_in_the_row_gap():
    by_net = {w.net: w for w in core.wires()}
    outer = by_net["ATT_V1"].points                        # P8.7, odd: left column, toward the PE4302 on the left
    inner = by_net["ATT_V2"].points                        # P8.8, even: must pass under P8.7
    assert outer[0][1] == outer[1][1]
    assert inner[1][1] > inner[0][1]
    x, y, w, h = core.pin_rect(pinmap.PINS["P8.7"])
    assert inner[1][1] > y + h                             # below the neighbouring pin, not through it


def test_every_category_has_a_colour_and_a_legend_entry():
    for pin in pinmap.PINS.values():
        assert pin.category in core.CATEGORY_COLOURS
    assert {k for k, _ in core.CATEGORY_LABELS} == set(core.CATEGORY_COLOURS)


def test_blocks_do_not_overlap():
    rects = [b.rect for b in core.blocks()]
    for i, (x, y, w, h) in enumerate(rects):
        for x2, y2, w2, h2 in rects[i + 1:]:
            assert x + w <= x2 or x2 + w2 <= x or y + h <= y2 or y2 + h2 <= y
