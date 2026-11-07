"""Logging for `sweepd` and its clients: levels, a ring buffer the GUI can fetch, repeat folding.

No dependencies beyond the standard library, so the daemon, the GUI and the tests share it.

Levels: TRACE (per point, per SPI word; ssh only), DEBUG, INFO, WARNING, ERROR.

- `setup()` points the `sadiy` logger at stderr (journald under systemd, so `journalctl -u sweepd -f`
  over ssh is the low-level debug path) and at a `RingLog` that keeps the last records, numbered, for
  clients. The ring never takes TRACE, so a client can not ask for the firehose.
- Identical records in a row are folded into one, followed by "repeated N more times", so a fault that
  recurs on every point or every sweep fills neither the ring nor the network.
- Nothing here blocks or raises into the caller: a listener that fails is dropped from that record.

Modules log with `logging.getLogger(__name__)`; their names start with `sadiy.` and land here. A module
that is also run as `python -m` has the name `__main__` then, so it names its logger explicitly.
"""
from __future__ import annotations

import logging
import secrets
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

LEVELS = {"trace": TRACE, "debug": logging.DEBUG, "info": logging.INFO,
          "warning": logging.WARNING, "error": logging.ERROR}
RING_MIN_LEVEL = logging.DEBUG           # the ring (and so the GUI) never sees TRACE
LOGGER_NAME = "sadiy"


def parse_level(level) -> int:
    """'info', 'WARN', 20 -> the numeric level. ValueError for anything else."""
    if isinstance(level, int):
        return level
    key = str(level).strip().lower()
    if key == "warn":
        key = "warning"
    if key not in LEVELS:
        raise ValueError(f"unknown log level {level!r}; use one of {', '.join(LEVELS)}")
    return LEVELS[key]


def level_name(level: int) -> str:
    return logging.getLevelName(level)


def level_from_verbosity(verbose: int = 0, quiet: int = 0, default: str = "info") -> int:
    """-v is debug, -vv is trace, -q is warning, -qq is error."""
    order = ["error", "warning", "info", "debug", "trace"]
    i = order.index(default) + verbose - quiet
    return LEVELS[order[min(max(i, 0), len(order) - 1)]]


@dataclass(frozen=True)
class LogEntry:
    seq: int
    t: float
    level: int
    name: str
    msg: str
    repeats: int = 0          # > 0: this record stands for `repeats` suppressed copies of `msg`
    boot: str = ""            # which run of the daemon numbered it: `seq` starts again at 1 after a restart

    def to_dict(self) -> dict:
        return {"seq": self.seq, "t": self.t, "level": self.level, "name": self.name,
                "msg": self.msg, "repeats": self.repeats, "boot": self.boot}

    @classmethod
    def from_dict(cls, d: dict) -> "LogEntry":
        return cls(int(d["seq"]), float(d["t"]), int(d["level"]), str(d["name"]), str(d["msg"]),
                   int(d.get("repeats", 0)), str(d.get("boot", "")))


def format_entry(e: LogEntry, with_date: bool = False) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S", time.localtime(e.t))
    name = e.name[len(LOGGER_NAME) + 1:] if e.name.startswith(LOGGER_NAME + ".") else e.name
    text = f"{e.msg} (repeated {e.repeats} more times)" if e.repeats else e.msg
    return f"{stamp} {level_name(e.level):<7} {name}: {text}"


class RingLog:
    """Numbered records, at most `capacity` kept (routine lines are dropped before warnings). Thread safe."""

    def __init__(self, capacity: int = 500, dedup_s: float = 5.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.dedup_s = dedup_s
        self.boot = secrets.token_hex(4)
        self._clock = clock
        self._lock = threading.Lock()
        self._capacity = max(1, int(capacity))
        self._ring: Deque[LogEntry] = deque()
        self._seq = 0
        self._listeners: List[Callable[[LogEntry], None]] = []
        self._key: Optional[tuple] = None      # (level, name, msg) of the last record emitted
        self._key_t = 0.0                      # when it was emitted
        self._folded = 0                       # copies suppressed since

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def add_listener(self, fn: Callable[[LogEntry], None]) -> None:
        self._listeners.append(fn)

    def entries(self, since_seq: int = 0, min_level: int = 0, limit: Optional[int] = None) -> List[LogEntry]:
        """Records newer than `since_seq` at or above `min_level`, oldest first; the newest `limit`."""
        with self._lock:
            out = [e for e in self._ring if e.seq > since_seq and e.level >= min_level]
        return out[-limit:] if limit else out

    def log(self, level: int, name: str, msg: str) -> None:
        if level < RING_MIN_LEVEL:
            return
        now = self._clock()
        new: List[LogEntry] = []
        with self._lock:
            key = (level, name, msg)
            if key == self._key and now - self._key_t < self.dedup_s:
                self._folded += 1
                return
            self._fold_into(new, now)
            new.append(self._append(now, level, name, msg))
            self._key, self._key_t = key, now
        self._notify(new)

    def flush(self) -> None:
        """Called from the daemon loop: closes a folded run once its window has passed."""
        new: List[LogEntry] = []
        with self._lock:
            if self._folded and self._clock() - self._key_t >= self.dedup_s:
                self._fold_into(new, self._clock())
        self._notify(new)

    def _fold_into(self, new: List[LogEntry], now: float) -> None:
        if self._folded and self._key is not None:
            level, name, msg = self._key
            new.append(self._append(now, level, name, msg, repeats=self._folded))
        self._folded = 0
        self._key = None

    def _append(self, now: float, level: int, name: str, msg: str, repeats: int = 0) -> LogEntry:
        self._seq += 1
        entry = LogEntry(self._seq, now, level, name, msg, repeats, self.boot)
        if len(self._ring) >= self._capacity:
            # Full: drop the oldest INFO / DEBUG record first, so a flood of routine lines can not
            # push warnings and errors out. Only when there are none left does the oldest go.
            for i, old in enumerate(self._ring):
                if old.level < logging.WARNING:
                    del self._ring[i]
                    break
            else:
                self._ring.popleft()
        self._ring.append(entry)
        return entry

    def _notify(self, new: List[LogEntry]) -> None:
        for entry in new:
            for fn in list(self._listeners):
                try:
                    fn(entry)
                except Exception:       # a broken listener must never reach the sweep loop
                    pass


class RingHandler(logging.Handler):
    """Feeds `logging` records into a RingLog. One line per record: an exception adds its type and
    text, the full traceback goes to the other handlers (stderr, journald)."""

    def __init__(self, ring: RingLog) -> None:
        super().__init__(level=RING_MIN_LEVEL)
        self.ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                msg += f" ({type(exc).__name__}: {exc})"
            self.ring.log(record.levelno, record.name, msg)
        except Exception:
            self.handleError(record)


_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level="info", stream=None, ring: Optional[RingLog] = None, capacity: int = 500) -> RingLog:
    """Route the `sadiy` logger to `stream` (stderr) at `level` and into a RingLog. Safe to call twice:
    handlers from an earlier call are replaced."""
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        if getattr(h, "_sadiy", False):
            logger.removeHandler(h)
    ring = ring if ring is not None else RingLog(capacity)
    stderr_level = parse_level(level)
    out = logging.StreamHandler(stream if stream is not None else sys.stderr)
    out.setLevel(stderr_level)
    out.setFormatter(logging.Formatter(_FORMAT))
    ring_handler = RingHandler(ring)
    for h in (out, ring_handler):
        h._sadiy = True                     # type: ignore[attr-defined]
        logger.addHandler(h)
    logger.setLevel(min(stderr_level, RING_MIN_LEVEL))
    logger.propagate = False
    return ring
