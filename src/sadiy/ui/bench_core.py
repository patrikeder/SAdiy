"""Logic of the Pins tab without Qt: the bench session, input parsing, pattern preview, board layout.

The rules (what may be driven, confirm, exclusivity) are enforced by the daemon in `server/bench.py`.
This module only asks the operator when the daemon says it needs a confirm, and remembers the answer
until bench mode closes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .. import patterns, pinmap
from ..drivers.adf4351 import register_of

Request = Callable[[dict], Optional[dict]]
Ask = Callable[[str], bool]

NO_REPLY = {"ok": False, "error": "No reply from sweepd (is it running?)"}
INIT_ORDER = (5, 4, 3, 2, 1, 0)


# ---------------------------------------------------------------- input parsing
def parse_word(text: str) -> int:
    """A 32-bit register word typed in hex, with or without 0x."""
    text = text.strip().replace("_", "").replace(" ", "")
    if not text:
        raise ValueError("enter a 32-bit word in hex")
    try:
        word = int(text, 16)
    except ValueError:
        raise ValueError(f"{text!r} is not a hex number") from None
    if not 0 <= word <= 0xFFFFFFFF:
        raise ValueError(f"{text} does not fit in 32 bits")
    return word


def init_sequence(texts: Sequence[str]) -> List[int]:
    """Six words in the order R5, R4, R3, R2, R1, R0. Each one's address bits must match its place."""
    if len(texts) != len(INIT_ORDER):
        raise ValueError("the init sequence is six words, R5 to R0")
    words = [parse_word(t) for t in texts]
    for reg, word in zip(INIT_ORDER, words):
        if register_of(word) != reg:
            raise ValueError(f"0x{word:08X} has address bits {register_of(word)}, but it is in the R{reg} box")
    return words


def describe_pin(pin: pinmap.Pin) -> str:
    """The text of the pin details panel."""
    access = {
        pinmap.WIRED: "can be driven, after a confirm: it goes to a board input",
        pinmap.INPUT_ONLY: "input-only: the board drives it",
        pinmap.ANALOG: "analog input: read through the ADC, never driven",
        pinmap.EXPERT: "free GPIO, not in the pin map: locked unless Expert is ticked",
        pinmap.DISPLAY: "display-only",
    }[pin.access]
    rows = [f"{pin.id}   {pin.name}"]
    if pin.net:
        rows.append(f"Net: {pin.net}")
        rows.append(f"Board pin: {pin.board} {pin.board_pin}")
    rows.append(f"GPIO: GPIO{pin.gpio // 32}_{pin.gpio % 32} (number {pin.gpio})" if pin.gpio is not None else "GPIO: none")
    if pin.ain is not None:
        rows.append(f"ADC channel: AIN{pin.ain}")
    rows.append(f"Use: {access}")
    if pin.note:
        rows.append(f"Notes: {pin.note}")
    return "\n".join(rows)


# ---------------------------------------------------------------- pattern preview
def waveform(p: patterns.Pattern, max_steps: int = 64) -> List[str]:
    """One text line per signal, one column per step (after the idle column)."""
    groups = patterns.step_groups(p)
    level = dict(p.idle)
    columns = {s: [level[s]] for s in p.idle}
    for group in groups[:max_steps]:
        for e in group:
            level[e.signal] = e.level
        for s in columns:
            columns[s].append(level[s])
    width = max((len(s) for s in columns), default=0)
    lines = [f"{s:<{width}} " + "".join("‾" if v else "_" for v in cols) for s, cols in columns.items()]
    if len(groups) > max_steps:
        lines.append(f"... first {max_steps} of {len(groups)} steps")
    return lines


def max_rate_hz(p: patterns.Pattern, limits: Optional[dict]) -> Optional[float]:
    """The step rate the backend can roughly hold for this pattern. An estimate: see `hal/base.py`."""
    if not limits:
        return None
    if p.spi_words is not None:
        return float(limits["max_spi_words_per_s"])
    groups = patterns.step_groups(p)
    writes = sum(len(g) for g in groups) / max(len(groups), 1)
    return float(limits["max_writes_per_s"]) / max(writes, 1.0)


