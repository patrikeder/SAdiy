"""Tests of rtl/regmap/gen_regs.py (stdlib + pytest only)."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

REGMAP_DIR = Path(__file__).resolve().parents[1] / "regmap"
GEN_PATH = REGMAP_DIR / "gen_regs.py"
TOML_PATH = REGMAP_DIR / "regmap.toml"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load(GEN_PATH, "gen_regs_under_test")
regs = _load(REGMAP_DIR / "regs.py", "regs_generated")

HEADER = """
[map]
name = "t"
data_width = 32
addr_width = 8
version = 0x00010000

[[reg]]
name = "ID"
offset = 0x00
  [[reg.field]]
  name = "magic"
  bits = "31:0"
  access = "const"
  reset = 0x1234

[[reg]]
name = "VERSION"
offset = 0x04
  [[reg.field]]
  name = "version"
  bits = "31:0"
  access = "const"
  reset = 0x00010000
"""


def _write(tmp_path, body, name="regmap.toml"):
    p = tmp_path / name
    p.write_text(HEADER + body)
    return p


def test_check_passes():
    r = subprocess.run([sys.executable, str(GEN_PATH), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_check_detects_stale_file(tmp_path):
    for name in gen.OUT_NAMES:
        (tmp_path / name).write_text((REGMAP_DIR / name).read_text())
    (tmp_path / "regs.h").write_text("stale\n")
    assert gen.run(TOML_PATH, tmp_path, check=True) == 1
    assert (tmp_path / "regs.h").read_text() == "stale\n"       # --check writes nothing
    assert gen.run(TOML_PATH, tmp_path, check=False) == 0
    assert gen.run(TOML_PATH, tmp_path, check=True) == 0


def test_output_is_deterministic():
    model = gen.load_regmap(TOML_PATH)
    assert gen.generate(model) == gen.generate(model)
    for text in gen.generate(model).values():
        assert "generated from regmap.toml by gen_regs.py, do not edit" in "\n".join(text.splitlines()[:3])


def test_regs_py_matches_toml():
    model = gen.load_regmap(TOML_PATH)
    assert regs.ADDR_WIDTH == model["addr_width"] == 12
    assert regs.MAP_VERSION == model["version"]
    assert regs.ID_MAGIC == 0x53410001
    assert regs.SPI_DIV == 0x018
    assert regs.SPI_DIV_DIV_LSB == 0 and regs.SPI_DIV_DIV_WIDTH == 8 and regs.SPI_DIV_DIV_MASK == 0xFF
    assert regs.SPI_DIV_RESET == 5
    assert regs.PE4302 == 0x030
    assert regs.PE4302_RESET == 0x13F
    assert regs.PE4302_ACTIVE_HIGH_MASK == 0x100
    assert regs.CTRL_PIN_OWNER_MASK == 1 << 4
    assert regs.STATUS_STATE_LSB == 8 and regs.STATUS_STATE_MASK == 0xF00
    assert regs.RESULT_DATA_UNLOCKED_MASK == 0x80000000
    assert regs.RESULT_DATA_SUM_MASK == 0x0FFFFFFF
    assert regs.CAPS_CLK_MHZ_MASK == 0xFFFF0000
    assert regs.N_AVG_RESET == 1
    assert regs.REGISTERS["TABLE_W1"]["ext"] is True
    assert regs.REGISTERS["CTRL"]["ext"] is False
    assert regs.REGISTERS["CTRL"]["fields"]["start"]["access"] == "w1p"
    assert regs.REGISTERS["PE4302"]["fields"]["active_high"] == {
        "lsb": 8, "width": 1, "access": "rw", "reset": 1}
    # every register in the TOML is in the dict with the same offset
    for r in model["regs"]:
        assert regs.REGISTERS[r["name"]]["offset"] == r["offset"] == getattr(regs, r["name"])
        for f in r["fields"]:
            p = f"{r['name']}_{f['name'].upper()}"
            assert getattr(regs, p + "_MASK") == f["mask"]


def test_field_helpers():
    w = regs.set_field(0, 8, 4, 0xA)
    assert w == 0xA00
    assert regs.get_field(w, 8, 4) == 0xA
    assert regs.set_field(0xFFFFFFFF, 4, 8, 0) == 0xFFFFF00F
    assert regs.set_field(0, 0, 3, 0xFF) == 7           # value is masked


def test_regs_h_agrees_with_regs_py():
    text = (REGMAP_DIR / "regs.h").read_text()
    assert "#ifndef SADIY_REGS_H" in text and "#endif" in text
    defs = dict(re.findall(r"#define (\w+) (0x[0-9A-Fa-f]+|\d+)u", text))
    checked = 0
    for name, info in regs.REGISTERS.items():
        assert int(defs[f"SADIY_{name}"], 0) == info["offset"] == getattr(regs, name)
        assert int(defs[f"SADIY_{name}_RESET"], 0) == getattr(regs, name + "_RESET")
        for fname in info["fields"]:
            p = f"{name}_{fname.upper()}"
            for suffix in ("LSB", "WIDTH", "MASK"):
                assert int(defs[f"SADIY_{p}_{suffix}"], 0) == getattr(regs, f"{p}_{suffix}")
        checked += 1
    assert checked == len(regs.REGISTERS) > 20
    assert int(defs["SADIY_ADDR_WIDTH"], 0) == regs.ADDR_WIDTH
    assert int(defs["SADIY_MAP_VERSION"], 0) == regs.MAP_VERSION
    assert int(defs["SADIY_ID_MAGIC"], 0) == regs.ID_MAGIC


def test_sv_ports():
    sv = (REGMAP_DIR / "axil_regs.sv").read_text()
    assert "module axil_regs (" in sv
    assert "output logic [7:0] spi_div_div," in sv
    assert "output logic ctrl_start," in sv                       # w1p
    assert "input  logic [3:0] status_state," in sv               # ro
    assert "output logic table_w1_wr," in sv and "output logic table_w1_rd," in sv
    assert "input  logic [31:0] table_w1_rdata," in sv
    assert "magic" not in sv.split(");")[0]                       # const: no port
    assert "table_addr_index" not in sv                           # ext register: no storage / port
    # clk, resetn and reg_wdata come in the specified order
    assert sv.index("input  logic clk") < sv.index("input  logic resetn") < sv.index("s_axil_awaddr") \
        < sv.index("s_axil_rready") < sv.index("output logic [31:0] reg_wdata") < sv.index("ctrl_start")


def test_validator_accepts_minimal(tmp_path):
    p = _write(tmp_path, """
