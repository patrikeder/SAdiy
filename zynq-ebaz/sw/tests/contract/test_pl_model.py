"""PlModel behaviour, one test per behaviour of rtl-spec.md sections 4 to 9."""
import random

import pytest
from sadiy_ebaz.ebaz_pl_model import IDLE, SAMPLE, PlModel
from sadiy_ebaz.platform import TableEntry
from sadiy_ebaz.regmap_toml import OFFSET, REGS

from sadiy.drivers.pe4302 import DEFAULT_WEIGHTS_DB, PE4302, STEP_DB
from sadiy.hal.fake import FakeGpio, PinLog

STEPS = [int(round(w / STEP_DB)) for w in DEFAULT_WEIGHTS_DB]
CTRL = REGS["CTRL"].fields


class Rig:
    """The model with register access by name."""

    def __init__(self, **kw):
        self.m = PlModel(**kw)

    def w(self, reg, value):
        self.m.write(OFFSET[reg], value)

    def r(self, reg):
        return self.m.read(OFFSET[reg])

    def f(self, reg, field):
        return REGS[reg].fields[field].get(self.r(reg))

    def own(self):
        self.w("CTRL", self.r("CTRL") | CTRL["pin_owner"].mask)

    def load(self, entries, base=0):
        self.w("TABLE_ADDR", base)
        for e in entries:
            self.w("TABLE_W0", e.w0())
            self.w("TABLE_W1", e.w1())
        self.w("N_ENTRIES", len(entries) + base)

    def start(self):
        self.w("CTRL", self.r("CTRL") | CTRL["start"].mask)

    def pulse(self, name):
        self.w("CTRL", self.r("CTRL") | CTRL[name].mask)

    def results(self, n=None):
        n = self.f("POINT_COUNT", "count") if n is None else n
        self.w("RESULT_ADDR", 0)
        return [self.r("RESULT_DATA") for _ in range(n)]


def measure(word=0, **kw):
    return TableEntry(word, spi_en=kw.pop("spi_en", True), measure=True, **kw)


def rig_with(entries, src=1, base=0x100, n_avg=4, **kw):
    g = Rig(**kw)
    g.w("DET_CFG", src)
    g.w("DET_TEST", base)
    g.w("N_AVG", n_avg)
    g.own()
    g.load(entries)
    return g


# ---- registers --------------------------------------------------------------------------------------------
def test_reset_values():
    g = Rig()
    for reg in REGS.values():
        if reg.ext or reg.name in ("STATUS", "PIN_STATE", "CAPS"):
            continue
        for f in reg.fields.values():
            if f.access in ("rw", "const"):
                assert g.f(reg.name, f.name) == f.reset, (reg.name, f.name)
    assert g.r("ID") == 0x53410001 and g.r("VERSION") == 0x00010000
    assert g.r("PE4302") == 0x13F
    assert g.r("STATUS") == 0
    assert (g.r("N_AVG"), g.r("SPI_DIV"), g.r("T_ATT_GAP_CYC")) == (1, 5, 100)


def test_const_and_ro_ignore_writes_and_unknown_addresses_read_zero():
    g = Rig()
    g.w("ID", 0)
    g.w("STATUS", 0xFFFFFFFF)
    g.w("POINT_COUNT", 5)
    g.w("CAPS", 0)
    assert g.r("ID") == 0x53410001 and g.r("STATUS") == 0 and g.r("POINT_COUNT") == 0
    g.m.write(0x7FC, 123)
    assert g.m.read(0x7FC) == 0 and g.m.read(0x0A0) == 0


def test_rw_fields_truncate_and_unused_bits_read_zero():
    g = Rig()
    g.w("N_AVG", 0xFFFFFFFF)
    assert g.r("N_AVG") == 0xFFF
    g.w("SPI_DIV", 0x1FF)
    assert g.r("SPI_DIV") == 0xFF
    g.w("PE4302", 0xFFFFFFFF)
    assert g.r("PE4302") == 0x13F
    g.w("DET_CFG", 0xFFFFFFFF)
    assert g.r("DET_CFG") == 3
    g.w("T_MIN_US", 0xFFFFFFFF)
    assert g.r("T_MIN_US") == 0xFFFFF


def test_w1p_bits_read_zero_and_ctrl_keeps_rw_bits():
    g = Rig()
    g.w("CTRL", 0xFFFFFFFF & ~(CTRL["start"].mask | CTRL["abort"].mask | CTRL["soft_reset"].mask))
    assert g.r("CTRL") == CTRL["irq_en"].mask | CTRL["pin_owner"].mask | CTRL["stop_on_err"].mask


