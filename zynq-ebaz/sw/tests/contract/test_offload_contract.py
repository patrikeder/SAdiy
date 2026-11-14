"""Contract every SweepOffload backend must pass, run through RegOffload.

OFFLOAD_PLATFORMS lists the backends under test: (id, factory). `factory(**kw)` returns a Platform whose
`offload()` is the SweepOffload; `kw` may carry `det_src` and `sample_source` (see FakePlPlatform). Tests that
need to steer the engine (fail a lock, pick the detector source) use the `model` attribute of the platform and
are skipped for a backend without it. The hardware backends (ebaz-pl, written by the Linux lane) are added to
this list there; this file is the acceptance test for them.
"""
import pytest
from sadiy_ebaz.platform import SweepOffload, TableEntry, build_table
from sadiy_ebaz.platforms.fake_pl import FakePlPlatform
from sadiy_ebaz.reg_offload import RegOffload
from sadiy_ebaz.regmap_toml import OFFSET

from sadiy.core.freqplan import build_sweep
from sadiy.drivers.adf4351 import Adf4351, Output, Outputs
from sadiy.hal.fake import FakeSpi

OFFLOAD_PLATFORMS = [
    ("fake_pl", FakePlPlatform),
]

BASE = 10000


@pytest.fixture(params=[p[1] for p in OFFLOAD_PLATFORMS], ids=[p[0] for p in OFFLOAD_PLATFORMS])
def make(request):
    made = []

    def factory(**kw):
        plat = request.param(**kw)
        made.append(plat)
        return plat

    yield factory
    for p in made:
        p.close()


def table(n=6):
    synth = Adf4351(FakeSpi(), pfd_hz=25e6)
    synth.set_outputs(Outputs(main=Output(True, -4)))
    return build_table(build_sweep(50e6, 450e6, n, 10.7e6, "high", 25e6), synth, 0x15)


def steer(plat):
    model = getattr(plat, "model", None)
    if model is None:
        pytest.skip("backend cannot be steered")
    return model


def test_is_a_sweep_offload(make):
    assert isinstance(make().offload(), SweepOffload)


def test_capabilities(make):
    plat = make()
    cap = plat.capabilities
    assert cap.sweep_offload and cap.max_entries >= 64 and cap.max_points >= 64
    off = plat.offload()
    assert off.max_entries == cap.max_entries and off.max_points == cap.max_points


def test_one_sum_per_measure_entry_and_the_expected_sample(make):
    plat = make(det_src=1, det_test_base=BASE)
    off = plat.offload()
    entries = table(6)
    off.upload(entries)
    res = off.run(n_avg=4)
    assert len(res.sums) == sum(e.measure for e in entries) == 6
    assert res.sums == [4 * ((BASE + i) & 0xFFFF) for i in range(6)]
    assert res.unlocked == [False] * 6 and not res.aborted and not res.err_table
    assert res.n_avg == 4


def test_sums_scale_with_n_avg(make):
    off = make(det_src=1, det_test_base=BASE).offload()
    off.upload(table(3))
    for n in (1, 7, 100):
        assert off.run(n).sums == [n * (BASE + i) for i in range(3)]


def test_upload_twice_replaces_the_table(make):
    off = make(det_src=1, det_test_base=BASE).offload()
    off.upload(table(6))
    off.upload(table(2))
    assert len(off.run(1).sums) == 2


def test_unlocked_points_are_flagged(make):
    plat = make(det_src=1, det_test_base=BASE)
    steer(plat).lock_model = lambda i, w: i not in (1, 4)
    off = plat.offload()
    off.upload(table(6))
    res = off.run(2)
    assert res.unlocked == [False, True, False, False, True, False]
    assert res.err_lock
    assert res.sums[1] == 2 * (BASE + 1)
    assert off.status()["err_lock"] and off.status()["first_err_index"] == 1


