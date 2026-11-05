"""Wire format. A sweep frame is two ZeroMQ parts: a JSON header and float32 power data (dBm).

Commands (REQ/REP, JSON):
  {"cmd": "set", "start_hz":..., "stop_hz":..., "points":..., "atten_db":..., "auto_atten":true|false}
  {"cmd": "run"} | {"cmd": "stop"} | {"cmd": "status"}

Bench commands (see `server/bench.py`, refused while a sweep runs; `run` is refused while bench mode is
open). `bench_open` returns a token that every other command must carry, and each command renews a short
lease. `confirm` and `expert` are how the client says the operator agreed; without `confirm` a command
that drives a line wired to a board input gets {"ok": false, "needs_confirm": true, "error": ...}.
  {"cmd": "bench_open"} | {"cmd": "bench_close", "token":...} | {"cmd": "bench_status", "token":...}
  {"cmd": "bench_pin", "pin": "P8.7", "action": "read" | "input" | "bus" | "write", "value": 0|1, "confirm":..., "expert":...}
  {"cmd": "bench_atten", "db": 10.0 | "levels": [v1..v6], "raw": false, "confirm":...}
  {"cmd": "bench_spi", "word": n | "words": [n, ...], "confirm":...}
  {"cmd": "bench_rf", "main": bool, "aux": bool, "power_dbm": -4, "confirm":...}
  {"cmd": "bench_adc", "source": "ads1115", "channel": 0, "read": "single" | "regs"}
  {"cmd": "bench_adc", "source": "ain", "channel": 0, "n": 1}
  {"cmd": "bench_pattern", "action": "start", "spec": {...}, "rate_hz": 100, "loop": false, "confirm":..., "expert":...}
  {"cmd": "bench_pattern", "action": "stop"}
The pattern spec is documented in `patterns.from_spec`.
"""
from __future__ import annotations

import json
import time
from typing import List, Tuple

import numpy as np

VERSION = 1
TOPIC = b"sweep"
BENCH_PREFIX = "bench_"


def encode_frame(seq: int, f_start_hz: float, f_step_hz: float, atten_db: float, p_dbm) -> List[bytes]:
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
    return [TOPIC, json.dumps(header).encode(), p.tobytes()]


def decode_frame(parts) -> Tuple[dict, np.ndarray]:
    if parts[0] != TOPIC:
        raise ValueError("not a sweep frame")
    header = json.loads(parts[1])
    if header.get("v") != VERSION:
        raise ValueError(f"unsupported protocol version {header.get('v')}")
    p = np.frombuffer(parts[2], dtype="<f4")
    if p.size != header["n"]:
        raise ValueError("payload length does not match header")
    return header, p