[[reg]]
name = "A"
offset = 0x08
  [[reg.field]]
  name = "x"
  bits = "3:0"
  access = "rw"
""")
    model = gen.load_regmap(p)
    assert [r["name"] for r in model["regs"]] == ["ID", "VERSION", "A"]
    assert gen.generate(model)["axil_regs.sv"].count("module axil_regs") == 1


def test_validator_rejects_overlapping_fields(tmp_path):
    p = _write(tmp_path, """
[[reg]]
name = "A"
offset = 0x08
  [[reg.field]]
  name = "x"
  bits = "7:0"
  access = "rw"
  [[reg.field]]
  name = "y"
  bits = "8:4"
  access = "ro"
""")
    with pytest.raises(gen.RegmapError, match="overlap"):
        gen.load_regmap(p)


def test_validator_rejects_duplicate_offset(tmp_path):
    p = _write(tmp_path, """
[[reg]]
name = "A"
offset = 0x08
  [[reg.field]]
  name = "x"
  bits = "0"
  access = "rw"

[[reg]]
name = "B"
offset = 0x08
  [[reg.field]]
  name = "x"
  bits = "0"
  access = "rw"
""")
    with pytest.raises(gen.RegmapError, match="already used"):
        gen.load_regmap(p)


@pytest.mark.parametrize("body, match", [
    ('[[reg]]\nname = "A"\noffset = 0x0A\n', "multiple of 4"),
    ('[[reg]]\nname = "A"\noffset = 0x100\n', "outside"),
    ('[[reg]]\nname = "ID"\noffset = 0x08\n', "duplicate register name"),
    ('[[reg]]\nname = "A"\noffset = 0x08\n  [[reg.field]]\n  name = "x"\n  bits = "0"\n  access = "bogus"\n',
     "access"),
    ('[[reg]]\nname = "A"\noffset = 0x08\n  [[reg.field]]\n  name = "x"\n  bits = "0"\n  access = "rw"\n'
     '  [[reg.field]]\n  name = "x"\n  bits = "1"\n  access = "rw"\n', "duplicate field"),
    ('[[reg]]\nname = "A"\noffset = 0x08\n  [[reg.field]]\n  name = "x"\n  bits = "3:0"\n  access = "rw"\n'
     '  reset = 16\n', "does not fit"),
    ('[[reg]]\nname = "A"\noffset = 0x08\next = true\n  [[reg.field]]\n  name = "x"\n  bits = "0"\n'
     '  access = "w1p"\n', "ext"),
])
def test_validator_rejects_other_errors(tmp_path, body, match):
    with pytest.raises(gen.RegmapError, match=match):
        gen.load_regmap(_write(tmp_path, body))


def test_validator_rejects_version_mismatch(tmp_path):
    p = tmp_path / "regmap.toml"
    p.write_text(HEADER.replace("reset = 0x00010000", "reset = 0x00020000"))
    with pytest.raises(gen.RegmapError, match="version"):
        gen.load_regmap(p)


def test_ext_register_creates_no_storage(tmp_path):
    p = _write(tmp_path, """
[[reg]]
name = "E"
offset = 0x08
ext = true
  [[reg.field]]
  name = "v"
  bits = "7:0"
  access = "rw"
  reset = 3
""")
    sv = gen.generate(gen.load_regmap(p))["axil_regs.sv"]
    assert "output logic e_wr" in sv and "output logic e_rd" in sv and "input  logic [31:0] e_rdata" in sv
    assert "e_v" not in sv
    assert gen.load_regmap(p)["regs"][-1]["reset"] == 0


def test_main_cli_error_exit_code(tmp_path):
    p = _write(tmp_path, '[[reg]]\nname = "A"\noffset = 0x0A\n')
    assert gen.run(p, tmp_path, check=False) == 2
