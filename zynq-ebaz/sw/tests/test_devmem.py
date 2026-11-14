"""DevMemRegs on a regular file (no /dev/mem, no board needed)."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sadiy_ebaz.devmem import DevMemRegs  # noqa: E402


@pytest.fixture
def backing(tmp_path):
    p = tmp_path / "regs.bin"
    p.write_bytes(struct.pack("<II", 0x53410001, 0x00010000) + bytes(0x1000 - 8))
    return str(p)


def test_read_and_write_roundtrip(backing):
    with DevMemRegs(base=0, path=backing) as r:
        assert r.read(0) == 0x53410001
        assert r.read(4) == 0x00010000
        r.write(0x10, 0xDEADBEEF)
        assert r.read(0x10) == 0xDEADBEEF
    assert struct.unpack_from("<I", open(backing, "rb").read(), 0x10)[0] == 0xDEADBEEF


def test_write_masks_to_32_bit(backing):
    with DevMemRegs(base=0, path=backing) as r:
        r.write(8, 0x1_0000_0005)
        assert r.read(8) == 5


@pytest.mark.parametrize("off", [1, 2, 3, 0x1000, -4])
def test_bad_offsets_are_rejected(backing, off):
    with DevMemRegs(base=0, path=backing) as r:
        with pytest.raises(ValueError):
            r.read(off)


def test_unaligned_base_is_rejected(backing):
    with pytest.raises(ValueError):
        DevMemRegs(base=0x43C00004, path=backing)
