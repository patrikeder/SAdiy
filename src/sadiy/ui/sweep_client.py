"""ZeroMQ client for `sweepd` used by the GUI: newest-frame polling and short-timeout commands.

Never blocks the GUI for long: a command that gets no reply within the timeout returns None and
the REQ socket is rebuilt (the REQ state machine would otherwise be stuck waiting for the reply).
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import zmq

from ..server import protocol


class SweepClient:
    def __init__(self) -> None:
        self._ctx = zmq.Context.instance()
        self._sub: Optional[zmq.Socket] = None
        self._req: Optional[zmq.Socket] = None
        self._rep_url = ""
        self.bad_frames = 0

    @property
    def connected(self) -> bool:
        return self._sub is not None

    def connect(self, host: str, pub_port: int, rep_port: int) -> None:
        self.disconnect()
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.LINGER, 0)
        self._sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)
        self._sub.connect(f"tcp://{host}:{pub_port}")
        self._rep_url = f"tcp://{host}:{rep_port}"
        self._open_req()

    def disconnect(self) -> None:
        for sock in (self._sub, self._req):
            if sock is not None:
                sock.close(linger=0)
        self._sub = self._req = None

    def _open_req(self) -> None:
        if self._req is not None:
            self._req.close(linger=0)
        self._req = self._ctx.socket(zmq.REQ)
        self._req.setsockopt(zmq.LINGER, 0)
        self._req.setsockopt(zmq.SNDTIMEO, 100)
        self._req.connect(self._rep_url)

    def poll_latest(self) -> Optional[Tuple[dict, np.ndarray]]:
        """Drain the queue and decode only the newest frame (a slow GUI must not fall behind)."""
        if self._sub is None:
            return None
        latest = None
        while self._sub.poll(0):
            latest = self._sub.recv_multipart()
        if latest is None:
            return None
        try:
            return protocol.decode_frame(latest)
        except ValueError:
            self.bad_frames += 1
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
