from sadiy.bringup import walk_lines
from sadiy.hal.fake import FakeGpio, PinLog


def run(active_high=True):
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(6)]
    said, answers = [], []
    walk_lines(lines, active_high, ask=lambda m: answers.append(m) or "", say=said.append)
    return lines, said, answers


def test_walk_switches_one_stage_at_a_time_and_ends_safe():
    lines, said, answers = run()
    assert [ln.level for ln in lines] == [1] * 6          # ends with every stage in
    assert len(answers) == 8                              # all-in, all-out, then six single lines
    assert any("V6 only" in s and "392 mV" in s for s in said)
    assert any("V1 only" in s and "12 mV" in s for s in said)


def test_walk_active_low_ends_safe():
    lines, _, _ = run(active_high=False)
    assert [ln.level for ln in lines] == [0] * 6          # active low: stages in = low


def test_walk_single_line_states():
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(6)]
    snapshots = []

    def ask(msg):
        snapshots.append([ln.level for ln in lines])
        return ""

    walk_lines(lines, True, ask=ask, say=lambda m: None)
    assert snapshots[0] == [1] * 6 and snapshots[1] == [0] * 6
    for i in range(6):
        expected = [0] * 6
        expected[i] = 1
        assert snapshots[2 + i] == expected
