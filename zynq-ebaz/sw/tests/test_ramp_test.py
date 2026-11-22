"""The ramp self-test (`sadiy_ebaz.ramp_test`): passes against the PL model, and every kind of wrong answer fails
with the index named. The pass criteria themselves are in docs/selftest.md."""
import dataclasses

import pytest

from sadiy_ebaz import ramp_test as rt
from sadiy_ebaz.ebaz_pl_model import SRC_TEST, PlModel
from sadiy_ebaz.platform import OffloadResult
from sadiy_ebaz.reg_offload import RegOffload

OK_STATUS = dict(done=1, busy=0, state=0, wait_sample=0, err_lock=0, err_table=0, aborted=0, pin_owner_act=1)


def _result(n_points=300, n_avg=4, base=10000, **over):
    sums = rt.expected_sums(n_points, n_avg, base)
    return OffloadResult(sums=sums, unlocked=[False] * n_points, n_avg=n_avg, **over)


def _status(n_points=300, **over):
    return dict(OK_STATUS, point_count=n_points, entry_index=n_points, sweep_count=1, **over)


def _check(res, status=None, **kw):
    rep = rt.Report()
    n = kw.pop("n_points", 300)
    rt.check_sweep(rep, "sweep 1", res, status or _status(n), n_points=n, n_avg=kw.pop("n_avg", 4),
                   base=kw.pop("base", 10000), sweep_count_before=kw.pop("sweep_count_before", 0), **kw)
    return rep


def test_expected_values_follow_the_rtl_formula():
    want = rt.expected_sums(300, 4, 10000)
    assert want[0] == 40000 and want[255] == 4 * (10000 + 255)
    assert want[256] == want[0]                                   # the index part is 8 bits wide
    assert rt.expected_sums(20, 1, 0xFFF0)[16] == 0               # 16-bit wrap of base + index
    assert max(rt.expected_sums(256, 4095, 0xFFFF)) < 1 << 28     # never reaches the unlocked / ovr bits


def test_good_sweep_passes():
    rep = _check(_result(), previous=rt.expected_sums(300, 4, 10000), raw_words=rt.expected_sums(300, 4, 10000),
                 first_err_index=0, elapsed_s=0.0132, floor_s=0.0120, ceil_s=0.05)
    assert rep.ok, rep.lines()


def test_wrong_sum_names_the_index():
    res = _result()
    res.sums[17] += 1
    rep = _check(res)
    assert not rep.ok
    assert "first at index 17" in rep.failed[0].detail


@pytest.mark.parametrize("make,hint", [
    (lambda: [5] * 300, "stuck"),
    (lambda: [0] * 300, "stuck"),                                  # all equal wins over "all zero"
    (lambda: rt.expected_sums(300, 2, 10000), "N_AVG=2, DET_TEST.base=10000"),
    (lambda: rt.expected_sums(300, 4, 9000), "N_AVG=4, DET_TEST.base=9000"),
    (lambda: rt.expected_sums(301, 4, 10000)[1:], "everything from there on"),
])
def test_diagnosis_of_typical_faults(make, hint):
    got = make()[:300]
    rep = _check(dataclasses.replace(_result(), sums=got))
    assert not rep.ok
    assert hint in rep.failed[0].detail, rep.failed[0].detail


def test_lock_flags_fail():
    res = _result(err_lock=True)
    res.unlocked[3] = True
    rep = _check(res, _status(err_lock=1))
    assert {c.name.split(": ", 1)[1] for c in rep.failed} >= {"no lock error flag (lock wait is skipped)"}


def test_counters_are_checked():
    rep = _check(_result(), dict(_status(), point_count=299, entry_index=301, sweep_count=5), sweep_count_before=0)
    names = " | ".join(c.name for c in rep.failed)
    assert "POINT_COUNT" in names and "ENTRY_INDEX" in names and "SWEEP_COUNT" in names


def test_stray_result_bits_fail():
    raw = rt.expected_sums(300, 4, 10000)
    raw[42] |= 1 << 30
    rep = _check(_result(), raw_words=raw)
    assert "index 42" in rep.failed[0].detail


def test_engine_must_be_idle_and_own_the_pins():
    assert not _check(_result(), _status(state=7)).ok
    assert not _check(_result(), _status(wait_sample=1)).ok
    assert not _check(_result(), _status(pin_owner_act=0)).ok


def test_nonzero_first_err_index_fails():
    assert not _check(_result(), first_err_index=3).ok


