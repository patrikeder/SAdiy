import itertools

import pytest

from sadiy.drivers.pe4302 import PE4302
from sadiy.hal.fake import FakeGpio, PinLog
from sadiy.patterns import Edge, ParallelModel, pe4302_parallel


def make(weights=(0.5, 1.0, 2.0, 4.0, 8.0, 16.0), active_high=True):
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(len(weights))]
    dev = PE4302(lines, weights, active_high)
    return dev, lines, log


def levels(lines):
    return [ln.level for ln in lines]


def test_safe_state_at_construction():
    dev, lines, _ = make()
    assert levels(lines) == [1] * 6
    assert dev.attenuation_db == 31.5 == dev.max_db


def test_mapping_of_known_values():
    dev, lines, _ = make()
    assert dev.set_attenuation(10.0) == 10.0          # 8 dB (V5) + 2 dB (V3)
    assert levels(lines) == [0, 0, 1, 0, 1, 0]
    assert dev.set_attenuation(0.5) == 0.5
    assert levels(lines) == [1, 0, 0, 0, 0, 0]
    assert dev.set_attenuation(31.5) == 31.5
    assert levels(lines) == [1] * 6


def test_rounding_and_clamping():
    dev, _, _ = make()
    assert dev.set_attenuation(0.3) == 0.5
    assert dev.set_attenuation(0.2) == 0.0
    assert dev.set_attenuation(99) == 31.5
    assert dev.set_attenuation(-5) == 0.0
    assert dev.code_for(15.76) == 32


def test_active_low_and_reordered_weights():
    dev, lines, _ = make(weights=(16.0, 8.0, 4.0, 2.0, 1.0, 0.5), active_high=False)
    assert levels(lines) == [0] * 6                   # safe state, active low
    dev.set_attenuation(10.0)                         # 8 dB (V2) + 2 dB (V4) switched in = low
    assert levels(lines) == [1, 0, 1, 0, 1, 1]
    assert dev.attenuation_db == 10.0


def test_weight_validation():
    log = PinLog()
    lines = [FakeGpio(f"V{i}", log) for i in range(3)]
    with pytest.raises(ValueError):
        PE4302(lines, (0.5, 1.0))                     # wrong count
    with pytest.raises(ValueError):
        PE4302(lines, (0.5, 1.0, 3.0))                # 3 dB is not 0.5 x a power of two
    with pytest.raises(ValueError):
        PE4302(lines, (0.5, 1.0, 1.0))                # duplicate


def test_fewer_stages_clamps_to_their_total():
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(3)]
    dev = PE4302(lines, (0.5, 1.0, 2.0))
    assert dev.max_db == 3.5
    assert dev.set_attenuation(20) == 3.5


def test_never_below_the_lower_of_old_and_new():
    """Every one of the 64 x 64 transitions: no intermediate state is less attenuating than
    min(old, new), so there is no momentary 0 dB between two high settings."""
    codes = range(64)
    for old, new in itertools.product(codes, codes):
        p = pe4302_parallel(new * 0.5, from_db=old * 0.5)
        m = ParallelModel(p.idle)
        assert m.attenuation_db == old * 0.5
        seen = [m.attenuation_db]
        for e in p.edges:
            m.feed(e)
            seen.append(m.attenuation_db)
        assert seen[-1] == new * 0.5
        assert min(seen) >= min(old, new) * 0.5, (old, new, seen)


def test_naive_order_would_glitch():
    # documents why the order matters: clearing V5 (8 dB) before setting V6 (16 dB) on 15.5 -> 16 dB
    m = ParallelModel({"V1": 1, "V2": 1, "V3": 1, "V4": 1, "V5": 1, "V6": 0})
    assert m.attenuation_db == 15.5
    m.feed(Edge("V1", 0)); m.feed(Edge("V2", 0)); m.feed(Edge("V3", 0)); m.feed(Edge("V4", 0)); m.feed(Edge("V5", 0))
    assert m.attenuation_db == 0.0                    # naive: passes through 0 dB
    p = pe4302_parallel(16.0, from_db=15.5)
    m2 = ParallelModel(p.idle)
    lowest = m2.attenuation_db
    for e in p.edges:
        m2.feed(e)
        lowest = min(lowest, m2.attenuation_db)
    assert lowest == 15.5                             # the driver never drops below the old value here
