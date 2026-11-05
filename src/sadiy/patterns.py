"""Pattern maker: the exact pin states a driver should produce, and a model that replays them.

Attenuator (PE4302 module, parallel control V1..V6): the pattern is the ordered list of line writes
for a change from one setting to another, the final line levels, and the lowest attenuation seen at
any intermediate step. Compare it with a logic analyzer capture before connecting RF.

Synthesizer (ADF4351): SPI frames for register words (MSB first, 32 clocks, LE = chip select).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .drivers.pe4302 import DEFAULT_WEIGHTS_DB, PE4302
from .hal.fake import FakeGpio, PinLog

SPI_IDLE = {"CS": 1, "SCLK": 0, "MOSI": 0}


@dataclass(frozen=True)
class Edge:
    signal: str
    level: int


@dataclass
class Pattern:
    name: str
    idle: Dict[str, int]                 # levels before the first edge
    edges: List[Edge]
    notes: List[str] = field(default_factory=list)
    expected_db: Optional[float] = None
    weights_db: Optional[Sequence[float]] = None   # set for attenuator patterns (V1..V6)
    active_high: bool = True
    groups: Optional[List[List[Edge]]] = None      # bench patterns: the edges per time slot
    spi_words: Optional[List[int]] = None          # bench patterns sent through the SPI controller


# ----------------------------------------------------------------------------- attenuator
class ParallelModel:
    """Attenuation of a parallel-controlled PE4302 module for given line levels."""

    def __init__(self, levels: Dict[str, int], weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
                 active_high: bool = True) -> None:
        self.levels = dict(levels)
        self.weights_db = tuple(weights_db)
        self.active_high = active_high

    def feed(self, edge: Edge) -> None:
        self.levels[edge.signal] = edge.level

    @property
    def attenuation_db(self) -> float:
        on = 1 if self.active_high else 0
        return sum(w for i, w in enumerate(self.weights_db) if self.levels.get(f"V{i + 1}") == on)


def pe4302_parallel(db: float, from_db: Optional[float] = None, weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
                    active_high: bool = True) -> Pattern:
    """Line writes for a change from `from_db` (default: the safe state, all stages in) to `db`."""
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(len(weights_db))]
    dev = PE4302(lines, weights_db, active_high)
    if from_db is not None:
        dev.set_attenuation(from_db)
    idle = {ln.name: ln.level for ln in lines}
    log.events.clear()
    actual = dev.set_attenuation(db)
    start = ParallelModel(idle, weights_db, active_high).attenuation_db
    return Pattern(
        name=f"PE4302 parallel: {start} dB -> {actual} dB",
        idle=idle,
        edges=[Edge(n, v) for n, v in log.events],
        notes=[
            "V1..V6 weigh " + ", ".join(str(w) for w in weights_db) + " dB (assumed order, verify on the module)",
            "polarity: " + ("high" if active_high else "low") + " = stage switched in (verify on the module)",
            "stages turning on are written before stages turning off, so no step is below min(old, new)",
        ],
        expected_db=actual,
        weights_db=tuple(weights_db),
        active_high=active_high,
    )


def attenuation_steps(p: Pattern) -> List[float]:
    """Attenuation after every edge, starting with the idle state."""
    m = ParallelModel(p.idle, p.weights_db, p.active_high)
    out = [m.attenuation_db]
    for e in p.edges:
        m.feed(e)
        out.append(m.attenuation_db)
    return out


def replay(p: Pattern) -> ParallelModel:
    m = ParallelModel(p.idle, p.weights_db, p.active_high)
    for e in p.edges:
        m.feed(e)
    return m


# ----------------------------------------------------------------------------- synthesizer
def spi_frame(data: bytes) -> List[Edge]:
    """One chip-select frame: SPI mode 0, MSB first, active-low CS."""
    edges = [Edge("CS", 0)]
    for byte in data:
        for i in range(7, -1, -1):
            edges += [Edge("MOSI", (byte >> i) & 1), Edge("SCLK", 1), Edge("SCLK", 0)]
    edges.append(Edge("CS", 1))
    return edges


def decode_spi(edges: Sequence[Edge], idle: Optional[Dict[str, int]] = None) -> List[bytes]:
    """Decode mode 0, MSB first, active-low CS frames from an edge list."""
    level = dict(idle or SPI_IDLE)
    frames: List[bytes] = []
    bits: List[int] = []
    for e in edges:
        prev = level.get(e.signal, 0)
        level[e.signal] = e.level
        if e.signal == "SCLK" and prev == 0 and e.level == 1 and level["CS"] == 0:
            bits.append(level["MOSI"])
        if e.signal == "CS" and prev == 1 and e.level == 0:
            bits = []
        if e.signal == "CS" and prev == 0 and e.level == 1:
            usable = len(bits) - len(bits) % 8
            frames.append(bytes(int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, usable, 8)))
            bits = []
    return frames


def adf4351_words(words: Sequence[int]) -> Pattern:
    """32-bit register words, MSB first, LE = chip select (data latches on the rising edge)."""
    edges: List[Edge] = []
    for w in words:
        edges += spi_frame(w.to_bytes(4, "big"))
    return Pattern(
        name=f"ADF4351 SPI, {len(words)} word(s)",
        idle=dict(SPI_IDLE),
        edges=edges,
        notes=[
            "SPI mode 0, MSB first, 32 clocks per word; the 3 LSBs of each word are the register address",
            "LE (= CS) idles high; the register loads on the rising edge at the end of each word",
        ],
    )


# ----------------------------------------------------------------------------- bench patterns
# Pin checks for the bench mode. A pattern is a list of steps, one per time slot; a step can change
# several lines. Signals are net names ("ATT_V1") or pin ids ("P8.13") from pinmap.
MAX_STEPS = 100_000


def _from_frames(name: str, signals: Sequence[str], idle: Dict[str, int], frames: Sequence[Dict[str, int]],
                 notes: Sequence[str]) -> Pattern:
    """Writes only the lines that change. Within a step lines going high are written first: with an
    active-high PE4302 that keeps the make-before-break order."""
    level = dict(idle)
    groups: List[List[Edge]] = []
    for frame in frames:
        changes = [Edge(s, frame[s]) for s in signals if frame[s] != level[s]]
        changes.sort(key=lambda e: -e.level)
        level.update(frame)
        groups.append(changes)
    return Pattern(name, dict(idle), [e for g in groups for e in g], list(notes), groups=groups)


def walking(signals: Sequence[str], active: int = 1, cycles: int = 1) -> Pattern:
    """Walking one (active = 1) or walking zero (active = 0): one line differs at a time. Ends at idle."""
    if not signals:
        raise ValueError("pick at least one pin")
    rest = 1 - active
    idle = {s: rest for s in signals}
    frames = [{t: (active if t == s else rest) for t in signals} for _ in range(cycles) for s in signals]
    what = "one" if active else "zero"
    return _from_frames(f"Walking {what} over {len(signals)} line(s), {cycles} cycle(s)", signals, idle,
                        frames + [dict(idle)], [f"exactly one line is {active} in each step: a line that "
                                                "stays still or moves with another shows an open or a short"])


def square_wave(signal: str, cycles: int = 1) -> Pattern:
    """One line toggling. Two steps per period, so the frequency is half the step rate."""
    frames = [{signal: v} for _ in range(cycles) for v in (1, 0)]
    return _from_frames(f"Square wave on {signal}, {cycles} period(s)", [signal], {signal: 0}, frames,
                        ["two steps per period: frequency = step rate / 2"])


def binary_counter(signals: Sequence[str], steps: Optional[int] = None) -> Pattern:
    """Count up on the lines, first line = LSB, then return to 0."""
    if not signals:
        raise ValueError("pick at least one pin")
    total = 2 ** len(signals) if steps is None else steps
    if total > MAX_STEPS:
        raise ValueError(f"at most {MAX_STEPS} steps; pick fewer pins or give a step count")
    idle = {s: 0 for s in signals}
    frames = [{s: (n >> i) & 1 for i, s in enumerate(signals)} for n in range(1, total)]
    return _from_frames(f"Binary counter on {len(signals)} line(s), {total} steps", signals, idle,
                        frames + [dict(idle)], [f"{signals[0]} is the LSB"])


def pe4302_stage_sweep(signals: Sequence[str], weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
                       active_high: bool = True, mode: str = "one_out") -> Pattern:
    """Through the driver, so with make-before-break order, from the safe state back to it.

    mode "one_out": every stage in except one, so never below the maximum minus the largest stage.
    mode "one_in": only one stage in. Each stage shows alone, but the attenuation gets low: no RF!
    """
    if mode not in ("one_out", "one_in"):
        raise ValueError("mode must be one_out or one_in")
    log = PinLog()
    lines = [FakeGpio(s, log) for s in signals]
    dev = PE4302(lines, weights_db, active_high)
    idle = {ln.name: ln.level for ln in lines}
    groups: List[List[Edge]] = []
    targets = [w if mode == "one_in" else dev.max_db - w for w in weights_db] + [dev.max_db]
    for db in targets:
        log.events.clear()
        dev.set_attenuation(db)
        groups.append([Edge(n, v) for n, v in log.events])
    return Pattern(
        f"PE4302 stage by stage ({mode.replace('_', ' ')})", idle, [e for g in groups for e in g],
        ["attenuation per step: " + " -> ".join(f"{t:g}" for t in targets) + " dB"], groups=groups,
        weights_db=tuple(weights_db), active_high=active_high,
    )


def lowest_attenuation(p: Pattern, att_signals: Sequence[str], weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
                       active_high: bool = True) -> Optional[float]:
    """Lowest attenuation reached, when lines outside the pattern stay in the safe state. None if no
    attenuator line takes part."""
    if not set(att_signals) & set(p.idle):
        return None
    safe = 1 if active_high else 0
    level = {s: p.idle.get(s, safe) for s in att_signals}
    index = {s: i + 1 for i, s in enumerate(att_signals)}

    def now() -> float:
        return ParallelModel({f"V{index[s]}": v for s, v in level.items()}, weights_db, active_high).attenuation_db

    low = now()
    for e in p.edges:
        if e.signal in level:
            level[e.signal] = e.level
            low = min(low, now())
    return low


def step_groups(p: Pattern) -> List[List[Edge]]:
    """The edges per time slot. Patterns without steps have one edge per slot."""
    return p.groups if p.groups is not None else [[e] for e in p.edges]


def from_spec(spec: dict, att_signals: Sequence[str] = (), weights_db: Sequence[float] = DEFAULT_WEIGHTS_DB,
              active_high: bool = True) -> Pattern:
    """Build a bench pattern from its JSON form. The GUI uses this for the preview and CSV and the
    daemon for the run, so what is previewed is what runs.

    {"kind": "walking", "signals": [...], "active": 1, "cycles": 1}
    {"kind": "square", "signals": [one], "cycles": 1}
    {"kind": "counter", "signals": [...], "steps": null}
    {"kind": "pe4302_stages", "mode": "one_out"}
    {"kind": "adf4351_frame", "words": [...], "repeat": 1}
    """
    kind = spec.get("kind")
    signals = list(spec.get("signals", ()))
    cycles = int(spec.get("cycles", 1))
    if cycles < 1:
        raise ValueError("cycles must be at least 1")
    if kind == "walking":
        if int(spec.get("active", 1)) not in (0, 1):
            raise ValueError("active must be 0 or 1")
        p = walking(signals, int(spec.get("active", 1)), min(cycles, MAX_STEPS // max(len(signals), 1)))
    elif kind == "square":
        if len(signals) != 1:
            raise ValueError("a square wave needs exactly one pin")
        p = square_wave(signals[0], min(cycles, MAX_STEPS // 2))
    elif kind == "counter":
        steps = spec.get("steps")
        if len(signals) > 16 and steps is None:
            raise ValueError(f"at most {MAX_STEPS} steps; pick fewer pins or give a step count")
        p = binary_counter(signals, None if steps is None else int(steps))
    elif kind == "pe4302_stages":
        p = pe4302_stage_sweep(list(att_signals), weights_db, active_high, spec.get("mode", "one_out"))
    elif kind == "adf4351_frame":
        words = [int(w) for w in spec.get("words", ())]
        if not words:
            raise ValueError("give at least one 32-bit word")
        if any(not 0 <= w <= 0xFFFFFFFF for w in words):
            raise ValueError("SPI words must fit in 32 bits")
        words = words * max(1, int(spec.get("repeat", 1)))
        if len(words) > MAX_STEPS // 100:
            raise ValueError("too many SPI words in one pattern; use Loop instead")
        p = adf4351_words(words)
        p.spi_words = words
        p.notes.append("sent through the SPI controller: its clock is much faster than the step rate")
        return p
    else:
        raise ValueError(f"unknown pattern kind {kind!r}")
    low = lowest_attenuation(p, att_signals, weights_db, active_high) if att_signals else None
    if low is not None:
        p.notes.append(f"attenuation goes down to {low:g} dB during this pattern: keep RF off the input")
    return p


# ----------------------------------------------------------------------------- output
def to_csv(p: Pattern) -> str:
    """Levels of every signal after each edge: step, <signals...>."""
    sig = list(p.idle.keys())
    level = dict(p.idle)
    out = io.StringIO()
    out.write("step," + ",".join(sig) + "\n")
    out.write("0," + ",".join(str(level[s]) for s in sig) + "\n")
    for i, e in enumerate(p.edges, 1):
        level[e.signal] = e.level
        out.write(f"{i}," + ",".join(str(level[s]) for s in sig) + "\n")
    return out.getvalue()


def describe(p: Pattern) -> List[str]:
    lines = [p.name, ""] + [f"- {n}" for n in p.notes] + [""]
    if p.weights_db is not None:
        lines.append("line   weight   start  end")
        end = replay(p).levels
        for i, w in enumerate(p.weights_db, 1):
            lines.append(f"V{i}     {w:5.1f} dB   {p.idle[f'V{i}']}      {end[f'V{i}']}")
        lines.append("")
        steps = attenuation_steps(p)
        lines.append("writes: " + (" ".join(f"{e.signal}={e.level}" for e in p.edges) or "(none)"))
        lines.append("attenuation after each write: " + " -> ".join(f"{a:g}" for a in steps) + " dB")
        lines.append(f"lowest attenuation during the change: {min(steps):g} dB (old {steps[0]:g}, new {steps[-1]:g})")
    else:
        lines.append("idle: " + ", ".join(f"{k}={v}" for k, v in p.idle.items()))
        for i, frame in enumerate(decode_spi(p.edges, p.idle)):
            lines.append(f"frame {i}: {frame.hex()}  bits " + " ".join(f"{b:08b}" for b in frame))
        lines.append("edges: " + " ".join(f"{e.signal}={e.level}" for e in p.edges))
    return lines
