"""Who owns ADF4351 CE: the probe reads STATUS.ce_engine, and a map without that bit means Linux always."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sadiy_ebaz import ce_owner  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS, Field, Reg  # noqa: E402


def with_mux():
    status = REGS["STATUS"]
    fields = dict(status.fields, ce_engine=Field("ce_engine", 20, 1, "ro", 0))
    return dict(REGS, STATUS=Reg("STATUS", status.offset, status.ext, fields))


def test_the_current_map_has_no_ce_mux_so_linux_always_owns():
    assert not ce_owner.has_ce_mux()
    assert ce_owner.ce_owner_probe(lambda _o: 0xFFFFFFFF)() is False       # even with every status bit set


def test_probe_follows_the_status_bit():
    regs = with_mux()
    assert ce_owner.has_ce_mux(regs)
    word = [0]
    reads = []

    def read(offset):
        reads.append(offset)
        return word[0]

    owned = ce_owner.ce_owner_probe(read, regs)
    assert owned() is False
    word[0] = 1 << 20
    assert owned() is True
    assert set(reads) == {REGS["STATUS"].offset}
