"""ZeroMQ client for `sweepd` used by the GUI: newest-frame polling and short-timeout commands.

Never blocks the GUI for long: a command that gets no reply within the timeout returns None and
the REQ socket is rebuilt (the REQ state machine would otherwise be stuck waiting for the reply).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import zmq

from ..logs import LogEntry
from ..server import protocol


class SweepClient:
    def __init__(self) -> None:
        self._ctx = zmq.Context.instance()
        self._sub: Optional[zmq.Socket] = None
        self._req: Optional[zmq.Socket] = None
        self._rep_url = ""
        self.bad_frames = 0
        self.last_flags: Optional[np.ndarray] = None    # per-point flags of the frame `poll_latest` returned last
        self._logs: List[LogEntry] = []

    @property
    def connected(self) -> bool:
        return self._sub is not None

    def connect(self, host: str, pub_port: int, rep_port: int) -> None:
        self.disconnect()
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.LINGER, 0)
        self._sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)
        self._sub.setsockopt(zmq.SUBSCRIBE, protocol.LOG_TOPIC)
        self._sub.connect(f"tcp://{host}:{pub_port}")
        self._rep_url = f"tcp://{host}:{rep_port}"
        self._open_req()

    def disconnect(self) -> None:
        for sock in (self._sub, self._req):
            if sock is not None:
                sock.close(linger=0)
        self._sub = self._req = None
        self._logs = []

    def _open_req(self) -> None:
        if self._req is not None:
            self._req.close(linger=0)
        self._req = self._ctx.socket(zmq.REQ)
        self._req.setsockopt(zmq.LINGER, 0)
        self._req.setsockopt(zmq.SNDTIMEO, 100)
        self._req.connect(self._rep_url)

    def poll_latest(self) -> Optional[Tuple[dict, np.ndarray]]:
        """Drain the queue and decode only the newest frame (a slow GUI must not fall behind).
        Log records in the queue are decoded all, in order, and kept for `take_logs`."""
        if self._sub is None:
            return None
        latest = None
        while self._sub.poll(0):
            parts = self._sub.recv_multipart()
            if parts and parts[0] == protocol.LOG_TOPIC:
                try:
                    self._logs.append(protocol.decode_log(parts))
                except ValueError:
                    self.bad_frames += 1
            else:
                latest = parts
        if latest is None:
            return None
        try:
            header, p, self.last_flags = protocol.decode_frame_flags(latest)
            return header, p
        except ValueError:
            self.bad_frames += 1
            return None

    def take_logs(self) -> List[LogEntry]:
        """Live log records received since the last call (filled by `poll_latest`)."""
        out, self._logs = self._logs, []
        return out

    def fetch_log(self, since: int = 0, timeout_ms: int = 500) -> Optional[Tuple[List[LogEntry], str, int]]:
        """Ask the daemon for the records it kept after `since`: (entries, boot, last_seq), or None when
        it does not answer (or is an older sweepd without the `log` command)."""
        r = self.request({"cmd": "log", "since": int(since), "level": "debug"}, timeout_ms)
        if not r or not r.get("ok"):
            return None
        try:
            return [LogEntry.from_dict(d) for d in r["entries"]], str(r.get("boot", "")), int(r["last_seq"])
        except (KeyError, TypeError, ValueError):
            return None

    def request(self, cmd: dict, timeout_ms: int = 500) -> Optional[dict]:
        """Send one command; the reply dict, or None on timeout / not connected."""
        if self._req is None:
            return None
        try:
            self._req.send_json(cmd)
            if self._req.poll(timeout_ms):
                return self._req.recv_json()
        except zmq.ZMQError:
            pass
        self._open_req()
        return None
