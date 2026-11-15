"""Register offsets and field positions, read straight from regmap.toml (the single source).

The file is found without any setting in the two layouts that exist:
  repository / `deploy_to_board.sh`: `<zynq-ebaz>/rtl/regmap/regmap.toml` (two levels above this package),
  bring-up package (`make_bringup_pkg.sh`): `regmap.toml` next to the `sadiy_ebaz` folder.
The environment variable SADIY_REGMAP_TOML overrides both (`run.sh` / `sweepd.sh` of the package set it).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older Pythons
    import tomli as tomllib

_HERE = Path(__file__).resolve()
CANDIDATES = (_HERE.parents[2] / "rtl" / "regmap" / "regmap.toml",     # repository layout
              _HERE.parents[1] / "regmap.toml")                        # bring-up package layout
DEFAULT_PATH = next((c for c in CANDIDATES if c.is_file()), CANDIDATES[0])


@dataclass(frozen=True)
class Field:
    name: str
    lsb: int
    width: int
    access: str          # rw, ro, const, w1p
    reset: int

    @property
    def mask(self) -> int:
        """Mask of the field in place (already shifted)."""
        return ((1 << self.width) - 1) << self.lsb

    def get(self, value: int) -> int:
        return (value >> self.lsb) & ((1 << self.width) - 1)

    def put(self, value: int) -> int:
        """Field value shifted into place (truncated to the width)."""
        return (value & ((1 << self.width) - 1)) << self.lsb


@dataclass(frozen=True)
class Reg:
    name: str
    offset: int
    ext: bool
    fields: Dict[str, Field]

    def reset_value(self) -> int:
        return sum(f.put(f.reset) for f in self.fields.values() if f.access in ("rw", "const"))


def _bits(text: str):
    hi, _, lo = str(text).partition(":")
    hi_i = int(hi)
    lo_i = int(lo) if lo else hi_i
    return lo_i, hi_i - lo_i + 1


def load(path: Optional[str] = None) -> Dict[str, Reg]:
    """Parse regmap.toml into {register name: Reg}. `path` defaults to $SADIY_REGMAP_TOML, then DEFAULT_PATH."""
    chosen = path or os.environ.get("SADIY_REGMAP_TOML") or DEFAULT_PATH
    try:
        with open(chosen, "rb") as fh:
            doc = tomllib.load(fh)
    except FileNotFoundError:
        raise FileNotFoundError(f"regmap.toml not found at {chosen} (also looked at: "
                                f"{', '.join(str(c) for c in CANDIDATES)}); set SADIY_REGMAP_TOML=<file>") from None
    regs: Dict[str, Reg] = {}
    for r in doc["reg"]:
        fields = {}
        for f in r.get("field", ()):
            lsb, width = _bits(f["bits"])
            fields[f["name"]] = Field(f["name"], lsb, width, f["access"], int(f.get("reset", 0)))
        regs[r["name"]] = Reg(r["name"], int(r["offset"]), bool(r.get("ext", False)), fields)
    return regs


def map_version(path: Optional[str] = None) -> int:
    chosen = path or os.environ.get("SADIY_REGMAP_TOML") or DEFAULT_PATH
    with open(chosen, "rb") as fh:
        return int(tomllib.load(fh)["map"]["version"])


REGS: Dict[str, Reg] = load()
OFFSET: Dict[str, int] = {name: r.offset for name, r in REGS.items()}
