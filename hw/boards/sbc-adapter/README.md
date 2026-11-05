# SBC adapter (KiCad project)

One board that lets the **BeagleBone Black** reach the module boards (PE4302, ADF4351, detector, ADS1115). The board sits on the BBB like a cape: P8 and P9 are male pin headers on the **bottom** side, everything else (module headers, jumpers, test points) is on the **top** side.

**Raspberry Pi support was removed (2026-11-01)** to keep the board to one SBC: J3 (2x20 IDC), the 13 RPi-side series resistors (R2, R4 .. R26) and the RPi supply jumpers JP2 / JP4 are gone from the schematic and the board. Every BBB signal keeps its 220 ohm series resistor at the BBB header (R1, R3 .. R25), as source termination and fault-current limit.

The pin map comes from `../../netlist.md` and `../../wiring-bbb.md`. Nothing was remapped.

## Files

| File | Content |
|---|---|
| `sa_sbc_adapter.kicad_sch` | schematic (single sheet, A1), KiCad 8 file format |
| `sa_sbc_adapter.kicad_pro` | minimal project file |
| `sadiy.kicad_sym`, `sym-lib-table` | project symbol library (all symbols are custom, footprints are stock KiCad ones) |
| `gen_schematic.py` | generator of the FIRST (two-SBC) schematic, a record only: **do not run it over the `.kicad_sch`** |
| `check_schematic.py` | standalone connectivity check against the pin map (no KiCad needed) |
| `preview.svg`, `preview.png` | schematic preview drawn by the generator, **not a KiCad render** |
| `sa_sbc_adapter.kicad_pcb` | board, connectors placed to the BBB cape geometry (see "Board placement") |
| `sadiy.pretty/`, `fp-lib-table` | project footprint library: `BBB_Header_2x23_Male_Bottom` |
| `gen_footprints.py` | writes `sadiy.pretty/` and `fp-lib-table` |
| `remove_rpi.py` | removes J3, JP2, JP4 and the RPi-side resistors from the schematic and the board (record of the 2026-11-01 edit, not re-runnable) |
| `route_check.py`, `route_report.py`, `ROUTABILITY.md`, `routability/` | routability feasibility check (see `ROUTABILITY.md`) |
| `place_connectors.py` | (first layout, includes J3) puts J1, J2, J3 and the cape outline / keep-outs (`Dwgs.User`) on the board (re-runnable) |
| `align_components.py` | (first layout, before the hand edits and before J3 was removed) **places every other part on a regular lattice** (rows, columns, one orientation per class), fits the board outline to the parts and writes it on `Edge.Cuts`; deterministic, re-runnable. Run it after `place_connectors.py` |
| `place_components.py` | earlier free-form placement (greedy, net-driven) that was used to find the macro layout; superseded by `align_components.py`, kept for experiments |
| `check_components.py` | (needs J3, so it no longer runs on the current board) checks overlaps, the board outline, the alignment (lattice, orientations, rows) and the signal-integrity distances |
| `check_placement.py` | (needs J3) checks the pad positions in the board file against the cape geometry |
| `placement.svg`, `placement.png` | placement preview of ALL parts, drawn from the placement data (pads, courtyards, ratsnest of the signal nets), **not a KiCad render** |

The `.kicad_pcb` and `.kicad_sch` are yours. KiCad 10 re-saved them and the board has hand-placed parts (test points, some resistors, JP2/JP4/JP6 before they were removed or moved), so none of the placement scripts is re-run any more.

## Status

- The schematic was checked without KiCad: nets built from wires, labels and pin positions. After the RPi removal: every remaining pin keeps its net, no wire end dangles, no RPI_* label is left.
- **Not yet checked in KiCad.** Run ERC and DRC and pass the output back. Then use "Update PCB from Schematic" once to confirm that schematic and board agree (they were edited in the same way).

## Signal map