def preview_text(p: patterns.Pattern, rate_hz: float, limits: Optional[dict] = None, loop: bool = False) -> str:
    steps = len(p.spi_words) if p.spi_words is not None else len(patterns.step_groups(p))
    rows = [p.name, f"{steps} step(s), {len(p.edges)} line changes"]
    rows.append(f"At {rate_hz:g} steps/s: {steps / rate_hz:.3g} s per run" + (", looping until stopped" if loop else ""))
    best = max_rate_hz(p, limits)
    if best is not None:
        rows.append(f"Rough limit of this backend: about {best:.0f} steps/s (estimate; the measured rate shows while running)")
        if rate_hz > best:
            rows.append(f"WARNING: {rate_hz:g} steps/s is above that. It will run slower than asked.")
    rows += [f"- {n}" for n in p.notes]
    rows.append("")
    if p.spi_words is not None:
        for i, frame in enumerate(p.spi_words[:32]):
            rows.append(f"frame {i}: 0x{frame:08X}  (R{register_of(frame)})")
        if len(p.spi_words) > 32:
            rows.append(f"... first 32 of {len(p.spi_words)} words")
    else:
        rows += waveform(p)
    return "\n".join(rows)


# ---------------------------------------------------------------- session
class BenchSession:
    """One client's bench mode. Replies are the daemon's dicts; `ok` is False when it refused."""

    def __init__(self, request: Request, ask: Ask, weights_db: Sequence[float] = patterns.DEFAULT_WEIGHTS_DB,
                 active_high: bool = True) -> None:
        self.request = request
        self.ask = ask
        self.weights_db = tuple(weights_db)
        self.active_high = active_high
        self.expert = False
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.token: Optional[str] = None
        self.status: dict = {}
        self.limits: Optional[dict] = None
        self.warnings: List[str] = []
        self._confirmed: set = set()

    def _call(self, cmd: dict) -> dict:
        if self.token:
            cmd = dict(cmd, token=self.token)
        reply = self.request(cmd)
        return NO_REPLY if reply is None else reply

    def _confirmed_call(self, scope: str, cmd: dict) -> dict:
        """Send; when the daemon wants a confirm, ask the operator once per scope until bench mode closes."""
        if self.expert:
            cmd = dict(cmd, expert=True)
        if scope in self._confirmed:
            cmd = dict(cmd, confirm=True)
        reply = self._call(cmd)
        if reply.get("needs_confirm"):
            if not self.ask(reply["error"]):
                return {"ok": False, "error": "Cancelled", "cancelled": True}
            self._confirmed.add(scope)
            reply = self._call(dict(cmd, confirm=True))
        return reply

    # ---- mode
    def open(self, stop_sweep: Callable[[], bool]) -> dict:
        """Enter bench mode. A running sweep is only stopped when `stop_sweep` agrees."""
        reply = self._call({"cmd": "bench_open"})
        if reply.get("sweep_running"):
            if not stop_sweep():
                return {"ok": False, "error": "Cancelled: the sweep keeps running", "cancelled": True}
            reply = self._call({"cmd": "bench_open"})
        if reply.get("ok"):
            self.active = True
            self.token = reply["token"]
            self.limits = reply.get("limits")
            self.warnings = list(reply.get("warnings", ()))
            self.status = reply
        return reply

    def close(self) -> dict:
        if not self.active:
            return {"ok": True}
        reply = self._call({"cmd": "bench_close"})
        self.reset()
        return reply

    def poll(self) -> dict:
        """Renews the lease and refreshes the levels. Notices when the daemon closed the mode."""
        reply = self._call({"cmd": "bench_status"})
        if reply.get("ok") and not reply.get("owner"):
            self.reset()
            return {"ok": False, "closed": True, "error": f"Bench mode closed: {reply.get('closed_reason') or 'by sweepd'}"}
        if reply.get("ok"):
            self.status = reply
        return reply

    def level(self, pin_id: str) -> Tuple[Optional[int], Optional[str]]:
        """(level, direction) of a pin as last polled; (None, None) when not open."""
        entry = self.status.get("pins", {}).get(pin_id) if self.active else None
        return (entry["level"], entry["dir"]) if entry else (None, None)

    # ---- pins
    def drive(self, pin_id: str, value: int) -> dict:
        return self._confirmed_call(pin_id, {"cmd": "bench_pin", "pin": pin_id, "action": "write", "value": value})

    def read_pin(self, pin_id: str) -> dict:
        cmd = {"cmd": "bench_pin", "pin": pin_id, "action": "read"}
        return self._call(dict(cmd, expert=True) if self.expert else cmd)

    def release(self, pin_id: str) -> dict:
        cmd = {"cmd": "bench_pin", "pin": pin_id, "action": "input"}
        return self._call(dict(cmd, expert=True) if self.expert else cmd)

    def to_bus(self, pin_id: str) -> dict:
        return self._call({"cmd": "bench_pin", "pin": pin_id, "action": "bus"})

    # ---- raw access
    def set_db(self, db: float) -> dict:
        return self._confirmed_call("PE4302", {"cmd": "bench_atten", "db": db})

    def set_levels(self, levels: Sequence[int], raw: bool) -> dict:
        return self._confirmed_call("PE4302", {"cmd": "bench_atten", "levels": list(levels), "raw": raw})

    def send_words(self, words: Sequence[int]) -> dict:
        return self._confirmed_call("ADF4351", {"cmd": "bench_spi", "words": list(words)})

    def set_rf(self, main: bool, aux: bool, power_dbm: int) -> dict:
        cmd = {"cmd": "bench_rf", "main": main, "aux": aux, "power_dbm": power_dbm}
        reply = self._call(cmd)                     # always asks: never remembered
        if reply.get("needs_confirm") and self.ask(reply["error"]):
            reply = self._call(dict(cmd, confirm=True))
        elif reply.get("needs_confirm"):
            return {"ok": False, "error": "Cancelled", "cancelled": True}
        return reply

    def read_ads1115(self, channel: int, single: bool = True) -> dict:
        return self._call({"cmd": "bench_adc", "source": "ads1115", "channel": channel,
                           "read": "single" if single else "regs"})

    def read_ain(self, channel: int = 0, n: int = 1) -> dict:
        return self._call({"cmd": "bench_adc", "source": "ain", "channel": channel, "n": n})

    # ---- patterns
    def build_pattern(self, spec: dict) -> patterns.Pattern:
        return patterns.from_spec(spec, pinmap.ATT_NETS, self.weights_db, self.active_high)

    def start_pattern(self, spec: dict, rate_hz: float, loop: bool) -> dict:
        scope = "pattern:" + str(sorted(self.build_pattern(spec).idle))
        return self._confirmed_call(scope, {"cmd": "bench_pattern", "action": "start", "spec": spec,
                                            "rate_hz": rate_hz, "loop": loop})

    def stop_pattern(self) -> dict:
        return self._call({"cmd": "bench_pattern", "action": "stop"})


