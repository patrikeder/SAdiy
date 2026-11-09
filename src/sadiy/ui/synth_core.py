"""Qt-free logic of the Synth tab: the presets, the plan preview and the readback texts.

The presets are the LO settings that matter once the receiver sweeps. Everything is derived from what
`sweepd` reports in `status` ("lo": IF, injection, PFD, MOD limit; "limits": RF range), so a different IF in
the config changes the presets too. `f_lo_hz` is the ADF4351 output frequency, not the RF input frequency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..core import freqplan
from . import sa_core as core

POWER_CHOICES_DBM = (-4, -1, 2, 5)          # the ADF4351 steps


@dataclass(frozen=True)
class LoInfo:
    """What the synth tab needs to know about the receiver. Defaults match config/default.toml."""

    rf_min_hz: float = 30e6
    rf_max_hz: float = 480e6
    if_hz: float = 10.7e6
    injection: str = "high"
    pfd_hz: float = 25e6
    mod_max: int = 4095

    @classmethod
    def from_status(cls, status: dict) -> "LoInfo":
        """From a `status` reply. A sweepd that does not report "lo" (older version) keeps the defaults."""
        lim, lo = status.get("limits", {}), status.get("lo", {})
        d = cls()
        try:
            return cls(
                rf_min_hz=float(lim.get("rf_min_hz", d.rf_min_hz)), rf_max_hz=float(lim.get("rf_max_hz", d.rf_max_hz)),
                if_hz=float(lo.get("if_hz", d.if_hz)), injection=str(lo.get("injection", d.injection)),
                pfd_hz=float(lo.get("pfd_hz", d.pfd_hz)), mod_max=int(lo.get("mod_max", d.mod_max)),
            )
        except (TypeError, ValueError):
            return d

    def lo_for_rf(self, rf_hz: float) -> float:
        return freqplan.lo_for_rf(rf_hz, self.if_hz, self.injection)

    def lo_other_side(self, rf_hz: float) -> float:
        return freqplan.lo_for_rf(rf_hz, self.if_hz, freqplan.opposite_injection(self.injection))


@dataclass(frozen=True)
class Preset:
    name: str
    f_lo_hz: float
    power_dbm: int
    note: str


def presets(info: LoInfo, power_dbm: int = -4) -> List[Preset]:
    """The presets in the order of use: first light on the bench, then what a sweep needs of the LO."""
    mid = 0.5 * (info.rf_min_hz + info.rf_max_hz)
    p = power_dbm
    out = [
        Preset("100 MHz CW (first light)", 100e6, p,
               "The test frequency of the bring-up plan: integer-N (VCO 3.2 GHz / 32), the easiest lock to see."),
        Preset(f"LO for a {core.format_hz(100e6, 0)} signal", info.lo_for_rf(100e6), p,
               "Where a sweep puts the LO for the first simulated tone. Fractional-N: checks the FRAC / MOD words."),
        Preset(f"LO for a {core.format_hz(250e6, 0)} signal", info.lo_for_rf(250e6), p,
               "As above for the second tone: another divider and VCO range."),
        Preset(f"Sweep start (RF {core.format_hz(info.rf_min_hz, 0)})", info.lo_for_rf(info.rf_min_hz), p,
               "LO at the first point of the full-span sweep."),
        Preset(f"Sweep center (RF {core.format_hz(mid, 0)})", info.lo_for_rf(mid), p,
               "LO in the middle of the full-span sweep."),
        Preset(f"Sweep stop (RF {core.format_hz(info.rf_max_hz, 0)})", info.lo_for_rf(info.rf_max_hz), p,
               "LO at the last point of the full-span sweep, close to the AD831 limit of 500 MHz."),
        Preset(f"Image check (LO on the other side of {core.format_hz(100e6, 0)})", info.lo_other_side(100e6), p,
               "The LO that image rejection uses for the same signal; the IF is the same, the image is not."),
    ]
    return [x for x in out if freqplan.OUT_MIN_HZ <= x.f_lo_hz <= freqplan.LO_MAX_HZ]


def plan_text(f_lo_hz: float, info: LoInfo) -> str:
    """One line on how the ADF4351 would make `f_lo_hz`, or why it can not."""
    try:
        plan = freqplan.plan_pll(f_lo_hz, info.pfd_hz, info.mod_max)
    except ValueError as exc:
        return str(exc)
    mode = "integer-N" if plan.frac == 0 else f"fractional-N, FRAC {plan.frac} / MOD {plan.mod}"
    err = plan.f_actual_hz - plan.f_out_hz
    text = (f"{core.format_hz(plan.f_actual_hz, 6)}: {mode}, INT {plan.int_n}, VCO {core.format_hz(plan.f_vco_hz)} / {plan.rf_div}")
    if abs(err) >= 0.5:
        text += f", {err:+.1f} Hz from the request"
    if plan.f_actual_hz > freqplan.LO_MAX_HZ:
        text += f". Above the AD831 limit of {core.format_hz(freqplan.LO_MAX_HZ, 0)}: the output can not be turned on"
    return text


def _outputs_text(synth: dict) -> str:
    parts = []
    for key, label in (("main", "main"), ("aux", "aux")):
        out = synth.get(key)
        if out is None:
            continue
        parts.append(f"{label} {out['power_dbm']:+d} dBm" if out.get("enabled") else f"{label} off")
    return ", ".join(parts)


def _ld_text(ld: Optional[int]) -> str:
    return "LD ?" if ld is None else f"LD {ld}"


def status_text(synth: Optional[dict]) -> str:
    """The short readback for the status bar. Empty when nothing is known (not connected)."""
    if not synth:
        return ""
    f = synth.get("f_out_hz")
    if synth.get("source") == "sweep":
        return f"LO {core.format_hz(f, 3) if f else '-'} (sweeping)   {_ld_text(synth.get('ld'))}"
    where = core.format_hz(f, 6) if f else "not programmed"
    outs = _outputs_text(synth)
    return f"LO {where}   {_ld_text(synth.get('ld'))}" + (f"   RF {outs}" if outs else "")


def readback_text(synth: Optional[dict]) -> str:
    """The long readback for the Synth tab: every field of the decoded registers."""
    if not synth:
        return "No readback: bench mode is off and nothing is sweeping."
    if synth.get("source") == "sweep":
        f = synth.get("f_out_hz")
        return (f"Sweeping. Last LO tuned: {core.format_hz(f, 6) if f else '-'}\n{_ld_text(synth.get('ld'))}\n"
                "Enter bench mode to set the synthesizer by hand.")
    lines: List[str] = []
    f = synth.get("f_out_hz")
    if f is None:
        lines.append("Output: not programmed in this session (R0, R1 and R4 are needed)")
    else:
        lines.append(f"Output: {core.format_hz(f, 6)}   VCO {core.format_hz(synth['f_vco_hz'], 3)} / {synth['rf_div']}")
        lines.append(f"PLL: {synth['mode']}, INT {synth['int_n']}, FRAC {synth['frac']}, MOD {synth['mod']}, "
                     f"prescaler {synth['prescaler']}")
    lines.append(f"Lock detect: {'?' if synth.get('ld') is None else synth['ld']}   RF: {_outputs_text(synth) or '-'}")
    words = synth.get("words") or {}
    if words:
        lines.append("Last words written (the chip itself can not be read):")
        lines.append("  " + "  ".join(f"{r} {w}" for r, w in words.items()))
    return "\n".join(lines)
