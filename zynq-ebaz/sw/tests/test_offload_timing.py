"""RegOffload.run() reports the time of the sweep (start write until done is seen) and of the result readout
separately: the readout is register accesses of the host and grows with the point count."""
import pytest
from sadiy_ebaz.ebaz_pl_model import SRC_TEST, PlModel
from sadiy_ebaz.platform import TableEntry
from sadiy_ebaz.reg_offload import RegOffload
from sadiy_ebaz.regmap_toml import OFFSET, REGS

STATUS_S = 1e-3            # cost of one STATUS read: what the poll loop spends per round
RESULT_READ_S = 10e-6      # cost of one RESULT_DATA read


class Rig:
    def __init__(self):
        self.now = 0.0
        self.status_reads = 0
        self.status_at_start = 0
        self.model = PlModel()
        self.model.ld_now = True

        def rd(offset):
            if offset == OFFSET["STATUS"]:
                self.status_reads += 1
                self.now += STATUS_S
            elif offset == OFFSET["RESULT_DATA"]:
                self.now += RESULT_READ_S
            return self.model.read(offset)

        def wr(offset, value):
            if offset == OFFSET["CTRL"] and value & REGS["CTRL"].fields["start"].mask:
                self.status_at_start = self.status_reads       # polls before this belong to taking the pins
            self.model.write(offset, value)

        self.off = RegOffload(rd, wr, det_src=SRC_TEST, det_test_base=100, poll_s=0.0,
                              sleep=lambda s: None, clock=lambda: self.now)

    def run(self, n_points, n_avg=2):
        self.off.upload([TableEntry(word=0, measure=True, skip_lock=True) for _ in range(n_points)])
        res = self.off.run(n_avg)
        return res, self.status_reads - self.status_at_start


def test_sweep_and_readout_time_are_reported_separately():
    rig = Rig()
    res, status_reads = rig.run(20)
    assert len(res.sums) == 20
    assert rig.off.last_read_s == pytest.approx(20 * RESULT_READ_S)
    assert rig.off.last_sweep_s == pytest.approx(status_reads * STATUS_S) and status_reads >= 1


def test_readout_time_grows_with_the_points_and_the_sweep_time_does_not_include_it():
    rig = Rig()
    rig.run(8)
    small_read, small_sweep = rig.off.last_read_s, rig.off.last_sweep_s
    rig.run(200)
    assert rig.off.last_read_s == pytest.approx(25 * small_read)
    assert rig.off.last_sweep_s == pytest.approx(small_sweep)       # same polls: the readout is not in it


def test_the_times_belong_to_the_last_run_only():
    rig = Rig()
    rig.run(10)
    first = (rig.off.last_sweep_s, rig.off.last_read_s)
    rig.run(10)
    assert (rig.off.last_sweep_s, rig.off.last_read_s) == pytest.approx(first)


def test_times_start_at_zero():
    assert Rig().off.last_sweep_s == 0.0 and Rig().off.last_read_s == 0.0
