"""The register-only EBAZ platform (`platforms/ebaz_pl.py`) on the PlModel: no board needed."""
import numpy as np
import pytest
from sadiy_ebaz.ebaz_pl_model import PlModel
from sadiy_ebaz.platforms.ebaz_pl import EbazPlPlatform, engine_on
from sadiy_ebaz.regmap_toml import REGS

from sadiy import config
from sadiy.core.freqplan import build_sweep
from sadiy.drivers.adf4351 import r4_enables_output, register_of
from sadiy.server.sweepd import Sweepd

VPC = 4.096 / 32768.0


def model(code=8000, locked=True):
    m = PlModel()
    m.ld_now = locked
    m.lock_model = lambda i, w: locked
    m.adc_code = (lambda i: code) if code is not None else None
    return m


def platform(m, **kw):
    return EbazPlPlatform(m.read, m.write, poll_s=0.0, **kw)


def points(n=8):
    return build_sweep(50e6, 450e6, n, 10.7e6, "high", 25e6)


def test_pl_adc_configuration_and_pin_takeover():
    m = model()
    plat = platform(m, sps=860)
    cfgw = m.read(REGS["ADC_CFG"].offset)
    assert cfgw & 0xFFFF == 0xC3E3 and (cfgw >> 16) & 0x7F == 0x48      # AIN0, 4.096 V, single shot, 860 SPS
    assert m.read(REGS["ADC_T_CONV_US"].offset) == int(1.1e6 / 860) + 150
    assert REGS["DET_CFG"].fields["src"].get(m.read(REGS["DET_CFG"].offset)) == 3
    st = plat.offload().status()
    assert st["pin_owner_act"] == 1
    pins = m.read(REGS["PIN_STATE"].offset)
    assert REGS["PIN_STATE"].fields["pe_out"].get(pins) == 0x3F          # taken at the pull-up level: 31.5 dB
    assert REGS["PIN_STATE"].fields["ce"].get(pins) == 1 and REGS["PIN_STATE"].fields["i2c_pl"].get(pins) == 1


def test_detector_read_spi_words_and_attenuator_lines():
    m = model(code=12345)
    plat = platform(m)
    assert plat.detector().read_volts(4) == pytest.approx(12345 * VPC)
    plat.synth_link().xfer(bytes.fromhex("00580005" "008C803C"))
    assert m.spi_words[-2:] == [0x00580005, 0x008C803C]
    lines = plat.atten_port()
    lines[5].write(0)
    assert REGS["PIN_STATE"].fields["pe_out"].get(m.read(REGS["PIN_STATE"].offset)) == 0x1F
    assert lines[5].read() == 0 and lines[0].read() == 1
    assert plat.lock_detect()() is True


def test_outputs_are_enabled_only_after_the_first_lock():
    cfg = config.load()
    m = model(locked=True)
    engine_on(platform(m), cfg, sleep=lambda s: None)
    r4 = [w for w in m.spi_words if register_of(w) == 4]
    assert not r4_enables_output(r4[0]) and not r4_enables_output(r4[1])   # safe state, then the first tune
    assert r4_enables_output(r4[-1])
    r0_at = max(i for i, w in enumerate(m.spi_words) if register_of(w) == 0)
    on_at = max(i for i, w in enumerate(m.spi_words) if register_of(w) == 4 and r4_enables_output(w))
    assert on_at > r0_at

    m2 = model(locked=False)
    engine_on(platform(m2), cfg, sleep=lambda s: None)
    assert not any(r4_enables_output(w) for w in m2.spi_words if register_of(w) == 4)


def test_sweep_through_the_pl_adc_and_table_reupload_after_single_actions():
    cfg = config.load()
    m = model(code=9000)
    plat = platform(m)
    engine = engine_on(plat, cfg, sleep=lambda s: None)
    pts = points()
    p1 = engine.run(pts, 10.0)
    assert len(p1) == len(pts) and np.all(np.isfinite(p1))
    assert m.read(REGS["POINT_COUNT"].offset) == len(pts)
    assert REGS["PIN_STATE"].fields["pe_out"].get(m.read(REGS["PIN_STATE"].offset)) == engine.offload.code_for(10.0)
    uploads = engine.offload.uploads
    engine.run(pts, 10.0)
    assert engine.offload.uploads == uploads                 # unchanged table is not sent again
    plat.detector().read_volts(1)                            # uses the table for one private entry
    p3 = engine.run(pts, 10.0)
    assert engine.offload.uploads == uploads + 1 and np.allclose(p3, p1)
    assert m.read(REGS["T_SETTLE_US"].offset) == round(cfg["sweep"]["settle_s"] * 1e6)


def test_missing_adc_is_an_error_not_a_silent_zero():
    m = model(code=None)
    plat = platform(m)
    with pytest.raises(RuntimeError, match="ADS1115"):
        plat.detector().read_volts(1)


def test_ps_push_and_test_generator_sources():
    m = model()
    plat = platform(m, detector="ps", ps_sample_source=lambda: 4321)
    assert plat.detector().read_volts(3) == pytest.approx(4321 * VPC)
    assert REGS["PIN_STATE"].fields["i2c_pl"].get(m.read(REGS["PIN_STATE"].offset)) == 0   # the PS keeps the bus
    m2 = model()
    plat2 = platform(m2, detector="test", det_test_base=500)
    assert plat2.detector().read_volts(2) == pytest.approx(500 * VPC)
    with pytest.raises(ValueError):
        platform(model(), detector="ps")
    with pytest.raises(ValueError):
        platform(model(), detector="nonsense")


def test_old_bitstream_is_refused_for_the_pl_adc():
    class Old(PlModel):
        def read(self, offset):
            return 0x00010000 if offset == REGS["VERSION"].offset else super().read(offset)

    with pytest.raises(RuntimeError, match="register map 1.0"):
        platform(Old())


def test_sweepd_runs_sweeps_on_the_platform():
    cfg = config.load()
    cfg["platform"] = {"name": "ebaz"}
    m = model(code=9000)
    engine = engine_on(platform(m), cfg, sleep=lambda s: None)
    d = Sweepd(cfg, engine, None)
    assert d.apply({"cmd": "status"})["platform"] == "ebaz"
    assert d.apply({"cmd": "set", "points": 21})["ok"]
    before = m.read(REGS["SWEEP_COUNT"].offset)
    frame = d.step()
    assert frame is not None and m.read(REGS["SWEEP_COUNT"].offset) == before + 1
    assert m.read(REGS["POINT_COUNT"].offset) == 21
    assert d.last_error == ""
