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


def model(locked=True, pcf=0x27):
    m = PlModel()
    m.ld_now = locked
    m.lock_model = lambda i, w: locked
    m.pcf_address = pcf
    return m


def platform(m, **kw):
    return EbazPlPlatform(m.read, m.write, poll_s=0.0, **kw)


def points(n=8):
    return build_sweep(50e6, 450e6, n, 10.7e6, "high", 25e6)


def test_pcf8574_configuration_and_pin_takeover():
    m = model()
    plat = platform(m, pcf8574_address=0x27, backlight=1)
    assert m.read(REGS["ATT_I2C"].offset) == 0x327                      # address 0x27, P3 (backlight) and P7 high
    assert REGS["DET_CFG"].fields["src"].get(m.read(REGS["DET_CFG"].offset)) == 1      # test generator
    st = plat.offload().status()
    assert st["pin_owner_act"] == 1
    assert m.att_bytes == [(0xFF,)]                                     # taken at 31.5 dB: one byte, all ports high
    pins = m.read(REGS["PIN_STATE"].offset)
    assert REGS["PIN_STATE"].fields["ce"].get(pins) == 1 and REGS["PIN_STATE"].fields["i2c_pl"].get(pins) == 1
    m2 = model()
    platform(m2, pcf8574_address=0x3F, backlight=0)
    assert m2.read(REGS["ATT_I2C"].offset) == 0x23F


def test_missing_pcf8574_is_logged_not_fatal(caplog):
    m = model(pcf=None)
    platform(m)
    assert "PCF8574 attenuator does not answer at I2C address 0x27" in caplog.text


class SlowAtt:
    """ATT_STAT as on the board: after a transaction starts, `busy` for some reads and err_nack only at its end
    (the model finishes at once)."""

    def __init__(self, m, busy_reads=5):
        self.m, self.busy_reads, self.left = m, busy_reads, busy_reads

    def read(self, offset):
        v = self.m.read(offset)
        if offset == REGS["ATT_STAT"].offset and self.left:
            self.left -= 1
            f = REGS["ATT_STAT"].fields
            return (v & ~f["err_nack"].mask) | f["busy"].mask
        return v


def test_missing_pcf8574_is_reported_after_the_transaction_finished(caplog):
    m = model(pcf=None)
    slow = SlowAtt(m)
    EbazPlPlatform(slow.read, m.write, poll_s=0.0)
    assert slow.left == 0
    assert "PCF8574 attenuator does not answer" in caplog.text


def test_nack_during_a_sweep_is_logged_once(caplog):
    m = model()
    plat = platform(m)
    engine = engine_on(plat, config.load(), sleep=lambda s: None)
    engine.run(points(), 0.0)
    assert "did not acknowledge" not in caplog.text
    m.pcf_address = None                                               # PCF8574 unplugged between two sweeps
    engine.run(points(), 10.0)
    engine.run(points(), 20.0)
    assert caplog.text.count("did not acknowledge during the sweep") == 1


def test_detector_read_spi_words_and_attenuator_lines():
    m = model()
    plat = platform(m, det_test_base=1234)
    assert plat.detector().read_volts(4) == pytest.approx(1234 * VPC)
    plat.synth_link().xfer(bytes.fromhex("00580005" "008C803C"))
    assert m.spi_words[-2:] == [0x00580005, 0x008C803C]
    lines = plat.atten_port()
    lines[5].write(0)                                                   # V6 out: 0x3F -> 0x1F
    assert REGS["ATT_STAT"].fields["levels"].get(m.read(REGS["ATT_STAT"].offset)) == 0x1F
    assert m.att_bytes[-1] == (0xFF, 0b1011_1111)                       # make (all in), then P6 low
    assert lines[5].read() == 0 and lines[0].read() == 1
    lines[0].write(0)
    lines[1].write(0)                                                   # each change starts from the last one
    assert REGS["ATT_STAT"].fields["levels"].get(m.read(REGS["ATT_STAT"].offset)) == 0x1C
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


def test_sweep_and_table_reupload_after_single_actions():
    cfg = config.load()
    m = model()
    plat = platform(m)
    engine = engine_on(plat, cfg, sleep=lambda s: None)
    pts = points()
    p1 = engine.run(pts, 10.0)
    assert len(p1) == len(pts) and np.all(np.isfinite(p1))
    assert m.read(REGS["POINT_COUNT"].offset) == len(pts)
    assert REGS["ATT_STAT"].fields["levels"].get(m.read(REGS["ATT_STAT"].offset)) == engine.offload.code_for(10.0)
    uploads = engine.offload.uploads
    engine.run(pts, 10.0)
    assert engine.offload.uploads == uploads                 # unchanged table is not sent again
    plat.detector().read_volts(1)                            # uses the table for one private entry
    p3 = engine.run(pts, 10.0)
    assert engine.offload.uploads == uploads + 1 and np.allclose(p3, p1)
    assert m.read(REGS["T_SETTLE_US"].offset) == round(cfg["sweep"]["settle_s"] * 1e6)


def test_removed_and_unknown_detector_sources_are_refused():
    for old in ("pl", "ps"):
        with pytest.raises(ValueError, match="ADS1115 was removed"):
            platform(model(), detector=old)
    with pytest.raises(ValueError):
        platform(model(), detector="nonsense")


def test_bitstream_of_map_1_is_refused():
    class Old(PlModel):
        def read(self, offset):
            return 0x00010003 if offset == REGS["VERSION"].offset else super().read(offset)

    with pytest.raises(RuntimeError, match="register map version 1.3"):
        platform(Old())


def test_sweepd_runs_sweeps_on_the_platform():
    cfg = config.load()
    cfg["platform"] = {"name": "ebaz"}
    m = model()
    engine = engine_on(platform(m), cfg, sleep=lambda s: None)
    d = Sweepd(cfg, engine, None)
    assert d.apply({"cmd": "status"})["platform"] == "ebaz"
    assert d.apply({"cmd": "set", "points": 21})["ok"]
    before = m.read(REGS["SWEEP_COUNT"].offset)
    frame = d.step()
    assert frame is not None and m.read(REGS["SWEEP_COUNT"].offset) == before + 1
    assert m.read(REGS["POINT_COUNT"].offset) == 21
    assert d.last_error == ""
