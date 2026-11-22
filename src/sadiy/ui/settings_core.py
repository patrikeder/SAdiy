"""The GUI's settings on disk (no Qt): what the operator set, saved by the program and loaded on demand.

Three kinds of file, all JSON with the same layout:

- `config/default.json` in the repository: the settings as delivered. The program never writes it; "Restore as delivered"
  reads it (the built-in values of `SaSettings` are the fallback when the file is missing).
- `default.json` in the user's settings folder: what the GUI loads at start and writes at exit (and on "Save as default").
  It also keeps the connection (host and ports) the GUI was used with.
- `settings/<name>.json` in the same folder: named settings the user saved and loads on demand. They hold the
  measurement setup only, never the connection, so loading one does not move the GUI to another sweepd.

The folder is `$SADIY_CONFIG_DIR`, else `$XDG_CONFIG_HOME/sadiy`, else `~/.config/sadiy`.

Layout (format 1; unknown keys are ignored so a newer file still loads):
    {"format": 1,
     "sweep": {"start_hz", "stop_hz", "points", "averages", "atten_db", "auto_atten", "image_reject"},
     "display": {"ref_dbm", "db_per_div", "trace_mode"},
     "connection": {"host", "pub_port", "rep_port"}}          # only in the user's default.json
A value that is missing keeps the as-delivered one; a value of the wrong type or out of range is reported in
`Loaded.notes` and replaced by the as-delivered value (frequencies, points and attenuation are clamped to `Limits`).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import sa_core as core

FORMAT = 1
TRACE_MODES = ("clear_write", "max_hold", "min_hold", "average", "view", "blank")
AS_DELIVERED_PATH = Path(__file__).resolve().parents[3] / "config" / "default.json"
DEFAULT_NAME = "default.json"
NAMES_DIR = "settings"
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-+()]{0,63}$")


class SettingsError(ValueError):
    """A settings file or a name that can not be used; the text says why, for the status bar."""


@dataclass
class Connection:
    host: str = "127.0.0.1"
    pub_port: int = 5556
    rep_port: int = 5557


@dataclass
class Loaded:
    """What a settings file says, checked: ready to put into the GUI."""

    settings: core.SaSettings
    trace_mode: str = "clear_write"
    connection: Optional[Connection] = None
    notes: List[str] = field(default_factory=list)


def to_dict(settings: core.SaSettings, trace_mode: str, connection: Optional[Connection] = None) -> dict:
    d = {
        "format": FORMAT,
        "sweep": {
            "start_hz": settings.start_hz,
            "stop_hz": settings.stop_hz,
            "points": int(settings.points),
            "averages": int(settings.averages),
            "atten_db": float(settings.atten_db),
            "auto_atten": bool(settings.auto_atten),
            "image_reject": bool(settings.image_reject),
        },
        "display": {"ref_dbm": float(settings.ref_dbm), "db_per_div": float(settings.db_per_div),
                    "trace_mode": trace_mode},
    }
    if connection is not None:
        d["connection"] = {"host": connection.host, "pub_port": int(connection.pub_port),
                           "rep_port": int(connection.rep_port)}
    return d


def _number(section: dict, key: str, notes: List[str], kind=float):
    """`section[key]` as a number, or None (with a note) when it is not one. A bool is not a number here."""
    if key not in section:
        return None
    v = section[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
        notes.append(f"{key}: {v!r} is not a number, as delivered kept")
        return None
    return kind(v)


def _flag(section: dict, key: str, notes: List[str]) -> Optional[bool]:
    if key not in section:
        return None
    if not isinstance(section[key], bool):
        notes.append(f"{key}: {section[key]!r} is not true or false, as delivered kept")
        return None
    return section[key]


def parse(d, limits: Optional[core.Limits] = None, base: Optional[core.SaSettings] = None) -> Loaded:
    """Check a settings document. `base` supplies the values the file does not mention (default: as delivered)."""
    if not isinstance(d, dict):
        raise SettingsError("not a settings file (the top level is not an object)")
    if d.get("format", FORMAT) != FORMAT:
        raise SettingsError(f"settings format {d.get('format')!r} is not supported (this program reads format {FORMAT})")
    lim = limits or core.Limits()
    s = core.SaSettings(**vars(base)) if base is not None else core.SaSettings()
    notes: List[str] = []
    sweep = d.get("sweep", {})
    disp = d.get("display", {})
    if not isinstance(sweep, dict) or not isinstance(disp, dict):
        raise SettingsError("not a settings file (sweep and display must be objects)")

    start, stop = _number(sweep, "start_hz", notes), _number(sweep, "stop_hz", notes)
    if start is not None or stop is not None:
        a, b = (s.start_hz if start is None else start), (s.stop_hz if stop is None else stop)
        s.set_start_stop(a, b, lim)
        if (s.start_hz, s.stop_hz) != (round(a, 0), round(b, 0)):
            notes.append(f"frequencies {a / 1e6:g} to {b / 1e6:g} MHz set to {s.start_hz / 1e6:g} to {s.stop_hz / 1e6:g} MHz "
                         "(outside the range or too narrow)")
    points = _number(sweep, "points", notes, int)
    if points is not None:
        s.set_points(points, lim)
        if s.points != points:
            notes.append(f"points {points} set to {s.points}")
    avg = _number(sweep, "averages", notes, int)
    if avg is not None:
        s.averages = min(max(avg, 1), 64)
        if s.averages != avg:
            notes.append(f"averages {avg} set to {s.averages}")
    att = _number(sweep, "atten_db", notes)
    if att is not None:
        s.atten_db = min(max(att, 0.0), lim.atten_max_db)
        if s.atten_db != att:
            notes.append(f"attenuation {att:g} dB set to {s.atten_db:g} dB")
    for key in ("auto_atten", "image_reject"):
        v = _flag(sweep, key, notes)
        if v is not None:
            setattr(s, key, v)

    ref = _number(disp, "ref_dbm", notes)
    if ref is not None:
        s.ref_dbm = min(max(ref, -150.0), 30.0)
        if s.ref_dbm != ref:
            notes.append(f"reference level {ref:g} dBm set to {s.ref_dbm:g} dBm")
    dpd = _number(disp, "db_per_div", notes)
    if dpd is not None:
        if dpd in core.DB_PER_DIV_CHOICES:
            s.db_per_div = dpd
        else:
            notes.append(f"db_per_div {dpd:g} is not one of {', '.join(f'{c:g}' for c in core.DB_PER_DIV_CHOICES)}, "
                         "as delivered kept")
    mode = disp.get("trace_mode", "clear_write")
    if mode not in TRACE_MODES:
        notes.append(f"trace_mode {mode!r} is not known, Clear / Write used")
        mode = "clear_write"

    conn = None
    c = d.get("connection")
    if isinstance(c, dict):
        conn = Connection()
        host = c.get("host")
        if isinstance(host, str) and host.strip():
            conn.host = host.strip()
        elif "host" in c:
            notes.append("connection host is empty or not text, 127.0.0.1 kept")
        for key in ("pub_port", "rep_port"):
            v = _number(c, key, notes, int)
            if v is not None and 1 <= v <= 65535:
                setattr(conn, key, v)
            elif v is not None:
                notes.append(f"{key} {v} is not a port, default kept")
    return Loaded(s, mode, conn, notes)


def as_delivered(limits: Optional[core.Limits] = None, path: Optional[Path] = None) -> Loaded:
    """The settings as delivered: `config/default.json`, or the built-in values when the file is missing or unusable."""
    p = AS_DELIVERED_PATH if path is None else Path(path)
    try:
        return parse(json.loads(p.read_text(encoding="utf-8")), limits, core.SaSettings())
    except (OSError, ValueError):
        return Loaded(core.SaSettings())


def config_dir() -> Path:
    env = os.environ.get("SADIY_CONFIG_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "sadiy"


def check_name(name: str) -> str:
    """A name for saved settings: letters, digits, space and `_ . - + ( )`, at most 64 characters, so it is a safe file name."""
    n = (name or "").strip()
    if n.lower().endswith(".json"):
        n = n[:-5].rstrip()
    if not _NAME_OK.match(n):
        raise SettingsError(f"{name!r} is not a usable name: letters, digits, space and _ . - + ( ) only, "
                            "starting with a letter or digit, at most 64 characters")
    return n


class Store:
    """The user's settings folder."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.dir = Path(directory) if directory is not None else config_dir()

    @classmethod
    def user(cls) -> "Store":
        return cls()

    @property
    def default_path(self) -> Path:
        return self.dir / DEFAULT_NAME

    def path_of(self, name: str) -> Path:
        return self.dir / NAMES_DIR / f"{check_name(name)}.json"

    @staticmethod
    def _write(path: Path, d: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)               # a crash while writing never leaves half a file
        except OSError as exc:
            raise SettingsError(f"could not write {path}: {exc}") from exc

    @staticmethod
    def _read(path: Path, limits: Optional[core.Limits]) -> Loaded:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SettingsError(f"could not read {path}: {exc}") from exc
        try:
            return parse(json.loads(text), limits)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"{path.name} is not valid JSON: {exc}") from exc

    def save_default(self, d: dict) -> Path:
        self._write(self.default_path, d)
        return self.default_path

    def load_default(self, limits: Optional[core.Limits] = None) -> Optional[Loaded]:
        """The user's default.json, or None when there is none yet (first start)."""
        return self._read(self.default_path, limits) if self.default_path.is_file() else None

    def save(self, name: str, d: dict) -> Path:
        d = {k: v for k, v in d.items() if k != "connection"}        # a named setup never carries the connection
        path = self.path_of(name)
        self._write(path, d)
        return path

    def load(self, name: str, limits: Optional[core.Limits] = None) -> Loaded:
        path = self.path_of(name)
        if not path.is_file():
            raise SettingsError(f"no saved settings called {check_name(name)!r}")
        loaded = self._read(path, limits)
        loaded.connection = None
        return loaded

    def names(self) -> List[str]:
        folder = self.dir / NAMES_DIR
        if not folder.is_dir():
            return []
        return sorted((p.stem for p in folder.glob("*.json") if _NAME_OK.match(p.stem)), key=str.lower)

    def delete(self, name: str) -> None:
        path = self.path_of(name)
        try:
            path.unlink()
        except FileNotFoundError:
            raise SettingsError(f"no saved settings called {check_name(name)!r}") from None
        except OSError as exc:
            raise SettingsError(f"could not delete {path}: {exc}") from exc
