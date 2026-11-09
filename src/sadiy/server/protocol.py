"""Wire format. A sweep frame is a topic, a JSON header and float32 power data (dBm), and optionally a
fourth part with one flag byte per point (bits in `core.sweep`: unlocked, overload, at floor, outlier
rejected, image not suppressed; header["flags"] is true then). The fourth part is additive, so readers that know nothing of
it keep working and `VERSION` stays 1.

Commands (REQ/REP, JSON):
  {"cmd": "set", "start_hz":..., "stop_hz":..., "points":..., "atten_db":..., "auto_atten":true|false,
           "averages":..., "image_reject": true|false}   (image_reject: two sweeps per trace, see core/sweep.py)
  {"cmd": "run"} | {"cmd": "stop"} | {"cmd": "status"}
      status also has "lo" (if_hz, injection, pfd_hz, mod_max: what the LO presets are derived from) and "synth",
      the ADF4351 readback: while bench mode is open the words written in this session decoded (f_out_hz, f_vco_hz,
      rf_div, int_n, frac, mod, mode, prescaler, main / aux, words per register) plus the live lock detect "ld"
      (source "bench"); while sweeping the LO of the last point tuned (source "sweep"); else null. The chip can
      not be read over SPI on this wiring, so this is what it was told. `bench_status` carries the same "synth".
  {"cmd": "log", "since": seq, "level": "debug" | 10, "limit": n}
      -> {"ok": true, "entries": [{seq, t, level, name, msg, repeats, boot}, ...], "last_seq": n, "boot": id}
      Records the daemon kept, newer than `since`. A client calls it on connect and when it sees a gap in
      the live log records (PUB topic "log", one JSON part each, same fields), see `sadiy.logs`. `boot` names
      one run of the daemon: `seq` starts again at 1 after a restart, and `boot` changes.

Bench commands (see `server/bench.py`, refused while a sweep runs; `run` is refused while bench mode is
open). `bench_open` returns a token that every other command must carry, and each command renews a short
lease. `confirm` and `expert` are how the client says the operator agreed; without `confirm` a command
that drives a line wired to a board input gets {"ok": false, "needs_confirm": true, "error": ...}.
  {"cmd": "bench_open"} | {"cmd": "bench_close", "token":...} | {"cmd": "bench_status", "token":...}
  {"cmd": "bench_pin", "pin": "P8.7", "action": "read" | "input" | "bus" | "write", "value": 0|1, "confirm":..., "expert":...}
  {"cmd": "bench_atten", "db": 10.0 | "levels": [v1..v6], "raw": false, "confirm":...}
  {"cmd": "bench_spi", "word": n | "words": [n, ...], "confirm":...}
  {"cmd": "bench_rf", "main": bool, "aux": bool, "power_dbm": -4, "confirm":...}
  {"cmd": "bench_synth", "f_hz": 110.7e6, "power_dbm": -4, "main": bool, "aux": bool, "confirm":..., "confirm_rf":...}
      Program the PLL for one LO frequency: plan, outputs off, R5..R0, wait up to 0.2 s for lock detect, then the
      output only if asked and locked. `confirm` is for driving the SPI lines, `confirm_rf` for turning an output
      on; a missing one gives {"needs_confirm": true, "confirm_kind": "pins" | "rf"} before anything is written.
      Reply: ok, locked (true / false / null without LD), note, ld, f_target_hz, f_actual_hz, sent, rf, synth.
  {"cmd": "bench_adc", "source": "ads1115", "channel": 0, "read": "single" | "regs"}
  {"cmd": "bench_adc", "source": "ain", "channel": 0, "n": 1}
  {"cmd": "bench_pattern", "action": "start", "spec": {...}, "rate_hz": 100, "loop": false, "confirm":..., "expert":...}
  {"cmd": "bench_pattern", "action": "stop"}
The pattern spec is documented in `patterns.from_spec`.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional, Tuple

import numpy as np

from ..logs import LogEntry

VERSION = 1
TOPIC = b"sweep"
LOG_TOPIC = b"log"
BENCH_PREFIX = "bench_"


def encode_frame(seq: int, f_start_hz: float, f_step_hz: float, atten_db: float, p_dbm, flags=None,
                 image_reject: bool = False) -> List[bytes]:
    p = np.asarray(p_dbm, dtype="<f4")
    header = {
        "v": VERSION,
        "seq": seq,
        "t": time.time(),
        "f_start_hz": f_start_hz,
        "f_step_hz": f_step_hz,
        "n": int(p.size),
        "atten_db": atten_db,
    }
    if image_reject:
        header["image_reject"] = True       # the points are the lower of two sweeps, one per LO side
    parts = [TOPIC, json.dumps(header).encode(), p.tobytes()]
    if flags is not None:
        f = np.asarray(flags, dtype=np.uint8)
        if f.size != p.size:
            raise ValueError("one flag per point is required")
        header["flags"] = True
        parts[1] = json.dumps(header).encode()
        parts.append(f.tobytes())
    return parts


def decode_frame(parts) -> Tuple[dict, np.ndarray]:
    header, p, _flags = decode_frame_flags(parts)
    return header, p


def decode_frame_flags(parts) -> Tuple[dict, np.ndarray, Optional[np.ndarray]]:
    """Like `decode_frame`, plus the per-point flags (None when the frame has none)."""
    if parts[0] != TOPIC:
        raise ValueError("not a sweep frame")
    header = json.loads(parts[1])
    if header.get("v") != VERSION:
        raise ValueError(f"unsupported protocol version {header.get('v')}")
    p = np.frombuffer(parts[2], dtype="<f4")
    if p.size != header["n"]:
        raise ValueError("payload length does not match header")
    flags = None
    if header.get("flags") and len(parts) > 3:
        flags = np.frombuffer(parts[3], dtype=np.uint8)
        if flags.size != header["n"]:
            raise ValueError("flag length does not match header")
    return header, p, flags


def encode_log(entry: LogEntry) -> List[bytes]:
    return [LOG_TOPIC, json.dumps(entry.to_dict()).encode()]


def decode_log(parts) -> LogEntry:
    if parts[0] != LOG_TOPIC:
        raise ValueError("not a log record")
    try:
        return LogEntry.from_dict(json.loads(parts[1]))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed log record: {exc}") from exc
