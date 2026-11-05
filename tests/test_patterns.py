import pytest

from sadiy import patterns
from sadiy.patterns import Edge


def test_parallel_pattern_from_safe_state():
    p = patterns.pe4302_parallel(10.0)
    assert p.idle == {f"V{i}": 1 for i in range(1, 7)}               # starts with every stage in
    assert patterns.replay(p).attenuation_db == 10.0 == p.expected_db
    # nothing needs to switch in from the safe state, so only turn-offs are written
    assert all(e.level == 0 for e in p.edges)
    assert {e.signal for e in p.edges} == {"V1", "V2", "V4", "V6"}


def test_parallel_pattern_make_before_break():
    p = patterns.pe4302_parallel(16.0, from_db=15.5)
    steps = patterns.attenuation_steps(p)
    assert steps[0] == 15.5 and steps[-1] == 16.0
    assert min(steps) >= 15.5
    assert p.edges[0] == Edge("V6", 1)                                # the 16 dB stage goes in first


def test_active_low_pattern():
    p = patterns.pe4302_parallel(10.0, from_db=0.0, active_high=False)
    assert p.idle == {f"V{i}": 1 for i in range(1, 7)}               # 0 dB, active low: all out = high
    assert patterns.replay(p).attenuation_db == 10.0


@pytest.mark.parametrize("db", [c * 0.5 for c in range(64)])
def test_every_setting_reads_back(db):
    assert patterns.replay(patterns.pe4302_parallel(db)).attenuation_db == db
    assert patterns.replay(patterns.pe4302_parallel(db, from_db=0.0)).attenuation_db == db


def test_adf4351_frames_and_csv():
    p = patterns.adf4351_words([0x00580005, 0x00A5003C])
    assert patterns.decode_spi(p.edges, p.idle) == [bytes.fromhex("00580005"), bytes.fromhex("00a5003c")]
    rows = patterns.to_csv(p).strip().splitlines()
    assert rows[0] == "step,CS,SCLK,MOSI"
    assert rows[1] == "0,1,0,0"
    assert len(rows) == 2 + len(p.edges)


def test_attenuator_csv_columns():
    rows = patterns.to_csv(patterns.pe4302_parallel(10.0)).strip().splitlines()
    assert rows[0] == "step,V1,V2,V3,V4,V5,V6"
    assert rows[1] == "0,1,1,1,1,1,1"
    assert rows[-1] == "4,0,0,1,0,1,0"                               # V3 and V5 stay in = 2 + 8 dB


def test_describe_runs():
    text = "\n".join(patterns.describe(patterns.pe4302_parallel(16.0, from_db=15.5)))
    assert "lowest attenuation during the change: 15.5 dB" in text
    assert "V6" in text
    assert "frame 0: 00580005" in "\n".join(patterns.describe(patterns.adf4351_words([0x00580005])))
