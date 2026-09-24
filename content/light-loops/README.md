# Control-band loops

1920x120, 12 fixtures left to right in patch order, written at 120 bpm.

White on black on purpose: colour comes from a Solid Color layer under
them, or a Colorize on top. `hue-sweep` is the one exception.

| clip | bars | what |
|---|---|---|
| `wave.mp4` | 2 | a smooth sine travelling left to right |
| `chase.mp4` | 2 | a soft head sweeping left to right |
| `pingpong.mp4` | 4 | a head sweeping out and back |
| `breathe.mp4` | 4 | the whole rig swelling and falling |
| `pulse.mp4` | 1 | a hit on every beat, decaying |
| `strobe.mp4` | 1 | eighth-note strobe |
| `alternate.mp4` | 1 | odd and even pars flipping each beat |
| `build.mp4` | 4 | brighter and busier toward the end |
| `hue-sweep.mp4` | 4 | colour travelling across the pars |
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
| PAR_07 | 720–840 | x 780 |
| PAR_08 | 840–960 | x 900 |
| BAR_01 | 960–1200 | x 967 → 1193 (18 pixels) |
| BAR_02 | 1200–1440 | x 1207 → 1433 (18 pixels) |
| BAR_03 | 1440–1680 | x 1447 → 1673 (18 pixels) |
| BAR_04 | 1680–1920 | x 1687 → 1913 (18 pixels) |

Play `identify.mp4` and watch the previz (or the real rig): the pars
should light one at a time, left to right, in patch order. If they do not,
the fixtures are in the wrong cells.