def test_timing_floor_and_ceiling():
    assert not _check(_result(), elapsed_s=0.010, floor_s=0.012).ok          # faster than the hardware can be
    assert not _check(_result(), elapsed_s=0.200, floor_s=0.012, ceil_s=0.05).ok
    assert _check(_result(), elapsed_s=0.013, floor_s=0.012, ceil_s=0.05).ok


def test_a_failed_run_is_one_failed_check_not_an_exception():
    rep = _check(None)
    assert not rep.ok and len(rep.failed) == 1


def test_changed_sweep_fails_against_the_previous_one():
    prev = rt.expected_sums(300, 4, 10000)
    prev[5] += 4
    assert not _check(_result(), previous=prev).ok


def _model_offload(base=10000):
    m = PlModel()
    m.ld_now = True
    return m, RegOffload(m.read, m.write, det_src=SRC_TEST, det_test_base=base, poll_s=0.0)


def test_run_selftest_passes_against_the_model():
    m, off = _model_offload()
    rep = rt.run_selftest(off, n_points=401, sweeps=3)
    assert rep.ok, rep.lines()
    assert any("sweep 3" in c.name for c in rep.checks)


def test_run_selftest_catches_a_corrupting_engine():
    m, off = _model_offload()
    real = off.run

    def run(n_avg, timeout_s=10.0):
        res = real(n_avg, timeout_s)
        res.sums[300] ^= 0x400                                      # one flipped bit in one result
        return res

    off.run = run
    rep = rt.run_selftest(off, n_points=401, sweeps=1)
    assert not rep.ok and "first at index 300" in rep.failed[0].detail


def test_run_selftest_reports_a_refused_table_and_a_timeout():
    m, off = _model_offload()
    rep = rt.run_selftest(off, n_points=(1 << m.table_aw) + 1, sweeps=1)     # more than the core holds
    assert not rep.ok and rep.failed[0].name.endswith("table upload accepted")
    m, off = _model_offload()
    off.run = lambda n_avg, timeout_s=10.0: (_ for _ in ()).throw(TimeoutError("no done"))
    rep = rt.run_selftest(off, n_points=10, sweeps=2)
    assert len(rep.failed) == 2 and "TimeoutError" in rep.failed[0].detail