def test_caps():
    g = Rig(table_aw=5, result_aw=4, clk_hz=125_000_000)
    assert (g.f("CAPS", "table_aw"), g.f("CAPS", "result_aw"), g.f("CAPS", "clk_mhz")) == (5, 4, 125)


# ---- table and results -----------------------------------------------------------------------------------
def test_table_commit_and_auto_increment():
    g = Rig()
    g.w("TABLE_W0", 0xAAAA0001)
    assert g.r("TABLE_ADDR") == 0
    g.w("TABLE_W1", TableEntry(0, 0x15, True, True, True, True).w1())
    assert g.r("TABLE_ADDR") == 1 and g.r("TABLE_W1") == 0
    g.w("TABLE_W0", 0xBBBB0002)
    g.w("TABLE_W1", 1 << 8)
    assert g.r("TABLE_ADDR") == 2 and g.r("TABLE_W0") == 0xBBBB0002
    assert g.m._table[:2] == [(0xAAAA0001, 0xF15), (0xBBBB0002, 0x100)]
    g.w("TABLE_ADDR", 7)
    assert g.r("TABLE_ADDR") == 7


def test_table_w1_ignores_undefined_bits():
    g = Rig()
    g.w("TABLE_W1", 0xFFFFFFFF)
    assert g.m._table[0][1] == 0xF3F


def test_table_writes_ignored_while_busy():
    g = rig_with([measure(0x11)], src=3)
    g.start()
    assert g.f("STATUS", "busy")
    g.w("TABLE_ADDR", 5)
    g.w("TABLE_W0", 0x99)
    g.w("TABLE_W1", 0x100)
    assert g.r("TABLE_ADDR") == 1 and g.r("TABLE_W0") == 0x99     # W0 is plain storage; ADDR and W1 are frozen
    assert g.m._table[1] == (0, 0)


def test_result_addr_and_data_auto_increment():
    g = rig_with([measure(1), measure(2), measure(3)])
    g.start()
    g.w("RESULT_ADDR", 1)
    assert g.r("RESULT_DATA") == 4 * (0x100 + 1)
    assert g.r("RESULT_ADDR") == 2
    assert g.r("RESULT_DATA") == 4 * (0x100 + 2)
    assert g.r("RESULT_ADDR") == 3
    g.w("RESULT_DATA", 0xFFFF)                      # read only
    assert g.r("RESULT_ADDR") == 3


# ---- start and refusal ------------------------------------------------------------------------------------
@pytest.mark.parametrize("why", ["empty", "too_big", "not_owner"])
def test_start_refused(why):
    g = Rig(table_aw=3)
    g.w("DET_CFG", 1)
    if why != "not_owner":
        g.own()
    g.w("N_ENTRIES", {"empty": 0, "too_big": 9, "not_owner": 1}[why])
    g.start()
    assert g.f("STATUS", "err_table") and g.f("STATUS", "done") and not g.f("STATUS", "busy")
    assert g.f("POINT_COUNT", "count") == 0 and g.m.spi_words == []
    assert g.f("STATUS", "state") == IDLE


def test_start_clears_status():
    g = rig_with([measure(1)], src=3)
    g.start()
    g.pulse("abort")
    assert g.f("STATUS", "aborted") and g.f("STATUS", "done")
    g.w("DET_CFG", 1)
    g.start()
    assert g.f("STATUS", "done") and not g.f("STATUS", "aborted") and not g.f("STATUS", "err_lock")
    assert g.f("POINT_COUNT", "count") == 1


def test_start_ignored_while_busy():
    g = rig_with([measure(1)], src=3)
    g.start()
    n = len(g.m.spi_words)
    g.start()
    assert g.f("STATUS", "busy") and len(g.m.spi_words) == n


def test_start_in_same_write_as_taking_the_pins_is_refused():
    g = Rig()
    g.load([measure(1)])
    g.w("CTRL", CTRL["pin_owner"].mask | CTRL["start"].mask)
    assert g.f("STATUS", "err_table") and g.f("STATUS", "pin_owner_act") == 1


# ---- sweep execution ---------------------------------------------------------------------------------------
def test_entries_run_in_order_and_noop_does_nothing():
    es = [TableEntry(0x10, spi_en=True), TableEntry(0x99), TableEntry(0x20, spi_en=True),
          measure(0x30)]
    g = rig_with(es)
    g.start()
    assert g.m.spi_words == [0x10, 0x20, 0x30]
    assert g.f("POINT_COUNT", "count") == 1 and g.f("ENTRY_INDEX", "index") == 4
    assert g.f("STATUS", "done") and not g.f("STATUS", "busy")


