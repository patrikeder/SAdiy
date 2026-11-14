"""The platforms the SAdiy software knows: which SBC runs `sweepd` (and so which pins the bench and the GUI show).

`get("bbb")` and `get("ebaz")` return a `pinmap.PinMap`. `from_config` reads `[platform] name` of the daemon's
configuration; the default stays "bbb". The bench pin maps are separate from the sweep backends in
`hal/` and `zynq-ebaz/sw/sadiy_ebaz/`.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from . import pinmap, pinmap_ebaz
from .pinmap import PinMap

DEFAULT = "bbb"
MAPS: Dict[str, PinMap] = {"bbb": pinmap.BBB, "ebaz": pinmap_ebaz.EBAZ}
NAMES: Tuple[str, ...] = tuple(MAPS)
# `[platform] name` of the config picks the sweep backend: "ebaz-ps" and "ebaz-pl" are EBAZ4205 backends.
_ALIASES = {"ebaz-ps": "ebaz", "ebaz-pl": "ebaz"}


def normalize(name: Optional[str]) -> str:
    """"ebaz-ps" -> "ebaz"; None -> the default. ValueError for a name nobody knows."""
    key = (name or DEFAULT).strip().lower()
    key = _ALIASES.get(key, key)
    if key not in MAPS:
        raise ValueError(f"unknown platform {name!r}: expected one of {', '.join(NAMES)}")
    return key


def get(name: Optional[str] = None) -> PinMap:
    return MAPS[normalize(name)]


def from_config(cfg: dict) -> PinMap:
    return get(cfg.get("platform", {}).get("name"))
