# Colour clips for the Light colour layer

1920x120, 12 fixtures, at 140 bpm. Made by `uv run make_colour_loops.py`.

They sit on Resolume's Light colour layer, above the white presets on Lights,
in Multiply: the presets move the light, these colour it. Full brightness
everywhere, pars and bars alike; the presets decide how bright.

## Steady

| clip | bars | what |
|---|---|---|
| `amber` | 1 | everything amber |
| `warm white` | 1 | everything a warm, tungsten white |
| `red` | 1 | everything red |
| `magenta` | 1 | everything magenta |
| `violet` | 1 | everything violet |
| `blue` | 1 | everything deep blue |
| `cyan` | 1 | everything cyan |
| `ice` | 1 | everything a pale, cold blue |

## Split

| clip | bars | what |
|---|---|---|
| `bars blue, pars amber` | 1 | the pixel bars blue, the pars amber |
| `bars amber, pars blue` | 1 | the pixel bars amber, the pars blue |
| `sides red, middle ice` | 1 | the outer fixtures red, the middle pale blue |
| `left warm, right cool` | 1 | stage left amber, stage right cyan |

## Change

| clip | bars | what |
|---|---|---|
| `cycle warm` | 16 | amber, red, magenta, round again: four bars each, gliding |
| `cycle cool` | 16 | blue, cyan, violet, round again |
| `cycle all` | 32 | through every colour, slowly |
| `swap amber blue` | 8 | bars and pars trade amber and blue every four bars |
| `swap sides` | 8 | the two sides trade red and cyan every four bars |
| `travel warm cool` | 8 | a warm-to-cool edge sliding across the stage and back |
| `drift warm` | 16 | every fixture drifting between warm colours on its own |
| `drift cool` | 16 | every fixture drifting between cool colours on its own |
| `rainbow` | 16 | a soft rainbow across the stage, turning |
