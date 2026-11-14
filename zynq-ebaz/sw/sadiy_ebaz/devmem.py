"""32-bit register access to the PL sweep core through /dev/mem (lane L, S7).

`DevMemRegs(base).read` / `.write` are the `reg_read(offset)` / `reg_write(offset, value)` callables that
`RegOffload` takes. No UIO driver and no interrupt: completion is polled (STATUS.done).

The kernel needs CONFIG_DEVMEM=y and CONFIG_STRICT_DEVMEM unset (both true in the ebaz4205_sadiy image).
Only touch the core after the bitstream is loaded: an AXI access to an unconfigured PL range stalls the CPU.
`path` may be a regular file for tests.
"""
from __future__ import annotations

import mmap
import os

DEFAULT_BASE = 0x43C00000   # M_AXI_GP0, fixed in the Vivado address map (handover-F2)
DEFAULT_SIZE = 0x1000
PAGE = mmap.PAGESIZE


class DevMemRegs:
    def __init__(self, base: int = DEFAULT_BASE, size: int = DEFAULT_SIZE, path: str = "/dev/mem") -> None:
        if base % PAGE:
            raise ValueError(f"base 0x{base:X} is not page aligned")
        if size <= 0 or size % 4:
            raise ValueError("size must be a positive multiple of 4")
        self.base, self.size = base, size
        self._fd = os.open(path, os.O_RDWR | os.O_SYNC)
        try:
            self._mm = mmap.mmap(self._fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                                 offset=base)
        except Exception:
            os.close(self._fd)
            raise
        self._w = memoryview(self._mm).cast("I")   # one aligned 32-bit access per item

    def _index(self, offset: int) -> int:
        if offset % 4 or not 0 <= offset < self.size:
            raise ValueError(f"bad register offset 0x{offset:X}")
        return offset >> 2

    def read(self, offset: int) -> int:
        return self._w[self._index(offset)]

    def write(self, offset: int, value: int) -> None:
        self._w[self._index(offset)] = value & 0xFFFFFFFF

    def close(self) -> None:
        self._w.release()
        self._mm.close()
        os.close(self._fd)

    def __enter__(self) -> "DevMemRegs":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
