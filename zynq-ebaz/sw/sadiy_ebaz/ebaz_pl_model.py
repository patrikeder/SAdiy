"""Behavioural model (transaction level, not cycle level) of the PL sweep engine register interface.

Reference: `zynq-ebaz/docs/rtl-spec.md` (the text wins over this file). Register offsets and fields come from
`regmap.toml` through `regmap_toml`. What is NOT modelled: time (the microsecond waits just take no time), the
SPI bit stream, the AXI handshakes. What is: every value the registers show, the SPI words in order, the
PE4302 pin states in order, results, flags and the pause of the sequencer while it waits for detector samples.

Test side of the model (what a testbench drives):
  lock_model(result_index, last_spi_word) -> bool    lock reached before the timeout (default: always)
  ld_now                                             level of the lock detect pin (STATUS.ld_now)
  ext_samples(result_index) -> int                   one sample of the external stream (DET_CFG.src = 2)
  emio_pe_o / emio_pe_t / pad_pe                     PS side of the PE4302 pins (used while the PS owns them)
  spi_words, pe_trace                                everything the engine put on the pins, in order

A `start` write runs the whole sweep inside `write()`, except when it must wait for detector samples that only
the caller can supply (DET_CFG.src = 0: DET_PUSH writes; src = 3 / no stream: never): then the model stays in
SAMPLE, STATUS.busy = 1, STATUS.wait_sample = 1, until enough samples have been pushed (or `abort`).
"""
from __future__ import annotations

from typing import Callable, Dict, Generator, List, Optional

from .platform import SUM_MASK, UNLOCKED_BIT, W1_USED_MASK, TableEntry
from .regmap_toml import REGS

IDLE, FETCH, ATT, SPI, WAIT_MIN, WAIT_LOCK, SETTLE, SAMPLE, STORE, NEXT = range(10)

PE_ALL_IN = 0x3F
SRC_PUSH, SRC_TEST, SRC_EXT, SRC_NONE = range(4)

_END_NORMAL, _END_STOP_ON_ERR, _END_TABLE_FULL = "normal", "stop_on_err", "table_full"


def _always_locked(result_index: int, last_spi_word: int) -> bool:
    return True


