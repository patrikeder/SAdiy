"""Interactive bring-up helpers that need real GPIO lines (used by tools/bringup.py)."""
from __future__ import annotations

from typing import Callable, Sequence

from .hal.base import GpioLine


def walk_lines(
    lines: Sequence[GpioLine],
    active_high: bool = True,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    expected_db: Sequence[float] = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0),
    mv_per_db: float = 24.5,
) -> None:
    """Identify what each PE4302 input does. Switches ONE stage at a time (the others out) and waits.

    Setup: a low-level tone (-20 dBm or less at the module input) through the attenuator into the
    log detector, DMM on the detector output. With the log detector slope of about 24.5 mV/dB, the
    output RISES by weight x 24.5 mV when a stage switches in (less signal, higher voltage) (16 dB is about 390 mV, 0.5 dB about 12 mV).
    Ends with every stage switched in (maximum attenuation), the safe state.
    """
    on, off = (1 if active_high else 0), (0 if active_high else 1)

    def set_all(level: int) -> None:
        for ln in lines:
            ln.write(level)

    say("All stages switched in: maximum attenuation. Note the detector output (highest voltage = lowest signal).")
    set_all(on)
    ask("Enter to continue ")
    say("All stages switched out: minimum attenuation. Keep the RF level low. Note the detector output (lowest voltage).")
    set_all(off)
    ask("Enter to continue ")
    for i, ln in enumerate(lines):
        set_all(off)
        ln.write(on)
        w = expected_db[i] if i < len(expected_db) else float("nan")
        say(f"V{i + 1} only switched in. Expect the detector output to RISE by about {w * mv_per_db:.0f} mV "
            f"({w} dB less signal) if V{i + 1} is the {w} dB stage.")
        ask("Enter for the next line ")
    set_all(on)
    say("Done. All stages switched in (safe state). Write the measured weight of V1..V6 into "
        "config/default.toml (attenuator.weights_db) and check the polarity (active_high).")
