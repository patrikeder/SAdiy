"""Golden vectors: committed, current, well formed, and the make-before-break rule equals the driver."""
import importlib.util
import re
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[1] / "sim"
VEC = SIM / "vectors"
spec = importlib.util.spec_from_file_location("gen_vectors", SIM / "gen_vectors.py")
gv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gv)


def lines(name):
    return (VEC / name).read_text().splitlines()


def test_check_passes_vectors_are_committed_and_current():
    assert gv.main(["--check"]) == 0


def test_generation_is_deterministic():
    assert gv.build_files() == gv.build_files()


@pytest.mark.parametrize("name,count,width", [
    ("spi_words.hex", 16 * 6 + 5, 8), ("spi_words.cnt", 1, 8), ("mbb_high.hex", 4096, 5),
    ("mbb_low.hex", 4096, 5), ("sweep_unlock.hex", 24, 1), ("sweep_result.hex", 24, 8),
    ("sweep_meta.hex", 6, 8),
])
def test_line_counts_and_widths(name, count, width):
    ls = lines(name)
    assert len(ls) == count
    assert all(re.fullmatch(rf"[0-9A-F]{{{width}}}", x) for x in ls), name


def test_sweep_files_agree_with_each_other():
    meta = [int(x, 16) for x in lines("sweep_meta.hex")]
    n_entries, n_results, n_avg, base, att, n_spi = meta
    assert (n_results, n_avg, base, att) == (24, 4, 0x100, 0x15)
    table = lines("sweep_table.hex")
    assert len(table) == n_entries and all(re.fullmatch(r"[0-9A-F]{16}", x) for x in table)
    assert len(lines("sweep_spi.hex")) == n_spi
    table_words = [int(x, 16) for x in table]
    assert [w & 0xFFFFFFFF for w in table_words if w >> 40 & 1] == [int(x, 16) for x in lines("sweep_spi.hex")]
    assert sum(1 for w in table_words if w >> 42 & 1) == n_results             # measure entries
    assert table_words[0] >> 41 & 1 and table_words[0] >> 32 & 0x3F == att      # att_en + att on entry 0
    unlock = [int(x) for x in lines("sweep_unlock.hex")]
    assert [i for i, u in enumerate(unlock) if u] == [5, 17]
    for i, word in enumerate(int(x, 16) for x in lines("sweep_result.hex")):
        assert word >> 31 == unlock[i]
        assert word & 0x7FFFFFFF == 4 * (0x100 + i)


def test_spi_words_end_with_the_corner_words():
    ls = lines("spi_words.hex")
    assert ls[-5:] == ["00000000", "FFFFFFFF", "AAAAAAAA", "55555555", "80000001"]
    assert int(lines("spi_words.cnt")[0], 16) == len(ls)
    assert [int(x, 16) & 7 for x in ls[:6]] == [5, 4, 3, 2, 1, 0]


def split(value):
    return value >> 12 & 63, value >> 6 & 63, value & 63


def test_mbb_high_make_is_old_or_new():
    for idx, text in enumerate(lines("mbb_high.hex")):
        old, new, make = split(int(text, 16))
        assert (old, new) == divmod(idx, 64)
        assert make == old | new, idx


def test_mbb_low_make_is_old_and_new():
    for idx, text in enumerate(lines("mbb_low.hex")):
        old, new, make = split(int(text, 16))
        assert (old, new) == divmod(idx, 64)
        assert make == old & new, idx
