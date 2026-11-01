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