def test_skip_lock_entries_are_never_flagged(make):
    plat = make(det_src=1, det_test_base=BASE)
    steer(plat).lock_model = lambda i, w: False
    off = plat.offload()
    off.upload([TableEntry(0x1234, spi_en=True, measure=True, skip_lock=True)])
    assert off.run(1).unlocked == [False]


def test_empty_table_is_refused(make):
    off = make().offload()
    off.upload([])
    with pytest.raises(RuntimeError, match="refused"):
        off.run(1)


def test_table_larger_than_the_core_is_refused(make):
    plat = make()
    with pytest.raises(ValueError):
        plat.offload().upload([TableEntry(0, spi_en=True)] * (plat.capabilities.max_entries + 1))


def test_bad_n_avg(make):
    off = make().offload()
    off.upload(table(2))
    for n in (0, 4096):
        with pytest.raises(ValueError):
            off.run(n)


def test_timeout_aborts_the_sweep(make):
    plat = make(det_src=3)
    off = plat.offload()
    off.upload(table(2))
    with pytest.raises(TimeoutError):
        off.run(1, timeout_s=0.05)
    st = off.status()
    assert not st["busy"] and st["aborted"]
    plat.model.write(OFFSET["DET_CFG"], 1)             # the engine is usable again
    assert len(off.run(1).sums) == 2


def test_abort_from_a_sample_source(make):
    holder = []

    def source():
        source.calls += 1
        if source.calls == 5:                          # during the 3rd point (2 samples per point)
            holder[0].abort()
        return 100

    source.calls = 0
    plat = make(det_src=0, sample_source=source)
    off = plat.offload()
    holder.append(off)
    off.upload(table(6))
    res = off.run(2)
    assert res.aborted
    assert res.sums == [200, 200] and len(res.unlocked) == 2


def test_abort_when_idle_is_harmless(make):
    off = make().offload()
    off.abort()
    assert not off.status()["aborted"]


def test_ps_push_source(make):
    codes = iter(range(1000, 100000))
    plat = make(det_src=0, sample_source=lambda: next(codes))
    off = plat.offload()
    off.upload(table(3))
    res = off.run(3)
    assert res.sums == [3 * 1000 + 3, 3 * 1003 + 3, 3 * 1006 + 3]
    assert plat.model.read(OFFSET["DET_CFG"]) == 0


def test_ps_push_without_a_source_is_an_error():
    plat = FakePlPlatform(det_src=0)
    off = RegOffload(plat.model.read, plat.model.write, det_src=0)
    off.upload(table(2))
    with pytest.raises(RuntimeError, match="sample_source"):
        off.run(1)


def test_counts_to_volts(make):
    off = make().offload()
    assert off.counts_to_volts(0) == 0.0
    assert off.counts_to_volts(10000) == pytest.approx(10000 * 4.096 / 32768)


def test_status_has_the_basics(make):
    off = make().offload()
    st = off.status()
    for key in ("busy", "done", "err_lock", "aborted", "err_table", "wait_sample", "pin_owner_act",
                "point_count", "sweep_count", "entry_index"):
        assert key in st


def test_run_takes_the_pins_and_release_gives_them_back(make):
    plat = make(det_src=1)
    off = plat.offload()
    assert off.status()["pin_owner_act"] == 0
    off.upload(table(2))
    off.run(1)
    assert off.status()["pin_owner_act"] == 1
    off.release_pins()
    assert off.status()["pin_owner_act"] == 0


def test_core_identity_is_checked():
    plat = FakePlPlatform()
    real_read = plat.model.read

    def bad_id(offset):
        return 0x12345678 if offset == OFFSET["ID"] else real_read(offset)

    with pytest.raises(RuntimeError, match="ID"):
        RegOffload(bad_id, plat.model.write)

    def bad_version(offset):
        return 0x00020000 if offset == OFFSET["VERSION"] else real_read(offset)

    with pytest.raises(RuntimeError, match="version"):
        RegOffload(bad_version, plat.model.write)
