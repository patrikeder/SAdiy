"""Linux (bench mode) and the PL engine must put V1..V6 on the same PCF8574 port bits (register map 2.0)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sadiy import config  # noqa: E402
from sadiy.drivers import pcf8574  # noqa: E402
from sadiy_ebaz.ebaz_pl_model import PCF8574_ADDR, PlModel  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS  # noqa: E402


def test_same_port_byte_as_the_engine_model():
    model = PlModel()
    for levels in range(64):
        assert model.port_byte(levels) == pcf8574.port_byte(levels), levels


def test_same_default_address():
    assert PCF8574_ADDR == pcf8574.DEFAULT_ADDRESS == config.load()["attenuator"]["pcf8574_address"]
    assert REGS["ATT_I2C"].fields["addr"].get(REGS["ATT_I2C"].reset_value()) == pcf8574.DEFAULT_ADDRESS