def test_spi_en_off_sends_nothing_and_measure_off_stores_nothing():
    g = rig_with([TableEntry(0x77, spi_en=False), TableEntry(0x78, spi_en=True)])
    g.start()
    assert g.m.spi_words == [0x78] and g.f("POINT_COUNT", "count") == 0


def test_measure_without_spi_en_still_measures():
    g = rig_with([measure(0x55, spi_en=False)])
    g.start()
    assert g.m.spi_words == [] and len(g.results()) == 1


def test_att_en_make_before_break_trace_active_high():
    g = Rig()
    g.w("DET_CFG", 1)
    g.own()                                     # takes PE4302.manual = 0x3F
    g.m.pe_trace.clear()
    g.load([TableEntry(0, att=0b001100, att_en=True, spi_en=True, measure=True)])
    g.start()
    assert g.m.pe_trace == [0x3F, 0b001100]
    g.load([TableEntry(0, att=0b110000, att_en=True)])
    g.start()
    assert g.m.pe_trace[2:] == [0b111100, 0b110000]


def test_att_en_make_before_break_trace_active_low():
    g = Rig()
    g.w("PE4302", 0b001111 | 0)                 # active_high = 0, manual = 0x0F
    g.own()
    g.m.pe_trace.clear()
    g.load([TableEntry(0, att=0b111010, att_en=True)])
    g.start()
    assert g.m.pe_trace == [0b001010, 0b111010]


def test_att_en_without_change_still_traces():
    g = Rig()
    g.own()
    g.m.pe_trace.clear()
    g.load([TableEntry(0, att=0x3F, att_en=True)])
    g.start()
    assert g.m.pe_trace == [0x3F, 0x3F]


def test_att_applied_before_the_spi_word():
    g = Rig()
    g.own()
    order = []
    orig = g.m._change_pe
    g.m._change_pe = lambda new: (order.append("att"), orig(new))
    g.m.lock_model = lambda i, w: order.append("lock") or True
    g.load([TableEntry(0xAB, att=1, att_en=True, spi_en=True, measure=True)])
    g.w("DET_CFG", 1)
    g.start()
    assert order == ["att", "lock"] and g.m.spi_words == [0xAB]


def test_skip_lock_does_not_ask_the_lock_model():
    g = rig_with([measure(1, skip_lock=True), measure(2)])
    calls = []
    g.m.lock_model = lambda i, w: calls.append((i, w)) or True
    g.start()
    assert calls == [(1, 2)]


def test_lock_model_gets_index_and_last_spi_word():
    g = rig_with([TableEntry(0x11, spi_en=True), measure(0x22), measure(0x33)])
    calls = []
    g.m.lock_model = lambda i, w: calls.append((i, w)) or True
    g.start()
    assert calls == [(0, 0x22), (1, 0x33)]


def test_lock_timeout_flags_point_and_continues():
    g = rig_with([measure(i) for i in range(1, 6)])
    g.m.lock_model = lambda i, w: i not in (1, 3)
    g.start()
    res = g.results()
    assert len(res) == 5
    assert [bool(x >> 31) for x in res] == [False, True, False, True, False]
    assert res[1] & 0x7FFFFFFF == 4 * (0x100 + 1)                   # the sum was still taken
    assert g.f("STATUS", "err_lock") and g.f("FIRST_ERR_INDEX", "index") == 1
    assert g.f("STATUS", "done") and g.f("SWEEP_COUNT", "count") == 1


def test_lock_timeout_with_stop_on_err_ends_without_result():
    g = rig_with([measure(i) for i in range(1, 6)])
    g.w("CTRL", g.r("CTRL") | CTRL["stop_on_err"].mask)
    g.m.lock_model = lambda i, w: i != 2
    g.start()
    assert g.f("STATUS", "done") and g.f("STATUS", "err_lock") and not g.f("STATUS", "busy")
    assert g.f("POINT_COUNT", "count") == 2 and g.f("FIRST_ERR_INDEX", "index") == 2
    assert g.m.spi_words == [1, 2, 3]
    assert g.f("SWEEP_COUNT", "count") == 0 and not g.f("STATUS", "aborted")
    assert g.f("ENTRY_INDEX", "index") == 2


