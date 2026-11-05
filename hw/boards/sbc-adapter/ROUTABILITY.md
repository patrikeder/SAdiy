# Routability feasibility check (SBC adapter, BBB only, your current placement)

Question: can all connections of `sa_sbc_adapter.kicad_pcb` be routed on two layers? **Yes.** Checked on the board after the RPi
connector was removed and with your hand placement: all 44 routed nets (110 point-to-point connections, 154 pads) route with zero conflicts.
GND (28 pads) is assumed to be a pour. Nothing was written into the board; this is an analysis only.

Tools: `route_check.py` (router) and `route_report.py` (statistics, images). Pure Python + numpy, no KiCad, nothing installed.

## Model
2 copper layers, 0.254 mm grid aligned to the 2.54 mm pad lattice (one track fits between two header pads), 4-direction moves,
track 0.25 mm, clearance 0.20 mm, via 0.50/0.25 mm, copper to board edge 0.30 mm. THT pads on both layers, SMD/test points on F.Cu.
Conservative: Manhattan routing only, a via blocks 3 x 3 nodes. It does not replace DRC.

## Results
1. **Every connection alone** (empty board, parallel on both CPU cores): 110 of 110 have a path.
2. **All nets together**, negotiated congestion (PathFinder), 4 variants in parallel: one variant (short nets first) reached
   **0 unrouted pads and 0 conflicts** in 9 iterations; the others stalled (4 / 228 / 221 conflicts), so net order matters for an autorouter.
3. **GND pour**: all 28 GND pads end up in one copper area (both layers poured, pads connect through the through-hole pins).
4. **Supply widening** (share of the track with room for 0.5 mm): +3V3 85 %, BBB_3V3 76 %, +5V_SYN 74 %, 5V_EXT 67 %, +5V 62 %, +3V3_ATT 60 %,
   +5V_DET 54 %, BBB_5V 49 %. Route supplies first for wide tracks.

## Numbers
- Track 1547 mm (F.Cu 1057 mm, B.Cu 490 mm), 23 vias (14 nets use a via, at most 3 per net). Before the RPi removal: 1994 mm and 40 vias.
- Busiest 10 x 10 mm window 26 % of the capacity, so no congestion. Pictures: `routability/heat.png`, `routability/routed.png` (generator output, not a KiCad render).

| Net | Length | Vias |
|---|---|---|
| SYN_CLK / SYN_DATA / SYN_LE | 67 / 72 / 59 mm | 2 / 3 / 3 |
| SYN_LD / SYN_CE | 54 / 38 mm | 1 / 0 |
| I2C_SCL / I2C_SDA | 56 / 69 mm | 1 / 0 |
| DET_OUT | 28 mm | 0 |
| DET_DIV | 29 mm | 1 |
| BBB_AIN0 | 24 mm | 0 |
| ADS_A0 | 10 mm | 0 |

The shared SPI nets are shorter than before (59 to 72 mm instead of 93 to 113 mm) because there is no second SBC side any more.

## Points to watch when routing for real
- DET_DIV (divider to the ADC tap) runs 14.5 mm within 2.54 mm of a digital track in the autorouted result, closest 0.76 mm: keep it away from I2C/SPI or guard it with AGND.
- DET_OUT 2.5 mm within 2.54 mm of digital, BBB_AIN0 and ADS_A0 clean.
- Autorouter ignores 45 degree geometry, pour clearances and AGND/GND split; treat the lengths as estimates.
- DRC and ERC were never run in KiCad.