| Net | BBB | Module |
|---|---|---|
| SYN_CLK | P9.22 | J6 pin 7 (ADF4351 CLK) |
| SYN_DATA | P9.18 | J6 pin 6 (DAT) |
| SYN_LE | P9.17 | J6 pin 5 (LE) |
| SYN_LD | P9.23 | J6 pin 9 (LD), SBC input |
| SYN_CE | P9.27 | J12 pin 3, jumper to J6 pin 3 (CE) |
| ATT_V1..V6 | P8.7, 8, 9, 10, 11, 12 | J4 pins 2..7 (PE4302 V1..V6) |
| I2C_SDA / I2C_SCL | P9.20 / P9.19 (I2C2) | J10 pins 4 / 3 (ADS1115) |
| detector | P9.39 AIN0, P9.34 GNDA_ADC, P9.32 VDD_ADC (clamp only) | divider from J8 |

## Jumpers and options

| Part | Setting |
|---|---|
| JP1 | 5 V rail joins the BBB VDD_5V (P9.5/6). Case A: external 5 V on J11 powers the BBB, fit JP1 and do not plug the BBB's own supply. Case B: the BBB powers the modules, fit JP1 and leave J11 empty. A BBB powered over USB only has no VDD_5V. |
| JP3 | 3.3 V rail from the BBB (P9.3/4). |
| J12 | ADF4351 CE: jumper 1-2 = tied high (default), 2-3 = from the SBC pin. |
| JP5 | ADF4351 PDR tied high. Remove if the board already pulls it up. |
| JP6 | BBB analog path (divider to AIN0). |
| R27..R32 | 2.2k pull-ups on V1..V6, default after boot = 31.5 dB. Remove for 0 dB. |
| R38 (0R) | joins AGND to GND at one point. |
| 4.7k on I2C | not fitted (DNP). The BBB I2C2 already has pull-ups. |

## Parts (from the schematic)

25 resistors (13 x 220R series, 6 x 2.2k, 2 x 1k, 1 x 3.01k, 1 x 0R, 2 x 4.7k DNP), 10 capacitors (4 x 10u 0805, 6 x 100n 0603), 3 ferrite beads (0805, 2 A), 1 resettable fuse (1812, 2 A), 2 x BAT54S (SOT-23), 11 connectors, 4 jumper headers, 23 test points named as in `../../test-points.md` (TP_5V, TP_5V_SYN, TP_3V3_ATT, TP_PE_V1..V6, TP_SYN_*, TP_DET_OUT, TP_ADC_IN, plus grounds and rails). Footprints are assigned, using stock KiCad libraries.

## Decisions that go beyond the repo notes

- 220 ohm series resistors at the BBB header on every signal (source termination). With the 2.2k pull-ups the low level at the PE4302 input is about 0.3 V, well under its threshold.
- BBB divider is 1k over 3.01k (ratio 0.751, 1.9 V in gives about 1.43 V), 100 nF at the tap, BAT54S clamp to GNDA_ADC and VDD_ADC. Put `detector.divider_ratio = 0.751` in `config/default.toml`.
- ADS1115 path: 1k, 100 nF and a BAT54S clamp to 3V3 and ground. The ADS1115 is a **breakout header** (VDD GND SCL SDA ADDR ALRT A0 A1 A2 A3), not a chip on the board.
- The BBB I2C2 drives I2C_SDA / I2C_SCL for the ADS1115.
- Ferrite beads between the BBB rails and the ADF4351 5 V, the detector 5 V and the PE4302 3.3 V.

## Board placement

Cape geometry (BeagleBone cape, from the SparkFun `BEAGLE_BONE_BLACK_CAPE` footprint, which was made from the BBB gerbers), seen from the top, origin at the top-left corner of the 86.36 x 54.61 mm cape outline. The outline is drawn on `Dwgs.User` at (170, 40) on the board, to the right of the other parts. It is a reference, not the board edge.

| | pin 1 | rows |
|---|---|---|
| P8 (J2) | x = 20.32 mm, y = 4.445 mm | odd pins y = 4.445, even pins y = 1.905 (outer row, top edge) |
| P9 (J1) | x = 20.32 mm, y = 52.705 mm | odd pins y = 52.705 (outer row, bottom edge), even pins y = 50.165 |

