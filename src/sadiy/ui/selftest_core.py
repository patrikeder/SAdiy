"""Qt-free part of the Ramp self-test box (Advanced tab): the command to send and how to show the reply.

The self-test is the PL engine's own test ramp coming back with known values (zynq-ebaz/docs/selftest.md); sweepd
runs it between two sweeps and answers with the report. See `sadiy.server.protocol` for the command.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

DEFAULT_SWEEPS = 5
SWEEPS_MIN, SWEEPS_MAX = 1, 20
WAIT_FOR_SWEEP_S = 8.0       # a command is only answered between sweeps (3.5 s on the EBAZ, longer with many averages)
TEST_LIMIT_S = 30.0          # sweepd refuses a test that would take longer


@dataclass(frozen=True)
class Options:
    sweeps: int = DEFAULT_SWEEPS
    wrap: bool = False           # a second run with N_AVG 1, base 0xFFF0 (16-bit wrap)
    fill: bool = False           # 4096 points: the whole table and result memory

    def command(self) -> dict:
        return {"cmd": "selftest", "sweeps": max(SWEEPS_MIN, min(SWEEPS_MAX, int(self.sweeps))),
                "wrap": bool(self.wrap), "fill": bool(self.fill)}


def timeout_ms() -> int:
    """How long the GUI waits for the reply: the sweep in progress, then the longest test sweepd accepts."""
    return int((WAIT_FOR_SWEEP_S + TEST_LIMIT_S + 5.0) * 1000)


@dataclass(frozen=True)
class Result:
    passed: Optional[bool]       # None: no verdict (refused, no answer)
    summary: str
    lines: List[str]


def parse_reply(reply: Optional[dict]) -> Result:
    if reply is None:
        return Result(None, "no answer from sweepd (is it still running? the test may take a few seconds)", [])
    if not reply.get("ok"):
        return Result(None, f"not run: {reply.get('error', 'refused')}", [])
    lines = [str(x) for x in reply.get("lines", [])]
    seconds = float(reply.get("seconds", 0.0))
    checks = int(reply.get("checks", 0))
    failed = reply.get("failed", [])
    if reply.get("passed"):
        return Result(True, f"PASS: {checks} checks, {seconds:.1f} s", lines)
    return Result(False, f"FAIL: {len(failed)} of {checks} checks failed ({seconds:.1f} s)", lines)
