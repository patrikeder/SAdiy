"""A sweep larger than the core's table or result memory runs as several tables in a row (OffloadSweep.chunks)."""
import pytest
from sadiy_ebaz.ebaz_pl_model import PlModel
from sadiy_ebaz.offload_sweep import DEFAULT_STEPS, OffloadSweep, plan_chunks
from sadiy_ebaz.platform import build_table
from sadiy_ebaz.platforms.fake_pl import FakePlPlatform

from sadiy.core.freqplan import build_sweep
from sadiy.drivers.adf4351 import Adf4351, Output, Outputs
from sadiy.drivers.pe4302 import PE4302

N_AVG = 3
VPC = 4.096 / 32768.0


def points(n, start=50e6, stop=450e6):
    return build_sweep(start, stop, n, 10.7e6, "high", 25e6)


class CodeSource:
    """Detector code of the n-th measured point, whatever the way the sweep is split: PS push, N_AVG codes a point."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        code = 1000 + 7 * (self.calls // N_AVG)
        self.calls += 1
        return code


class Rig:
    def __init__(self, table_aw=12, result_aw=12, **kw):
        model = PlModel(table_aw=table_aw, result_aw=result_aw)
        self.plat = FakePlPlatform(model, det_src=0, sample_source=CodeSource(), volts_per_count=VPC)
        self.synth = Adf4351(self.plat.synth_link(), pfd_hz=25e6)
        self.synth.set_outputs(Outputs(main=Output(True, -4)))
        self.atten = PE4302(self.plat.atten_port())
        self.offload = self.plat.offload()
        self.adapter = OffloadSweep(self.offload, self.synth, DEFAULT_STEPS, True, atten=self.atten, **kw)
        self.uploaded = []
        real = self.offload.upload
        self.offload.upload = lambda entries: (self.uploaded.append(list(entries)), real(entries))[1]


def words_of(points_, synth):
    from sadiy_ebaz.platform import point_words
    return point_words(points_, synth)


# ---- the planner -----------------------------------------------------------------------------------------------
def test_plan_covers_every_point_once_in_order_and_fits():
    rig = Rig()
    pts = points(60)
    words = words_of(pts, rig.synth)
    unlimited = plan_chunks(words, None, None)
    assert unlimited == [(0, 60)]
    chunks = plan_chunks(words, 64, None)
    assert len(chunks) > 1
    assert chunks[0][0] == 0 and chunks[-1][1] == 60
    assert all(b[0] == a[1] for a, b in zip(chunks, chunks[1:]))
    for first, stop in chunks:
        table = build_table(pts[first:stop], rig.synth, 0)
        assert len(table) <= 64
        assert sum(e.measure for e in table) == stop - first


def test_plan_closes_a_run_only_when_the_next_point_does_not_fit():
    rig = Rig()
    pts = points(60)
    words = words_of(pts, rig.synth)
    chunks = plan_chunks(words, 64, None)
    for first, stop in chunks[:-1]:
        longer = build_table(pts[first:stop + 1], rig.synth, 0)
        assert len(longer) > 64
        assert len(longer) > len(build_table(pts[first:stop], rig.synth, 0))


def test_every_run_starts_with_the_full_register_set():
    rig = Rig()
    pts = points(60)
    for first, stop in plan_chunks(words_of(pts, rig.synth), 64, None)[1:]:
        table = build_table(pts[first:stop], rig.synth, 0)
        first_point = table[:next(i for i, e in enumerate(table) if e.measure) + 1]
        assert sorted(e.word & 7 for e in first_point) == [0, 1, 2, 3, 4, 5]


def test_plan_limits_the_points_of_a_run_by_the_result_memory():
    rig = Rig()
    words = words_of(points(40), rig.synth)
    chunks = plan_chunks(words, None, 16)
    assert chunks == [(0, 16), (16, 32), (32, 40)]


def test_plan_refuses_a_point_that_does_not_fit_alone():
    rig = Rig()
    words = words_of(points(5), rig.synth)
    with pytest.raises(ValueError, match="point 0 needs 6 table entries"):
        plan_chunks(words, 5, None)


def test_plan_of_nothing_is_empty():
    assert plan_chunks([], 64, 64) == []


# ---- the adapter against the PL model --------------------------------------------------------------------------
def run(rig, pts, atten_db=10.0):
    return rig.adapter.run_points(pts, atten_db, N_AVG)


def test_chunked_sweep_gives_the_result_of_one_big_table():
    pts = points(60)
    big, small = Rig(), Rig(table_aw=6, result_aw=6)
    want = run(big, pts)
    got = run(small, pts)
    assert big.adapter.chunks == 1 and small.adapter.chunks > 1
    assert got[0] == pytest.approx(want[0], abs=0)
    assert got[1:] == want[1:]
    assert len(got[0]) == 60
    assert all(len(t) <= 64 for t in small.uploaded)
    assert len(small.uploaded) == small.adapter.chunks


def test_a_small_result_memory_alone_splits_the_sweep():
    pts = points(40)
    rig = Rig(result_aw=4)                                   # 16 results, plenty of table
    out = run(rig, pts)
    assert rig.adapter.chunks == 3 and len(out[0]) == 40
    assert [sum(e.measure for e in t) for t in rig.uploaded] == [16, 16, 8]
    assert out[0] == run(Rig(), pts)[0]


def test_chunk_boundaries_lose_no_point_and_repeat_none():
    pts = points(37)
    rig = Rig(table_aw=6, result_aw=6)
    volts = run(rig, pts)[0]
    codes = [round(v / VPC) for v in volts]
    assert codes == [1000 + 7 * i for i in range(37)]        # point i got the i-th code: first, boundaries, last


def test_a_chunked_sweep_uploads_all_tables_again_at_every_sweep():
    rig = Rig(table_aw=6, result_aw=6)
    pts = points(60)
    run(rig, pts)
    n = len(rig.uploaded)
    run(rig, pts)
    assert len(rig.uploaded) == 2 * n and rig.adapter.uploads == 2 * n


def test_a_sweep_that_fits_still_uploads_once():
    rig = Rig()
    pts = points(12)
    run(rig, pts)
    run(rig, pts)
    assert rig.adapter.uploads == 1 and rig.adapter.chunks == 1


def test_a_changed_sweep_is_planned_again():
    rig = Rig(table_aw=6, result_aw=6)
    run(rig, points(60))
    first = rig.adapter.chunks
    run(rig, points(12))
    assert rig.adapter.chunks == 1 and first > 1
    run(rig, points(60))
    assert rig.adapter.chunks == first


def test_an_incomplete_run_raises_and_forgets_the_table():
    rig = Rig(table_aw=6, result_aw=6)
    pts = points(60)
    real = rig.offload.run
    count = {"n": 0}

    def short(n_avg, timeout_s=10.0):
        res = real(n_avg, timeout_s)
        count["n"] += 1
        if count["n"] == 2:
            res.sums = res.sums[:-1]
        return res

    rig.offload.run = short
    with pytest.raises(RuntimeError, match="incomplete"):
        run(rig, pts)
    assert rig.adapter._key is None


def test_a_point_larger_than_the_core_is_an_error():
    rig = Rig(table_aw=2)                                    # 4 entries: the first point needs 6
    with pytest.raises(ValueError, match="table entries"):
        run(rig, points(5))