def test_first_err_index_is_the_first():
    g = rig_with([measure(i) for i in range(4)])
    g.m.lock_model = lambda i, w: i not in (2, 3)
    g.start()
    assert g.f("FIRST_ERR_INDEX", "index") == 2


def test_n_avg_zero_is_one():
    g = rig_with([measure(1)], n_avg=0)
    g.start()
    assert g.results() == [0x100]


def test_n_avg_max_fits_28_bits():
    g = rig_with([measure(1)], n_avg=4095, base=0xFFFF)
    g.start()
    assert g.results() == [4095 * 0xFFFF]


def test_result_memory_overflow_is_err_table():
    g = rig_with([measure(i) for i in range(5)], result_aw=2)
    g.start()
    assert g.f("STATUS", "err_table") and g.f("STATUS", "done") and not g.f("STATUS", "busy")
    assert g.f("POINT_COUNT", "count") == 4 and g.f("SWEEP_COUNT", "count") == 0
    assert g.m.spi_words == [0, 1, 2, 3, 4]


def test_src1_test_generator_formula():
    g = rig_with([measure(i) for i in range(300)], base=0xFF80, n_avg=3, table_aw=9, result_aw=9)
    g.start()
    res = g.results(300)
    assert res[0] == 3 * 0xFF80
    assert res[0x7F] == 3 * 0xFFFF
    assert res[0x80] == 3 * 0 and res[0xFF] == 3 * ((0xFF80 + 0xFF) & 0xFFFF)
    assert res[0x100] == res[0] and res[299] == 3 * ((0xFF80 + (299 & 0xFF)) & 0xFFFF)


def test_src2_external_stream():
    g = rig_with([measure(1), measure(2)], src=2, n_avg=3)
    calls = []
    g.m.ext_samples = lambda idx: calls.append(idx) or 100 + idx
    g.start()
    assert g.results() == [300, 303] and calls == [0, 0, 0, 1, 1, 1]


def test_src2_without_stream_waits_forever():
    g = rig_with([measure(1)], src=2)
    g.start()
    assert g.f("STATUS", "busy") and g.f("STATUS", "wait_sample")


def test_src0_pauses_until_n_avg_pushes():
    g = rig_with([measure(1), measure(2)], src=0, n_avg=3)
    g.start()
    assert g.f("STATUS", "busy") and g.f("STATUS", "wait_sample") and g.f("STATUS", "state") == SAMPLE
    assert g.m.spi_words == [1]
    g.w("DET_PUSH", 10)
    g.w("DET_PUSH", 20)
    assert g.f("STATUS", "busy") and g.f("POINT_COUNT", "count") == 0
    g.w("DET_PUSH", 0x1_0030)                       # 16 bit sample
    assert g.f("POINT_COUNT", "count") == 1 and g.f("STATUS", "busy")
    assert g.m.spi_words == [1, 2] and g.f("STATUS", "wait_sample")
    for v in (1, 2, 3):
        g.w("DET_PUSH", v)
    assert g.f("STATUS", "done") and not g.f("STATUS", "busy") and not g.f("STATUS", "wait_sample")
    assert g.results() == [10 + 20 + 0x30, 6]
    assert g.r("DET_PUSH") == 0


def test_det_push_outside_sample_is_dropped():
    g = rig_with([measure(1)], src=0, n_avg=1)
    g.w("DET_PUSH", 77)                             # idle
    g.start()
    assert g.f("STATUS", "busy") and g.f("POINT_COUNT", "count") == 0
    g.w("DET_PUSH", 5)
    g.w("DET_PUSH", 99)                             # done: dropped
    assert g.results() == [5]
    g2 = rig_with([measure(1)], src=1)
    g2.start()
    g2.w("DET_PUSH", 99)
    assert g2.results() == [4 * 0x100]


def test_src3_pauses_forever_and_abort_ends_it():
    g = rig_with([measure(1), measure(2)], src=3)
    g.start()
    for _ in range(5):
        g.w("DET_PUSH", 1)
    assert g.f("STATUS", "busy") and g.f("STATUS", "wait_sample")
    g.pulse("abort")
    assert g.f("STATUS", "done") and g.f("STATUS", "aborted") and not g.f("STATUS", "busy")
    assert g.f("POINT_COUNT", "count") == 0 and g.m.spi_words == [1]
    assert g.f("SWEEP_COUNT", "count") == 0 and g.f("ENTRY_INDEX", "index") == 0
    assert not g.f("STATUS", "wait_sample")


