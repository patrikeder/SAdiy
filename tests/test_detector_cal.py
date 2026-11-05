import pytest

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.sweep import next_atten_db


def test_detector_matches_datasheet_points():
    d = Detector()
    assert d.volts_from_dbm(-10.0) == pytest.approx(0.735, abs=0.01)   # datasheet: about 0.73 V
    assert d.dbm_from_volts(d.volts_from_dbm(-37.5)) == pytest.approx(-37.5)


def test_divider_is_undone():
    d = Detector(divider_ratio=0.8)
    v_adc = d.volts_from_dbm(-30.0) * 0.8
    assert d.dbm_from_adc_volts(v_adc) == pytest.approx(-30.0)


def test_cal_default_and_table(tmp_path):
    c = Cal(default_gain_db=22.0)
    assert c.to_dbm(-8.0, 100e6, 0.0) == pytest.approx(-30.0)
    assert c.to_dbm(-8.0, 100e6, 10.0) == pytest.approx(-20.0)   # attenuator is added back
    t = Cal([50e6, 450e6], [23.0, 21.0])
    assert t.gain_db(250e6) == pytest.approx(22.0)
    assert t.gain_db(10e6) == 23.0                                # clamped at the table edge
    path = str(tmp_path / "gain.json")
    t.save(path)
    assert Cal.load(path).gain_db(250e6) == pytest.approx(22.0)


def test_autorange():
    assert next_atten_db(-15.0, 10.0) == 10.0
    assert next_atten_db(-5.0, 10.0) == 20.0       # 10 dB too hot: add 10 dB
    assert next_atten_db(-35.0, 10.0) == 0.0       # 20 dB too low: remove, clamp at 0
    assert next_atten_db(30.0, 10.0) == 31.5       # clamp at max
