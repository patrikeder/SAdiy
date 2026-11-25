"""SweepOffload on top of two register access callables: the same code runs on the PL model and on the real
core (UIO mmap). Software sequence of `rtl-spec.md` section 9.

    reg_read(offset) -> int          32-bit read of the core's register at byte `offset`
    reg_write(offset, value) -> None 32-bit write

Offsets and field positions come from regmap.toml (`regmap_toml`).
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Sequence

from .platform import OffloadResult, TableEntry
from .regmap_toml import REGS

log = logging.getLogger("sadiy.ebaz_pl")

ID_MAGIC = 0x53410001
SUPPORTED_MAJOR = 2    # map 2.0: PE4302 through a PCF8574 on I2C, no ADS1115 reader
SRC_PUSH = 0
SRC_TEST = 1
SRC_STREAM = 2         # sample stream (ADC front end, generator, adapter port)
I2C_BITS_PER_ATT = 29  # bus bits of the longest attenuator transaction: START, address, make, final, STOP
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
        self.version = version
        self.table_dirty = False          # the table holds something else than the last `upload` (see send_words)
        self.last_sweep_s = 0.0           # last `run`: start write until done is seen (hardware time + poll granularity)
        self.last_read_s = 0.0            # last `run`: reading the results back (register accesses of the host)
        self.last_att_nack = False        # last `run`: the PCF8574 did not acknowledge (attenuation may be wrong)
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
    def acquire_pins(self, levels: Optional[int] = None) -> None:
        """Hand the ADF4351 SPI pins, CE and the I2C bus (PCF8574 attenuator) to the engine. Taking them sends
        PE4302.manual to the PCF8574 as one byte: `levels` sets it first (default: the levels the engine sent
        last, ATT_STAT.levels; after reset all stages in, 31.5 dB, the PCF8574's power-up state). The engine cannot
        read the PCF8574: what Linux wrote to it while it owned the bus is not known here. The PS must not use I2C0
        at this moment. Only while idle."""
        if levels is None:
            levels = self.pin_levels()
        manual = _fld("PE4302", "manual")
        cur = self._rd(_off("PE4302"))
        self._wr(_off("PE4302"), (cur & ~manual.mask) | manual.put(levels))
        self._set_ctrl_bits(pin_owner=1)
        if not self._status()["pin_owner_act"]:
            raise RuntimeError("the engine did not take the pins (sweep running?)")

    def pin_levels(self) -> int:
        """PE4302 levels V1..V6 the engine sent to the PCF8574 last (ATT_STAT.levels)."""
        return _fld("ATT_STAT", "levels").get(self._rd(_off("ATT_STAT")))

    def att_status(self) -> dict:
        v = self._rd(_off("ATT_STAT"))
        return {name: f.get(v) for name, f in REGS["ATT_STAT"].fields.items()}

    def wait_att(self, timeout_s: float = 0.05) -> dict:
        """ATT_STAT once no attenuator transaction is running. `err_nack` is set only at the end of one (about
        0.3 ms at 100 kHz), so read it through this after anything that starts one."""
        deadline = self._clock() + timeout_s
        while True:
            att = self.att_status()
            if not att["busy"]:
                return att
            if self._clock() >= deadline:
                raise TimeoutError("attenuator transaction did not finish (ATT_STAT.busy)")
            self._sleep(min(self._poll_s, 0.0005))

    def configure_att(self, address: int = 0x27, p3: int = 1, p7: int = 1, i2c_div: Optional[int] = None) -> None:
        """PCF8574: 7-bit address, levels of P3 (backlight LED of the LCD adapter board) and P7, I2C divider
        (f_scl = clk / (4 * div); reset 250 = 100 kHz, the PCF8574 maximum)."""
        f = REGS["ATT_I2C"].fields
        self._wr(_off("ATT_I2C"), f["addr"].put(address) | f["p3"].put(p3) | f["p7"].put(p7))
        if i2c_div is not None:
            self._wr(_off("ATT_I2C_DIV"), _fld("ATT_I2C_DIV", "div").put(i2c_div))

    def release_pins(self) -> None:
        """Give the pins and the I2C bus back to the PS. The PCF8574 keeps the levels of `pin_levels()`; call only
        when the PS SPI is idle."""
        self._set_ctrl_bits(pin_owner=0)

    def set_att_pins(self, levels: int, timeout_s: float = 0.05) -> None:
        """Change the engine's PE4302 state through the PCF8574 (make-before-break), while it owns the pins and is
        idle, and wait until the transaction is done (about 0.3 ms at 100 kHz), so that `pin_levels()` is current
        for the next change. Without the pins (or during a sweep) the value is only stored."""
        manual = _fld("PE4302", "manual")
        cur = self._rd(_off("PE4302"))
        self._wr(_off("PE4302"), (cur & ~manual.mask) | manual.put(levels))
        st = self._status()
        if not st["pin_owner_act"] or st["busy"]:
            return
        deadline = self._clock() + timeout_s
        while True:
            att = self.att_status()
            if not att["busy"] and att["levels"] == levels & 0x3F:
                return
            if self._clock() >= deadline:
                raise TimeoutError(f"attenuator did not reach 0x{levels & 0x3F:02X} (ATT_STAT.levels 0x{att['levels']:02X})")
            self._sleep(min(self._poll_s, 0.0005))

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
        self.table_dirty = False

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
        if src != SRC_PUSH:
            timeout_s = max(timeout_s, self.estimated_s(n_avg))
        t_start = self._clock()
        self._pulse("start")
        deadline = t_start + timeout_s
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
        t_done = self._clock()
        self.last_sweep_s = t_done - t_start
        self.last_read_s = 0.0
        if st["err_table"]:
            raise RuntimeError(f"sweep refused or result memory full (N_ENTRIES={self._n_entries}, "
                               f"pin_owner_act={st['pin_owner_act']})")
        nack = bool(self.att_status()["err_nack"])
        if nack and not self.last_att_nack:      # once, not on every sweep of a continuous run
            log.warning("PCF8574 attenuator did not acknowledge during the sweep: the attenuation may be wrong")
        self.last_att_nack = nack
        count = _fld("POINT_COUNT", "count").get(self._rd(_off("POINT_COUNT")))
        self._wr(_off("RESULT_ADDR"), 0)
        words = [self._rd(_off("RESULT_DATA")) for _ in range(count)]
        self.last_read_s = self._clock() - t_done
        return OffloadResult.from_result_words(words, n_avg, aborted=bool(st["aborted"]),
                                               err_table=False, err_lock=bool(st["err_lock"]))

    def estimated_s(self, n_avg: int) -> float:
        """Upper estimate of the time the uploaded table takes (every point waiting for the lock timeout),
        from the timing registers. Used as the minimum timeout when the PL takes the samples itself."""
        us = lambda name: self._rd(_off(name)) & 0xFFFFF  # noqa: E731
        sample_us = 1.0
        div = max(4, _fld("ATT_I2C_DIV", "div").get(self._rd(_off("ATT_I2C_DIV"))))
        att_us = I2C_BITS_PER_ATT * 4 * div / (self.clk_hz / 1e6) + (self._rd(_off("T_ATT_GAP_CYC")) & 0xFFFF) / (self.clk_hz / 1e6)
        per_point = us("T_MIN_US") + us("T_LOCK_TIMEOUT_US") + us("T_SETTLE_US") + n_avg * sample_us
        return 0.5 + 1.2e-6 * per_point * max(1, self._n_measure) + (20e-6 + 1.2e-6 * att_us) * self._n_entries

    # ---- single actions through the engine (register-only platforms: no PS SPI / GPIO / I2C) -----------------
    def _run_private(self, entries: Sequence[TableEntry], n_avg: int = 1, timeout_s: float = 2.0) -> OffloadResult:
        """Run a short private table. The sweep table is overwritten: `table_dirty` tells the caller."""
        saved = (self._n_entries, self._n_measure)
        try:
            self.upload(entries)
            return self.run(n_avg, timeout_s)
        finally:
            self._n_entries, self._n_measure = saved
            self.table_dirty = True

    def send_words(self, words: Sequence[int]) -> None:
        """Send SPI words to the ADF4351 now, in order (no measurement)."""
        self._run_private([TableEntry(word=w, spi_en=True) for w in words])

    def read_detector(self, n: int = 1) -> float:
        """Mean detector code of `n` samples taken now with the configured source (no SPI, no lock wait)."""
        res = self._run_private([TableEntry(word=0, measure=True, skip_lock=True)], n_avg=n)
        if len(res.sums) != 1:
            raise RuntimeError("detector read did not complete")
        return res.sums[0] / n

    def lock_detect(self) -> bool:
        return bool(self._status()["ld_now"])

    def set_ce(self, level: int) -> None:
        """Level of the ADF4351 CE pin while the engine owns the pins."""
        self._wr(_off("ADF_PINS"), _fld("ADF_PINS", "ce").put(level))

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
