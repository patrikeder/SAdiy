"""A `Platform` made of the PL model and the recording fakes of `sadiy.hal.fake`. For tests, and the worked
example for the hardware backend: everything the offload does goes through `reg_read` / `reg_write`."""
from __future__ import annotations

from typing import Callable, List, Optional

from sadiy.core.cal import Cal
from sadiy.core.detector import Detector
from sadiy.core.sweep import SweepEngine
from sadiy.drivers.adc import Adc
from sadiy.drivers.adf4351 import Adf4351, Outputs
from sadiy.drivers.pe4302 import PE4302, STEP_DB
from sadiy.hal.fake import FakeGpio, FakeSpi, PinLog

from ..ebaz_pl_model import SRC_TEST, PlModel
from ..offload_sweep import OffloadSweep
from ..platform import Capabilities
from ..reg_offload import RegOffload


class FakeAdc(Adc):
    """Detector ADC with a settable level; `PS push` samples come from it."""

    def __init__(self, volts: float = 1.0) -> None:
        self.volts = volts

    def read_volts(self, n: int = 1) -> float:
        return self.volts


class FakePlPlatform:
    def __init__(self, model: Optional[PlModel] = None, *, det_src: int = SRC_TEST, det_test_base: int = 10000,
                 volts_per_count: float = 4.096 / 32768.0,
                 sample_source: Optional[Callable[[], int]] = None) -> None:
        self.model = model or PlModel()
        self.model.ld_now = True
        self.det_src = det_src
        self.det_test_base = det_test_base
        self.volts_per_count = volts_per_count
        self._sample_source = sample_source
        self.capabilities = Capabilities("fake_pl", True, 16, 1 << self.model.table_aw, 1 << self.model.result_aw)
        self.pin_log = PinLog()
        self._spi = FakeSpi()
        # PS lines as the PE4302 driver wants them: outputs, all stages in. Set `line.output = False` in a test
        # to model a line that is still an input (the model then sees the adapter pull-up level).
        self._lines: List[FakeGpio] = [FakeGpio(f"V{i + 1}", self.pin_log, 1) for i in range(6)]
        self._adc = FakeAdc()
        self._offload: Optional[RegOffload] = None

    def synth_link(self) -> FakeSpi:
        return self._spi

    def atten_port(self) -> List[FakeGpio]:
        return self._lines

    def lock_detect(self) -> Callable[[], bool]:
        return lambda: bool(self.model.ld_now)

    def detector(self) -> FakeAdc:
        return self._adc

    def _sync_ps_pins(self) -> None:
        """What the board shows the core: PS GPIO levels and directions (on hardware this is the EMIO wiring)."""
        o = t = 0
        for i, ln in enumerate(self._lines):
            o |= ln.level << i if ln.output else 0
            t |= 0 if ln.output else 1 << i
        self.model.emio_pe_o, self.model.emio_pe_t = o, t

    def _reg_read(self, offset: int) -> int:
        self._sync_ps_pins()
        return self.model.read(offset)

    def _push_code(self) -> int:
        return max(0, min(0xFFFF, round(self._adc.read_volts(1) / self.volts_per_count)))

    def offload(self) -> RegOffload:
        if self._offload is None:
            self._offload = RegOffload(self._reg_read, self.model.write,
                                       sample_source=self._sample_source or self._push_code,
                                       volts_per_count=self.volts_per_count, det_src=self.det_src,
                                       det_test_base=self.det_test_base, poll_s=0.0)
        return self._offload

    def close(self) -> None:
        self._spi.close()


def build_engine(cfg: dict) -> SweepEngine:
    """Engine on the fake platform: ADF4351 and PE4302 drivers on the fakes, sweep through the PL model."""
    pcfg = cfg.get("platform", {})
    plat = FakePlPlatform(det_src=int(pcfg.get("det_src", SRC_TEST)),
                          det_test_base=int(pcfg.get("det_test_base", 10000)),
                          volts_per_count=float(cfg["adc"].get("ads1115_full_scale_v", 4.096)) / 32768.0)
    syn = cfg["synth"]
    synth = Adf4351(plat.synth_link(), pfd_hz=float(syn["pfd_hz"]), mod_max=int(syn.get("mod_max", 4095)))
    synth.set_outputs(Outputs.from_config(syn))
    att = cfg["attenuator"]
    active_high = bool(att.get("active_high", True))
    atten = PE4302(plat.atten_port(), att["weights_db"], active_high)
    steps = [int(round(w / STEP_DB)) for w in att["weights_db"]]
    offload = OffloadSweep(plat.offload(), synth, steps, active_high, atten=atten)
    sw = cfg["sweep"]
    det = Detector.from_config(cfg["detector"])
    return SweepEngine(synth, atten, plat.detector(), det, Cal(default_gain_db=cfg["cal"]["default_gain_db"]),
                       averages=sw["averages"], settle_s=0.0, sleep=lambda s: None, offload=offload,
                       lock=plat.lock_detect())
