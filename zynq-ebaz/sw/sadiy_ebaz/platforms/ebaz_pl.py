"""EBAZ4205 with the PL sweep engine, register access only (`[platform] name = "ebaz-pl"`).

Everything goes through the engine's registers at 0x43C0_0000 (/dev/mem): SPI words to the ADF4351, the PE4302
attenuator (through the PCF8574 on the I2C bus, register map 2.0), CE, lock detect and the detector samples. No
spidev, GPIO or I2C device of Linux is needed, and the engine owns the pins and the I2C bus for as long as sweepd
runs.

Detector source, `[platform] detector`:
  "test"  (default) the test generator of the PL (DET_CFG.src = 1): a ramp, no RF. The ADS1115 is gone (map 2.0);
          the detector of the real chain will be the IF path behind the AD9226 front end (not wired yet).

PCF8574 (`[attenuator]`): `pcf8574_address` (default 0x27), `pcf8574_backlight` (P3, default 1 = LED on).
Other `[platform]` keys: `base` (register base), `require_lock` (default true: without lock detect the RF outputs
stay off), `det_test_base`. Needs a bitstream with register map 2.x.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.sweep import SweepEngine
from sadiy.drivers.adc import Adc
from sadiy.drivers.adf4351 import Adf4351, Outputs
from sadiy.drivers.pe4302 import PE4302, STEP_DB
from sadiy.hal.base import GpioLine, SpiBus

from ..offload_sweep import OffloadSweep
from ..platform import Capabilities
from ..reg_offload import SRC_TEST, RegOffload
from ..regmap_toml import REGS

log = logging.getLogger("sadiy.ebaz_pl")
DETECTORS = {"test": SRC_TEST}
REMOVED_DETECTORS = ("pl", "ps")         # the ADS1115 (PL reader or Linux) until register map 1.3


class PlSpi(SpiBus):
    """ADF4351 SPI through the engine: every 4-byte transfer is one word sent by the PL."""

    def __init__(self, offload: RegOffload) -> None:
        self._offload = offload

    def xfer(self, data: bytes) -> bytes:
        if len(data) % 4:
            raise ValueError("the engine sends 32-bit words only")
        self._offload.send_words([int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)])
        return bytes(len(data))


class PlLine(GpioLine):
    """One PE4302 control line through `PE4302.manual`; the engine sends it to the PCF8574 make-before-break."""

    def __init__(self, port: "PlAttenPort", bit: int) -> None:
        self._port, self._bit = port, bit

    def write(self, value: int) -> None:
        self._port.set_bit(self._bit, value)

    def read(self) -> int:
        return (self._port.levels() >> self._bit) & 1

    def set_direction(self, output: bool, initial: int = 0) -> None:
        if output:
            self.write(initial)


class PlAttenPort:
    def __init__(self, offload: RegOffload, reg_read: Callable[[int], int]) -> None:
        self._offload, self._rd = offload, reg_read
        self.lines: List[PlLine] = [PlLine(self, i) for i in range(6)]

    def set_bit(self, bit: int, value: int) -> None:
        cur = self._offload.pin_levels()         # read each time: a sweep table may have changed the pins
        new = (cur & ~(1 << bit)) | ((1 if value else 0) << bit)
        if new != cur:
            self._offload.set_att_pins(new)

    def levels(self) -> int:
        """Levels the engine sent to the PCF8574 last (the PCF8574 cannot be read back by the engine)."""
        return self._offload.pin_levels()


class PlAdc(Adc):
    """Detector volts through the engine's sampler (whatever source it is set to)."""

    def __init__(self, offload: RegOffload) -> None:
        self._offload = offload

    def read_volts(self, n: int = 1) -> float:
        return self._offload.counts_to_volts(self._offload.read_detector(n))


class EbazPlPlatform:
    def __init__(self, reg_read: Callable[[int], int], reg_write: Callable[[int, int], None], *,
                 detector: str = "test", full_scale_v: float = 4.096, det_test_base: int = 10000,
                 pcf8574_address: int = 0x27, backlight: int = 1, poll_s: float = 0.001,
                 close: Optional[Callable[[], None]] = None) -> None:
        if detector in REMOVED_DETECTORS:
            raise ValueError(f"[platform] detector {detector!r}: the ADS1115 was removed (register map 2.0); "
                             f"use one of {', '.join(DETECTORS)}")
        if detector not in DETECTORS:
            raise ValueError(f"[platform] detector must be one of {', '.join(DETECTORS)}, not {detector!r}")
        self.detector_kind = detector
        self._rd, self._close = reg_read, close
        self._offload = RegOffload(reg_read, reg_write, volts_per_count=full_scale_v / 32768.0,
                                   det_src=DETECTORS[detector], det_test_base=det_test_base, poll_s=poll_s)
        o = self._offload
        self.capabilities = Capabilities("ebaz_pl", True, 16, o.max_entries, o.max_points)
        o.configure_att(pcf8574_address, p3=int(bool(backlight)))
        o.set_ce(1)
        if not o.status()["pin_owner_act"]:
            o.acquire_pins()                      # sends PE4302.manual (reset: all stages in, 31.5 dB)
        if o.wait_att()["err_nack"]:
            log.warning("PCF8574 attenuator does not answer at I2C address 0x%02X: the attenuation is not set "
                        "(wiring, pull-ups, address; [attenuator] pcf8574_address)", pcf8574_address)
        self._spi = PlSpi(o)
        self._port = PlAttenPort(o, reg_read)
        self._adc = PlAdc(o)

    def synth_link(self) -> PlSpi:
        return self._spi

    def atten_port(self) -> List[PlLine]:
        return self._port.lines

    def lock_detect(self) -> Callable[[], bool]:
        return self._offload.lock_detect

    def detector(self) -> PlAdc:
        return self._adc

    def offload(self) -> RegOffload:
        return self._offload

    def close(self) -> None:
        if self._close is not None:
            self._close()


