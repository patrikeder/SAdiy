"""ZeroMQ client for `sweepd` used by the GUI: newest-frame polling and short-timeout commands.

Never blocks the GUI for long: a command that gets no reply within the timeout returns None and
the REQ socket is rebuilt (the REQ state machine would otherwise be stuck waiting for the reply).
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

import numpy as np
import zmq

from ..logs import LogEntry
from ..server import protocol


class AsyncRequest:
    """One command whose reply takes seconds (the ramp self-test waits for the sweep in progress, then runs). It has its own
    REQ socket, so the GUI's normal commands keep working, and is polled from the GUI timer: nothing blocks."""

    def __init__(self, ctx, url: str, cmd: dict, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._deadline = clock() + timeout_s
        self._sock: Optional[zmq.Socket] = ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.SNDTIMEO, 100)
        self._sock.connect(url)
        try:
            self._sock.send_json(cmd)
        except zmq.ZMQError:
            self.close()

    def poll(self) -> Tuple[bool, Optional[dict]]:
        """(finished, reply). The reply is None when the daemon did not answer in time (or the send failed)."""
        if self._sock is None:
            return True, None
        try:
            if self._sock.poll(0):
                reply = self._sock.recv_json()
                self.close()
                return True, reply
        except zmq.ZMQError:
            self.close()
            return True, None
        if self._clock() >= self._deadline:
            self.close()
            return True, None
        return False, None

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close(linger=0)
            self._sock = None


class SweepClient:
    def __init__(self) -> None:
        self._ctx = zmq.Context.instance()
        self._sub: Optional[zmq.Socket] = None
        self._req: Optional[zmq.Socket] = None
        self._rep_url = ""
        self.bad_frames = 0
        self.last_flags: Optional[np.ndarray] = None    # per-point flags of the frame `poll_latest` returned last
        self.last_ideal: Optional[np.ndarray] = None    # expected trace of that frame (virtual spectrum), else None
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
            header, p, self.last_flags, self.last_ideal = protocol.decode_frame_all(latest)
            return header, p
        except ValueError:
            self.bad_frames += 1
            return None

    def take_logs(self) -> List[LogEntry]:
        """Live log records received since the last call (filled by `poll_latest`)."""
        out, self._logs = self._logs, []
        return out

    @staticmethod
    def log_command(since: int = 0) -> dict:
        return {"cmd": "log", "since": int(since), "level": "debug"}

    @staticmethod
    def parse_log_reply(r: Optional[dict]) -> Optional[Tuple[List[LogEntry], str, int]]:
        """(entries, boot, last_seq) from a `log` reply, or None when there is no usable reply."""
        if not r or not r.get("ok"):
            return None
        try:
            return [LogEntry.from_dict(d) for d in r["entries"]], str(r.get("boot", "")), int(r["last_seq"])
        except (KeyError, TypeError, ValueError):
            return None

    def fetch_log(self, since: int = 0, timeout_ms: int = 500) -> Optional[Tuple[List[LogEntry], str, int]]:
        """Ask the daemon for the records it kept after `since`: (entries, boot, last_seq), or None when
        it does not answer (or is an older sweepd without the `log` command). Blocks up to `timeout_ms`; the GUI
        uses `log_command` with `request_async` instead, because a sweepd on the PL engine answers only between sweeps."""
        return self.parse_log_reply(self.request(self.log_command(since), timeout_ms))

    def request_async(self, cmd: dict, timeout_ms: int) -> Optional[AsyncRequest]:
        """Start a command that may take long; None when not connected. Poll the returned object."""
        if self._req is None:
            return None
        return AsyncRequest(self._ctx, self._rep_url, cmd, timeout_ms / 1000.0)

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
