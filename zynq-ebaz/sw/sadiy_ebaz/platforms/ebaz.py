"""`[platform] name = "ebaz"` (what `sweepd --platform ebaz` sets): the EBAZ4205 with its PL sweep engine."""
from .ebaz_pl import build_engine  # noqa: F401


def build_bench_backend(cfg: dict):
    """Hook of `sweepd` for `--bench-only` on the real board: Linux owns the pins (PS GPIO, spidev0.0, i2c-0)."""
    from ..ps_backend import EbazPsBackend

    b = cfg.get("bench", {})
    p = cfg.get("platform", {})
    return EbazPsBackend(
        spi_bus=int(p.get("spi_bus", 0)), spi_device=int(p.get("spi_device", 0)), spi_hz=int(b.get("spi_hz", 1_000_000)),
        i2c_bus=int(p.get("i2c_bus", 0)), i2c_address=int(b.get("ads1115_address", 0x48)),
        regs_base=int(p["base"]) if "base" in p else None,       # the PL register base, as for the engine
    )
