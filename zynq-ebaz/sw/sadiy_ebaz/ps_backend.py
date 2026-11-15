"""Bench mode on the real EBAZ4205 with Linux as the owner of the pins (lane L, plan S5).

`sweepd --platform ebaz --bench-only` uses this backend: the PE4302 lines, CE and lock detect are EMIO GPIO
lines of the PS (Linux line = 54 + EMIO n = the pin map number), the ADF4351 sits on `/dev/spidev0.0` (PS SPI0)
and the ADS1115 on `/dev/i2c-0` (PS I2C0). No pin mux exists here (the buses are wired in the bitstream), and
there is no on-chip ADC input.

The PL sweep engine's pin mux must hand the pins to the PS for this to work. After a reset it does
(`CTRL.pin_owner = 0`); `prepare()` checks, and releases the pins if a killed `sweepd` left the engine owning
them. It touches the core only when the FPGA manager says `operating` and the ID register answers (an AXI
access to an unconfigured PL stalls the CPU).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, List, Optional

from sadiy.hal.base import AnalogInput, BenchBackend, I2cBus, SpiBus
from sadiy.hal.linux import LinuxI2c, SpidevBus, SysfsGpio, zynq_gpio_base

from .devmem import FPGA_STATE, pl_not_ready
from .regmap_toml import REGS

log = logging.getLogger("sadiy.ebaz_ps")


def release_pl_pins(regs, *, timeout_s: float = 0.5, sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic) -> str:
    """Make the PS the owner of the pins. `regs`: object with read(offset) / write(offset, value) (DevMemRegs).
    Returns a sentence about what was found or done ("" when there is nothing to say)."""
    ident = REGS["ID"]
    if regs.read(ident.offset) != ident.reset_value():
        return "no sweep core answers at the register base: the PL pins were not checked"
    status, ctrl = REGS["STATUS"], REGS["CTRL"]
    act, owner = status.fields["pin_owner_act"], ctrl.fields["pin_owner"]
    if not act.get(regs.read(status.offset)):
        return ""
    word = regs.read(ctrl.offset)
    keep = 0                                           # rw level bits stay, the pulse bits (start, abort, ...) are 0
    for f in ctrl.fields.values():
        if f.access == "rw":
            keep |= f.put(f.get(word))
    regs.write(ctrl.offset, (keep & ~owner.mask) | ctrl.fields["abort"].put(1))      # PS owner, stop a running sweep
    end = clock() + timeout_s
    while clock() < end:
        if not act.get(regs.read(status.offset)):
            return "the PL engine owned the pins (left over from a sweep): handed back to Linux"
        sleep(0.01)
    return "the PL engine still owns the pins (a sweep is running?): bench writes will not reach the board"


class EbazPsBackend(BenchBackend):
    name = "EBAZ4205 (PS: sysfs EMIO GPIO, spidev, i2c-dev)"
    can_mux = False

    def __init__(self, spi_bus: int = 0, spi_device: int = 0, spi_hz: int = 1_000_000, i2c_bus: int = 0,
                 i2c_address: int = 0x48, regs_base: Optional[int] = None, gpio_root: Optional[Path] = None,
                 state_path: Path = FPGA_STATE, open_regs: Optional[Callable[[], object]] = None) -> None:
        self._spi_args = (spi_bus, spi_device, spi_hz)
        self._i2c_args = (i2c_bus, i2c_address)
        self._base: Optional[int] = None            # sysfs number of the first line of the PS GPIO chip
        self._regs_base = regs_base
        self._gpio_root = gpio_root
        self._state_path = state_path
        self._open_regs = open_regs

    def gpio(self, number: int, output: bool = False, initial: int = 0) -> SysfsGpio:
        if self._base is None:
            self._base = zynq_gpio_base(self._gpio_root)
            if self._base is None:
                raise OSError("no Zynq PS GPIO chip (118 lines) in /sys/class/gpio")
        return SysfsGpio(self._base + number, output, initial)

    def spi(self) -> SpiBus:
        bus, device, _hz = self._spi_args
        try:
            return SpidevBus(*self._spi_args)
        except OSError as exc:
            raise OSError(f"could not open /dev/spidev{bus}.{device} ({exc}); run sweepd as root") from exc

    def i2c(self) -> I2cBus:
        return LinuxI2c(*self._i2c_args)

    def ain(self, channel: int) -> AnalogInput:
        raise OSError("the EBAZ4205 has no on-chip ADC input: use the ADS1115")

    def set_mux(self, config_pin_name: str, mode: str) -> None:
        raise OSError("the EBAZ4205 has no pin mux: SPI and I2C are wired to the PS in the bitstream")

    def prepare(self) -> List[str]:
        """Called when bench mode opens: hand the pins to the PS if the PL engine holds them."""
        why = pl_not_ready(self._state_path)
        if why:
            return [f"{why}: pin ownership not checked"]
        try:
            if self._open_regs is None:
                from .devmem import DEFAULT_BASE, DevMemRegs
                regs = DevMemRegs(DEFAULT_BASE if self._regs_base is None else self._regs_base)
            else:
                regs = self._open_regs()
        except (OSError, ValueError) as exc:
            return [f"PL registers not reachable ({exc}): pin ownership not checked"]
        try:
            note = release_pl_pins(regs)
        finally:
            close = getattr(regs, "close", None)
            if close:
                close()
        return [note] if note else []