Both headers: pin 1 at the Ethernet (left) end, 23 pins per row, 2.54 mm pitch, even pins above odd pins. The two headers are 48.26 mm apart.

- **J1, J2** are on the bottom side with the custom footprint `sadiy:BBB_Header_2x23_Male_Bottom`. The stock 2x23 header cannot be used there: KiCad mirrors a footprint when it moves to the bottom, which gives the wrong pad pattern for P8/P9. The custom footprint is the mirror image, so after KiCad flips it the pads sit exactly on the BBB pattern. Pin 1 is the footprint origin; keep the orientation at 0 and the side at B.Cu. It has no 3D model.
- Also drawn on `Dwgs.User`: the Ethernet connector keep-out, the top-left cut and the three rounded corners of the cape (from the same SparkFun footprint). The reference outline is only for orientation: the board is larger than the cape (see "Component placement"). Not placed: the four BBB mounting holes.
- Verified with `check_placement.py` (maximum pad error 0.000 mm against the cape table, nets of J1/J2 unchanged; written for the first layout), **not** in KiCad. Please confirm physically: print the board at 1:1 (pads only) and hold it over the BBB headers. Pin 1 of P9 is the GND pin at the Ethernet end, in the row next to the board edge.

## Component placement

The first layout (`align_components.py`, lattice rows and columns, 112 x 67 mm outline with the Ethernet cut-out) was hand-edited by you in KiCad afterwards (test points, several resistors, JP2/JP4/JP6, some rotations). The RPi removal changed **nothing else**: all remaining parts are where you left them, and the outline is unchanged. The area where J3 and the RPi-side resistors were (between P8 and the middle of the board, and the row below it) is now empty, so the board can be made smaller if you want; say so and I will propose an outline.

One point from my overlap check on the current board: the courtyards of J5 and TP8 are closer than 0.7 mm (my own rule, not a KiCad DRC rule).

## PCB notes

- J1 and J2: 2x23 male headers with the plastic body on the **bottom** side, long pins down into the BBB sockets (see "Board placement").
- Keep the analog front end (R33, R34, C1, C2, D1, D2, R38) next to J8 and P9.34 / P9.39. One star point for GND and AGND.
- No mounting holes, no cape EEPROM yet.

## Module headers checked against the photos (2026-11-01)

| Schematic | Photo | Result |
|---|---|---|
| J4 PE4302: GND V1..V6 | one row of 7 pins labelled GND V1 V2 V3 V4 V5 V6 | matches |
| J5 PE4302 supply | two pads with a red and a black lead, no marking | cannot be told from the photo, measure |
| J6 ADF4351: GND CE LE CLK LD / 3V3 GND DAT MUX PDR | 2x5 header, left column GND CE LE CLK LD, right column 3V3 GND DAT MUX PDR | matches, row by row, so a straight 2x5 ribbon works |
| J7 ADF4351 DC jack | polarity symbol reads centre-positive (+ joined to the centre pin) | confirm with a DMM |
| J8 detector OUT | 2-pin header with no marking of OUT or GND | still open, measure |
| J9 detector VCC / GND | two pads labelled VCC and GND | matches |

## Assumptions to confirm on the real hardware

1. ADF4351 header order (J6) as given in `../../netlist.md`: row 1 GND CE LE CLK LD, row 2 3V3 GND DAT MUX PDR. Pin 2 (board 3V3) is left open on purpose.
2. PE4302 header order `GND V1..V6` and the weights (use `tools/bringup.py pe4302-walk`).
3. Which pin of the detector OUT header is OUT (J8 pin 1 must be OUT), and the DC jack polarity of the ADF4351 board (J7).
4. Ferrite and fuse values, and that 3.3 V from the BBB can carry the PE4302 and the ADS1115 (tiny load).
5. Names of the unused BBB pins come from the BBB system reference, not from the repo. The used pins come from the repo.
