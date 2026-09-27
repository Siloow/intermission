# Control-band presets

1920x120, 12 fixtures, written at 120 bpm. Made in stage space from
rig.json: re-run `uv run make_light_loops.py` after moving fixtures.

White on black on purpose: colour comes from a Solid Color layer under
them, or a Colorize on top. The Colour category carries its own.

## Wash

| clip | bars | what |
|---|---|---|
| `breathe.mp4` | 4 | the whole rig swelling and falling |
| `breathe-slow.mp4` | 8 | the same, over eight bars |
| `glow-drift.mp4` | 8 | every fixture drifting on its own, slowly |
| `candle.mp4` | 2 | a warm, uneven flicker |
| `full.mp4` | 1 | everything on, steady |

## Sweep

| clip | bars | what |
|---|---|---|
| `wave.mp4` | 2 | a smooth sine travelling across the stage |
| `sweep-lr.mp4` | 2 | a soft head crossing the stage, left to right on the plan |
| `sweep-rl.mp4` | 2 | the same, right to left on the plan |
| `pingpong.mp4` | 4 | a head sweeping across and back |
| `sweep-out.mp4` | 2 | from you outward, the nearest first |
| `sweep-in.mp4` | 2 | from the far edges in toward you |
| `rotate.mp4` | 2 | a beam of light going around you |
| `rotate-back.mp4` | 2 | around you the other way |

## Chase

| clip | bars | what |
|---|---|---|
| `chase.mp4` | 1 | eighth notes, zone by zone across the stage |
| `chase-pairs.mp4` | 1 | mirrored pairs, from the middle out |
| `chase-random.mp4` | 2 | one fixture at a time, at random, on the eighths |
| `alternate.mp4` | 1 | odd and even fixtures flipping each beat |
| `sides.mp4` | 1 | stage right, stage left, on the beat |

## Rhythm

| clip | bars | what |
|---|---|---|
| `pulse.mp4` | 1 | a hit on every beat, decaying |
| `pulse-8.mp4` | 1 | a hit on every eighth |
| `kick-snare.mp4` | 1 | hard on 1 and 3, softer on 2 and 4 |
| `offbeat.mp4` | 1 | hits on the and |
| `downbeat.mp4` | 1 | one long hit per bar |
| `gate.mp4` | 1 | a sixteenth-note trance gate |

## Strobe

| clip | bars | what |
|---|---|---|
| `strobe.mp4` | 1 | eighth-note strobe |
| `strobe-16.mp4` | 1 | sixteenth-note strobe, short flashes |
| `strobe-random.mp4` | 2 | fixtures flashing at random, on the sixteenths |
| `blinder.mp4` | 1 | one full flash on the downbeat |

## Build

| clip | bars | what |
|---|---|---|
| `build.mp4` | 4 | brighter and busier toward the end |
| `riser-strobe.mp4` | 4 | a strobe speeding up over four bars |
| `riser-sweep.mp4` | 4 | sweeps speeding up over four bars |
| `fill-up.mp4` | 4 | fixtures joining one by one, outside in |

## Colour

| clip | bars | what |
|---|---|---|
| `hue-sweep.mp4` | 4 | colour travelling across the stage |
| `hue-rotate.mp4` | 4 | colour going around you |
| `two-tone.mp4` | 4 | warm and cool halves, swapping each bar |

## Bars

| clip | bars | what |
|---|---|---|
| `bar-scan.mp4` | 1 | a dot running along each pixel bar |
| `sparkle.mp4` | 2 | pixels and pars twinkling at random |

## Utility

| clip | bars | what |
|---|---|---|
| `identify.mp4` | 4 | one fixture at a time, in patch order, to check it |

## Where the fixtures sample

From `band.py` (run `python3 band.py` to print it). In the Lumiverse, put
each par on its sample point, and stretch each bar's pixels from its first
sample to its last:

| fixture | cell | samples |
|---|---|---|
| PAR_01 | 0–120 | x 60 |
| PAR_02 | 120–240 | x 180 |
| PAR_03 | 240–360 | x 300 |
| PAR_04 | 360–480 | x 420 |
| PAR_05 | 480–600 | x 540 |
| PAR_06 | 600–720 | x 660 |
| PAR_08 | 720–840 | x 780 |
| PAR_07 | 840–960 | x 900 |
| BAR_01 | 960–1200 | x 967 → 1193 (18 pixels) |
| BAR_02 | 1200–1440 | x 1207 → 1433 (18 pixels) |
| BAR_03 | 1440–1680 | x 1447 → 1673 (18 pixels) |
| BAR_04 | 1680–1920 | x 1687 → 1913 (18 pixels) |

Play `identify.mp4` and watch the previz (or the real rig): the fixtures
should light one at a time in patch order. If they do not, the fixtures
are in the wrong cells.