class PlModel:
    def __init__(self, table_aw: int = 12, result_aw: int = 12, clk_hz: int = 100_000_000) -> None:
        self.table_aw = table_aw
        self.result_aw = result_aw
        self.clk_hz = clk_hz
        # testbench side
        self.lock_model: Callable[[int, int], bool] = _always_locked
        self.ld_now = False
        self.ext_samples: Optional[Callable[[int], int]] = None
        self.emio_pe_o = PE_ALL_IN       # level the PS drives on the PE4302 lines
        self.emio_pe_t = PE_ALL_IN       # 1 = PS line is an input (not driven)
        self.pad_pe = PE_ALL_IN          # level the board (pull-ups) gives an undriven line
        self.emio_adf = (0, 0, 1)        # clk, dat, le as the PS drives them
        self.spi_words: List[int] = []
        self.pe_trace: List[int] = []
        self._reset()

    # ---- reset ----------------------------------------------------------------------------------------------
    def _reset(self) -> None:
        self._rw: Dict[tuple, int] = {
            (r.name, f.name): f.reset for r in REGS.values() for f in r.fields.values() if f.access == "rw"}
        self._table = [(0, 0)] * (1 << self.table_aw)
        self._results = [0] * (1 << self.result_aw)
        self._table_addr = 0
        self._result_addr = 0
        self._pe_engine = PE_ALL_IN       # reset value of the engine's PE4302 state: all stages in
        self._pin_owner_act = 0
        self._last_spi_word = 0
        self._sweep_count = 0
        self._reset_sequencer()

    def _reset_sequencer(self) -> None:
        self._gen: Optional[Generator] = None
        self._busy = False
        self._state = IDLE
        self._done = self._err_lock = self._aborted = self._err_table = False
        self._point_count = 0
        self._first_err_index = 0
        self._entry = 0
        self._samples: List[int] = []
        self._samples_needed = 1

    def soft_reset(self) -> None:
        """CTRL.soft_reset: sequencer, SPI writer and status; configuration, tables and results stay."""
        if self._gen is not None:
            self._gen.close()
        self._reset_sequencer()
        self._sweep_count = 0
        self._update_owner()

    @property
    def irq(self) -> bool:
        return bool(self._rw[("CTRL", "irq_en")] and self._done)

    # ---- bus ------------------------------------------------------------------------------------------------
    def read(self, offset: int) -> int:
        name = self._reg_at(offset)
        if name is None:
            return 0
        if name == "RESULT_DATA":
            return self._read_result_data()
        if name in ("TABLE_W1", "DET_PUSH"):
            return 0
        if name == "TABLE_ADDR":
            return self._table_addr
        if name == "RESULT_ADDR":
            return self._result_addr
        ro = self._ro_values()
        value = 0
        for f in REGS[name].fields.values():
            if f.access == "rw":
                value |= f.put(self._rw[(name, f.name)])
            elif f.access == "const":
                value |= f.put(f.reset)
            elif f.access == "ro":
                value |= f.put(ro[(name, f.name)])
        return value

    def write(self, offset: int, value: int) -> None:
        name = self._reg_at(offset)
        if name is None:
            return
        value &= 0xFFFF_FFFF
        if name == "CTRL":
            self._write_ctrl(value)
        elif name == "TABLE_ADDR":
            if not self._busy:
                self._table_addr = value & 0xFFFF
        elif name == "TABLE_W1":
            self._write_table_w1(value)
        elif name == "RESULT_ADDR":
            self._result_addr = value & 0xFFFF
        elif name == "DET_PUSH":
            self._push(value & 0xFFFF)
        elif name == "PE4302":
            self._write_pe4302(value)
        else:
            self._store_rw(name, value)

    def _store_rw(self, name: str, value: int) -> None:
        for f in REGS[name].fields.values():
            if f.access == "rw":
                self._rw[(name, f.name)] = f.get(value)

    @staticmethod
    def _reg_at(offset: int) -> Optional[str]:
        offset &= 0xFFC
        for r in REGS.values():
            if r.offset == offset:
                return r.name
        return None

    def _ro_values(self) -> Dict[tuple, int]:
        pe_out, pe_t = self._pe_pins()
        pe_in = (pe_out & ~pe_t | self.pad_pe & pe_t) & 0x3F
        clk, dat, le = (0, 0, 1) if self._engine_owns() else self.emio_adf
        return {
            ("STATUS", "busy"): int(self._busy), ("STATUS", "done"): int(self._done),
            ("STATUS", "err_lock"): int(self._err_lock), ("STATUS", "aborted"): int(self._aborted),
            ("STATUS", "ld_now"): int(self.ld_now), ("STATUS", "wait_sample"): int(self._state == SAMPLE),
            ("STATUS", "err_table"): int(self._err_table), ("STATUS", "pin_owner_act"): self._pin_owner_act,
            ("STATUS", "state"): self._state,
            ("PIN_STATE", "pe_in"): pe_in, ("PIN_STATE", "ld"): int(self.ld_now),
            ("PIN_STATE", "le"): le, ("PIN_STATE", "clk"): clk, ("PIN_STATE", "dat"): dat,
            ("PIN_STATE", "pe_out"): pe_out, ("PIN_STATE", "pe_t"): pe_t,
            ("FIRST_ERR_INDEX", "index"): self._first_err_index,
            ("POINT_COUNT", "count"): self._point_count,
            ("SWEEP_COUNT", "count"): self._sweep_count,
            ("ENTRY_INDEX", "index"): self._entry,
            ("CAPS", "table_aw"): self.table_aw, ("CAPS", "result_aw"): self.result_aw,
            ("CAPS", "clk_mhz"): self.clk_hz // 1_000_000,
        }

    # ---- table and results ----------------------------------------------------------------------------------
    def _write_table_w1(self, value: int) -> None:
        if self._busy:
            return
        self._table[self._table_addr & ((1 << self.table_aw) - 1)] = (self._rw[("TABLE_W0", "word")],
                                                                     value & W1_USED_MASK)
        self._table_addr = (self._table_addr + 1) & 0xFFFF

    def _read_result_data(self) -> int:
        word = self._results[self._result_addr & ((1 << self.result_aw) - 1)]
        self._result_addr = (self._result_addr + 1) & 0xFFFF
        return word

    # ---- CTRL -----------------------------------------------------------------------------------------------
    def _write_ctrl(self, value: int) -> None:
        f = REGS["CTRL"].fields
        for name in ("irq_en", "pin_owner", "stop_on_err"):
            self._rw[("CTRL", name)] = f[name].get(value)
        if f["soft_reset"].get(value):
            self.soft_reset()
            return
        if f["irq_ack"].get(value):
            self._done = False
        if f["abort"].get(value):
            self._abort()
        # start sees pin_owner_act as it was before this write (a registered signal in the RTL)
        if f["start"].get(value):
            self._start()
        self._update_owner()

    def _start(self) -> None:
        if self._busy:
            return
        self._done = self._err_lock = self._aborted = self._err_table = False
        self._point_count = 0
        self._first_err_index = 0
        n = self._rw[("N_ENTRIES", "n")]
        if n == 0 or n > (1 << self.table_aw) or not self._pin_owner_act:
            self._err_table = True
            self._done = True
            return
        self._busy = True
        self._entry = 0
        self._gen = self._sweep(n)
        self._advance()

    def _abort(self) -> None:
        """Only a sweep that waits (for samples) can be caught here; others have finished inside write()."""
        if not self._busy:
            return
        if self._gen is not None:
            self._gen.close()
        self._finish(aborted=True)

    # ---- sweep states ---------------------------------------------------------------------------------------
    def _advance(self) -> None:
        """Run the sweep until it ends or pauses in SAMPLE."""
        try:
            next(self._gen)
        except StopIteration as stop:
            self._finish(reason=stop.value)

    def _finish(self, reason: str = _END_NORMAL, aborted: bool = False) -> None:
        self._gen = None
        self._busy = False
        self._state = IDLE
        self._samples = []
        self._done = True
        if aborted:
            self._aborted = True
        elif reason == _END_NORMAL:
            self._sweep_count = (self._sweep_count + 1) & 0xFFFF_FFFF
        elif reason == _END_TABLE_FULL:
            self._err_table = True
        self._update_owner()

    def _sweep(self, n_entries: int) -> Generator:
        while self._entry < n_entries:
            self._state = FETCH
            entry = TableEntry.from_words(*self._table[self._entry])
            self._state_att(entry)
            self._state_spi(entry)
            if entry.measure:
                reason = yield from self._measure(entry)
                if reason is not None:
                    return reason
            self._state = NEXT
            self._entry += 1
        return _END_NORMAL

    def _state_att(self, entry: TableEntry) -> None:
        if entry.att_en:
            self._state = ATT
            self._change_pe(entry.att)

    def _state_spi(self, entry: TableEntry) -> None:
        if entry.spi_en:
            self._state = SPI
            self.spi_words.append(entry.w0())
            self._last_spi_word = entry.w0()

    def _measure(self, entry: TableEntry) -> Generator:
        """WAIT_MIN .. STORE of one measured entry. Returns None to go on, or the reason the sweep ends."""
        index = self._point_count
        unlocked = False
        self._state = WAIT_MIN
        if not entry.skip_lock:
            self._state = WAIT_LOCK
            unlocked = not self.lock_model(index, self._last_spi_word)
        if unlocked:
            if not self._err_lock:
                self._first_err_index = index
            self._err_lock = True
            if self._rw[("CTRL", "stop_on_err")]:
                return _END_STOP_ON_ERR
        self._state = SETTLE
        total = yield from self._sample(index)
        self._state = STORE
        if self._point_count >= len(self._results):
            return _END_TABLE_FULL
        self._results[self._point_count] = (int(unlocked) << UNLOCKED_BIT) | (total & SUM_MASK)
        self._point_count += 1
        return None

    def _sample(self, index: int) -> Generator:
        """SAMPLE: sum N_AVG samples of the selected source; pauses while the caller must supply them."""
        n_avg = self._rw[("N_AVG", "n")] or 1
        src = self._rw[("DET_CFG", "src")]
        self._state = SAMPLE
        if src == SRC_TEST:
            base = self._rw[("DET_TEST", "base")]
            return n_avg * ((base + (index & 0xFF)) & 0xFFFF)
        if src == SRC_EXT and self.ext_samples is not None:
            return sum(self.ext_samples(index) & 0xFFFF for _ in range(n_avg))
        self._samples = []
        self._samples_needed = n_avg
        while src == SRC_NONE or src == SRC_EXT or len(self._samples) < n_avg:
            yield                      # PS source: wait for DET_PUSH; no stream / src 3: forever (abort ends it)
        total = sum(self._samples)
        self._samples = []
        return total

    def _push(self, sample: int) -> None:
        """DET_PUSH: counts only in SAMPLE with src 0, dropped otherwise."""
        if not (self._busy and self._state == SAMPLE and self._rw[("DET_CFG", "src")] == SRC_PUSH):
            return
        self._samples.append(sample)
        if len(self._samples) >= self._samples_needed:
            self._advance()

    # ---- PE4302 and pin owner -------------------------------------------------------------------------------
    def _engine_owns(self) -> bool:
        return bool(self._pin_owner_act)

    def _pe_pins(self):
        """(levels driven, tri-state mask) after the pin mux."""
        if self._engine_owns():
            return self._pe_engine, 0
        return self.emio_pe_o & 0x3F, self.emio_pe_t & 0x3F

    def _make_state(self, old: int, new: int) -> int:
        return (old | new) if self._rw[("PE4302", "active_high")] else (old & new)

    def _change_pe(self, new: int) -> None:
        """Make-before-break: the make state, then the new state (both appear in the trace)."""
        new &= 0x3F
        self.pe_trace.append(self._make_state(self._pe_engine, new))
        self.pe_trace.append(new)
        self._pe_engine = new

    def _write_pe4302(self, value: int) -> None:
        f = REGS["PE4302"].fields
        manual = f["manual"].get(value)
        self._rw[("PE4302", "manual")] = manual
        self._rw[("PE4302", "active_high")] = f["active_high"].get(value)
        if not self._busy and self._engine_owns() and manual != self._pe_engine:
            self._change_pe(manual)

    def _update_owner(self) -> None:
        """pin_owner_act follows CTRL.pin_owner while idle; taking the pins loads PE4302.manual directly."""
        if self._busy:
            return
        wanted = self._rw[("CTRL", "pin_owner")]
        if wanted == self._pin_owner_act:
            return
        self._pin_owner_act = wanted
        if wanted:
            self._pe_engine = self._rw[("PE4302", "manual")]
            self.pe_trace.append(self._pe_engine)
