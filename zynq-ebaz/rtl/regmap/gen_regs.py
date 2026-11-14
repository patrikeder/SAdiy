#!/usr/bin/env python3
"""Register-map generator for the SAdiy PL sweep engine.

Reads regmap.toml (next to this script) and writes next to it:
  axil_regs.sv  regs.py  regs.h  regmap.md

  gen_regs.py            write the four files
  gen_regs.py --check    write nothing, exit 1 if a file on disk differs from the generated text

Python 3.11+, stdlib only. Output is deterministic (no timestamps).
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOML_PATH = HERE / "regmap.toml"
OUT_NAMES = ("axil_regs.sv", "regs.py", "regs.h", "regmap.md")

ACCESS = ("rw", "ro", "const", "w1p")
BANNER = "generated from regmap.toml by gen_regs.py, do not edit"
RESERVED_PORTS = {
    "clk", "resetn", "reg_wdata",
    "s_axil_awaddr", "s_axil_awvalid", "s_axil_awready", "s_axil_wdata", "s_axil_wstrb",
    "s_axil_wvalid", "s_axil_wready", "s_axil_bresp", "s_axil_bvalid", "s_axil_bready",
    "s_axil_araddr", "s_axil_arvalid", "s_axil_arready", "s_axil_rdata", "s_axil_rresp",
    "s_axil_rvalid", "s_axil_rready",
    # internal names of axil_regs.sv
    "wr_phase", "rd_phase", "bvalid_q", "rvalid_q", "waddr_q", "raddr_q", "wdata_q", "rdata_q",
    "rd_mux",
}


class RegmapError(ValueError):
    """The register map is inconsistent."""


# ---------------------------------------------------------------- model

def _parse_bits(spec, where: str) -> tuple[int, int]:
    """Return (lsb, width) for "7:0" or "4"."""
    s = str(spec).strip()
    m = re.fullmatch(r"(\d+)(?::(\d+))?", s)
    if not m:
        raise RegmapError(f"{where}: bad bits {spec!r}")
    hi = int(m.group(1))
    lo = int(m.group(2)) if m.group(2) is not None else hi
    if hi < lo:
        raise RegmapError(f"{where}: bits {spec!r} has msb below lsb")
    if hi > 31:
        raise RegmapError(f"{where}: bits {spec!r} outside the 32-bit word")
    return lo, hi - lo + 1


def _as_int(v, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise RegmapError(f"{where}: expected an integer, got {v!r}")
    return v


def load_regmap(path) -> dict:
    """Parse and validate a regmap TOML; return the model dict."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    m = raw.get("map")
    if not isinstance(m, dict):
        raise RegmapError("missing [map]")
    for key in ("name", "data_width", "addr_width", "version"):
        if key not in m:
            raise RegmapError(f"[map] lacks {key}")
    if m["data_width"] != 32:
        raise RegmapError("[map] data_width must be 32")
    aw = _as_int(m["addr_width"], "[map] addr_width")
    if not 3 <= aw <= 32:
        raise RegmapError("[map] addr_width must be 3..32")
    version = _as_int(m["version"], "[map] version")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(m["name"])):
        raise RegmapError(f"[map] name {m['name']!r} must be lower case identifier")

    regs = []
    seen_names: dict[str, int] = {}
    seen_offsets: dict[int, str] = {}
    idents: dict[str, str] = {}      # generated identifier (lower case) -> origin, to catch collisions

    def claim(ident: str, origin: str):
        if ident in idents:
            raise RegmapError(f"{origin}: generated name {ident!r} collides with {idents[ident]}")
        idents[ident] = origin

    for r in raw.get("reg", []):
        name = r.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise RegmapError(f"register name {name!r} must be UPPER_CASE")
        if name in seen_names:
            raise RegmapError(f"duplicate register name {name}")
        seen_names[name] = 1
        if "offset" not in r:
            raise RegmapError(f"{name}: no offset")
        off = _as_int(r["offset"], f"{name} offset")
        if off % 4:
            raise RegmapError(f"{name}: offset 0x{off:X} is not a multiple of 4")
        if off < 0 or off >= (1 << aw):
            raise RegmapError(f"{name}: offset 0x{off:X} outside the {aw}-bit address space")
        if off in seen_offsets:
            raise RegmapError(f"{name}: offset 0x{off:X} already used by {seen_offsets[off]}")
        seen_offsets[off] = name
        ext = bool(r.get("ext", False))
        low = name.lower()
        claim(f"py:{low}", name)
        claim(f"py:{low}_reset", f"{name} reset constant")
        wr_strobe = bool(r.get("wr_strobe", False))
        if wr_strobe and ext:
            raise RegmapError(f"{name}: wr_strobe is only for registers that are not ext")
        if wr_strobe:
            if f"{low}_wr" in RESERVED_PORTS:
                raise RegmapError(f"{name}: port {low}_wr is reserved")
            claim(f"port:{low}_wr", f"{name} write strobe")
        if ext:
            for suffix in ("wr", "rd", "rdata"):
                p = f"{low}_{suffix}"
                if p in RESERVED_PORTS:
                    raise RegmapError(f"{name}: port {p} is reserved")
                claim(f"port:{p}", f"{name} ext port")

        fields = []
        used = 0
        fnames = set()
        for fl in r.get("field", []):
            fname = fl.get("name")
            where = f"{name}.{fname}"
            if not isinstance(fname, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", fname):
                raise RegmapError(f"{where}: field name must be lower_case")
            if fname in fnames:
                raise RegmapError(f"{where}: duplicate field name")
            fnames.add(fname)
            access = fl.get("access")
            if access not in ACCESS:
                raise RegmapError(f"{where}: access {access!r} not in {ACCESS}")
            if "bits" not in fl:
                raise RegmapError(f"{where}: no bits")
            lsb, width = _parse_bits(fl["bits"], where)
            mask = ((1 << width) - 1) << lsb
            if used & mask:
                raise RegmapError(f"{where}: bits {fl['bits']} overlap another field of {name}")
            used |= mask
            reset = _as_int(fl.get("reset", 0), f"{where} reset")
            if reset < 0 or reset >> width:
                raise RegmapError(f"{where}: reset 0x{reset:X} does not fit {width} bit(s)")
            if access == "w1p" and width != 1:
                raise RegmapError(f"{where}: w1p fields must be 1 bit wide")
            if access == "w1p" and reset:
                raise RegmapError(f"{where}: w1p field reads 0, reset must be 0")
            if ext and access in ("w1p", "const"):
                raise RegmapError(f"{where}: ext registers cannot have {access} fields")
            if not ext and access != "const":
                port = f"{low}_{fname}"
                if port in RESERVED_PORTS:
                    raise RegmapError(f"{where}: port {port} is reserved")
                claim(f"port:{port}", where)
            claim(f"py:{low}_{fname}", where)
            fields.append({"name": fname, "lsb": lsb, "width": width, "mask": mask,
                           "access": access, "reset": reset, "doc": str(fl.get("doc", ""))})
        regs.append({"name": name, "offset": off, "ext": ext, "wr_strobe": wr_strobe,
                     "doc": str(r.get("doc", "")),
                     "fields": fields})

    # reset value of the whole register: rw and const storage (ext registers have none)
    for r in regs:
        r["reset"] = 0 if r["ext"] else sum(
            f["reset"] << f["lsb"] for f in r["fields"] if f["access"] in ("rw", "const"))

    by_name = {r["name"]: r for r in regs}
    if "VERSION" not in by_name:
        raise RegmapError("register VERSION missing")
    vf = [f for f in by_name["VERSION"]["fields"] if f["name"] == "version"]
    if not vf or vf[0]["access"] != "const" or vf[0]["width"] != 32:
        raise RegmapError("VERSION.version must be a 32-bit const field")
    if vf[0]["reset"] != version:
        raise RegmapError(f"VERSION.version reset 0x{vf[0]['reset']:08X} != [map] version 0x{version:08X}")
    if "ID" not in by_name or not any(f["name"] == "magic" and f["access"] == "const" and f["width"] == 32
                                      for f in by_name["ID"]["fields"]):
        raise RegmapError("ID.magic must be a 32-bit const field")
    magic = next(f for f in by_name["ID"]["fields"] if f["name"] == "magic")["reset"]

    return {"name": str(m["name"]), "addr_width": aw, "version": version, "id_magic": magic,
            "regs": regs}


# ---------------------------------------------------------------- helpers

def _port_name(reg, field) -> str:
    return f"{reg['name'].lower()}_{field['name']}"


def _rng(width: int) -> str:
    return f"[{width - 1}:0] " if width > 1 else ""


def _slice(f) -> str:
    return f"[{f['lsb'] + f['width'] - 1}:{f['lsb']}]" if f["width"] > 1 else f"[{f['lsb']}]"


def _hex32(v: int) -> str:
    return f"0x{v:08X}"


def _addr_hex(model, off: int) -> str:
    wa = model["addr_width"] - 2
    digits = (wa + 3) // 4
    return f"{wa}'h{off >> 2:0{digits}X}"


def _wa_range(model) -> str:
    return f"[{model['addr_width'] - 1}:2]"


# ---------------------------------------------------------------- axil_regs.sv

def gen_sv(model) -> str:
    aw = model["addr_width"]
    regs = model["regs"]
    ports: list[str] = [
        "input  logic clk",
        "input  logic resetn",
        "",
        f"input  logic [{aw - 1}:0] s_axil_awaddr",
        "input  logic s_axil_awvalid",
        "output logic s_axil_awready",
        "input  logic [31:0] s_axil_wdata",
        "input  logic [3:0] s_axil_wstrb",
        "input  logic s_axil_wvalid",
        "output logic s_axil_wready",
        "output logic [1:0] s_axil_bresp",
        "output logic s_axil_bvalid",
        "input  logic s_axil_bready",
        f"input  logic [{aw - 1}:0] s_axil_araddr",
        "input  logic s_axil_arvalid",
        "output logic s_axil_arready",
        "output logic [31:0] s_axil_rdata",
        "output logic [1:0] s_axil_rresp",
        "output logic s_axil_rvalid",
        "input  logic s_axil_rready",
        "",
        "output logic [31:0] reg_wdata",
    ]
    for r in regs:
        ports.append("")
        ports.append(f"// {r['name']} @ 0x{r['offset']:03X}" + (" (ext)" if r["ext"] else ""))
        low = r["name"].lower()
        if r["ext"]:
            ports.append(f"output logic {low}_wr")
            ports.append(f"output logic {low}_rd")
            ports.append(f"input  logic [31:0] {low}_rdata")
            continue
        for f in r["fields"]:
            p = _port_name(r, f)
            if f["access"] in ("rw", "w1p"):
                ports.append(f"output logic {_rng(f['width'])}{p}")
            elif f["access"] == "ro":
                ports.append(f"input  logic {_rng(f['width'])}{p}")
        if r["wr_strobe"]:
            ports.append(f"output logic {low}_wr")
    # comma placement: after every real port except the last one
    real = [i for i, p in enumerate(ports) if p and not p.startswith("//")]
    last = real[-1]
    plines = []
    for i, p in enumerate(ports):
        if not p:
            plines.append("")
        elif p.startswith("//"):
            plines.append("  " + p)
        else:
            plines.append("  " + p + ("" if i == last else ","))

    w1 = _wa_range(model)
    L: list[str] = []
    a = L.append
    a(f"// {BANNER}")
    a("// Source: rtl/regmap/regmap.toml. Specification: docs/rtl-spec.md, section 4.")
    a("//")
    a("// AXI4-Lite slave with a register file. WSTRB is ignored, responses are always OKAY, unknown")
    a("// addresses read 0 and ignore writes, the two address LSBs are ignored. All AXI outputs come from")
    a("// registers (no combinational path from an AXI input to an AXI output).")
    a("//")
    a("// Write: when awvalid and wvalid are both seen (and no response is pending) the address and data are")
    a("// latched and awready = wready is high for exactly one clock (the accept clock, T0). At the end of T0")
    a("// the storage, the w1p pulses, the ext *_wr strobes and bvalid are all updated; so in T1 the new")
    a("// storage value, the pulse / strobe and bvalid are visible together, and reg_wdata holds the write")
    a("// data in T1 (and in T0). bvalid stays until bready.")
    a("// Read: when arvalid is seen (and no response is pending) the address is latched and arready is high")
    a("// for one clock (T0). In T0 the ext *_rd strobe is high, *_rdata is sampled, together with all other")
    a("// register values, into the read data register at the end of T0; rvalid is high in T1 until rready.")
    a("// The ext *_rd strobe is derived from state registers only (not from AXI inputs).")
    a("")
    a("/* verilator lint_off UNUSEDSIGNAL */")
    a("module axil_regs (")
    L.extend(plines)
    a(");")
    a("")
    a("  // ---- write channel")
    a(f"  logic wr_phase;                 // T0: awready = wready = 1")
    a("  logic bvalid_q;")
    a(f"  logic [{aw - 1}:0] waddr_q;")
    a("  logic [31:0] wdata_q;")
    a("")
    a("  assign s_axil_awready = wr_phase;")
    a("  assign s_axil_wready  = wr_phase;")
    a("  assign s_axil_bresp   = 2'b00;")
    a("  assign s_axil_bvalid  = bvalid_q;")
    a("  assign reg_wdata      = wdata_q;")
    a("")
    a("  always_ff @(posedge clk) begin")
    a("    if (!resetn) begin")
    a("      wr_phase <= 1'b0;")
    a("      bvalid_q <= 1'b0;")
    a(f"      waddr_q  <= {aw}'d0;")
    a("      wdata_q  <= 32'd0;")
    a("    end else if (wr_phase) begin")
    a("      wr_phase <= 1'b0;")
    a("      bvalid_q <= 1'b1;")
    a("    end else if (bvalid_q) begin")
    a("      if (s_axil_bready) bvalid_q <= 1'b0;")
    a("    end else if (s_axil_awvalid && s_axil_wvalid) begin")
    a("      wr_phase <= 1'b1;")
    a("      waddr_q  <= s_axil_awaddr;")
    a("      wdata_q  <= s_axil_wdata;")
    a("    end")
    a("  end")
    a("")
    a("  // ---- register storage, w1p pulses and ext write strobes (all updated at the end of T0)")
    a("  always_ff @(posedge clk) begin")
    # defaults: pulses and strobes low
    for r in regs:
        low = r["name"].lower()
        if r["ext"] or r["wr_strobe"]:
            a(f"    {low}_wr <= 1'b0;")
        if not r["ext"]:
            for f in r["fields"]:
                if f["access"] == "w1p":
                    a(f"    {_port_name(r, f)} <= 1'b0;")
    a("    if (!resetn) begin")
    for r in regs:
        if r["ext"]:
            continue
        for f in r["fields"]:
            if f["access"] == "rw":
                a(f"      {_port_name(r, f)} <= {f['width']}'h{f['reset']:X};")
    a("    end else if (wr_phase) begin")
    a(f"      case (waddr_q{w1})")
    for r in regs:
        low = r["name"].lower()
        body = []
        if r["ext"]:
            body.append(f"{low}_wr <= 1'b1;")
        else:
            for f in r["fields"]:
                if f["access"] in ("rw", "w1p"):
                    body.append(f"{_port_name(r, f)} <= wdata_q{_slice(f)};")
            if r["wr_strobe"]:
                body.append(f"{low}_wr <= 1'b1;")
        if not body:
            continue
        a(f"        {_addr_hex(model, r['offset'])}: begin  // {r['name']}")
        for b in body:
            a(f"          {b}")
        a("        end")
    a("        default: ;")
    a("      endcase")
    a("    end")
    a("  end")
    a("")
    a("  // ---- read channel")
    a("  logic rd_phase;                 // T0: arready = 1, ext *_rd strobes")
    a("  logic rvalid_q;")
    a(f"  logic [{aw - 1}:0] raddr_q;")
    a("  logic [31:0] rdata_q;")
    a("  logic [31:0] rd_mux;")
    a("")
    a("  assign s_axil_arready = rd_phase;")
    a("  assign s_axil_rdata   = rdata_q;")
    a("  assign s_axil_rresp   = 2'b00;")
    a("  assign s_axil_rvalid  = rvalid_q;")
    a("")
    ext_regs = [r for r in regs if r["ext"]]
    for r in ext_regs:
        low = r["name"].lower()
        a(f"  assign {low}_rd = rd_phase && (raddr_q{w1} == {_addr_hex(model, r['offset'])});")
    if ext_regs:
        a("")
    a("  always_comb begin")
    a("    rd_mux = 32'd0;")
    a(f"    case (raddr_q{w1})")
    for r in regs:
        low = r["name"].lower()
        lines = []
        if r["ext"]:
            lines.append(f"rd_mux = {low}_rdata;")
        else:
            for f in r["fields"]:
                if f["access"] == "const":
                    lines.append(f"rd_mux{_slice(f)} = {f['width']}'h{f['reset']:X};")
                elif f["access"] in ("rw", "ro"):
                    lines.append(f"rd_mux{_slice(f)} = {_port_name(r, f)};")
        if not lines:
            continue
        a(f"      {_addr_hex(model, r['offset'])}: begin  // {r['name']}")
        for ln in lines:
            a(f"        {ln}")
        a("      end")
    a("      default: ;")
    a("    endcase")
    a("  end")
    a("")
    a("  always_ff @(posedge clk) begin")
    a("    if (!resetn) begin")
    a("      rd_phase <= 1'b0;")
    a("      rvalid_q <= 1'b0;")
    a(f"      raddr_q  <= {aw}'d0;")
    a("      rdata_q  <= 32'd0;")
    a("    end else if (rd_phase) begin")
    a("      rd_phase <= 1'b0;")
    a("      rvalid_q <= 1'b1;")
    a("      rdata_q  <= rd_mux;")
    a("    end else if (rvalid_q) begin")
    a("      if (s_axil_rready) rvalid_q <= 1'b0;")
    a("    end else if (s_axil_arvalid) begin")
    a("      rd_phase <= 1'b1;")
    a("      raddr_q  <= s_axil_araddr;")
    a("    end")
    a("  end")
    a("")
    a("endmodule")
    a("/* verilator lint_on UNUSEDSIGNAL */")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- regs.py

def gen_py(model) -> str:
    L: list[str] = []
    a = L.append
    a('"""Register map constants of the SAdiy PL sweep engine.')
    a("")
    a(f"{BANNER}.")
    a('"""')
    a("")
    a(f"ADDR_WIDTH = {model['addr_width']}")
    a(f"MAP_VERSION = {_hex32(model['version'])}")
    a(f"ID_MAGIC = {_hex32(model['id_magic'])}")
    a("")
    a("")
    a("def get_field(word, lsb, width):")
    a('    """Extract the field at bit lsb, width bits wide, from a 32-bit word."""')
    a("    return (word >> lsb) & ((1 << width) - 1)")
    a("")
    a("")
    a("def set_field(word, lsb, width, value):")
    a('    """Return word with the field at lsb / width replaced by value (value is masked)."""')
    a("    mask = ((1 << width) - 1) << lsb")
    a("    return (word & ~mask) | ((value << lsb) & mask)")
    a("")
    a("")
    a("# register offsets, field positions and reset values")
    for r in model["regs"]:
        n = r["name"]
        a("")
        a(f"{n} = 0x{r['offset']:03X}")
        a(f"{n}_RESET = {_hex32(r['reset'])}")
        for f in r["fields"]:
            p = f"{n}_{f['name'].upper()}"
            a(f"{p}_LSB = {f['lsb']}")
            a(f"{p}_WIDTH = {f['width']}")
            a(f"{p}_MASK = {_hex32(f['mask'])}")
    a("")
    a("")
    a("REGISTERS = {")
    for r in model["regs"]:
        a(f'    "{r["name"]}": {{')
        a(f'        "offset": 0x{r["offset"]:03X},')
        a(f'        "ext": {r["ext"]},')
        a('        "fields": {')
        for f in r["fields"]:
            a(f'            "{f["name"]}": {{"lsb": {f["lsb"]}, "width": {f["width"]}, '
              f'"access": "{f["access"]}", "reset": {_hex32(f["reset"])}}},')
        a("        },")
        a("    },")
    a("}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- regs.h

def gen_h(model) -> str:
    pre = model["name"].upper()
    L: list[str] = []
    a = L.append
    a(f"/* {BANNER} */")
    a(f"#ifndef {pre}_REGS_H")
    a(f"#define {pre}_REGS_H")
    a("")
    a(f"#define {pre}_ADDR_WIDTH {model['addr_width']}u")
    a(f"#define {pre}_MAP_VERSION {_hex32(model['version'])}u")
    a(f"#define {pre}_ID_MAGIC {_hex32(model['id_magic'])}u")
    for r in model["regs"]:
        n = r["name"]
        a("")
        a(f"#define {pre}_{n} 0x{r['offset']:03X}u")
        a(f"#define {pre}_{n}_RESET {_hex32(r['reset'])}u")
        for f in r["fields"]:
            p = f"{pre}_{n}_{f['name'].upper()}"
            a(f"#define {p}_LSB {f['lsb']}u")
            a(f"#define {p}_WIDTH {f['width']}u")
            a(f"#define {p}_MASK {_hex32(f['mask'])}u")
    a("")
    a(f"#endif /* {pre}_REGS_H */")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- regmap.md

def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def gen_md(model) -> str:
    L: list[str] = []
    a = L.append
    a(f"<!-- {BANNER} -->")
    a("# Register map")
    a("")
    a(f"Map `{model['name']}`, version {_hex32(model['version'])}, {model['addr_width']}-bit address, "
      "32-bit registers. Writes are full words (WSTRB ignored); bits without a field read 0.")
    a("Registers marked *ext* are implemented outside `axil_regs.sv`.")
    a("")
    a("| Offset | Name | Reset | Description |")
    a("|---|---|---|---|")
    for r in model["regs"]:
        name = r["name"] + (" (ext)" if r["ext"] else "")
        a(f"| 0x{r['offset']:03X} | {name} | {_hex32(r['reset'])} | {_cell(r['doc'])} |")
    for r in model["regs"]:
        a("")
        a(f"## {r['name']} (0x{r['offset']:03X})" + (" ext" if r["ext"] else ""))
        a("")
        a(_cell(r["doc"]))
        a("")
        a("| Bits | Name | Access | Reset | Description |")
        a("|---|---|---|---|---|")
        for f in sorted(r["fields"], key=lambda x: -x["lsb"]):
            bits = f"{f['lsb'] + f['width'] - 1}:{f['lsb']}" if f["width"] > 1 else str(f["lsb"])
            a(f"| {bits} | {f['name']} | {f['access']} | 0x{f['reset']:X} | {_cell(f['doc'])} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- driver

def generate(model) -> dict[str, str]:
    return {"axil_regs.sv": gen_sv(model), "regs.py": gen_py(model),
            "regs.h": gen_h(model), "regmap.md": gen_md(model)}


def run(toml_path=TOML_PATH, out_dir=None, check=False) -> int:
    toml_path = Path(toml_path)
    out_dir = Path(out_dir) if out_dir is not None else toml_path.parent
    try:
        model = load_regmap(toml_path)
    except RegmapError as e:
        print(f"gen_regs: error: {e}", file=sys.stderr)
        return 2
    files = generate(model)
    stale = []
    for name, text in files.items():
        p = out_dir / name
        if check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            p.write_text(text, encoding="utf-8", newline="\n")
    if check:
        if stale:
            print("gen_regs: out of date: " + ", ".join(stale) + " (run gen_regs.py)", file=sys.stderr)
            return 1
        print("gen_regs: generated files are current")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="write nothing, exit 1 if files differ")
    args = ap.parse_args(argv)
    return run(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
