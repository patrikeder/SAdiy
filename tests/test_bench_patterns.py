import pytest

from sadiy import patterns, pinmap
from sadiy.patterns import Edge


def levels_per_step(p):
    level = dict(p.idle)
    out = []
    for group in patterns.step_groups(p):
        for e in group:
            level[e.signal] = e.level
        out.append(dict(level))
    return out


def test_walking_one_has_one_line_high_per_step_and_ends_idle():
    p = patterns.walking(["A", "B", "C"])
    steps = levels_per_step(p)
    assert [sum(s.values()) for s in steps] == [1, 1, 1, 0]
    assert [next(k for k, v in s.items() if v) for s in steps[:3]] == ["A", "B", "C"]


def test_walking_zero_is_the_inverse():
    p = patterns.walking(["A", "B"], active=0)
    assert p.idle == {"A": 1, "B": 1}
    assert [sum(s.values()) for s in levels_per_step(p)] == [1, 1, 2]


def test_walking_cycles_repeat():
    assert len(patterns.step_groups(patterns.walking(["A", "B"], cycles=3))) == 7


def test_walking_writes_rising_line_first():
    p = patterns.walking(["A", "B"])
    assert patterns.step_groups(p)[1] == [Edge("B", 1), Edge("A", 0)]


def test_square_wave_two_steps_per_period():
    p = patterns.square_wave("A", cycles=2)
    assert [e.level for e in p.edges] == [1, 0, 1, 0]
    assert p.idle == {"A": 0}


def test_binary_counter_counts_lsb_first_and_returns_to_zero():
    steps = levels_per_step(patterns.binary_counter(["A", "B"]))
    assert [(s["A"], s["B"]) for s in steps] == [(1, 0), (0, 1), (1, 1), (0, 0)]


def test_binary_counter_refuses_huge_patterns():
    with pytest.raises(ValueError, match="steps"):
        patterns.binary_counter([f"S{i}" for i in range(20)])


@pytest.mark.parametrize("mode, low", [("one_out", 15.5), ("one_in", 0.5)])
def test_stage_sweep_uses_the_driver_and_ends_safe(mode, low):
    nets = pinmap.ATT_NETS
    p = patterns.pe4302_stage_sweep(nets, mode=mode)
    assert p.idle == {n: 1 for n in nets}
    assert levels_per_step(p)[-1] == {n: 1 for n in nets}
    assert patterns.lowest_attenuation(p, nets) == low


def test_stage_sweep_one_out_never_drops_below_its_own_steps():
    nets = pinmap.ATT_NETS
    p = patterns.pe4302_stage_sweep(nets, mode="one_out")
    first = patterns.step_groups(p)[0]             # 31.5 -> 31: only V1 goes out
    assert first == [Edge("ATT_V1", 0)]
    assert all(g[0].level == 1 or len(g) == 1 for g in patterns.step_groups(p))   # make before break


def test_lowest_attenuation_keeps_other_stages_at_safe():
    p = patterns.square_wave("ATT_V6")
    assert patterns.lowest_attenuation(p, pinmap.ATT_NETS) == 15.5     # only the 16 dB stage moves
    assert patterns.lowest_attenuation(patterns.square_wave("P8.13"), pinmap.ATT_NETS) is None


def test_from_spec_warns_when_attenuation_gets_low():
    p = patterns.from_spec({"kind": "walking", "signals": list(pinmap.ATT_NETS)}, pinmap.ATT_NETS)
    assert any("keep RF off" in n for n in p.notes)


def test_from_spec_adf4351_frame_repeats_words():
    p = patterns.from_spec({"kind": "adf4351_frame", "words": [0x00580005], "repeat": 3})
    assert p.spi_words == [0x00580005] * 3
    assert patterns.decode_spi(p.edges, p.idle) == [bytes.fromhex("00580005")] * 3


@pytest.mark.parametrize("spec", [
    {"kind": "nope"},
    {"kind": "walking", "signals": []},
    {"kind": "square", "signals": ["A", "B"]},
    {"kind": "walking", "signals": ["A"], "cycles": 0},
    {"kind": "walking", "signals": ["A"], "active": 2},
    {"kind": "adf4351_frame", "words": []},
    {"kind": "adf4351_frame", "words": [1 << 32]},
    {"kind": "pe4302_stages", "mode": "both"},
])
def test_from_spec_rejects(spec):
    with pytest.raises(ValueError):
        patterns.from_spec(spec, pinmap.ATT_NETS)


def test_csv_of_a_bench_pattern_is_per_edge():
    rows = patterns.to_csv(patterns.walking(["A", "B"])).strip().splitlines()
    assert rows[0] == "step,A,B"
    assert rows[1] == "0,0,0"
    assert rows[-1] == "4,0,0"
