"""Bench mode: direct pin control, raw board access and check patterns for wiring tests on the BBB.

Runs inside `sweepd`, the only process that touches the hardware, and is exclusive with sweeping
(`Sweepd` enforces that). No ZeroMQ here: `handle()` takes a command dict and returns a reply dict.

Safety rules, enforced here and not in the client, so that any client gets them:
- Only pins from `pinmap` can be driven. Power, ground, eMMC and HDMI pins are refused, lock detect and
  the analog inputs are input-only, other free GPIO needs `expert: true`.
- Driving a pin wired to a board input needs `confirm: true`; without it the reply has `needs_confirm`.
- A raw R4 word that enables an RF output is refused. Outputs turn on only through `bench_rf`, and only
  after an R0 was sent in this session and lock detect reads high. While an output is on, raw SPI words
  (other than an R4 that turns it off) and anything using the SPI pins as GPIO are refused.
- `safe_state()` (PE4302 at maximum attenuation, RF outputs off, every other line released) runs on
  bench_close, on any hardware error, when the client's lease runs out and when the daemon exits.
  A client that vanishes cannot leave a line driven: every bench command renews a short lease.
- SPI pins used as GPIO can latch random data into the ADF4351, so an outputs-off R4 is written again
  as soon as they go back to SPI.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from .. import logs, patterns, pinmap
from ..drivers.adc import Ads1115
from ..drivers.adf4351 import Adf4351, Output, Outputs, r4_enables_output, r4_with_outputs, register_of
from ..drivers.pe4302 import PE4302
from ..hal.base import BenchBackend, GpioLine
from ..hal.fake import FakeBackend

log = logging.getLogger(__name__)       # sadiy.server.bench: this module is never run as __main__

AIN_MAX_CODE = 4095
AIN_CHANNELS = 7
ADS1115_CONFIG_REG = Ads1115.REG_CONFIG
ADS1115_CONVERSION_REG = Ads1115.REG_CONVERSION

SPI_PINS = tuple(pinmap.BY_NET[n].id for n in pinmap.SPI_NETS)
I2C_PINS = tuple(pinmap.BY_NET[n].id for n in pinmap.I2C_NETS)
ATT_PINS = tuple(pinmap.BY_NET[n].id for n in pinmap.ATT_NETS)
LD_PIN = pinmap.BY_NET[pinmap.LOCK_NET].id
CE_PIN = pinmap.BY_NET[pinmap.CE_NET].id
BUS_PINS = SPI_PINS + I2C_PINS


class Refused(ValueError):
    """The command breaks a rule or is malformed. Nothing was touched."""


class NeedsConfirm(Refused):
    """The command would drive a line wired to a board input and did not say `confirm`."""


def fake_backend() -> FakeBackend:
    """The simulated board used by `sweepd --sim`."""
    return FakeBackend(lock_gpio=pinmap.BY_NET[pinmap.LOCK_NET].gpio)


def linux_backend(cfg: dict) -> BenchBackend:
    from ..hal.linux import LinuxBackend

    b = cfg.get("bench", {})
    return LinuxBackend(
        spi_bus=int(b.get("spi_bus", 1)), spi_device=int(b.get("spi_device", 0)), spi_hz=int(b.get("spi_hz", 1_000_000)),
        i2c_bus=int(b.get("i2c_bus", 2)), i2c_address=int(b.get("ads1115_address", 0x48)),
        iio_device=str(b.get("iio_device", "iio:device0")),
    )


class _LoggedLine(GpioLine):
    """Keeps the order of the driver's writes, so the reply can show it."""

    def __init__(self, line: GpioLine, name: str, log: List[List]) -> None:
        self._line, self._name, self._log = line, name, log

    def write(self, value: int) -> None:
        self._line.write(value)
        self._log.append([self._name, 1 if value else 0])

    def read(self) -> int:
        return self._line.read()

    def set_direction(self, output: bool, initial: int = 0) -> None:
        self._line.set_direction(output, initial)