def test_abort_keeps_finished_points_and_drops_the_unfinished_one():
    g = rig_with([measure(1), measure(2)], src=0, n_avg=2)
    g.start()
    g.w("DET_PUSH", 4)
    g.w("DET_PUSH", 6)
    g.w("DET_PUSH", 9)                              # one of two samples of point 1
    g.pulse("abort")
    assert g.results() == [10] and g.f("STATUS", "aborted")
    g.w("DET_CFG", 1)
    g.start()                                       # a new sweep works and clears aborted
    assert not g.f("STATUS", "aborted") and len(g.results()) == 2


def test_abort_when_idle_does_nothing():
    g = Rig()
    g.pulse("abort")
    assert g.r("STATUS") == 0


def test_soft_reset_clears_sequencer_keeps_config_and_memory():
    g = rig_with([measure(1), measure(2)], src=0, n_avg=3)
    g.w("SPI_DIV", 9)
    g.start()
    g.w("DET_PUSH", 1)
    g.pulse("soft_reset")
    assert g.r("STATUS") == 0x80                    # only pin_owner_act (owner stays requested)
    assert g.f("POINT_COUNT", "count") == 0 and g.f("ENTRY_INDEX", "index") == 0
    assert g.f("SPI_DIV", "div") == 9 and g.f("N_AVG", "n") == 3 and g.f("N_ENTRIES", "n") == 2
    assert g.m._table[1][0] == 2
    g.w("DET_PUSH", 1)                              # dropped, idle
    assert g.f("POINT_COUNT", "count") == 0
    g.w("DET_CFG", 1)
    g.start()
    assert g.f("POINT_COUNT", "count") == 2


def test_soft_reset_clears_done_and_flags():
    g = rig_with([measure(1)])
    g.m.lock_model = lambda i, w: False
    g.start()
    assert g.f("STATUS", "err_lock") and g.f("STATUS", "done")
    g.pulse("soft_reset")
    assert g.f("STATUS", "err_lock") == 0 and g.f("STATUS", "done") == 0


def test_results_are_only_cleared_by_overwriting():
    g = rig_with([measure(1)])
    g.start()
    first = g.results()
    g.pulse("soft_reset")
    assert g.results(1) == first


def test_irq_is_irq_en_and_done_and_irq_ack_clears():
    g = rig_with([measure(1)])
    assert not g.m.irq
    g.start()
    assert g.f("STATUS", "done") and not g.m.irq               # irq_en off
    g.w("CTRL", g.r("CTRL") | CTRL["irq_en"].mask)
    assert g.m.irq
    g.pulse("irq_ack")
    assert not g.m.irq and not g.f("STATUS", "done") and g.f("CTRL", "irq_en") == 1


def test_counters():
    g = rig_with([measure(1), measure(2)])
    g.start()
    g.start()
    assert (g.f("SWEEP_COUNT", "count"), g.f("POINT_COUNT", "count"), g.f("ENTRY_INDEX", "index")) == (2, 2, 2)
    g.w("DET_CFG", 3)
    g.start()
    g.pulse("abort")
    assert g.f("SWEEP_COUNT", "count") == 2


def test_sweep_count_wraps():
    g = rig_with([measure(1)])
    g.m._sweep_count = 0xFFFFFFFF
    g.start()
    assert g.r("SWEEP_COUNT") == 0


def test_the_model_only_emits_words_of_the_table():
    rnd = random.Random(7)
    g = Rig(table_aw=8, result_aw=8)
    g.w("DET_CFG", 1)
    g.own()
    entries = [TableEntry(rnd.getrandbits(32), rnd.getrandbits(6), rnd.random() < .7, rnd.random() < .3,
                          rnd.random() < .5, rnd.random() < .5) for _ in range(200)]
    g.load(entries)
    g.m.lock_model = lambda i, w: rnd.random() < .8
    g.start()
    words = {e.word for e in entries if e.spi_en}
    assert g.m.spi_words == [e.word for e in entries if e.spi_en]
    assert set(g.m.spi_words) <= words
    assert g.f("POINT_COUNT", "count") == sum(e.measure for e in entries)


# ---- pins ---------------------------------------------------------------------------------------------------
def test_pin_owner_act_follows_request_only_while_idle():
    g = rig_with([measure(1)], src=3)
    assert g.f("STATUS", "pin_owner_act") == 1
    g.start()
    g.w("CTRL", g.r("CTRL") & ~CTRL["pin_owner"].mask)         # request the PS while busy
    assert g.f("STATUS", "pin_owner_act") == 1
    g.pulse("abort")
    assert g.f("STATUS", "pin_owner_act") == 0
    g.w("CTRL", CTRL["pin_owner"].mask)
    assert g.f("STATUS", "pin_owner_act") == 1


