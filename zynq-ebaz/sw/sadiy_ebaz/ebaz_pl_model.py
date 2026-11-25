"""Behavioural model (transaction level, not cycle level) of the PL sweep engine register interface.

Reference: `zynq-ebaz/docs/rtl-spec.md` (the text wins over this file). Register offsets and fields come from
`regmap.toml` through `regmap_toml`. What is NOT modelled: time (the microsecond waits just take no time), the
SPI bit stream, the I2C bit stream, the AXI handshakes. What is: every value the registers show, the SPI words in
order, the attenuator states and the PCF8574 transactions in order (register map 2.0: the PE4302 hangs on a PCF8574
on I2C), results, flags and the pause of the sequencer while it waits for detector samples.

Test side of the model (what a testbench drives):
  lock_model(result_index, last_spi_word) -> bool    lock reached before the timeout (default: always)
  ld_now                                             level of the lock detect pin (STATUS.ld_now)
  ext_samples(result_index) -> int                   one sample of the external stream (DET_CFG.src = 2)
  ext_stream                                         samples of an ADC adapter on the det_ext port (stream format,
                                                     played cyclically from index 0 at every measurement); None: no stream
  fe_pins(n) -> (code, otr)                          ADC front end, FE_CFG.src = 2: what the module puts on the data lines
                                                     for the n-th sample (default: nothing wired, the board top ties the
                                                     lines to 0x800 / 0)
  emio_ce_o / emio_ce_t / pad_ce                     PS side of the CE pin and the level of an undriven pin
  pcf_address                                        7-bit address the PCF8574 answers at (None: nothing on the bus)
  spi_words                                          every SPI word the engine sent, in order
  pe_trace                                           attenuator levels V1..V6 of every byte the engine sent, in order
                                                     (a decrease: make state, then final state; otherwise one state)
  att_bytes                                          every PCF8574 transaction as a tuple of port bytes (P7..P0),
                                                     only those the PCF8574 acknowledged

A `start` write runs the whole sweep inside `write()`, except when it must wait for detector samples that only
the caller can supply (DET_CFG.src = 0: DET_PUSH writes; src = 2 without a stream: never): then the model stays in
SAMPLE, STATUS.busy = 1, STATUS.wait_sample = 1, until enough samples have been pushed (or `abort`).
"""
from __future__ import annotations

from typing import Callable, Dict, Generator, List, Optional

from .ifpath import _ROM, OVR_BIT, if_power_ref
from .platform import SUM_MASK, UNLOCKED_BIT, W1_USED_MASK, TableEntry
from .regmap_toml import REGS

IDLE, FETCH, ATT, SPI, WAIT_MIN, WAIT_LOCK, SETTLE, SAMPLE, STORE, NEXT = range(10)

