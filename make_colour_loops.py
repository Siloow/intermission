# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Make the colour clips for the Light colour layer.

    uv run make_colour_loops.py              # every one, into content/colour-loops
    uv run make_colour_loops.py --list       # what there is

The presets on the Lights layer are white on black: movement only. Light colour
is the layer above them, in Multiply, so whatever colour it holds is the colour
the presets light in, fixture by fixture. These clips are that colour, for the
whole rig (pars and bars), full brightness: the presets decide how bright.

Three kinds:
  Steady  one colour for everything
  Split   two colours, by where the fixtures stand
  Change  colour moving: cycling, swapping, travelling across the stage

Made in stage space from rig.json, like the presets (make_light_loops.py), and
encoded the same way: an mp4 for the browser, DXV for Resolume, looping at the
show's tempo.
"""
import argparse, json, math, os, shutil
import numpy as np
import band
from make_light_loops import Stage, render, card, hsv, TAU

HERE = os.path.dirname(os.path.abspath(__file__))

# colours as RGB 0..1. Saturated on purpose: Multiply only ever takes light
# away, and the fixtures' white LEDs come from Arena splitting the RGB.
C = {
    "amber":      (1.00, 0.42, 0.04),
    "warm white": (1.00, 0.78, 0.50),
    "red":        (1.00, 0.06, 0.02),
    "magenta":    (1.00, 0.05, 0.55),
    "violet":     (0.45, 0.10, 1.00),
    "blue":       (0.05, 0.20, 1.00),
    "cyan":       (0.05, 0.85, 1.00),
    "ice":        (0.65, 0.85, 1.00),
}
col = lambda n: np.array(C[n])


def steady(name):
    return lambda t, S, B: np.tile(col(name), (S.w, 1))


def split(where, a, b):
    """Colour a where `where(S)` is true, else b."""
    return lambda t, S, B: np.where(where(S)[:, None], col(a), col(b))


def blend(a, b, x):
    x = np.clip(np.asarray(x, dtype=float), 0, 1)[..., None]
    return np.asarray(a) * (1 - x) + np.asarray(b) * x


def smooth(x):
    return 0.5 - 0.5 * np.cos(math.pi * np.clip(x, 0, 1))


def through(names):
    """A loop through these colours, an equal share each, gliding between them."""
    stops = [col(n) for n in names]
    def fn(t, S, B):
        k = t * len(stops)
        i = int(k) % len(stops)
        f = k - int(k)
        a, b = stops[i], stops[(i + 1) % len(stops)]
        c = blend(a, b, smooth((f - 0.6) / 0.4))       # hold, then glide over the last 40%
        return np.tile(c, (S.w, 1))
    return fn


def swap(a, b, where):
    """Two colours trading places each half of the loop, crossfading."""
    def fn(t, S, B):
        half = (t * 2) % 1.0
        x = smooth((half - 0.8) / 0.2)                   # glide over the last fifth of each half
        first = t < 0.5
        p, q = (col(a), col(b)) if first else (col(b), col(a))
        here = blend(p, q, x)
        there = blend(q, p, x)
        return np.where(where(S)[:, None], here, there)
    return fn


def travel(a, b):
    """A soft edge between two colours travelling across the stage and back."""
    def fn(t, S, B):
        edge = 0.5 - 0.5 * math.cos(TAU * t)              # 0 .. 1 .. 0 over the loop
        x = smooth((S.UX - edge) / 0.35 + 0.5)
        return blend(col(a), col(b), x)
    return fn


def drift(names):
    """Each fixture drifting slowly between the colours of a palette, on its own."""
    stops = np.array([col(n) for n in names])
    def fn(t, S, B):
        ph = (t + S.fix_rand[S.FI, 0]) % 1.0 * len(stops)
        i = ph.astype(int) % len(stops)
        f = smooth(ph - np.floor(ph))
        return stops[i] * (1 - f[:, None]) + stops[(i + 1) % len(stops)] * f[:, None]
    return fn


def rainbow(t, S, B):
    return hsv(S.UX * 0.25 + t, 0.9)


is_bar = lambda S: S.BAR
is_left = lambda S: S.SIDE < 0
is_outer = lambda S: S.AX > 0.5

CATEGORIES = ["Steady", "Split", "Change"]
LOOPS = [
    ("amber",           steady("amber"),        1, "Steady", "everything amber"),
    ("warm white",      steady("warm white"),   1, "Steady", "everything a warm, tungsten white"),
    ("red",             steady("red"),          1, "Steady", "everything red"),
    ("magenta",         steady("magenta"),      1, "Steady", "everything magenta"),
    ("violet",          steady("violet"),       1, "Steady", "everything violet"),
    ("blue",            steady("blue"),         1, "Steady", "everything deep blue"),
    ("cyan",            steady("cyan"),         1, "Steady", "everything cyan"),
    ("ice",             steady("ice"),          1, "Steady", "everything a pale, cold blue"),

    ("bars blue, pars amber", split(is_bar, "blue", "amber"),   1, "Split", "the pixel bars blue, the pars amber"),
    ("bars amber, pars blue", split(is_bar, "amber", "blue"),   1, "Split", "the pixel bars amber, the pars blue"),
    ("sides red, middle ice", split(is_outer, "red", "ice"),    1, "Split", "the outer fixtures red, the middle pale blue"),
    ("left warm, right cool", split(is_left, "amber", "cyan"),  1, "Split", "stage left amber, stage right cyan"),

    ("cycle warm",      through(["amber", "red", "magenta"]),          16, "Change", "amber, red, magenta, round again: four bars each, gliding"),
    ("cycle cool",      through(["blue", "cyan", "violet"]),           16, "Change", "blue, cyan, violet, round again"),
    ("cycle all",       through(["amber", "red", "magenta", "violet", "blue", "cyan"]), 32, "Change", "through every colour, slowly"),
    ("swap amber blue", swap("amber", "blue", is_bar),                 8, "Change", "bars and pars trade amber and blue every four bars"),
    ("swap sides",      swap("red", "cyan", is_left),                   8, "Change", "the two sides trade red and cyan every four bars"),
    ("travel warm cool", travel("amber", "blue"),                       8, "Change", "a warm-to-cool edge sliding across the stage and back"),
    ("drift warm",      drift(["amber", "warm white", "red"]),          16, "Change", "every fixture drifting between warm colours on its own"),
    ("drift cool",      drift(["blue", "ice", "violet"]),               16, "Change", "every fixture drifting between cool colours on its own"),
    ("rainbow",         rainbow,                                         16, "Change", "a soft rainbow across the stage, turning"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", default="1920x120", help="the control band, WxH")
    ap.add_argument("--bpm", type=float, help="default: the tempo in show.json")
    ap.add_argument("--fps", type=int, default=30, help="colour moves slowly: 30 is plenty")
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--only", help="comma-separated names")
    ap.add_argument("--list", action="store_true", help="print them and stop")
    ap.add_argument("--out", default=os.path.join(HERE, "content", "colour-loops"))
    a = ap.parse_args()
    if a.list:
        for cat in CATEGORIES:
            print(f"\n  {cat}")
            for n, _, b, c, what in LOOPS:
                if c == cat:
                    print(f"    {n:<24} {b:>2} bar{'s' if b > 1 else ' '}  {what}")
        return
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found")
    w, h = (int(v) for v in a.size.lower().split("x"))
    a.bpm = a.bpm or float(band.load("show.json", {}).get("tempo") or 120)
    S = Stage(w)
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    print(f"[colour] {w}x{h}, {S.n} fixtures, {a.bpm:g} bpm -> {a.out}\n")
    for name, fn, bars, cat, what in LOOPS:
        if only and name not in only:
            continue
        path, frames, seconds = render(name, fn, bars, S, h, a.fps, a.bpm, a.out, a.crf)
        card(name, fn, bars, S, a.out)
        print(f"  {cat:<7} {name:<24} {bars:>2} bar(s)  {seconds:5.1f}s")
    json.dump({"bpm": a.bpm, "fps": a.fps, "size": [w, h], "categories": CATEGORIES,
               "loops": [{"file": f"{n}.mp4", "name": n, "bars": b, "category": c, "what": wh,
                          "card": f"{n}.png", "colour": True} for n, _, b, c, wh in LOOPS]},
              open(os.path.join(a.out, "loops.json"), "w"), indent=1)
    lines = ["# Colour clips for the Light colour layer", "",
             f"{w}x{h}, {S.n} fixtures, at {a.bpm:g} bpm. Made by `uv run make_colour_loops.py`.", "",
             "They sit on Resolume's Light colour layer, above the white presets on Lights,",
             "in Multiply: the presets move the light, these colour it. Full brightness",
             "everywhere, pars and bars alike; the presets decide how bright.", ""]
    for cat in CATEGORIES:
        lines += [f"## {cat}", "", "| clip | bars | what |", "|---|---|---|"]
        lines += [f"| `{n}` | {b} | {what} |" for n, _, b, c, what in LOOPS if c == cat]
        lines.append("")
    open(os.path.join(a.out, "README.md"), "w").write("\n".join(lines))
    print(f"\n[colour] wrote {len(LOOPS) if not only else len(only)} clip(s), loops.json and README.md")


if __name__ == "__main__":
    main()
