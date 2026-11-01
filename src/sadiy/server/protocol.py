"""Wire format. A sweep frame is two ZeroMQ parts: a JSON header and float32 power data (dBm).

Commands (REQ/REP, JSON):
  {"cmd": "set", "start_hz":..., "stop_hz":..., "points":..., "atten_db":..., "auto_atten":true|false}
  {"cmd": "run"} | {"cmd": "stop"} | {"cmd": "status"}
"""
from __future__ import annotations

import json
import time
from typing import List, Tuple

import numpy as np

VERSION = 1
TOPIC = b"sweep"


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