# ---------------------------------------------------------------- board drawing
# Fill colour per pin category, same family as the palette of tools/gen_diagrams.py.
CATEGORY_COLOURS: Dict[str, str] = {
    "spi": "#1971c2", "pe4302": "#2b8a3e", "lock": "#e67700", "synth": "#b08900", "adc": "#9c36b5", "i2c": "#0b7285",
    "gnd": "#495057", "power": "#e8590c", "reserved": "#adb5bd", "free": "#e9ecef",
}
CATEGORY_LABELS: Tuple[Tuple[str, str], ...] = (
    ("spi", "SPI"), ("pe4302", "PE4302"), ("lock", "Lock detect"), ("synth", "ADF4351 CE"), ("i2c", "I2C (ADS1115)"),
    ("adc", "ADC input"), ("power", "Power"), ("gnd", "Ground"), ("reserved", "eMMC / HDMI / reserved"), ("free", "Free"),
)

ROWS = 23
PIN_W, PIN_H, ROW_H = 27.0, 19.0, 23.0
HEADER_TOP = 58.0
Rect = Tuple[float, float, float, float]   # x, y, width, height


def pin_rect(pin: pinmap.Pin) -> Rect:
    """P8 left, P9 right, pin 1 at the top, odd pins in the left column: as in hw/diagrams/bbb-p*-pinout."""
    x0 = 280.0 if pin.header == "P8" else 470.0
    x = x0 + (0 if pin.number % 2 else PIN_W + 3)
    return (x, HEADER_TOP + (pin.number - 1) // 2 * ROW_H, PIN_W, PIN_H)


@dataclass(frozen=True)
class BlockRow:
    net: str
    pin_id: str
    rect: Rect
    anchor: Tuple[float, float]       # where the wire ends


@dataclass(frozen=True)
class Block:
    board: pinmap.BoardBlock
    rect: Rect
    rows: Tuple[BlockRow, ...]


@dataclass(frozen=True)
class Wire:
    net: str
    pin_id: str
    points: Tuple[Tuple[float, float], ...]     # polyline from the pin, the last two segments are a curve


CANVAS_W, CANVAS_H = 930.0, 640.0
_BLOCK_ROW_H = 22.0
_BLOCK_HEAD = 40.0
_STRAP_H = 14.0


def _block(board: pinmap.BoardBlock, x: float, y: float, w: float, anchor_right: bool) -> Block:
    rows = []
    for i, net in enumerate(board.nets):
        ry = y + _BLOCK_HEAD + i * _BLOCK_ROW_H
        anchor = (x + w, ry + _BLOCK_ROW_H / 2) if anchor_right else (x, ry + _BLOCK_ROW_H / 2)
        rows.append(BlockRow(net, pinmap.BY_NET[net].id, (x + 2, ry, w - 4, _BLOCK_ROW_H), anchor))
    h = _BLOCK_HEAD + len(board.nets) * _BLOCK_ROW_H + 6 + len(board.straps) * _STRAP_H + 4
    return Block(board, (x, y, w, h), tuple(rows))


def blocks() -> Tuple[Block, ...]:
    """PE4302 left of P8 (its lines are on P8), ADF4351, ADS1115 and AIN0 right of P9."""
    by = {b.title: b for b in pinmap.BOARDS}
    return (
        _block(by["PE4302"], 8, 60, 186, True),
        _block(by["ADF4351"], 680, 60, 242, False),
        _block(by["ADS1115"], 680, 285, 242, False),
        _block(by["AIN0"], 680, 410, 242, False),
    )


def wire_for(pin: pinmap.Pin, anchor: Tuple[float, float]) -> Wire:
    """A pin leaves toward its board. A pin in the inner column runs in the gap under its neighbour, so
    the wire can not be mistaken for the neighbour's."""
    x, y, w, h = pin_rect(pin)
    mid = y + h / 2
    gap = y + h + (ROW_H - h) / 2
    going_right = anchor[0] > x
    inner = (pin.number % 2 == 1) if going_right else (pin.number % 2 == 0)
    start_x = x + w if going_right else x
    neighbour_end = start_x + (PIN_W + 3 + 4) * (1 if going_right else -1)
    pts = [(start_x, mid)]
    if inner:
        pts.append((neighbour_end, gap))
    else:
        pts.append((neighbour_end, mid))
    return Wire(pin.net, pin.id, tuple(pts) + (anchor,))


def wires() -> Tuple[Wire, ...]:
    out = []
    for block in blocks():
        for row in block.rows:
            out.append(wire_for(pinmap.PINS[row.pin_id], row.anchor))
    return tuple(out)


def _inside(rect: Rect, x: float, y: float) -> bool:
    return rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]


def hit_test(x: float, y: float) -> Optional[str]:
    """The pin id under a canvas position: a header pin, or a net row on a board block."""
    for pin in pinmap.PINS.values():
        if _inside(pin_rect(pin), x, y):
            return pin.id
    for block in blocks():
        for row in block.rows:
            if _inside(row.rect, x, y):
                return row.pin_id
    return None