def test_taking_ownership_loads_manual_without_make_before_break():
    g = Rig()
    g.w("PE4302", 0x15 | 1 << 8)                              # PS owner: no engine action
    assert g.m.pe_trace == []
    g.own()
    assert g.m.pe_trace == [0x15]
    assert g.f("PIN_STATE", "pe_out") == 0x15 and g.f("PIN_STATE", "pe_t") == 0


def test_manual_change_while_idle_and_owner_is_make_before_break():
    g = Rig()
    g.own()
    g.m.pe_trace.clear()
    g.w("PE4302", 0b000011 | 1 << 8)
    assert g.m.pe_trace == [0x3F, 0b000011]
    g.w("PE4302", 0b001100 | 1 << 8)
    assert g.m.pe_trace[2:] == [0b001111, 0b001100]
    g.w("PE4302", 0b001100 | 1 << 8)                          # no change: nothing
    assert len(g.m.pe_trace) == 4


def test_manual_change_active_low_uses_and():
    g = Rig()
    g.own()
    g.w("PE4302", 0b000011)                                   # active_high = 0
    g.m.pe_trace.clear()
    g.w("PE4302", 0b001100)
    assert g.m.pe_trace == [0b000000, 0b001100]


def test_manual_write_without_ownership_or_while_busy_does_not_touch_pins():
    g = Rig()
    g.w("PE4302", 0x01 | 1 << 8)
    assert g.m.pe_trace == []
    g2 = rig_with([measure(1)], src=3)
    g2.start()
    before = list(g2.m.pe_trace)
    g2.w("PE4302", 0x02 | 1 << 8)
    assert g2.m.pe_trace == before and g2.f("PIN_STATE", "pe_out") == 0x3F


def test_engine_value_resets_to_all_stages_in():
    g = Rig()
    g.w("PE4302", 0x01 | 1 << 8)
    g.own()
    g.w("PE4302", 0x3F | 1 << 8)
    assert g.f("PIN_STATE", "pe_out") == 0x3F
    assert Rig().m._pe_engine == 0x3F


def test_pin_state_shows_ps_pins_for_ps_owner_and_engine_pins_otherwise():
    g = Rig()
    g.m.emio_pe_o, g.m.emio_pe_t, g.m.pad_pe = 0x05, 0x30, 0x3F
    assert g.f("PIN_STATE", "pe_out") == 0x05 and g.f("PIN_STATE", "pe_t") == 0x30
    assert g.f("PIN_STATE", "pe_in") == 0x05 | 0x30
    g.m.ld_now = True
    assert g.f("PIN_STATE", "ld") == 1 and g.f("STATUS", "ld_now") == 1
    assert (g.f("PIN_STATE", "le"), g.f("PIN_STATE", "clk")) == (1, 0)
    g.own()
    assert g.f("PIN_STATE", "pe_t") == 0 and g.f("PIN_STATE", "pe_in") == g.f("PIN_STATE", "pe_out") == 0x3F


@pytest.mark.parametrize("active_high", [True, False])
def test_mbb_trace_equals_the_pe4302_driver_for_all_transitions(active_high):
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(6)]
    dev = PE4302(lines, DEFAULT_WEIGHTS_DB, active_high)
    ah = 1 << 8 if active_high else 0

    def code_of(levels):
        on = levels if active_high else ~levels & 0x3F
        return sum(s for i, s in enumerate(STEPS) if on >> i & 1)

    g = Rig()
    g.w("PE4302", ah | 0x3F)
    g.own()
    for old in range(64):
        for new in range(64):
            dev.set_attenuation(code_of(old) * STEP_DB)
            g.w("PE4302", ah | old)                           # settle the engine at `old`
            if g.m._pe_engine != old:
                pytest.fail("engine not at old")
            log.events.clear()
            dev.set_attenuation(code_of(new) * STEP_DB)
            state, make, seen_off = old, None, False
            for name, level in log.events:
                bit = 1 << (int(name[1:]) - 1)
                if (level == 1) != active_high and not seen_off:
                    make, seen_off = state, True
                state = state & ~bit | (bit if level else 0)
            make = state if make is None else make
            g.m.pe_trace.clear()
            g.w("PE4302", ah | new)
            expect = [] if new == old else [make, new]
            assert g.m.pe_trace == expect, (old, new)