def test_main_against_the_model_exits_zero(capsys):
    assert rt.main(["--model", "--wrap", "--sweeps", "2"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out and "N_AVG 1, base 0xFFF0" in out


def test_main_exits_one_when_the_table_is_too_big(capsys):
    assert rt.main(["--model", "--points", "5000"]) == 1
    assert "table can hold the test" in capsys.readouterr().out


def test_main_without_a_bitstream_exits_two(tmp_path, capsys):
    state = tmp_path / "state"
    state.write_text("unknown\n")
    assert rt.main(["--fpga-state", str(state)]) == 2
    assert "run ./fpga.sh" in capsys.readouterr().err


def test_sweepd_test_ramp_flag_selects_the_test_detector(monkeypatch):
    from sadiy.server import sweepd

    seen = {}

    def fake_build(cfg):
        seen["detector"] = cfg["platform"]["detector"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(sweepd, "build_hw_engine", fake_build)
    with pytest.raises(SystemExit):
        sweepd.main(["--platform", "ebaz", "--test-ramp"])
    assert seen["detector"] == "test"


class MemoryOffload:
    """An engine with a result memory that is not cleared by start (like the PL's); `writes` says for how many runs it
    stores results (None = always), `ignore_base` makes it ignore DET_TEST.base changes."""

    def __init__(self, n_points, base, writes=None):
        self.base, self.n_points, self.writes, self.runs, self.sweeps = base, n_points, writes, 0, 0
        self.mem = [0] * n_points

    def upload(self, entries):
        pass

    def run(self, n_avg, timeout_s=10.0):
        self.runs += 1
        if self.writes is None or self.runs <= self.writes:
            self.mem = rt.expected_sums(self.n_points, n_avg, self.base)
            self.sweeps += 1
        return OffloadResult(sums=list(self.mem), unlocked=[False] * self.n_points, n_avg=n_avg)

    def abort(self):
        pass

    def status(self):
        return dict(OK_STATUS, point_count=self.n_points, entry_index=self.n_points, sweep_count=self.sweeps)


def _memory_run(n_points=300, **kw):
    off = MemoryOffload(n_points, 10000, kw.pop("writes", None))

    def set_base(b):
        off.base = b

    return off, rt.run_selftest(off, n_points=n_points, set_base=set_base, sweep_count=lambda: off.sweeps, **kw)


def test_sweep_bases_all_differ_and_the_last_repeats_the_first():
    assert rt.sweep_bases(100, 1) == [100]
    assert rt.sweep_bases(100, 2) == [100, 101]
    assert rt.sweep_bases(100, 5) == [100, 101, 102, 103, 100]
    assert rt.sweep_bases(0xFFFF, 3) == [0xFFFF, 0, 0xFFFF]


def test_engine_that_writes_results_every_run_passes():
    off, rep = _memory_run(sweeps=5)
    assert rep.ok, rep.lines()
    assert any("identical" in c.name for c in rep.checks)           # the repeated base
    assert any("poison" in c.name for c in rep.checks)


@pytest.mark.parametrize("writes", [0, 1, 2])
def test_engine_that_stops_writing_results_fails_even_when_the_old_ones_fit(writes):
    """The result memory keeps its content: without a changing base the later sweeps would pass on stale data."""
    off, rep = _memory_run(sweeps=4, writes=writes)
    assert not rep.ok
    assert any("sweep" in c.name and "every sum" in c.name for c in rep.failed), rep.lines()


def test_pins_must_stay_as_they_were():
    off = MemoryOffload(50, 10000)
    rep = rt.run_selftest(off, n_points=50, sweeps=1, pins_before=(0x2A, 1), pins_now=lambda: (0x3F, 1))
    assert [c.name for c in rep.failed] == ["sweep 1: pins unchanged (PE4302 levels the engine drives, CE)"]
    rep = rt.run_selftest(off, n_points=50, sweeps=1, pins_before=(0x2A, 1), pins_now=lambda: (0x2A, 1))
    assert rep.ok


def _model_with_config():
    from sadiy_ebaz import regmap_toml

    m = PlModel()
    m.ld_now = True
    off = RegOffload(m.read, m.write, det_src=3, det_test_base=1234, poll_s=0.0)
    for name, v in (("T_MIN_US", 77), ("T_SETTLE_US", 88), ("N_AVG", 9)):
        m.write(regmap_toml.REGS[name].offset, v)
    return m, off, (lambda n: m.read(regmap_toml.REGS[n].offset))


def test_main_restores_the_configuration_it_changed(monkeypatch):
    """T_MIN / T_SETTLE / DET_* are set by the test; whatever was in the registers before comes back."""
    m, off, reg = _model_with_config()
    before = {n: reg(n) for n in ("T_MIN_US", "T_SETTLE_US", "N_AVG", "DET_CFG", "DET_TEST")}
    monkeypatch.setattr(rt, "_model_offload", lambda: off)
    assert rt.main(["--model", "--sweeps", "2", "--t-min", "20", "--t-settle", "30"]) == 0
    assert {n: reg(n) for n in before} == before


def test_run_on_core_in_a_running_daemon_keeps_pins_and_config():
    """The in-process use (sweepd command): no pin release, no soft reset, PE4302 / ADF_PINS not written back."""
    from sadiy_ebaz import regmap_toml

    m, off, reg = _model_with_config()
    off.acquire_pins()                                          # as a sweeping daemon has them
    writes = []
    real = m.write
    off._wr = lambda o, v: (writes.append(o), real(o, v))[1]
    before = {n: reg(n) for n in ("T_MIN_US", "T_SETTLE_US", "N_AVG", "DET_CFG", "DET_TEST")}
    rep = rt.run_on_core(off, sweeps=3)
    assert rep.ok, rep.lines()
    assert {n: reg(n) for n in before} == before
    st = off.status()
    assert st["pin_owner_act"], "the engine still owns the pins"
    pe = regmap_toml.REGS["PE4302"].offset
    assert not any(w == pe for w in writes), "PE4302 must not be written while the engine owns the pins"
    assert regmap_toml.REGS["ADF_PINS"].offset not in writes, "ADF_PINS.ce is already driven by the owning engine"


def test_run_on_core_presets_ce_only_before_taking_the_pins():
    from sadiy_ebaz import regmap_toml

    m, off, reg = _model_with_config()                          # the engine does not own the pins yet
    writes = []
    real = m.write
    off._wr = lambda o, v: (writes.append(o), real(o, v))[1]
    assert rt.run_on_core(off, sweeps=2).ok
    assert regmap_toml.REGS["ADF_PINS"].offset in writes


def test_model_is_recognised_as_simulated():
    m, off, _ = _model_with_config()
    assert rt.is_simulated(off)


def test_main_fill_uses_the_whole_memory(capsys):
    assert rt.main(["--model", "--fill", "--sweeps", "2"]) == 0
    assert "4096 points" in capsys.readouterr().out