def first_lock(synth: Adf4351, lock: Callable[[], bool], f_lo_hz: float, *, timeout_s: float = 0.2,
               sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> bool:
    """Program the PLL with the outputs off and wait for lock detect. True when locked."""
    for word in synth.registers(synth.plan(f_lo_hz)):
        synth.write_word(word)
    deadline = clock() + timeout_s
    while True:
        if lock():
            return True
        if clock() >= deadline:
            return False
        sleep(0.002)


def engine_on(plat: EbazPlPlatform, cfg: dict, *, sleep: Callable[[float], None] = time.sleep) -> SweepEngine:
    """The sweep engine on `plat`. The RF outputs are enabled only after the PLL locked once with them off."""
    pcfg = cfg.get("platform", {})
    syn = cfg["synth"]
    synth = Adf4351(plat.synth_link(), pfd_hz=float(syn["pfd_hz"]), mod_max=int(syn.get("mod_max", 4095)))
    rf = cfg["rf"]
    if str(rf.get("injection", "high")) == "high":
        f_lo = float(rf["rf_min_hz"]) + float(rf["if_hz"])
    else:
        f_lo = float(rf["rf_max_hz"]) - float(rf["if_hz"])
    locked = first_lock(synth, plat.lock_detect(), f_lo, sleep=sleep)
    wanted = Outputs.from_config(syn)
    if locked:
        synth.set_outputs(wanted)
    elif bool(pcfg.get("require_lock", True)):
        log.error("ADF4351 did not lock at %.3f MHz: RF outputs stay off (check CE, the 5 V supply, the LD wire; "
                  "[platform] require_lock = false overrides)", f_lo / 1e6)
    else:
        log.warning("ADF4351 did not lock, outputs enabled anyway ([platform] require_lock = false)")
        synth.set_outputs(wanted)
    att = cfg["attenuator"]
    active_high = bool(att.get("active_high", True))
    atten = PE4302(plat.atten_port(), att["weights_db"], active_high)
    steps = [int(round(w / STEP_DB)) for w in att["weights_db"]]
    offload = OffloadSweep(plat.offload(), synth, steps, active_high, atten=None)
    sw = cfg["sweep"]
    # the PL does the settling: its T_SETTLE_US register follows [sweep] settle_s
    settle_us = max(1, int(round(float(sw.get("settle_s", 0.0005)) * 1e6)))
    plat.offload()._wr(REGS["T_SETTLE_US"].offset, settle_us)
    det = Detector.from_config(cfg["detector"])
    return SweepEngine(synth, atten, plat.detector(), det, Cal(default_gain_db=cfg["cal"]["default_gain_db"]),
                       averages=sw["averages"], settle_s=0.0, sleep=lambda s: None, offload=offload,
                       lock=plat.lock_detect(), combine_method=sw.get("combine", "median"),
                       outlier_db=float(sw.get("outlier_db", 3.0)), lock_retries=int(sw.get("lock_retries", 2)))


def build_engine(cfg: dict) -> SweepEngine:
    """Hook of `sweepd.build_hw_engine`: the real board through /dev/mem."""
    from ..devmem import DEFAULT_BASE, DevMemRegs

    pcfg = cfg.get("platform", {})
    att = cfg.get("attenuator", {})
    detector = str(pcfg.get("detector", "test"))
    regs = DevMemRegs(int(pcfg.get("base", DEFAULT_BASE)))
    plat = EbazPlPlatform(regs.read, regs.write, detector=detector,
                          det_test_base=int(pcfg.get("det_test_base", 10000)),
                          pcf8574_address=int(att.get("pcf8574_address", 0x27)),
                          backlight=int(att.get("pcf8574_backlight", 1)), close=regs.close)
    log.info("EBAZ PL engine: register map %d.%d, detector source %s", plat.offload().version >> 16,
             plat.offload().version & 0xFFFF, detector)
    return engine_on(plat, cfg)
