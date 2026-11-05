"""Configuration loading. TOML file, optionally overridden section by section."""
from __future__ import annotations

from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older Pythons (BBB images)
    import tomli as tomllib

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "default.toml"


def load(path=None) -> dict:
    """Load the default config, then merge `path` on top (section by section)."""
    with open(DEFAULT_PATH, "rb") as fh:
        cfg = tomllib.load(fh)
    if path is not None:
        with open(path, "rb") as fh:
            override = tomllib.load(fh)
        for section, values in override.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
            else:
                cfg[section] = values
    return cfg
