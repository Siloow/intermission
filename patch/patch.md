# Lighting patch

Generated from `venue.blend` by `export_patch.py`. This is the contract:
Resolume, the real rig and the previz all follow this table. Change it in
`build_venue.py`, rebuild, re-export.

- Universe **0**, channels **1-320** of 512
- **8 pars** (GM Light RGBW IP65 7x10, 25 deg, 4 channels each) and **4 bars** (Showtec Pixel Bar 18 Q4, 18 deg, 18 pixels in 72 channels each)
- Positions are metres from where the performer sits, seen from above:
  +X is stage left, +Y is toward the audience, 0 deg is facing the audience

## Patch table

| fixture | address | channels | side | distance | angle | x | y |
|---|---|---|---|---|---|---|---|
| BAR_01 | **33** | 33-104 (R/G/B/W) | stage right | 4.3 m | -102° | -4.20 | -0.90 |
| BAR_02 | **105** | 105-176 (R/G/B/W) | stage right | 1.84 m | -119° | -1.60 | -0.90 |
| BAR_03 | **177** | 177-248 (R/G/B/W) | stage left | 2.25 m | +45° | +1.59 | +1.59 |
| BAR_04 | **249** | 249-320 (R/G/B/W) | stage left | 4.3 m | +102° | +4.20 | -0.90 |
| PAR_01 | **1** | 1-4 (R/G/B/W) | stage right | 2.2 m | -150° | -1.10 | -1.91 |
| PAR_02 | **5** | 5-8 (R/G/B/W) | stage right | 2.2 m | -120° | -1.91 | -1.10 |
| PAR_03 | **9** | 9-12 (R/G/B/W) | stage right | 2.2 m | -90° | -2.20 | +0.00 |
| PAR_04 | **13** | 13-16 (R/G/B/W) | stage right | 2.2 m | -50° | -1.69 | +1.41 |
| PAR_05 | **17** | 17-20 (R/G/B/W) | stage left | 2.2 m | +50° | +1.69 | +1.41 |
| PAR_06 | **21** | 21-24 (R/G/B/W) | stage left | 2.2 m | +90° | +2.20 | +0.00 |
| PAR_07 | **25** | 25-28 (R/G/B/W) | stage left | 2.2 m | +120° | +1.91 | -1.10 |
| PAR_08 | **29** | 29-32 (R/G/B/W) | stage left | 2.2 m | +150° | +1.10 | -1.91 |

## On the fixtures

**Pars** — GM Light LED PAR RGBW IP65 7x10: set each to the **4-channel**
mode (R, G, B, W) and give it the address above. The 8-channel mode adds a
master dimmer and strobe, which pixel mapping cannot reach.

**Bars** — Showtec Pixel Bar 18 Q4 Tour: set each to the **72-channel** mode,
which gives all 18 LEDs their own RGBW. The 6-channel mode makes the whole
bar one colour; if you use it, change the mode in `rig.json` so the previz
matches. Note the bars are IP20 - indoor only, unlike the IP65 pars.

## In Resolume Arena

Everything is pixel mapped, so each fixture is an area of the composition:

1. **Output → Advanced** → add a **Lumiverse** (DMX), set it to **Art-Net**.
2. Target IP: the lighting node on the day. For previz at home use `127.0.0.1`, universe 0.
3. Add **8 par fixtures**, each **1 x 1 pixel**, colour space RGBW,
   at the addresses in the table.
4. Add **4 bar fixtures**, each **18 x 1 pixels**, colour space RGBW,
   at the addresses in the table. Resolume then feeds 18 colours down each bar,
   which is what makes chases across a bar possible.
5. Place each fixture over the part of the composition it should take its colour
   from - a dedicated lighting strip is easier to control than the picture itself.

## On the floor

Measure from the middle of your seat. Angles are from the direction you face
(the audience), positive toward stage left.

- **BAR_01** (bar, address 33-104): 4.3 m out, 102° to stage right
- **BAR_02** (bar, address 105-176): 1.84 m out, 119° to stage right
- **BAR_03** (bar, address 177-248): 2.25 m out, 45° to stage left, turned 15°
- **BAR_04** (bar, address 249-320): 4.3 m out, 102° to stage left
- **PAR_01** (par, address 1-4): 2.2 m out, 150° to stage right, beam 25°
- **PAR_02** (par, address 5-8): 2.2 m out, 120° to stage right, beam 25°
- **PAR_03** (par, address 9-12): 2.2 m out, 90° to stage right, beam 25°
- **PAR_04** (par, address 13-16): 2.2 m out, 50° to stage right, beam 25°
- **PAR_05** (par, address 17-20): 2.2 m out, 50° to stage left, beam 25°
- **PAR_06** (par, address 21-24): 2.2 m out, 90° to stage left, beam 25°
- **PAR_07** (par, address 25-28): 2.2 m out, 120° to stage left, beam 25°
- **PAR_08** (par, address 29-32): 2.2 m out, 150° to stage left, beam 25°

See `floorplan.svg` for the same thing as a drawing.
