"""The board bring-up script (sw/tools/pl_bringup.py) against the PlModel: it must pass on a correct core and
fail where the core misbehaves. No board needed."""
import importlib.util
import sys
from pathlib import Path

import pytest

SW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SW))
from sadiy_ebaz.ebaz_pl_model import PlModel  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS  # noqa: E402

spec = importlib.util.spec_from_file_location("pl_bringup", SW / "tools" / "pl_bringup.py")
pl_bringup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl_bringup)

RESULT_DATA = REGS["RESULT_DATA"].offset
ID = REGS["ID"].offset


def run(model, *stages):
    return pl_bringup.run(["--no-prompt", *stages], model=model)


def locking_model(ld: bool) -> PlModel:
    m = PlModel()
    m.ld_now = ld
    m.lock_model = lambda idx, word: ld
    m.adc_code = lambda idx: 9000 + idx
    return m


def test_all_stages_pass_on_a_correct_core(capsys):
    assert run(locking_model(False), "all") == 0
    out = capsys.readouterr().out
    assert "0 failed" in out and "FAIL" not in out


def test_lock_stage_with_lock_detect_high(capsys):
    assert run(locking_model(True), "lock") == 0
    assert "LD high: no err_lock" in capsys.readouterr().out


def test_wrong_results_are_reported(capsys):
    class Bad(PlModel):
        def read(self, offset):
            v = super().read(offset)
            return v ^ 1 if offset == RESULT_DATA else v

    assert run(Bad(), "gen") == 1
    assert "FAIL" in capsys.readouterr().out


def test_wrong_lock_flag_is_reported(capsys):
    # LD reads high but the core times out anyway: the LD-high branch must fail
    m = PlModel()
    m.ld_now = True
    m.lock_model = lambda idx, word: False
    assert run(m, "lock") == 1


def test_unknown_core_stops_before_any_write(capsys):
    writes = []

    class NotOurs(PlModel):
        def read(self, offset):
            return 0 if offset == ID else super().read(offset)

        def write(self, offset, value):
            writes.append(offset)
            super().write(offset, value)

    assert run(NotOurs(), "all") == 2
    assert writes == []


def test_unknown_stage_is_refused():
    assert pl_bringup.run(["nonsense"], model=PlModel()) == 2


def test_missing_adc_is_reported(capsys):
    m = locking_model(False)
    m.adc_code = None
    assert run(m, "adc") == 1
    assert "FAIL  the ADS1115 acknowledged" in capsys.readouterr().out


def test_old_bitstream_skips_the_adc_stage(capsys):
    class Old(PlModel):
        def read(self, offset):
            return 0x00010000 if offset == REGS["VERSION"].offset else super().read(offset)

    assert run(Old(), "adc", "ce", "if") == 0
    assert capsys.readouterr().out.count("SKIP") == 3


def test_if_stage_detects_a_wrong_dsp_result(capsys):
    class Bad(PlModel):
        def read(self, offset):
            v = super().read(offset)
            return v ^ 0x10 if offset == RESULT_DATA and self._rw[("DET_CFG", "mode")] else v

    assert run(Bad(), "if") == 1
    assert "FAIL  every result word equals the Python reference" in capsys.readouterr().out


@pytest.mark.parametrize("stage", ["ident", "regs", "gen", "push", "owner", "ctrl", "adc", "if", "ce", "spi", "att"])
def test_each_stage_alone(stage):
    assert run(locking_model(False), stage) == 0
