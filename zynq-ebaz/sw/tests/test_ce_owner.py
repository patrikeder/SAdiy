"""Who owns ADF4351 CE: the engine while STATUS.pin_owner_act = 1 (map with the CE mux), Linux otherwise."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sadiy_ebaz import ce_owner  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS, Reg  # noqa: E402


def test_the_current_map_has_the_ce_mux():
    assert ce_owner.has_ce_mux()
    assert "ce" in REGS["ADF_PINS"].fields and "pin_owner_act" in REGS["STATUS"].fields


def test_probe_follows_pin_owner_act():
    word = [0]
    reads = []

    def read(offset):
        reads.append(offset)
        return 0x00010002 if offset == REGS["VERSION"].offset else word[0]

    owned = ce_owner.ce_owner_probe(read)
    assert owned() is False
    word[0] = REGS["STATUS"].fields["pin_owner_act"].put(1)
    assert owned() is True
    word[0] = ~REGS["STATUS"].fields["pin_owner_act"].mask & 0xFFFFFFFF          # every other status bit set
    assert owned() is False
    assert set(reads) == {REGS["STATUS"].offset, REGS["VERSION"].offset}
    assert reads.count(REGS["VERSION"].offset) == 1                  # the bitstream is asked once


def test_a_map_1_0_bitstream_has_no_mux_even_with_a_newer_regmap():
    status = REGS["STATUS"].fields["pin_owner_act"].put(1)
    old_core = ce_owner.ce_owner_probe(lambda o: 0x00010000 if o == REGS["VERSION"].offset else status)
    assert old_core() is False
    new_core = ce_owner.ce_owner_probe(lambda o: 0x00010001 if o == REGS["VERSION"].offset else status)
    assert new_core() is True


def test_an_old_map_without_the_mux_means_linux_always_owns():
    old = {k: v for k, v in REGS.items() if k != "ADF_PINS"}
    assert not ce_owner.has_ce_mux(old)
    assert ce_owner.ce_owner_probe(lambda _o: 0xFFFFFFFF, old)() is False
    stripped = dict(REGS, STATUS=Reg("STATUS", REGS["STATUS"].offset, REGS["STATUS"].ext,
                                     {k: v for k, v in REGS["STATUS"].fields.items() if k != "pin_owner_act"}))
    assert not ce_owner.has_ce_mux(stripped)
