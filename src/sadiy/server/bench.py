"""Bench mode: direct pin control, raw board access and check patterns for wiring tests on the BBB or the EBAZ4205.

Runs inside `sweepd`, the only process that touches the hardware, and is exclusive with sweeping
(`Sweepd` enforces that). No ZeroMQ here: `handle()` takes a command dict and returns a reply dict.

Safety rules, enforced here and not in the client, so that any client gets them:
- Only pins from `pinmap` can be driven. Power, ground, eMMC and HDMI pins are refused, lock detect and
  the analog inputs are input-only, other free GPIO needs `expert: true`.
- Driving a pin wired to a board input needs `confirm: true`; without it the reply has `needs_confirm`.
- A raw R4 word that enables an RF output is refused. Outputs turn on only through `bench_rf`, and only
  after an R0 was sent in this session and lock detect reads high. While an output is on, raw SPI words
  (other than an R4 that turns it off) and anything using the SPI pins as GPIO are refused.
- The PE4302 hangs on a PCF8574 port expander on the I2C bus: its V1..V6 are not SBC pins. `bench_atten` and patterns
  on ATT_V1..V6 write the expander, one I2C write per step, make-before-break. They ask for the same confirm as
  driving the I2C pins. I2C pins used as GPIO could send the expander anything, so its setting is written again as
  soon as they go back to the bus. After a write the pins are read back: a difference means a missing pull-up.
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

from .. import logs, patterns, pinmap, platforms
from ..core.freqplan import LO_MAX_HZ
from ..drivers.adf4351 import (POWER_CODE, Adf4351, Output, Outputs, decode_registers, r4_enables_output,
                               r4_with_outputs, register_of)
from ..drivers.pcf8574 import DEFAULT_ADDRESS, Pcf8574, levels_of
from ..drivers.pe4302 import PE4302Pcf8574
from ..hal.base import BenchBackend, GpioLine
from ..hal.fake import FakeBackend

log = logging.getLogger(__name__)       # sadiy.server.bench: this module is never run as __main__

AIN_MAX_CODE = 4095
AIN_CHANNELS = 7

SPI_PINS = tuple(pinmap.BY_NET[n].id for n in pinmap.SPI_NETS)
I2C_PINS = tuple(pinmap.BY_NET[n].id for n in pinmap.I2C_NETS)
LD_PIN = pinmap.BY_NET[pinmap.LOCK_NET].id
CE_PIN = pinmap.BY_NET[pinmap.CE_NET].id
BUS_PINS = SPI_PINS + I2C_PINS


class Refused(ValueError):
    """The command breaks a rule or is malformed. Nothing was touched."""


class NeedsConfirm(Refused):
    """The command would drive a line wired to a board input and did not say `confirm`."""

    kind = "pins"


class NeedsRfConfirm(NeedsConfirm):
    """The command would turn an RF output on and did not say `confirm_rf`."""

    kind = "rf"


def fake_backend(platform=None) -> FakeBackend:
    """The simulated board used by `sweepd --sim`. `platform`: a name from `platforms` or a PinMap (default BBB).
    On the EBAZ4205 the SPI and I2C pins are fixed in the bitstream: no pin mux, as on the real board."""
    pm = platform if isinstance(platform, pinmap.PinMap) else platforms.get(platform)
    return FakeBackend(lock_gpio=pm.by_net[pm.lock_net].gpio, can_mux=pm.name == "bbb")


def linux_backend(cfg: dict) -> BenchBackend:
    from ..hal.linux import LinuxBackend

    b = cfg.get("bench", {})
    return LinuxBackend(
        spi_bus=int(b.get("spi_bus", 1)), spi_device=int(b.get("spi_device", 0)), spi_hz=int(b.get("spi_hz", 1_000_000)),
        i2c_bus=int(b.get("i2c_bus", 2)), i2c_address=int(cfg["attenuator"].get("pcf8574_address", DEFAULT_ADDRESS)),
        iio_device=str(b.get("iio_device", "iio:device0")),
    )


@dataclass
class _Run:
    """A pattern being sent."""

    pattern: patterns.Pattern
    period_s: float
    loop: bool
    rate_hz: float
    pins: List[str]
    att: List[str] = field(default_factory=list)      # ATT_V.. signals of the pattern: outputs of the PCF8574
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
                 sleep: Callable[[float], None] = time.sleep, platform=None) -> None:
        """`platform`: a name from `platforms` or a PinMap; default is `[platform] name` of the config (bbb)."""
        self.backend = backend
        self.pm = platform if isinstance(platform, pinmap.PinMap) else (
            platforms.get(platform) if platform else platforms.from_config(cfg))
        self.spi_pins = self.pm.ids(self.pm.spi_nets)
        self.i2c_pins = self.pm.ids(self.pm.i2c_nets)
        self.att_nets = tuple(self.pm.att_nets)         # V1..V6 behind the PCF8574, not SBC pins
        self.ld_pin = self.pm.by_net[self.pm.lock_net].id
        self.ce_pin = self.pm.by_net[self.pm.ce_net].id
        self.bus_pins = self.spi_pins + self.i2c_pins
        att = cfg["attenuator"]
        self.weights_db = tuple(att["weights_db"])
        self.active_high = bool(att["active_high"])
        self.pcf_address = int(att.get("pcf8574_address", DEFAULT_ADDRESS))
        self.pcf_backlight = int(att.get("pcf8574_backlight", 1))
        self.pfd_hz = cfg["synth"]["pfd_hz"]
        self.mod_max = cfg["synth"]["mod_max"]
        self.vref = float(cfg["adc"]["vref"])
        self.ain0_divider_ratio = float(cfg["adc"].get("ain0_divider_ratio", 0.751))
        bench_cfg = cfg.get("bench", {})
        self.lease_s = float(bench_cfg.get("lease_s", 5.0))
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
        self._att: Optional[PE4302Pcf8574] = None
        self._spi_bus = None
        self._spi_problem = ""
        self._adf: Optional[Adf4351] = None
        self._outputs = Outputs()
        self._last_r4: Optional[int] = None
        self._regs: Dict[int, int] = {}   # last word written to each ADF4351 register in this session
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
            "bench_adc": self._adc, "bench_pattern": self._pattern, "bench_synth": self._synth,
        }.get(name)
        if handler is None:
            return {"ok": False, "error": f"unknown bench command {name!r}"}
        return self._guard(handler, cmd)

    def _guard(self, handler, cmd: dict) -> dict:
        try:
            return handler(cmd)
        except NeedsConfirm as exc:
            log.debug("%s needs the operator's confirm: %s", cmd.get("cmd"), exc)
            return {"ok": False, "needs_confirm": True, "confirm_kind": exc.kind, "error": str(exc)}
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
        try:
            warnings.extend(self.backend.prepare())
        except OSError as exc:
            warnings.append(f"board check failed: {exc}")
        warnings.extend(self._open_attenuator())          # first: it protects the chain
        for pid in (self.ld_pin, self.ce_pin):
            try:
                self._lines[pid] = self.backend.gpio(self.pm.pins[pid].gpio, output=False)
                self._dir[pid] = "in"
            except OSError as exc:
                warnings.append(f"{self.pm.pins[pid].net} not available: {exc}")
        try:
            self._spi_bus = self.backend.spi()
            self._adf = Adf4351(self._spi_bus, self.pfd_hz, self.mod_max)        # writes outputs-off R4
            self._last_r4 = self._adf.r4_word()
            self._regs[4] = self._last_r4
        except (OSError, ImportError) as exc:
            self._spi_problem = str(exc)
            warnings.append(f"SPI not available, the RF output state is unknown: {exc}")
        log.info("bench mode opened (%s backend)", self.backend.name)
        for w in warnings:
            log.warning("bench open: %s", w)
        reply = self._status({})
        reply.update(
            token=self.token, warnings=warnings, platform=self.pm.name,
            limits={
                "backend": self.backend.name, "simulated": self.backend.simulated,
                "max_writes_per_s": self.backend.max_writes_per_s,
                "max_spi_words_per_s": self.backend.max_spi_words_per_s,
                "can_mux": self.backend.can_mux,
            },
        )
        return reply

    def _open_attenuator(self) -> List[str]:
        """The PE4302 behind the PCF8574, set to maximum attenuation. Returns warnings."""
        try:
            bus = self.backend.i2c()
        except (OSError, ImportError) as exc:
            return [f"I2C not available, so no PE4302 attenuator: {exc}"]
        try:
            self._att = PE4302Pcf8574(Pcf8574(bus, self.pcf_backlight), self.weights_db, self.active_high)
            warning = self._readback_warning()
        except OSError as exc:                  # expected with nothing on the bus
            self._att = None
            bus.close()
            return [f"PE4302 not available: no answer from the PCF8574 at I2C address 0x{self.pcf_address:02X} ({exc}). "
                    "Check wiring, its 3.3 V supply and the address ([attenuator] pcf8574_address)"]
        return [warning] if warning else []

    def _readback_warning(self) -> str:
        """"" when the expander's pins show what was written (V1..V6 only)."""
        seen = self._att.port.read_levels()
        wrote = self._att.port.levels
        if seen == wrote:
            return ""
        bad = ", ".join(f"V{i + 1}" for i in range(6) if (seen ^ wrote) >> i & 1)
        return (f"the PCF8574 pins do not follow what was written ({bad}): each V line needs a pull-up to 3.3 V "
                "(2.2k), or a line is shorted. The attenuation is NOT what was set")

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
        for pid in [p for p in self.i2c_pins if p in self._gpio_mode]:      # the attenuator needs its bus back
            attempt(self._restore_bus, pid, False)
        attempt(self._att_safe)
        for pid in list(self._lines):
            if pid in self.bus_pins:
                attempt(self._restore_bus, pid)
            elif pid != self.ld_pin:
                attempt(self._release, pid)
        attempt(self._rf_off)
        return errors

    def close(self, reason: str = "") -> List[str]:
        if not self.active:
            return []
        errors = self.safe_state()
        for bus in (self._spi_bus, self._att.port if self._att else None):
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
        if self._att is not None:
            self._att.safe_state()

    def _release(self, pid: str) -> None:
        self._lines[pid].set_direction(False)
        self._dir[pid] = "in"
        if self.pm.pins[pid].access == pinmap.EXPERT:
            del self._lines[pid]
            del self._dir[pid]

    def _restore_bus(self, pid: str, rewrite: bool = True) -> None:
        """Back from GPIO to the bus function. The chip on it may have latched junk: SPI writes R4 off again, I2C
        writes the attenuator's setting again (`rewrite` False when the caller sets it anyway)."""
        pin = self.pm.pins[pid]
        line = self._lines.pop(pid, None)
        self._dir.pop(pid, None)
        if line is not None:
            line.set_direction(False)
        self.backend.set_mux(pin.config_pin_name, pin.mux)
        self._gpio_mode.discard(pid)
        if pid in self.spi_pins and not self._gpio_mode.intersection(self.spi_pins):
            self._rf_off()
        if rewrite and pid in self.i2c_pins and not self._gpio_mode.intersection(self.i2c_pins) and self._att is not None:
            self._att.write_current()

    def _ensure_bus(self, pins: Sequence[str]) -> None:
        for pid in pins:
            if pid in self._gpio_mode:
                self._restore_bus(pid)

    def _rf_off(self) -> None:
        if self._adf is None or self._gpio_mode.intersection(self.spi_pins):
            return
        self._outputs = Outputs()
        self._adf.outputs = self._outputs
        self._write_r4(r4_with_outputs(self._last_r4, self._outputs))

    def _write_r4(self, word: int) -> None:
        self._last_r4 = word
        self._regs[4] = word
        self._adf.write_word(word)

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
            if as_gpio and pin.id in self.spi_pins:
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
        if pin.id in self.bus_pins and pin.id not in self._gpio_mode and not self.backend.can_mux:
            raise Refused(f"{pin.id} ({pin.net}) stays on its bus: this image has no config-pin to make it a GPIO")

    def _require_no_pattern(self) -> None:
        if self._run is not None:
            raise Refused("a pattern is running: stop it first")

    def _as_gpio(self, pin: pinmap.Pin, output: bool, level: int) -> GpioLine:
        """The line of a pin, with the direction and level asked for, opening or re-muxing it if needed."""
        if pin.id in self.bus_pins and pin.id not in self._gpio_mode:
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
        for pid in self.bus_pins:
            if pid not in self._gpio_mode:
                out[pid] = {"level": None, "dir": "bus"}
        return out

    def _att_pins_seen(self) -> Optional[int]:
        """V1..V6 as the expander's pins show them (bit 0 = V1); None without it or while I2C is used as GPIO."""
        if self._att is None or self._gpio_mode.intersection(self.i2c_pins):
            return None
        return self._att.port.read_levels()

    def _att_db(self, seen: Optional[int] = None) -> Optional[float]:
        seen = self._att_pins_seen() if seen is None else seen
        if seen is None:
            return None
        levels = {f"V{i + 1}": (seen >> i) & 1 for i in range(6)}
        return patterns.ParallelModel(levels, self.weights_db, self.active_high).attenuation_db

    def _ld(self) -> Optional[int]:
        line = self._lines.get(self.ld_pin)
        return None if line is None else line.read()

    def synth_state(self) -> Optional[dict]:
        """The ADF4351 as far as it can be known: the words written in this session, decoded (the chip can not
        be read back), and the live lock detect level. None without SPI."""
        if self._adf is None:
            return None
        state = decode_registers(self._regs, self.pfd_hz)
        state["source"] = "bench"
        state["ld"] = self._ld()
        state["programmed"] = 0 in self._regs and 1 in self._regs      # R0 and R1 were sent, not only an R4
        return state

    def _pattern_status(self) -> Optional[dict]:
        run = self._run
        if run is None:
            return self._last_run
        return {
            "running": True, "name": run.pattern.name, "step": run.index, "total": run.total, "loops": run.loops,
            "rate_hz": run.rate_hz, "measured_hz": run.measured_hz,
        }

    def _status(self, _cmd: dict) -> dict:
        seen = self._att_pins_seen()
        return {
            "ok": True, "active": True, "owner": True, "pins": self._levels(), "ld": self._ld(),
            "attenuation_db": None if seen is None else self._att_db(seen),
            "att_levels": None if seen is None else [(seen >> i) & 1 for i in range(6)],
            "att_ok": None if seen is None else seen == self._att.port.levels,
            "attenuator": self._att is not None,
            "rf": {"main": self._outputs.main.enabled, "aux": self._outputs.aux.enabled},
            "synth": self.synth_state(),
            "pattern": self._pattern_status(), "last_error": self.last_error,
            "spi": self._adf is not None,
        }

    # ------------------------------------------------------------ pins
    def _pin(self, cmd: dict) -> dict:
        self._require_no_pattern()
        if str(cmd["pin"]) in self.att_nets:
            raise Refused(f"{cmd['pin']} is an output of the PCF8574 on I2C, not an SBC pin: use the PE4302 controls")
        pin = self.pm.find(str(cmd["pin"]))
        action = cmd.get("action", "read")
        if action == "read":
            return self._pin_read(pin, cmd)
        if action == "input":
            return self._pin_input(pin, cmd)
        if action == "bus":
            if pin.id not in self.bus_pins:
                raise Refused(f"{pin.id} has no bus function")
            self._ensure_bus([pin.id])
        elif action == "write":
            self._check_drive([pin], cmd)
            value = int(cmd["value"])
            if value not in (0, 1):
                raise Refused("value must be 0 or 1")
            line = self._as_gpio(pin, True, value)
            return {"ok": True, "pin": pin.id, "level": line.read(), "dir": "out", "attenuation_db": self._att_db()}
        else:
            raise Refused(f"unknown pin action {action!r}")
        return {"ok": True, "pin": pin.id, "level": None, "dir": "bus"}

    def _pin_read(self, pin: pinmap.Pin, cmd: dict) -> dict:
        if pin.access == pinmap.DISPLAY:
            raise Refused(f"{pin.id} ({pin.name}) is display-only")
        if pin.access == pinmap.ANALOG:
            raise Refused(f"{pin.id} ({pin.name}) is analog: read it with bench_adc")
        if pin.id in self.bus_pins and pin.id not in self._gpio_mode:
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
        if pin.id in self.spi_pins:
            self._require_rf_off(f"{pin.id} ({pin.net}) as a GPIO")
        self._require_mux(pin)
        line = self._as_gpio(pin, False, 0)
        return {"ok": True, "pin": pin.id, "level": line.read(), "dir": "in", "attenuation_db": self._att_db()}

    # ------------------------------------------------------------ attenuator
    def _check_attenuator(self, cmd: dict) -> None:
        """Writing the PE4302 drives the I2C pins (confirm like any line to a board input)."""
        if self._att is None:
            raise Refused("the PE4302 is not available: the PCF8574 did not answer when bench mode opened")
        self._check_drive([self.pm.pins[p] for p in self.i2c_pins], cmd, as_gpio=False)

    def _atten(self, cmd: dict) -> dict:
        self._require_no_pattern()
        self._check_attenuator(cmd)
        mask = None
        if "levels" in cmd:
            levels = [int(v) for v in cmd["levels"]]
            if len(levels) != len(self.att_nets) or any(v not in (0, 1) for v in levels):
                raise Refused("levels must be six values of 0 or 1 (V1..V6)")
            mask = sum(v << i for i, v in enumerate(levels))
        db = None if mask is not None else float(cmd["db"])
        self._ensure_bus(self.i2c_pins)
        before = self._att.port.levels
        if mask is None:
            self._att.set_attenuation(db)
        elif cmd.get("raw"):                    # wiring test: exactly these levels in one byte, no make step
            self._att.set_levels(mask)
        else:
            model = {f"V{i + 1}": v for i, v in enumerate(levels)}
            self._att.set_attenuation(patterns.ParallelModel(model, self.weights_db, self.active_high).attenuation_db)
        warning = self._readback_warning()
        if warning:
            log.warning("bench: %s", warning)
        writes, previous = [], before
        for byte in self._att.last_bytes:       # which line changed in which byte, in order
            now = levels_of(byte)
            writes += [[net, (now >> i) & 1] for i, net in enumerate(self.att_nets) if (now ^ previous) >> i & 1]
            previous = now
        return {"ok": True, "attenuation_db": self._att_db(), "writes": writes,
                "port_bytes": [f"0x{b:02X}" for b in self._att.last_bytes], "warning": warning, "pins": self._levels()}

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
        self._regs[reg] = word
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
        self._check_drive([self.pm.pins[p] for p in self.spi_pins], cmd, as_gpio=False)
        self._ensure_bus(self.spi_pins)
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
        self._ensure_bus(self.spi_pins)
        self._set_outputs(main, aux, power)
        return {"ok": True, "rf": {"main": main, "aux": aux}, "sent": f"0x{self._last_r4:08X}", "ld": self._ld()}

    def _set_outputs(self, main: bool, aux: bool, power: int) -> None:
        """Write the R4 that switches the outputs (the caller has checked lock and confirm)."""
        self._outputs = Outputs(main=Output(main, power) if main else Output(), aux=Output(aux, power) if aux else Output())
        self._adf.outputs = self._outputs
        self._write_r4(r4_with_outputs(self._last_r4, self._outputs))
        log.info("RF output main=%s aux=%s%s", "on" if main else "off", "on" if aux else "off",
                 f" at {power} dBm" if main or aux else "")

    LOCK_POLLS = 40         # lock detect is read this often, LOCK_POLL_S apart: 0.2 s in all
    LOCK_POLL_S = 0.005

    def _synth(self, cmd: dict) -> dict:
        """Program the PLL for one frequency in a single step: plan, outputs off, R5..R0, wait for lock, and only if
        asked and locked, the outputs on. `f_hz` is the ADF4351 output (the LO), not the RF input frequency.
        {"f_hz", "power_dbm", "main", "aux"}; `confirm` for the SPI lines, `confirm_rf` for turning an output on
        (both asked before anything is written). A PLL that does not lock leaves the outputs off and says so."""
        self._require_no_pattern()
        self._require_spi()
        f_hz = float(cmd["f_hz"])
        power = int(cmd.get("power_dbm", -4))
        main, aux = bool(cmd.get("main")), bool(cmd.get("aux"))
        if power not in POWER_CODE:
            raise Refused(f"output power must be one of {sorted(POWER_CODE)} dBm")
        pll = self._adf.plan(f_hz)                      # ValueError: outside the ADF4351 range -> refused
        if main or aux:
            if f_hz > LO_MAX_HZ:
                raise Refused(f"{f_hz / 1e6:.3f} MHz is above the {LO_MAX_HZ / 1e6:g} MHz the AD831 LO input takes: "
                              "the output stays off (program it without the output to look at it elsewhere)")
        self._adf.outputs = Outputs()
        words = self._adf.registers(pll)                # ValueError: INT outside the prescaler's range -> refused
        self._check_drive([self.pm.pins[p] for p in self.spi_pins], cmd, as_gpio=False)
        if (main or aux) and not cmd.get("confirm_rf"):
            raise NeedsRfConfirm("This turns an ADF4351 RF output on once the PLL is locked. "
                                 "The other output of the pair must be terminated.")
        self._ensure_bus(self.spi_pins)
        self._rf_off()                                  # nothing unlocked reaches the mixer while the PLL moves
        for w in words:
            self._send_word(w)
        ld = self._ld()
        for _ in range(self.LOCK_POLLS):
            if ld != 0:                                 # locked, or no lock detect line to wait for
                break
            self._sleep(self.LOCK_POLL_S)
            ld = self._ld()
        note = ""
        if main or aux:
            if ld == 1:
                self._set_outputs(main, aux, power)
            else:
                note = ("the PLL did not lock (LD is low): RF outputs stay off" if ld == 0 else
                        "no lock detect line: RF outputs stay off")
        log.info("synth: LO %.6f MHz (%s, INT %d FRAC %d MOD %d, /%d, VCO %.3f MHz), LD %s%s", pll.f_actual_hz / 1e6,
                 "integer-N" if pll.frac == 0 else "fractional-N", pll.int_n, pll.frac, pll.mod, pll.rf_div,
                 pll.f_vco_hz / 1e6, ld, f", {note}" if note else "")
        if note:
            log.warning("synth: %s", note)
        return {
            "ok": True, "locked": None if ld is None else bool(ld), "note": note, "ld": ld,
            "f_target_hz": f_hz, "f_actual_hz": pll.f_actual_hz, "sent": [f"0x{w:08X}" for w in words],
            "rf": {"main": self._outputs.main.enabled, "aux": self._outputs.aux.enabled},
            "synth": self.synth_state(),
        }

    # ------------------------------------------------------------ ADCs
    def _adc(self, cmd: dict) -> dict:
        self._require_no_pattern()
        source = cmd.get("source", "ain")
        if source != "ain":
            gone = " (the ADS1115 was removed)" if source == "ads1115" else ""
            raise Refused(f"unknown ADC source {source!r}{gone}")
        if not any(p.ain is not None for p in self.pm.pins.values()):
            raise Refused(f"{self.pm.label} has no ADC input in bench mode (the ADS1115 was removed)")
        channel = int(cmd.get("channel", 0))
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
        pat = patterns.from_spec(spec, self.att_nets, self.weights_db, self.active_high)
        run = _Run(pat, 1.0 / rate, bool(cmd.get("loop")), rate, [])
        if pat.spi_words is not None:
            self._check_words(pat.spi_words)
            self._check_drive([self.pm.pins[p] for p in self.spi_pins], cmd, as_gpio=False)
            self._ensure_bus(self.spi_pins)
            run.words = pat.spi_words
        else:
            run.att = [s for s in pat.idle if s in self.att_nets]
            pins = [self.pm.find(s) for s in pat.idle if s not in self.att_nets]
            if run.att:
                if any(p.id in self.i2c_pins for p in pins):
                    raise Refused("the attenuator lines need the I2C bus: a pattern can not use the I2C pins as GPIO too")
                self._check_attenuator(cmd)
            self._check_drive(pins, cmd)
            run.groups = patterns.step_groups(pat)
            run.pins = [p.id for p in pins]
            if run.att:                                     # idle levels of the expander lines, make-before-break
                self._ensure_bus(self.i2c_pins)
                self._att.apply_lines({self.att_nets.index(s): pat.idle[s] for s in run.att})
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
            expander = {}
            for edge in run.groups[run.index]:
                if edge.signal in self.att_nets:
                    expander[self.att_nets.index(edge.signal)] = edge.level
                else:
                    run.lines[edge.signal].write(edge.level)
            if expander:                                    # one I2C write per step
                self._att.apply_lines(expander)
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
        if run.att:
            self._att_safe()
        for pid in run.pins:
            if pid in self.bus_pins:
                self._restore_bus(pid)
            else:
                self._release(pid)
