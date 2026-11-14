"""SweepOffload on top of two register access callables: the same code runs on the PL model and on the real
core (UIO mmap). Software sequence of `rtl-spec.md` section 9.

    reg_read(offset) -> int          32-bit read of the core's register at byte `offset`
    reg_write(offset, value) -> None 32-bit write

Offsets and field positions come from regmap.toml (`regmap_toml`).
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Sequence

from .platform import OffloadResult, TableEntry
from .regmap_toml import REGS

ID_MAGIC = 0x53410001
SUPPORTED_MAJOR = 1
SRC_PUSH = 0
MAX_N_AVG = 4095


def _off(name: str) -> int:
    return REGS[name].offset


def _fld(reg: str, name: str):
    return REGS[reg].fields[name]


class RegOffload:
    def __init__(
        self,
        reg_read: Callable[[int], int],
        reg_write: Callable[[int, int], None],
        *,
        sample_source: Optional[Callable[[], int]] = None,
        volts_per_count: float = 4.096 / 32768.0,
        det_src: Optional[int] = None,
        det_test_base: Optional[int] = None,
        stop_on_err: bool = False,
        poll_s: float = 0.001,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`sample_source() -> int` returns one raw 16-bit detector code; used when DET_CFG.src = 0 (the PS
        pushes the samples). `det_src` / `det_test_base` are written to DET_CFG / DET_TEST when given.
        `volts_per_count` converts a detector code to volts. Raises RuntimeError when the core is not ours."""
        self._rd, self._wr = reg_read, reg_write
        self.sample_source = sample_source
        self.volts_per_count = volts_per_count
        self._poll_s, self._sleep, self._clock = poll_s, sleep, clock
        magic = self._rd(_off("ID"))
        if magic != ID_MAGIC:
            raise RuntimeError(f"not a SAdiy sweep core: ID register reads 0x{magic:08X}, expected 0x{ID_MAGIC:08X}")
        version = self._rd(_off("VERSION"))
        if version >> 16 != SUPPORTED_MAJOR:
            raise RuntimeError(f"sweep core register map version {version >> 16}.{version & 0xFFFF}, "
                               f"this software supports major {SUPPORTED_MAJOR}")
        caps = self._rd(_off("CAPS"))
        self.max_entries = 1 << _fld("CAPS", "table_aw").get(caps)
        self.max_points = 1 << _fld("CAPS", "result_aw").get(caps)
        self.clk_hz = _fld("CAPS", "clk_mhz").get(caps) * 1_000_000
        self._n_entries = 0
        self._n_measure = 0
        self._set_ctrl_bits(stop_on_err=int(stop_on_err))
        if det_src is not None:
            self._wr(_off("DET_CFG"), _fld("DET_CFG", "src").put(det_src))
        if det_test_base is not None:
            self._wr(_off("DET_TEST"), _fld("DET_TEST", "base").put(det_test_base))

    # ---- helpers ----------------------------------------------------------------------------------------------
    def _status(self) -> dict:
        v = self._rd(_off("STATUS"))
        return {name: f.get(v) for name, f in REGS["STATUS"].fields.items()}

    def _ctrl_rw(self) -> int:
        """Current rw bits of CTRL (pulse bits read 0), to write back unchanged."""
        return self._rd(_off("CTRL"))

    def _set_ctrl_bits(self, **fields: int) -> None:
        v = self._ctrl_rw()
        for name, value in fields.items():
            f = _fld("CTRL", name)
            v = (v & ~f.mask) | f.put(value)
        self._wr(_off("CTRL"), v)

    def _pulse(self, name: str) -> None:
        self._wr(_off("CTRL"), self._ctrl_rw() | _fld("CTRL", name).mask)

    def _src(self) -> int:
        return _fld("DET_CFG", "src").get(self._rd(_off("DET_CFG")))

    # ---- pins -------------------------------------------------------------------------------------------------
    def acquire_pins(self) -> None:
        """Hand the ADF4351 SPI pins and the PE4302 pins to the engine. The engine starts from the levels the
        PE4302 pins show now (PIN_STATE.pe_in), so the change is seamless. Only while idle."""
        pe = _fld("PIN_STATE", "pe_in").get(self._rd(_off("PIN_STATE")))
        manual = _fld("PE4302", "manual")
        cur = self._rd(_off("PE4302"))
        self._wr(_off("PE4302"), (cur & ~manual.mask) | manual.put(pe))
        self._set_ctrl_bits(pin_owner=1)
        if not self._status()["pin_owner_act"]:
            raise RuntimeError("the engine did not take the pins (sweep running?)")

    def pin_levels(self) -> int:
        """PE4302 levels the engine drives now (meaningful while it owns the pins)."""
        return _fld("PIN_STATE", "pe_out").get(self._rd(_off("PIN_STATE")))

    def release_pins(self) -> None:
        """Give the pins back to the PS. Call only when the PS GPIO lines already drive `pin_levels()`
        and the PS SPI is idle."""
        self._set_ctrl_bits(pin_owner=0)

    def set_att_pins(self, levels: int) -> None:
        """Change the engine's PE4302 state (make-before-break), while it owns the pins and is idle."""
        manual = _fld("PE4302", "manual")
        cur = self._rd(_off("PE4302"))
        self._wr(_off("PE4302"), (cur & ~manual.mask) | manual.put(levels))

    # ---- SweepOffload -----------------------------------------------------------------------------------------
    def upload(self, entries: Sequence[TableEntry]) -> None:
        if len(entries) > self.max_entries:
            raise ValueError(f"{len(entries)} table entries, the core holds {self.max_entries}")
        n_measure = sum(1 for e in entries if e.measure)
        if n_measure > self.max_points:
            raise ValueError(f"{n_measure} measured points, the core stores {self.max_points}")
        self._wr(_off("TABLE_ADDR"), 0)
        for e in entries:
            self._wr(_off("TABLE_W0"), e.w0())
            self._wr(_off("TABLE_W1"), e.w1())
        if self._rd(_off("TABLE_ADDR")) != len(entries):
            raise RuntimeError("table upload was not accepted (sweep running?)")
        self._n_entries, self._n_measure = len(entries), n_measure

    def run(self, n_avg: int, timeout_s: float = 10.0) -> OffloadResult:
        if not 1 <= n_avg <= MAX_N_AVG:
            raise ValueError(f"n_avg must be 1..{MAX_N_AVG}")
        src = self._src()
        if src == SRC_PUSH and self.sample_source is None:
            raise RuntimeError("DET_CFG.src = 0 (PS push) needs a sample_source")
        if not self._status()["pin_owner_act"]:
            self.acquire_pins()
        self._wr(_off("N_ENTRIES"), self._n_entries)
        self._wr(_off("N_AVG"), n_avg)
        self._pulse("start")
        deadline = self._clock() + timeout_s
        while True:
            st = self._status()
            if st["done"] and not st["busy"]:
                break
            if st["wait_sample"] and src == SRC_PUSH:
                for _ in range(n_avg):
                    self._wr(_off("DET_PUSH"), self.sample_source() & 0xFFFF)
                continue
            if self._clock() >= deadline:
                self.abort()
                raise TimeoutError(f"sweep did not finish within {timeout_s} s (state {st['state']})")
            self._sleep(self._poll_s)
        if st["err_table"]:
            raise RuntimeError(f"sweep refused or result memory full (N_ENTRIES={self._n_entries}, "
                               f"pin_owner_act={st['pin_owner_act']})")
        count = _fld("POINT_COUNT", "count").get(self._rd(_off("POINT_COUNT")))
        self._wr(_off("RESULT_ADDR"), 0)
        words = [self._rd(_off("RESULT_DATA")) for _ in range(count)]
        return OffloadResult.from_result_words(words, n_avg, aborted=bool(st["aborted"]),
                                               err_table=False, err_lock=bool(st["err_lock"]))

    def abort(self) -> None:
        self._pulse("abort")

    def soft_reset(self) -> None:
        self._pulse("soft_reset")

    def status(self) -> dict:
        st = self._status()
        for reg, key in (("POINT_COUNT", "point_count"), ("SWEEP_COUNT", "sweep_count"),
                         ("ENTRY_INDEX", "entry_index"), ("FIRST_ERR_INDEX", "first_err_index")):
            st[key] = self._rd(_off(reg)) & ((1 << 32) - 1 if reg == "SWEEP_COUNT" else 0xFFFF)
        return st

    def counts_to_volts(self, mean_count: float) -> float:
        return mean_count * self.volts_per_count