@dataclass
class _Run:
    """A pattern being sent."""

    pattern: patterns.Pattern
    period_s: float
    loop: bool
    rate_hz: float
    pins: List[str]
    groups: List[List[patterns.Edge]] = field(default_factory=list)
    lines: Dict[str, GpioLine] = field(default_factory=dict)
    words: Optional[List[int]] = None
    index: int = 0
    loops: int = 0
    done: int = 0
    started: float = 0.0
    next_t: float = 0.0
    measured_hz: float = 0.0

    @property
    def total(self) -> int:
        return len(self.words) if self.words is not None else len(self.groups)


class Bench:
    def __init__(self, backend: BenchBackend, cfg: dict, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.backend = backend
        att = cfg["attenuator"]
        self.weights_db = tuple(att["weights_db"])
        self.active_high = bool(att["active_high"])
        self.pfd_hz = cfg["synth"]["pfd_hz"]
        self.mod_max = cfg["synth"]["mod_max"]
        self.vref = float(cfg["adc"]["vref"])
        self.ain0_divider_ratio = float(cfg["adc"].get("ain0_divider_ratio", 0.751))
        bench_cfg = cfg.get("bench", {})
        self.lease_s = float(bench_cfg.get("lease_s", 5.0))
        self.ads_full_scale_v = float(cfg["adc"].get("ads1115_full_scale_v", 4.096))
        self.ads_sps = int(cfg["adc"].get("ads1115_sps", 128))
        self._clock = clock
        self._sleep = sleep
        self.active = False
        self.token: Optional[str] = None
        self.closed_reason = ""
        self._reset()

    def _reset(self) -> None:
        self._lines: Dict[str, GpioLine] = {}
        self._dir: Dict[str, str] = {}
        self._gpio_mode: set = set()      # bus pins switched to GPIO
        self._att: Optional[PE4302] = None
        self._att_log: List[List] = []
        self._spi_bus = None
        self._spi_problem = ""
        self._adf: Optional[Adf4351] = None
        self._ads: Optional[Ads1115] = None
        self._outputs = Outputs()
        self._last_r4: Optional[int] = None
        self._r0_sent = False
        self._run: Optional[_Run] = None
        self._last_run: Optional[dict] = None
        self.last_error = ""
        self._renewed = 0.0

    # ------------------------------------------------------------ commands
    @property
    def pattern_running(self) -> bool:
        return self._run is not None

    def handle(self, cmd: dict) -> dict:
        name = cmd.get("cmd")
        if name == "bench_open":
            return self._guard(self._open, cmd)
        if cmd.get("token") != self.token or not self.active:
            if name == "bench_status":        # anyone may ask whether bench mode is on
                return {"ok": True, "active": self.active, "owner": False, "closed_reason": self.closed_reason}
            error = "bench mode is held by another client" if self.active else "bench mode is not open"
            return {"ok": False, "error": error}
        self._renewed = self._clock()
        handler = {
            "bench_close": self._close_cmd, "bench_status": self._status, "bench_pin": self._pin,
            "bench_atten": self._atten, "bench_spi": self._spi, "bench_rf": self._rf,
            "bench_adc": self._adc, "bench_pattern": self._pattern,
        }.get(name)
        if handler is None:
            return {"ok": False, "error": f"unknown bench command {name!r}"}
        return self._guard(handler, cmd)

    def _guard(self, handler, cmd: dict) -> dict:
        try:
            return handler(cmd)
        except NeedsConfirm as exc:
            log.debug("%s needs the operator's confirm: %s", cmd.get("cmd"), exc)
            return {"ok": False, "needs_confirm": True, "error": str(exc)}
        except (Refused, ValueError, TypeError, KeyError) as exc:
            log.debug("%s refused: %s", cmd.get("cmd"), exc)    # the client gets the reason in the reply
            return {"ok": False, "error": str(exc)}
        except (OSError, RuntimeError) as exc:                 # the board said no: leave it safe
            return {"ok": False, "error": self._fail(exc)}

    def _fail(self, exc: Exception) -> str:
        errors = self.safe_state()
        self.last_error = f"hardware error: {exc}. All lines returned to the safe state"
        if errors:
            self.last_error += " except: " + "; ".join(errors)
        log.error("%s", self.last_error, exc_info=exc)
        return self.last_error

    def tick(self) -> None:
        """Called from the daemon loop: closes bench mode when its client has gone quiet."""
        if self.active and self._clock() - self._renewed > self.lease_s:
            log.warning("bench client silent for %g s: closing bench mode and returning to the safe state",
                        self.lease_s)
            self.close(f"no command from the client for {self.lease_s:g} s")

    # ------------------------------------------------------------ open, close, safe state
    def _open(self, _cmd: dict) -> dict:
        if self.active:
            raise Refused("bench mode is already open (another client?)")
        self._reset()
        self.closed_reason = ""
        self.active = True
        self.token = secrets.token_hex(8)
        self._renewed = self._clock()
        warnings: List[str] = []
        safe = 1 if self.active_high else 0
        try:                                    # the attenuator first: it protects the chain
            lines = []
            for pid in ATT_PINS:
                pin = pinmap.PINS[pid]
                self._lines[pid] = self.backend.gpio(pin.gpio, output=True, initial=safe)
                self._dir[pid] = "out"
                lines.append(_LoggedLine(self._lines[pid], pin.net, self._att_log))
            self._att = PE4302(lines, self.weights_db, self.active_high)
        except OSError as exc:
            warnings.append(f"PE4302 lines not available: {exc}")
        for pid in (LD_PIN, CE_PIN):
            try:
                self._lines[pid] = self.backend.gpio(pinmap.PINS[pid].gpio, output=False)
                self._dir[pid] = "in"
            except OSError as exc:
                warnings.append(f"{pinmap.PINS[pid].net} not available: {exc}")
        try:
            self._spi_bus = self.backend.spi()
            self._adf = Adf4351(self._spi_bus, self.pfd_hz, self.mod_max)        # writes outputs-off R4
            self._last_r4 = self._adf.r4_word()
        except (OSError, ImportError) as exc:
            self._spi_problem = str(exc)
            warnings.append(f"SPI not available, the RF output state is unknown: {exc}")
        try:
            bus = self.backend.i2c()
        except (OSError, ImportError) as exc:
            warnings.append(f"I2C not available, so no ADS1115: {exc}")
        else:
            try:
                self._ads = Ads1115(bus, self.ads_full_scale_v, self.ads_sps, sleep=self._sleep)
                self._ads.read_register(ADS1115_CONFIG_REG)
            except OSError as exc:              # expected with nothing on the bus
                self._ads = None
                bus.close()
                warnings.append(f"ADS1115 not available: {exc}")
        log.info("bench mode opened (%s backend)", self.backend.name)
        for w in warnings:
            log.warning("bench open: %s", w)
        reply = self._status({})
        reply.update(
            token=self.token, warnings=warnings,
            limits={
                "backend": self.backend.name, "simulated": self.backend.simulated,
                "max_writes_per_s": self.backend.max_writes_per_s,
                "max_spi_words_per_s": self.backend.max_spi_words_per_s,
                "can_mux": self.backend.can_mux,
            },
        )
        return reply

    def safe_state(self) -> List[str]:
        """Stop any pattern, PE4302 to maximum attenuation, RF outputs off, every other line released.
        Tries everything even when a step fails; returns what failed."""
        errors: List[str] = []

        def attempt(fn, *args) -> None:
            try:
                fn(*args)
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))

        self._stop_run()
        attempt(self._att_safe)
        for pid in list(self._lines):
            if pid in BUS_PINS:
                attempt(self._restore_bus, pid)
            elif pid not in ATT_PINS and pid != LD_PIN:
                attempt(self._release, pid)
        attempt(self._rf_off)
        return errors

    def close(self, reason: str = "") -> List[str]:
        if not self.active:
            return []
        errors = self.safe_state()
        for bus in (self._spi_bus, self._ads):
            if bus is not None:
                try:
                    bus.close()
                except OSError as exc:
                    errors.append(str(exc))
        self.active = False
        self.token = None
        self.closed_reason = reason
        log.info("bench mode closed%s", f": {reason}" if reason else "")
        for e in errors:
            log.warning("bench close: %s", e)
        return errors

    def _close_cmd(self, _cmd: dict) -> dict:
        errors = self.close("closed by the client")
        return {"ok": not errors, "error": "; ".join(errors), "active": False}

    def _att_safe(self) -> None:
        if self._att is None:
            return
        safe = 1 if self.active_high else 0
        for pid in ATT_PINS:
            if self._dir.get(pid) != "out":
                self._lines[pid].set_direction(True, safe)
                self._dir[pid] = "out"
        self._att.safe_state()

    def _release(self, pid: str) -> None:
        self._lines[pid].set_direction(False)
        self._dir[pid] = "in"
        if pinmap.PINS[pid].access == pinmap.EXPERT:
            del self._lines[pid]
            del self._dir[pid]

    def _restore_bus(self, pid: str) -> None:
        """Back from GPIO to the bus function. SPI: the chip may have latched junk, so R4 off again."""
        pin = pinmap.PINS[pid]
        line = self._lines.pop(pid, None)
        self._dir.pop(pid, None)
        if line is not None:
            line.set_direction(False)
        self.backend.set_mux(pin.config_pin_name, pin.mux)
        self._gpio_mode.discard(pid)
        if pid in SPI_PINS and not self._gpio_mode.intersection(SPI_PINS):
            self._rf_off()

    def _ensure_bus(self, pins: Sequence[str]) -> None:
        for pid in pins:
            if pid in self._gpio_mode:
                self._restore_bus(pid)

    def _rf_off(self) -> None:
        if self._adf is None or self._gpio_mode.intersection(SPI_PINS):
            return
        self._outputs = Outputs()
        self._adf.outputs = self._outputs
        self._last_r4 = r4_with_outputs(self._last_r4, self._outputs)
        self._adf.write_word(self._last_r4)

    # ------------------------------------------------------------ what may be driven
    def _check_drive(self, pins: Sequence[pinmap.Pin], cmd: dict, as_gpio: bool = True) -> None:
        """Refuse what is not allowed; ask for the confirm step for lines wired to board inputs.
        `as_gpio` is False when the pins keep their bus function (the SPI controller sends the words)."""
        wired = []
        for pin in pins:
            if pin.access == pinmap.DISPLAY:
                raise Refused(f"{pin.id} ({pin.name}) is display-only")
            if pin.access == pinmap.ANALOG:
                raise Refused(f"{pin.id} ({pin.name}) is an analog input: input-only, read it with bench_adc")
            if pin.access == pinmap.INPUT_ONLY:
                raise Refused(f"{pin.id} ({pin.net}) is driven by the {pin.board}: input-only")
            if pin.access == pinmap.EXPERT and not cmd.get("expert"):
                raise Refused(f"{pin.id} is not in the pin map: tick Expert to use it")
            if pin.access == pinmap.WIRED:
                wired.append(pin)
            if as_gpio and pin.id in SPI_PINS:
                self._require_rf_off(f"{pin.id} ({pin.net}) as a GPIO")
            if as_gpio:
                self._require_mux(pin)
        if wired and not cmd.get("confirm"):
            names = ", ".join(f"{p.id} = {p.net} ({p.board} {p.board_pin})" for p in wired)
            raise NeedsConfirm(f"This drives lines wired to board inputs: {names}")

    def _require_rf_off(self, what: str) -> None:
        if self._outputs.main.enabled or self._outputs.aux.enabled:
            raise Refused(f"an RF output is on: turn it off before using {what}")

    def _require_mux(self, pin: pinmap.Pin) -> None:
        if pin.id in BUS_PINS and pin.id not in self._gpio_mode and not self.backend.can_mux:
            raise Refused(f"{pin.id} ({pin.net}) stays on its bus: this image has no config-pin to make it a GPIO")

    def _require_no_pattern(self) -> None:
        if self._run is not None:
            raise Refused("a pattern is running: stop it first")

    def _as_gpio(self, pin: pinmap.Pin, output: bool, level: int) -> GpioLine:
        """The line of a pin, with the direction and level asked for, opening or re-muxing it if needed."""
        if pin.id in BUS_PINS and pin.id not in self._gpio_mode:
            self.backend.set_mux(pin.config_pin_name, "gpio")
            self._gpio_mode.add(pin.id)
        line = self._lines.get(pin.id)
        if line is None:
            line = self._lines[pin.id] = self.backend.gpio(pin.gpio, output=output, initial=level)
        else:
            line.set_direction(output, level)
        self._dir[pin.id] = "out" if output else "in"
        return line

    # ------------------------------------------------------------ status
    def _levels(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for pid, line in self._lines.items():
            out[pid] = {"level": line.read(), "dir": self._dir.get(pid)}
        for pid in BUS_PINS:
            if pid not in self._gpio_mode:
                out[pid] = {"level": None, "dir": "bus"}
        return out

    def _att_db(self) -> Optional[float]:
        if self._att is None:
            return None
        levels = {f"V{i + 1}": self._lines[pid].read() for i, pid in enumerate(ATT_PINS)}
        return patterns.ParallelModel(levels, self.weights_db, self.active_high).attenuation_db

    def _ld(self) -> Optional[int]:
        line = self._lines.get(LD_PIN)
        return None if line is None else line.read()

    def _pattern_status(self) -> Optional[dict]:
        run = self._run
        if run is None:
            return self._last_run
        return {
            "running": True, "name": run.pattern.name, "step": run.index, "total": run.total, "loops": run.loops,
            "rate_hz": run.rate_hz, "measured_hz": run.measured_hz,
        }

    def _status(self, _cmd: dict) -> dict:
        return {
            "ok": True, "active": True, "owner": True, "pins": self._levels(), "ld": self._ld(),
            "attenuation_db": self._att_db(),
            "rf": {"main": self._outputs.main.enabled, "aux": self._outputs.aux.enabled},
            "pattern": self._pattern_status(), "last_error": self.last_error,
            "spi": self._adf is not None, "ads1115": self._ads is not None,
        }

    # ------------------------------------------------------------ pins
    def _pin(self, cmd: dict) -> dict:
        self._require_no_pattern()
        pin = pinmap.find(str(cmd["pin"]))
        action = cmd.get("action", "read")
        if action == "read":
            return self._pin_read(pin, cmd)
        if action == "input":
            return self._pin_input(pin, cmd)
        if action == "bus":
            if pin.id not in BUS_PINS:
                raise Refused(f"{pin.id} has no bus function")
            self._ensure_bus([pin.id])
        elif action == "write":
            self._check_drive([pin], cmd)
            value = int(cmd["value"])
            if value not in (0, 1):
                raise Refused("value must be 0 or 1")
            line = self._as_gpio(pin, True, value)
            if pin.id in ATT_PINS and self._att is not None:
                self._att.sync_from_lines()
            return {"ok": True, "pin": pin.id, "level": line.read(), "dir": "out", "attenuation_db": self._att_db()}
        else:
            raise Refused(f"unknown pin action {action!r}")
        return {"ok": True, "pin": pin.id, "level": None, "dir": "bus"}

    def _pin_read(self, pin: pinmap.Pin, cmd: dict) -> dict:
        if pin.access == pinmap.DISPLAY:
            raise Refused(f"{pin.id} ({pin.name}) is display-only")
        if pin.access == pinmap.ANALOG:
            raise Refused(f"{pin.id} ({pin.name}) is analog: read it with bench_adc")
        if pin.id in BUS_PINS and pin.id not in self._gpio_mode:
            return {"ok": True, "pin": pin.id, "level": None, "dir": "bus"}
        if pin.access == pinmap.EXPERT and pin.id not in self._lines and not cmd.get("expert"):
            raise Refused(f"{pin.id} is not in the pin map: tick Expert to use it")
        if pin.id not in self._lines:
            self._as_gpio(pin, False, 0)
        return {"ok": True, "pin": pin.id, "level": self._lines[pin.id].read(), "dir": self._dir[pin.id]}

    def _pin_input(self, pin: pinmap.Pin, cmd: dict) -> dict:
        """Stop driving a pin. Harmless on a board input, so no confirm; a bus pin leaves its bus."""
        if pin.access in (pinmap.DISPLAY, pinmap.ANALOG):
            raise Refused(f"{pin.id} ({pin.name}) can not be used as a GPIO")
        if pin.access == pinmap.EXPERT and not cmd.get("expert"):
            raise Refused(f"{pin.id} is not in the pin map: tick Expert to use it")
        if pin.id in SPI_PINS:
            self._require_rf_off(f"{pin.id} ({pin.net}) as a GPIO")
        self._require_mux(pin)
        line = self._as_gpio(pin, False, 0)
        return {"ok": True, "pin": pin.id, "level": line.read(), "dir": "in", "attenuation_db": self._att_db()}

    # ------------------------------------------------------------ attenuator
    def _atten(self, cmd: dict) -> dict:
        self._require_no_pattern()
        if self._att is None:
            raise Refused("the PE4302 lines are not available")
        pins = [pinmap.PINS[p] for p in ATT_PINS]
        self._check_drive(pins, cmd)
        for pid in ATT_PINS:                      # a line left as an input must be driven again
            if self._dir.get(pid) != "out":
                self._lines[pid].set_direction(True, self._lines[pid].read())
                self._dir[pid] = "out"
        self._att.sync_from_lines()
        del self._att_log[:]
        if "levels" in cmd:
            levels = [int(v) for v in cmd["levels"]]
            if len(levels) != len(ATT_PINS) or any(v not in (0, 1) for v in levels):
                raise Refused("levels must be six values of 0 or 1 (V1..V6)")
            if cmd.get("raw"):                    # wiring test: V1 to V6 in order, no make-before-break
                for pid, level in zip(ATT_PINS, levels):
                    line = self._lines[pid]
                    line.write(level)
                    self._att_log.append([pinmap.PINS[pid].net, level])
                self._att.sync_from_lines()
            else:
                model = {f"V{i + 1}": v for i, v in enumerate(levels)}
                self._att.set_attenuation(patterns.ParallelModel(model, self.weights_db, self.active_high).attenuation_db)
        else:
            self._att.set_attenuation(float(cmd["db"]))
        return {"ok": True, "attenuation_db": self._att_db(), "writes": list(self._att_log),
                "pins": self._levels()}

    # ------------------------------------------------------------ synthesizer
    def _require_spi(self) -> None:
        if self._adf is None:
            raise Refused(f"SPI is not available: {self._spi_problem}")

    def _check_words(self, words: Sequence[int]) -> None:
        self._require_spi()
        for w in words:
            if not isinstance(w, int) or not 0 <= w <= 0xFFFFFFFF:
                raise Refused(f"{w!r} is not a 32-bit word")
            if r4_enables_output(w):
                raise Refused(f"0x{w:08X} is an R4 that enables an RF output: lock first, then use the output controls")
            if register_of(w) != 4:
                self._require_rf_off(f"raw word 0x{w:08X}")

    def _send_word(self, word: int) -> None:
        log.log(logs.TRACE, "SPI word 0x%08X (R%d)", word, register_of(word))
        self._adf.write_word(word)
        reg = register_of(word)
        if reg == 4:
            self._last_r4 = word
            self._outputs = Outputs()
            self._adf.outputs = self._outputs
        elif reg == 0:
            self._r0_sent = True

    def _spi(self, cmd: dict) -> dict:
        self._require_no_pattern()
        words = cmd["words"] if "words" in cmd else [cmd["word"]]
        self._check_words(words)
        self._check_drive([pinmap.PINS[p] for p in SPI_PINS], cmd, as_gpio=False)
        self._ensure_bus(SPI_PINS)
        for w in words:
            self._send_word(w)
        return {"ok": True, "sent": [f"0x{w:08X}" for w in words], "ld": self._ld()}

    def _rf(self, cmd: dict) -> dict:
        """Explicit RF output control. Turning on needs lock; turning off always works."""
        self._require_no_pattern()
        self._require_spi()
        main, aux = bool(cmd.get("main")), bool(cmd.get("aux"))
        power = int(cmd.get("power_dbm", -4))
        if main or aux:
            if not self._r0_sent:
                raise Refused("program the PLL first: no R0 was sent in this session")
            if self._ld() != 1:
                raise Refused("the PLL is not locked (LD is low): RF outputs stay off")
            if not cmd.get("confirm"):
                raise NeedsConfirm("This turns an ADF4351 RF output on. The other output of the pair must be terminated.")
        self._ensure_bus(SPI_PINS)
        self._outputs = Outputs(main=Output(main, power) if main else Output(), aux=Output(aux, power) if aux else Output())
        self._adf.outputs = self._outputs
        self._last_r4 = r4_with_outputs(self._last_r4, self._outputs)
        self._adf.write_word(self._last_r4)
        log.info("RF output main=%s aux=%s%s", "on" if main else "off", "on" if aux else "off",
                 f" at {power} dBm" if main or aux else "")
        return {"ok": True, "rf": {"main": main, "aux": aux}, "sent": f"0x{self._last_r4:08X}", "ld": self._ld()}

    # ------------------------------------------------------------ ADCs
    def _adc(self, cmd: dict) -> dict:
        self._require_no_pattern()
        source = cmd.get("source", "ads1115")
        channel = int(cmd.get("channel", 0))
        if source == "ain":
            if not 0 <= channel < AIN_CHANNELS:
                raise Refused(f"AIN channel must be 0..{AIN_CHANNELS - 1}")
            ain = self.backend.ain(channel)
            count = max(1, min(int(cmd.get("n", 1)), 256))
            raw = sum(ain.read_raw() for _ in range(count)) / count
            volts = raw * self.vref / AIN_MAX_CODE
            reply = {"ok": True, "source": "ain", "channel": channel, "raw": raw, "volts": volts}
            if channel == 0:
                reply["volts_detector"] = volts / self.ain0_divider_ratio
            return reply
        if source != "ads1115":
            raise Refused(f"unknown ADC source {source!r}")
        if self._ads is None:
            raise Refused("the ADS1115 is not available")
        self._ensure_bus(I2C_PINS)
        reply = {"ok": True, "source": "ads1115", "channel": channel, "full_scale_v": self.ads_full_scale_v}
        if cmd.get("read", "single") == "single":
            code = self._ads.convert(channel)
            reply.update(code=code, volts=self._ads.to_volts(code))
        reply["config"] = self._ads.read_register(ADS1115_CONFIG_REG)
        reply["conversion"] = self._ads.read_register(ADS1115_CONVERSION_REG)
        return reply

    # ------------------------------------------------------------ patterns
    def _pattern(self, cmd: dict) -> dict:
        action = cmd.get("action", "start")
        if action == "stop":
            self._finish_run("stopped")
            return {"ok": True, "pattern": self._pattern_status()}
        if action != "start":
            raise Refused(f"unknown pattern action {action!r}")
        self._require_no_pattern()
        rate = float(cmd.get("rate_hz", 100.0))
        if rate <= 0:
            raise Refused("the rate must be above 0")
        spec = cmd["spec"]
        pat = patterns.from_spec(spec, pinmap.ATT_NETS, self.weights_db, self.active_high)
        run = _Run(pat, 1.0 / rate, bool(cmd.get("loop")), rate, [])
        if pat.spi_words is not None:
            self._check_words(pat.spi_words)
            self._check_drive([pinmap.PINS[p] for p in SPI_PINS], cmd, as_gpio=False)
            self._ensure_bus(SPI_PINS)
            run.words = pat.spi_words
        else:
            pins = [pinmap.find(s) for s in pat.idle]
            self._check_drive(pins, cmd)
            run.groups = patterns.step_groups(pat)
            run.pins = [p.id for p in pins]
            # idle levels, high first so an active-high PE4302 never dips below its target
            for pin in sorted(pins, key=lambda p: -pat.idle[p.signal]):
                run.lines[pin.signal] = self._as_gpio(pin, True, pat.idle[pin.signal])
        if run.total == 0:
            raise Refused("the pattern has no steps")
        run.started = run.next_t = self._clock()
        self._run = run
        self._last_run = None
        log.info("pattern %s started: %d steps at %g Hz%s", pat.name, run.total, rate,
                 ", looping" if run.loop else "")
        return {"ok": True, "pattern": self._pattern_status()}

    def service(self, budget_s: float = 0.01) -> None:
        """Send pattern steps on schedule for at most `budget_s`, then return so the daemon can read
        commands (one of them may be stop). A slow backend does not catch up: the measured rate shows it."""
        run = self._run
        if run is None:
            return
        end = self._clock() + budget_s
        try:
            while True:
                now = self._clock()
                if now >= end:
                    return
                if now < run.next_t:
                    self._sleep(min(run.next_t - now, end - now))
                    continue
                self._step(run)
                run.done += 1
                elapsed = self._clock() - run.started
                if elapsed > 0:
                    run.measured_hz = run.done / elapsed
                run.next_t = max(run.next_t + run.period_s, now)
                if run.index >= run.total:
                    run.loops += 1
                    if not run.loop:
                        self._finish_run("finished")
                        return
                    run.index = 0
        except (OSError, RuntimeError) as exc:
            self._fail(exc)
            self._last_run = {"running": False, "name": run.pattern.name, "end": "error", "error": self.last_error}

    def _step(self, run: _Run) -> None:
        if run.words is not None:
            self._send_word(run.words[run.index])
        else:
            for edge in run.groups[run.index]:
                run.lines[edge.signal].write(edge.level)
        run.index += 1

    def _stop_run(self) -> None:
        self._run = None

    def _finish_run(self, how: str) -> None:
        """A pattern never leaves lines where it put them: everything it used goes back to safe."""
        run = self._run
        if run is None:
            return
        self._run = None
        self._last_run = {
            "running": False, "name": run.pattern.name, "end": how, "steps": run.done, "loops": run.loops,
            "rate_hz": run.rate_hz, "measured_hz": run.measured_hz,
        }
        log.info("pattern %s %s after %d steps, measured %.0f Hz of %g Hz asked", run.pattern.name, how,
                 run.done, run.measured_hz, run.rate_hz)
        if run.measured_hz and run.measured_hz < 0.9 * run.rate_hz:
            log.warning("pattern %s ran at %.0f Hz instead of %g Hz: the backend can not keep up",
                        run.pattern.name, run.measured_hz, run.rate_hz)
        if any(p in ATT_PINS for p in run.pins):
            self._att_safe()
        for pid in run.pins:
            if pid in BUS_PINS:
                self._restore_bus(pid)
            elif pid not in ATT_PINS:
                self._release(pid)