PE_ALL_IN = 0x3F
SRC_PUSH, SRC_TEST, SRC_EXT = range(3)              # DET_CFG.src; 3 = 2 (was the ADS1115 reader up to map 1.3)
PCF8574_ADDR = 0x27
FE_TIE_OFF, FE_GENERATOR = 0, 1                      # FE_CFG.src (2 and 3: the pins)
FE_RAMP, FE_WALK, FE_TONE, FE_CONST = range(4)       # FE_CFG.tg_mode
FE_MAX_SAMPLES = 1 << 17                             # longest stream the model builds for one measurement (then cyclic)
FE_TICK = 17                                         # samples the FE_STAT counter advances per read (stands for time)

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
        self.emio_ce_o, self.emio_ce_t, self.pad_ce = 0, 1, 1
        self.ext_stream: Optional[List[int]] = None
        self.fe_pins: Optional[Callable[[int], tuple]] = None
        self.pcf_address: Optional[int] = PCF8574_ADDR
        self.emio_adf = (0, 0, 1)        # clk, dat, le as the PS drives them
        self.spi_words: List[int] = []
        self.pe_trace: List[int] = []
        self.att_bytes: List[tuple] = []
        self._reset()

    # ---- reset ----------------------------------------------------------------------------------------------
    def _reset(self) -> None:
        self._rw: Dict[tuple, int] = {
            (r.name, f.name): f.reset for r in REGS.values() for f in r.fields.values() if f.access == "rw"}
        self._table = [(0, 0)] * (1 << self.table_aw)
        self._results = [0] * (1 << self.result_aw)
        self._table_addr = 0
        self._result_addr = 0
        self._pe_engine = PE_ALL_IN       # levels the engine sent last; reset = PCF8574 power-up (all ports high)
        self._att_last_byte = 0xFF
        self._att_count = 0
        self._att_err = False
        self._pin_owner_act = 0
        self._last_spi_word = 0
        self._sweep_count = 0
        self._gen_mem = [0] * 4096
        self._gen_addr = 0
        self._if_inc = 0
        self._ovr = False
        self._stream_ovr = False
        self._fe_count = 0
        self._fe_otr_seen = False
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
        self._att_err = False
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
        if name == "GEN_DATA":
            return 0
        if name == "GEN_ADDR":
            return self._gen_addr
        if name == "TABLE_ADDR":
            return self._table_addr
        if name == "RESULT_ADDR":
            return self._result_addr
        if name == "FE_STAT":
            self._fe_tick()
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
        elif name == "GEN_ADDR":
            self._gen_addr = value & 0xFFF
        elif name == "GEN_DATA":
            v = value & 0xFFFF
            self._gen_mem[self._gen_addr] = v - 0x10000 if v & 0x8000 else v
            self._gen_addr = (self._gen_addr + 1) & 0xFFF
        elif name == "PE4302":
            self._write_pe4302(value)
        elif name == "FE_CFG":
            self._store_rw(name, value)
            if value >> 6 & 1:                          # clear (w1p)
                self._fe_count = 0
                self._fe_otr_seen = False
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
        clk, dat, le = (0, 0, 1) if self._engine_owns() else self.emio_adf
        return {
            ("STATUS", "busy"): int(self._busy), ("STATUS", "done"): int(self._done),
            ("STATUS", "err_lock"): int(self._err_lock), ("STATUS", "aborted"): int(self._aborted),
            ("STATUS", "ld_now"): int(self.ld_now), ("STATUS", "wait_sample"): int(self._state == SAMPLE),
            ("STATUS", "err_table"): int(self._err_table), ("STATUS", "pin_owner_act"): self._pin_owner_act,
            ("STATUS", "state"): self._state,
            ("PIN_STATE", "ld"): int(self.ld_now),
            ("PIN_STATE", "le"): le, ("PIN_STATE", "clk"): clk, ("PIN_STATE", "dat"): dat,
            ("PIN_STATE", "ce"): self._ce_pin(), ("PIN_STATE", "scl"): 1, ("PIN_STATE", "sda"): 1,
            ("PIN_STATE", "i2c_pl"): int(self._engine_owns()),
            ("ATT_STAT", "levels"): self._pe_engine, ("ATT_STAT", "byte"): self._att_last_byte,
            ("ATT_STAT", "err_nack"): int(self._att_err), ("ATT_STAT", "busy"): 0,
            ("ATT_STAT", "count"): self._att_count & 0xFF,
            ("FIRST_ERR_INDEX", "index"): self._first_err_index,
            ("POINT_COUNT", "count"): self._point_count,
            ("SWEEP_COUNT", "count"): self._sweep_count,
            ("ENTRY_INDEX", "index"): self._entry,
            ("CAPS", "table_aw"): self.table_aw, ("CAPS", "result_aw"): self.result_aw,
            ("CAPS", "clk_mhz"): self.clk_hz // 1_000_000,
            ("FE_STAT", "last_code"): self._fe_sample(self._fe_count)[0] if self._rw[("FE_CFG", "enable")] else 0,
            ("FE_STAT", "last_otr"): int(self._fe_sample(self._fe_count)[1]) if self._rw[("FE_CFG", "enable")] else 0,
            ("FE_STAT", "otr_seen"): int(self._fe_otr_seen), ("FE_STAT", "count"): self._fe_count,
        }

    # ---- ADC front end (register map 1.3) --------------------------------------------------------------------
    def _fe_sample(self, n: int) -> tuple:
        """(raw 12-bit code, otr) the capture sees for the n-th sample of the enabled front end."""
        src = self._rw[("FE_CFG", "src")]
        tie, tie_otr = self._rw[("FE_TIE", "code")], bool(self._rw[("FE_TIE", "otr")])
        if src == FE_TIE_OFF:
            return tie, tie_otr
        if src == FE_GENERATOR:
            mode = self._rw[("FE_CFG", "tg_mode")]
            if mode == FE_RAMP:
                code = n & 0xFFF
                return code, code == 0xFFF
            if mode == FE_WALK:
                return 1 << (n % 12), False
            if mode == FE_TONE:
                sin = _ROM[((n * self._rw[("FE_TG_INC", "inc")]) & 0xFFFF_FFFF) >> 21]
                return ((sin >> 4) + 2048) & 0xFFF, False                 # {!sin[15], sin[14:4]}
            return tie, tie_otr
        if self.fe_pins is not None:
            code, otr = self.fe_pins(n)
            return code & 0xFFF, bool(otr)
        return 0x800, False

    def _fe_data(self, code: int) -> int:
        """Stream word (16 bit two's complement) of a raw code, as adc_ad9226.sv converts it."""
        if self._rw[("FE_CFG", "twos")]:
            v = code - 4096 if code & 0x800 else code
        else:
            v = code - 2048
        return v << 4

    def _fe_tick(self) -> None:
        """Stand-in for time: every FE_STAT read of an enabled front end advances the counter by FE_TICK samples."""
        if not self._rw[("FE_CFG", "enable")]:
            return
        for k in range(FE_TICK):
            self._fe_otr_seen |= self._fe_sample(self._fe_count + k)[1]
        self._fe_count = (self._fe_count + FE_TICK) & 0xFFFF

    def _fe_stream(self) -> List[int]:
        """Samples of one measurement (n_avg + skip filter outputs of R samples), from sample 0, cyclic beyond.
        Sets `_stream_ovr` when any of them has OTR. A tie-off is one constant (cyclic). Tone, ramp and walking one
        are free-running in the hardware: the start phase there is not sample 0, so only tie-off is bit exact."""
        n = ((self._rw[("N_AVG", "n")] or 1) + self._rw[("IF_CIC", "skip")] + 1) * max(1, self._rw[("IF_CIC", "r")]) + 8
        constant = (self._rw[("FE_CFG", "src")] == FE_TIE_OFF
                    or (self._rw[("FE_CFG", "src")] == FE_GENERATOR and self._rw[("FE_CFG", "tg_mode")] == FE_CONST))
        n = 1 if constant else min(n, FE_MAX_SAMPLES)
        out, ovr = [], False
        for k in range(n):
            code, otr = self._fe_sample(k)
            out.append(self._fe_data(code))
            ovr |= otr
        self._stream_ovr = ovr
        return out

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
        self._att_err = False
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
        self._results[self._point_count] = ((int(unlocked) << UNLOCKED_BIT) | (int(self._ovr) << OVR_BIT)
                                            | (total & SUM_MASK))
        self._point_count += 1
        return None

    def _sample(self, index: int) -> Generator:
        """SAMPLE: sum N_AVG samples of the selected source; pauses while the caller must supply them."""
        n_avg = self._rw[("N_AVG", "n")] or 1
        src = self._rw[("DET_CFG", "src")]
        self._state = SAMPLE
        self._ovr = False
        if self._rw[("DET_CFG", "mode")]:              # IF path: NCO, mixer, CIC, power (bit-exact reference)
            stream = self._stream()
            step = self._rw[("IF_NCO_STEP", "step")]
            self._if_inc = self._rw[("IF_NCO", "inc")] if index == 0 else (self._if_inc + step) & 0xFFFF_FFFF
            while stream is None:
                yield                                   # no samples: forever (abort ends it)
            total, self._ovr = if_power_ref(stream, self._if_inc, self._rw[("IF_CIC", "r")],
                                            self._rw[("IF_CIC", "shift")], self._rw[("IF_CIC", "skip")], n_avg,
                                            self._stream_ovr)
            return total
        if src == 3:
            src = SRC_EXT                               # 3 = 2 since map 2.0
        if src == SRC_EXT and self._stream() is not None:
            stream = self._stream()                     # video path: negative samples count as 0
            return sum(max(0, stream[k % len(stream)]) for k in range(n_avg))
        if src == SRC_TEST:
            base = self._rw[("DET_TEST", "base")]
            return n_avg * ((base + (index & 0xFF)) & 0xFFFF)
        if src == SRC_EXT and self.ext_samples is not None:
            return sum(self.ext_samples(index) & 0xFFFF for _ in range(n_avg))
        self._samples = []
        self._samples_needed = n_avg
        while src == SRC_EXT or len(self._samples) < n_avg:
            yield                      # PS source: wait for DET_PUSH; src 2 without a stream: forever (abort ends it)
        total = sum(self._samples)
        self._samples = []
        return total

    def _stream(self) -> Optional[List[int]]:
        """The selected sample stream as one period, or None when nothing delivers samples. The model plays it
        from index 0 at every measurement (the generator with GEN_CFG.sync = 1)."""
        if self._rw[("DET_CFG", "stream")]:
            if not self._rw[("GEN_CFG", "enable")]:
                return None
            self._stream_ovr = False
            return self._gen_mem[:self._rw[("GEN_CFG", "len_m1")] + 1]
        if self._rw[("FE_CFG", "enable")]:
            return self._fe_stream()
        self._stream_ovr = False
        return self.ext_stream

    def _ce_pin(self) -> int:
        if self._engine_owns():
            return self._rw[("ADF_PINS", "ce")]
        return self.pad_ce if self.emio_ce_t else self.emio_ce_o

    def _push(self, sample: int) -> None:
        """DET_PUSH: counts only in SAMPLE with src 0, dropped otherwise."""
        if not (self._busy and self._state == SAMPLE and self._rw[("DET_CFG", "src")] == SRC_PUSH):
            return
        self._samples.append(sample)
        if len(self._samples) >= self._samples_needed:
            self._advance()

    # ---- PE4302 through the PCF8574, and pin owner ----------------------------------------------------------
    def _engine_owns(self) -> bool:
        return bool(self._pin_owner_act)

    def _make_state(self, old: int, new: int) -> int:
        return (old | new) if self._rw[("PE4302", "active_high")] else (old & new)

    def port_byte(self, levels: int) -> int:
        """PCF8574 port byte of V1..V6 levels: P0..P2 = V1..V3, P3 = ATT_I2C.p3, P4..P6 = V4..V6, P7 = ATT_I2C.p7."""
        p3, p7 = self._rw[("ATT_I2C", "p3")], self._rw[("ATT_I2C", "p7")]
        return (p7 << 7) | ((levels >> 3 & 7) << 4) | (p3 << 3) | (levels & 7)

    def _send(self, states: List[int]) -> None:
        """One PCF8574 transaction with one byte per state. Without an answer at ATT_I2C.addr: ATT_STAT.err_nack,
        nothing reaches the port; ATT_STAT.levels follows anyway (as in the RTL)."""
        self.pe_trace.extend(states)
        acked = self.pcf_address is not None and self.pcf_address == self._rw[("ATT_I2C", "addr")]
        if acked:
            self.att_bytes.append(tuple(self.port_byte(s) for s in states))
        else:
            self._att_err = True
        self._pe_engine = states[-1]
        self._att_last_byte = self.port_byte(states[-1])
        self._att_count += 1

    def _change_pe(self, new: int) -> None:
        """Make-before-break: the make state, then the new state, in one transaction; one byte when they agree."""
        new &= 0x3F
        make = self._make_state(self._pe_engine, new)
        self._send([make, new] if make != new else [new])

    def _write_pe4302(self, value: int) -> None:
        f = REGS["PE4302"].fields
        manual = f["manual"].get(value)
        self._rw[("PE4302", "manual")] = manual
        self._rw[("PE4302", "active_high")] = f["active_high"].get(value)
        if not self._busy and self._engine_owns() and manual != self._pe_engine:
            self._change_pe(manual)

    def _update_owner(self) -> None:
        """pin_owner_act follows CTRL.pin_owner while idle; taking the pins sends PE4302.manual as one byte."""
        if self._busy:
            return
        wanted = self._rw[("CTRL", "pin_owner")]
        if wanted == self._pin_owner_act:
            return
        self._pin_owner_act = wanted
        if wanted:
            self._send([self._rw[("PE4302", "manual")]])
