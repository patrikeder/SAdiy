"""Qt-free state of the Device log box in the GUI: what the daemon said, in order, without gaps.

Records reach the GUI two ways: live on the PUB socket (can be lost, or missed before connecting) and
by the `log` command (everything the daemon still keeps). `LogBuffer` takes both and keeps one
numbered, duplicate-free list. A live record that skips a number sets `gap`; the GUI then fetches
from `last_seq` and feeds the answer to `add_fetched`. A different `boot` means the daemon restarted:
a marker line is added and numbering starts over.
"""
from __future__ import annotations

import html
import logging
import time
from collections import deque
from typing import Deque, Iterable, List, Optional

from ..logs import LogEntry, format_entry

LOCAL_NAME = "gui"          # entries the GUI makes itself (connection events) use this name

# Choices in the level box: label, minimum level shown.
LEVEL_CHOICES = (("Error", logging.ERROR), ("Warning", logging.WARNING),
                 ("Info", logging.INFO), ("Debug", logging.DEBUG))
DEFAULT_LEVEL = logging.INFO

# Readable on a light and on a dark background; routine lines keep the theme's own text colour.
LEVEL_COLORS = {logging.ERROR: "#e05050", logging.WARNING: "#d08a00", logging.DEBUG: "#8a8a8a"}


class LogBuffer:
    def __init__(self, max_lines: int = 2000) -> None:
        self.entries: Deque[LogEntry] = deque(maxlen=max(1, int(max_lines)))
        self.last_seq = 0
        self.boot: Optional[str] = None
        self.gap = True                   # nothing known yet: fetch before trusting the live feed
        self.unseen_warnings = 0
        self.unseen_errors = 0

    # ------------------------------------------------------------ input

    def add_live(self, entries: Iterable[LogEntry]) -> List[LogEntry]:
        """Records from the PUB socket. Returns those added. Stops at a gap and sets `gap`."""
        added: List[LogEntry] = []
        for e in entries:
            if self.gap:
                break                     # wait for the fetch: it will contain this record too
            self._check_boot(e, added)
            if e.seq <= self.last_seq:
                continue                  # already have it (the fetch and the live feed overlap)
            if e.seq != self.last_seq + 1:
                self.gap = True
                break
            self._append(e, added)
        return added

    def add_fetched(self, entries: Iterable[LogEntry], boot: Optional[str] = None,
                    last_seq: Optional[int] = None) -> List[LogEntry]:
        """The answer to the `log` command (pass its `boot` and `last_seq` too, they matter when it has no
        entries). Accepts a start that is not contiguous: the daemon's ring may have dropped older
        records, which is a loss, not a gap to chase."""
        added: List[LogEntry] = []
        if boot is not None:
            self._check_boot_id(boot, added)
        for e in entries:
            self._check_boot_id(e.boot, added)
            if e.seq > self.last_seq:
                self._append(e, added)
        if last_seq is not None:
            self.last_seq = max(self.last_seq, last_seq)
        self.gap = False
        return added

    def note(self, level: int, msg: str) -> LogEntry:
        """A line from the GUI itself (connected, connection lost, ...). Not numbered by the daemon."""
        e = LogEntry(0, time.time(), level, LOCAL_NAME, msg)
        self.entries.append(e)
        self._count(e)
        return e

    def _check_boot(self, e: LogEntry, added: List[LogEntry]) -> None:
        self._check_boot_id(e.boot, added)

    def _check_boot_id(self, boot: str, added: List[LogEntry]) -> None:
        if self.boot is None:
            self.boot = boot
        elif boot != self.boot:
            self.boot = boot
            self.last_seq = 0
            added.append(self.note(logging.WARNING, "sweepd restarted: its numbering starts again"))

    def _append(self, e: LogEntry, added: List[LogEntry]) -> None:
        self.entries.append(e)
        self.last_seq = e.seq
        added.append(e)
        self._count(e)

    def _count(self, e: LogEntry) -> None:
        if e.repeats:
            return                        # the first copy was counted already
        if e.level >= logging.ERROR:
            self.unseen_errors += 1
        elif e.level >= logging.WARNING:
            self.unseen_warnings += 1

    # ------------------------------------------------------------ output

    def visible(self, min_level: int = DEFAULT_LEVEL) -> List[LogEntry]:
        return [e for e in self.entries if e.level >= min_level]

    def text(self, min_level: int = DEFAULT_LEVEL) -> str:
        return "\n".join(format_entry(e) for e in self.visible(min_level))

    def mark_seen(self) -> None:
        self.unseen_warnings = self.unseen_errors = 0

    def clear(self) -> None:
        """Empties the list. The sequence state stays, so nothing already shown comes back."""
        self.entries.clear()
        self.mark_seen()

    @property
    def badge(self) -> str:
        """For the tab title: '' when nothing is unseen, else e.g. ' (2 errors, 1 warning)'."""
        parts = []
        if self.unseen_errors:
            parts.append(f"{self.unseen_errors} error{'s' if self.unseen_errors != 1 else ''}")
        if self.unseen_warnings:
            parts.append(f"{self.unseen_warnings} warning{'s' if self.unseen_warnings != 1 else ''}")
        return f" ({', '.join(parts)})" if parts else ""


def entry_html(e: LogEntry) -> str:
    """One line for a rich-text box, coloured by level."""
    text = html.escape(format_entry(e))
    if e.level >= logging.ERROR:
        color = LEVEL_COLORS[logging.ERROR]
    elif e.level >= logging.WARNING:
        color = LEVEL_COLORS[logging.WARNING]
    elif e.level <= logging.DEBUG:
        color = LEVEL_COLORS[logging.DEBUG]
    else:
        color = None
    body = f'<span style="color:{color}">{text}</span>' if color else text
    return f'<span style="white-space:pre">{body}</span>'
