# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Make the control-band presets the fixtures sample in Resolume.

    uv run make_light_loops.py                 # every preset, into content/light-loops
    uv run make_light_loops.py --only chase,rotate
    uv run make_light_loops.py --bpm 140       # default: the tempo in show.json
    uv run make_light_loops.py --list          # the presets, by category

The band is not projected: it is a strip of the composition that only the
Lumiverse fixtures look at. Where each fixture sits on it comes from band.py.

The presets are made in STAGE space, not band space: each one is a function of
where a fixture really stands (from rig.json) — its stage x, its distance and
angle from you, and for a pixel bar where each pixel is along it. So "sweep
left to right" crosses the stage, "rotate" goes around you, and a bar shows a
sweep passing through it pixel by pixel. Move the fixtures in the floor plan,
and run this again to follow.

Movement presets are white on black: colour comes from a Solid Color layer
under them, or a Colorize on top, so one preset serves every mood. The Colour
category carries its own.

Each preset also gets a pattern card (name.png): the fixtures left to right in
stage order, time running down the loop. A chase reads as a diagonal, a strobe
as stripes — the floor plan's preset browser shows them.

Everything loops seamlessly at the given tempo. ffmpeg does the encoding.
"""
import argparse, json, math, os, shutil, subprocess, sys
import numpy as np
import band

HERE = os.path.dirname(os.path.abspath(__file__))
TAU = 2 * math.pi


# ------------------------------------------------------------ the stage ------
class Stage:
    """Per band column: where the fixture (or bar pixel) it feeds stands."""
    def __init__(self, w):
        cells = band.layout(width=w)
        rig = {f["name"]: f for f in band.load("rig.json", {"fixtures": []}).get("fixtures", [])}
        profiles = band.load("fixtures.json", {}).get("profiles", {})
        self.w, self.cells, self.n = w, cells, len(cells)
        X, Y, FI, K, BAR = (np.zeros(w) for _ in range(5))
        for i, c in enumerate(cells):
            f = rig.get(c["name"], {})
            cols = np.arange(c["x0"], min(w, c["x1"]))
            x, y = float(f.get("x", 0)), float(f.get("y", 0))
            FI[cols] = i
            if c["kind"] == "bar":
                n = len(c["samples"])
                k = np.minimum(((cols - c["x0"]) / max(1, c["x1"] - c["x0"]) * n).astype(int), n - 1)
                frac = (k + 0.5) / n
                L = float((profiles.get(f.get("profile"), {}).get("body") or {}).get("length", 1.04))
                rot = math.radians(f.get("rot_deg") or 0)
                X[cols] = x + math.cos(rot) * L * (frac - 0.5)
                Y[cols] = y + math.sin(rot) * L * (frac - 0.5)
                K[cols], BAR[cols] = frac, 1
            else:
                X[cols], Y[cols], K[cols] = x, y, 0.5
        self.X, self.Y, self.FI, self.K, self.BAR = X, Y, FI.astype(int), K, BAR.astype(bool)
        span = max(1e-6, X.max() - X.min())
        self.UX = (X - X.min()) / span                         # 0 stage right .. 1 stage left
        self.R = np.hypot(X, Y)
        self.RN = (self.R - self.R.min()) / max(1e-6, self.R.max() - self.R.min())
        self.ANG = np.arctan2(X, Y)                            # 0 toward the audience
        self.AX = np.abs(X) / max(1e-6, np.abs(X).max())       # 0 centre .. 1 the far sides
        # each fixture's own stage-x rank, for chases that go fixture by fixture
        fx = np.array([float(rig.get(c["name"], {}).get("x", 0)) for c in cells])
        rank = np.argsort(np.argsort(fx))
        self.RANK = rank[self.FI]
        self.SIDE = np.where(np.array([fx[i] for i in self.FI]) < 0, -1, 1)
        rng = np.random.default_rng(7)                         # the same "random" every run
        self.fix_rand = rng.random((self.n, 8))                # per fixture
        self.col_rand = rng.random((w, 4))                     # per column (bar pixels)

    def per_fixture(self, values):
        """Spread one value per fixture (in patch order) across its columns."""
        return np.asarray(values)[self.FI]


def head(d, width, sharp=1.5):
    """A soft bright head: 1 at d=0, fading to 0 at |d| = width."""
    return np.clip(1 - np.abs(d) / width, 0, 1) ** sharp


def wrap(d):
    return (d + 0.5) % 1.0 - 0.5


def env(phase, speed):
    """An exponential decay through each step: a hit."""
    return np.exp(-np.asarray(phase) * speed)


def hsv(h, s=1.0, v=1.0):
    h = np.asarray(h) % 1.0
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    table = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,))
    for k, (r, g, b) in enumerate(table):
        m = i == k
        for ch, val in enumerate((r, g, b)):
            out[..., ch][m] = (np.broadcast_to(val, h.shape))[m]
    return out


# ---------------------------------------------------------------- presets ----
# Each takes (t, S, beats): t is 0..1 through the loop, S the Stage, beats how
# many beats the loop lasts. It returns a value per column (0..1), or RGB.
def p_breathe(t, S, B):     return np.full(S.w, (0.5 - 0.5 * math.cos(TAU * t)) ** 1.4)
def p_glow_drift(t, S, B):
    r = S.fix_rand
    v = 0.4 + 0.3 * np.sin(TAU * (t + r[:, 0])) + 0.15 * np.sin(TAU * (2 * t + r[:, 1]))
    return S.per_fixture(np.clip(v, 0, 1))
def p_candle(t, S, B):
    r = S.fix_rand
    v = (0.55 + 0.18 * np.sin(TAU * (3 * t + r[:, 2])) + 0.12 * np.sin(TAU * (7 * t + r[:, 3]))
         + 0.08 * np.sin(TAU * (13 * t + r[:, 4])))
    return S.per_fixture(np.clip(v, 0, 1) * 0.8)
def p_full(t, S, B):        return np.ones(S.w)

def p_wave(t, S, B):        return (0.5 + 0.5 * np.sin(TAU * (S.UX - t))) ** 1.6
def p_sweep_lr(t, S, B):    return head(S.UX - (t * 1.4 - 0.2), 0.18)
def p_sweep_rl(t, S, B):    return head(S.UX - (1.2 - t * 1.4), 0.18)
def p_pingpong(t, S, B):    return head(S.UX - (-0.1 + 1.2 * (1 - abs(2 * t - 1))), 0.16)
def p_sweep_out(t, S, B):   return head(S.RN - (t * 1.4 - 0.2), 0.2)
def p_sweep_in(t, S, B):    return head(S.RN - (1.2 - t * 1.4), 0.2)
def p_rotate(t, S, B):      return head(wrap(S.ANG / TAU - t), 0.12)
def p_rotate_back(t, S, B): return head(wrap(S.ANG / TAU + t), 0.12)

def _steps(t, B, per_beat):
    s = t * B * per_beat
    return np.floor(s).astype(int), s - np.floor(s)
def p_chase(t, S, B):
    s, f = _steps(t, B, 2)                                     # 8ths, 8 zones across the stage
    zone = np.minimum((S.UX * 8).astype(int), 7)
    return (zone == s % 8) * env(f, 2.5)
def p_chase_pairs(t, S, B):
    s, f = _steps(t, B, 2)                                     # from the middle out, mirrored
    zone = np.minimum((S.AX * 4).astype(int), 3)
    return (zone == s % 4) * env(f, 2.5)
def p_chase_random(t, S, B):
    s, f = _steps(t, B, 2)
    pick = int(S.fix_rand[s % S.n, 5] * 997 + s * 31) % S.n  # one fixture per step, fixed per step
    return (S.FI == pick) * env(f, 3)
def p_alternate(t, S, B):
    s, f = _steps(t, B, 1)
    return ((S.RANK % 2) == (s % 2)) * env(f, 1.2)
def p_sides(t, S, B):
    s, f = _steps(t, B, 1)
    return (S.SIDE == (-1 if s % 2 == 0 else 1)) * env(f, 1.6)

def p_pulse(t, S, B):       s, f = _steps(t, B, 1); return np.full(S.w, env(f, 6))
def p_pulse_8(t, S, B):     s, f = _steps(t, B, 2); return np.full(S.w, env(f, 7))
def p_kick_snare(t, S, B):
    s, f = _steps(t, B, 1)
    return np.full(S.w, env(f, 7) if s % 2 == 0 else 0.6 * env(f, 3.5))
def p_offbeat(t, S, B):
    s, f = _steps((t + 0.5 / B) % 1.0, B, 1)                   # hits on the "and"
    return np.full(S.w, env(f, 7))
def p_downbeat(t, S, B):    return np.full(S.w, env((t * B / 4) % 1.0, 4))
GATE = [1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1]
def p_gate(t, S, B):
    s, f = _steps(t, B, 4)
    return np.full(S.w, 1.0 if GATE[s % 16] and f < 0.7 else 0.0)

def p_strobe(t, S, B):      return np.full(S.w, 1.0 if int(t * B * 2) % 2 == 0 else 0.0)
def p_strobe_16(t, S, B):   s, f = _steps(t, B, 4); return np.full(S.w, 1.0 if f < 0.3 else 0.0)
def p_strobe_random(t, S, B):
    s, f = _steps(t, B, 4)
    on = S.fix_rand[:, (s % 8)] > 0.68 - 0.1 * ((s // 8) % 2)
    return S.per_fixture(on) * (1.0 if f < 0.35 else 0.0)
def p_blinder(t, S, B):     return np.full(S.w, env((t * B / 4) % 1.0, 11))

def p_build(t, S, B):
    speed = 2 + 14 * t
    flicker = 0.5 + 0.5 * np.sin(TAU * (S.UX * 2 - t * speed))
    return flicker * (0.1 + 0.9 * t * t * (3 - 2 * t))
def p_riser_strobe(t, S, B):
    # 2 → 32 flashes a bar over the loop: the phase is the integral of the rate
    bars = B / 4
    phase = bars * (2 * t + 15 * t * t)
    return np.full(S.w, 1.0 if (phase % 1.0) < 0.3 else 0.0) * (0.4 + 0.6 * t)
def p_riser_sweep(t, S, B):
    bars = B / 4
    phase = bars * (0.5 * t + 3.5 * t * t)
    return head(wrap(S.UX - phase % 1.0), 0.14) * (0.4 + 0.6 * t)
def p_fill_up(t, S, B):
    # from the outside in, one fixture at a time, and everything brighter as it goes
    order = np.argsort(np.argsort(-np.array([S.AX[S.FI == i].mean() for i in range(S.n)])))
    lit = int(t * (S.n + 1))
    return S.per_fixture(order < lit) * (0.35 + 0.65 * t)

def p_hue_sweep(t, S, B):   return hsv(S.UX * 0.8 - t)
def p_hue_rotate(t, S, B):  return hsv(S.ANG / TAU + t)
def p_two_tone(t, S, B):
    warm, cool = np.array([1.0, 0.45, 0.08]), np.array([0.08, 0.3, 1.0])
    bars = B / 4
    bar = t * bars
    x = (bar % 1.0)
    swap = int(bar) % 2
    mix = np.clip((x - 0.75) / 0.25, 0, 1) if True else 0          # crossfade over the last quarter bar
    a = warm if swap == 0 else cool
    b = cool if swap == 0 else warm
    left = a * (1 - mix) + b * mix
    right = b * (1 - mix) + a * mix
    return np.where((S.SIDE < 0)[:, None], left, right)

def p_bar_scan(t, S, B):
    pos = (t * B / 2) % 1.0                                    # twice a bar along each bar
    return np.where(S.BAR, head(wrap(S.K - pos), 0.12), 0.0)
def p_sparkle(t, S, B):
    r = S.col_rand
    rate = 1 + (r[:, 0] * 6).astype(int)                       # whole cycles: it loops
    v = np.maximum(0, np.sin(TAU * (rate * t + r[:, 1]))) ** 14
    return v

def p_identify(t, S, B):
    step = int(t * (S.n + 2))                                   # patch order: one at a time
    return (S.FI == step).astype(float)


CATEGORIES = ["Wash", "Sweep", "Chase", "Rhythm", "Strobe", "Build", "Colour", "Bars", "Utility"]
PRESETS = [
    # name,           fn,              bars, category, what
    ("breathe",       p_breathe,       4, "Wash",    "the whole rig swelling and falling"),
    ("breathe-slow",  p_breathe,       8, "Wash",    "the same, over eight bars"),
    ("glow-drift",    p_glow_drift,    8, "Wash",    "every fixture drifting on its own, slowly"),
    ("candle",        p_candle,        2, "Wash",    "a warm, uneven flicker"),
    ("full",          p_full,          1, "Wash",    "everything on, steady"),

    ("wave",          p_wave,          2, "Sweep",   "a smooth sine travelling across the stage"),
    ("sweep-lr",      p_sweep_lr,      2, "Sweep",   "a soft head crossing the stage, left to right on the plan"),
    ("sweep-rl",      p_sweep_rl,      2, "Sweep",   "the same, right to left on the plan"),
    ("pingpong",      p_pingpong,      4, "Sweep",   "a head sweeping across and back"),
    ("sweep-out",     p_sweep_out,     2, "Sweep",   "from you outward, the nearest first"),
    ("sweep-in",      p_sweep_in,      2, "Sweep",   "from the far edges in toward you"),
    ("rotate",        p_rotate,        2, "Sweep",   "a beam of light going around you"),
    ("rotate-back",   p_rotate_back,   2, "Sweep",   "around you the other way"),

    ("chase",         p_chase,         1, "Chase",   "eighth notes, zone by zone across the stage"),
    ("chase-pairs",   p_chase_pairs,   1, "Chase",   "mirrored pairs, from the middle out"),
    ("chase-random",  p_chase_random,  2, "Chase",   "one fixture at a time, at random, on the eighths"),
    ("alternate",     p_alternate,     1, "Chase",   "odd and even fixtures flipping each beat"),
    ("sides",         p_sides,         1, "Chase",   "stage right, stage left, on the beat"),

    ("pulse",         p_pulse,         1, "Rhythm",  "a hit on every beat, decaying"),
    ("pulse-8",       p_pulse_8,       1, "Rhythm",  "a hit on every eighth"),
    ("kick-snare",    p_kick_snare,    1, "Rhythm",  "hard on 1 and 3, softer on 2 and 4"),
    ("offbeat",       p_offbeat,       1, "Rhythm",  "hits on the and"),
    ("downbeat",      p_downbeat,      1, "Rhythm",  "one long hit per bar"),
    ("gate",          p_gate,          1, "Rhythm",  "a sixteenth-note trance gate"),

    ("strobe",        p_strobe,        1, "Strobe",  "eighth-note strobe"),
    ("strobe-16",     p_strobe_16,     1, "Strobe",  "sixteenth-note strobe, short flashes"),
    ("strobe-random", p_strobe_random, 2, "Strobe",  "fixtures flashing at random, on the sixteenths"),
    ("blinder",       p_blinder,       1, "Strobe",  "one full flash on the downbeat"),

    ("build",         p_build,         4, "Build",   "brighter and busier toward the end"),
    ("riser-strobe",  p_riser_strobe,  4, "Build",   "a strobe speeding up over four bars"),
    ("riser-sweep",   p_riser_sweep,   4, "Build",   "sweeps speeding up over four bars"),
    ("fill-up",       p_fill_up,       4, "Build",   "fixtures joining one by one, outside in"),

    ("hue-sweep",     p_hue_sweep,     4, "Colour",  "colour travelling across the stage"),
    ("hue-rotate",    p_hue_rotate,    4, "Colour",  "colour going around you"),
    ("two-tone",      p_two_tone,      4, "Colour",  "warm and cool halves, swapping each bar"),

    ("bar-scan",      p_bar_scan,      1, "Bars",    "a dot running along each pixel bar"),
    ("sparkle",       p_sparkle,       2, "Bars",    "pixels and pars twinkling at random"),

    ("identify",      p_identify,      4, "Utility", "one fixture at a time, in patch order, to check it"),
]
COLOUR = {"Colour"}


def rgb(values):
    v = np.asarray(values, dtype=float)
    return v if v.ndim == 2 else np.repeat(v[:, None], 3, 1)


def render(name, fn, bars, S, h, fps, bpm, out_dir, crf):
    seconds = bars * 4 * 60 / bpm
    frames = max(1, round(seconds * fps))
    beats = bars * 4
    path = os.path.join(out_dir, f"{name}.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{S.w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(frames):
        row = (np.clip(rgb(fn(i / frames, S, beats)), 0, 1) * 255).astype(np.uint8)
        p.stdin.write(np.repeat(row[None], h, 0).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg failed on {name}")
    return path, frames, seconds


def card(name, fn, bars, S, out_dir, rows=48):
    """The pattern card: fixtures left to right in stage order, time down."""
    order = sorted(range(S.n), key=lambda i: float(np.mean(S.X[S.FI == i])))
    cols, width = [], 0
    for i in order:
        c = S.cells[i]
        pts = c["samples"] if c["kind"] == "bar" else [c["samples"][0]] * 8
        cols.append(pts); width += len(pts) + 2
    width -= 2
    img = np.zeros((rows, width, 3))
    for r in range(rows):
        v = np.clip(rgb(fn(r / rows, S, bars * 4)), 0, 1)
        x = 0
        for pts in cols:
            img[r, x:x + len(pts)] = v[pts]
            x += len(pts) + 2
    data = (img * 255).astype(np.uint8)
    png = band.png(width, rows, [bytes(data[r].tobytes()) for r in range(rows)])
    open(os.path.join(out_dir, f"{name}.png"), "wb").write(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", default="1920x120", help="the control band, WxH")
    ap.add_argument("--bpm", type=float, help="default: the tempo in show.json")
    # 60 fps so eighth notes land on whole frames at any sensible tempo
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--crf", type=int, default=14, help="lower is better quality")
    ap.add_argument("--only", help="comma-separated preset names")
    ap.add_argument("--list", action="store_true", help="print the presets and stop")
    ap.add_argument("--out", default=os.path.join(HERE, "content", "light-loops"))
    ap.add_argument("--cells", type=int, help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.list:
        for cat in CATEGORIES:
            print(f"\n  {cat}")
            for n, _, b, c, what in PRESETS:
                if c == cat:
                    print(f"    {n:<14} {b} bar{'s' if b > 1 else ' '}  {what}")
        print(f"\n  {len(PRESETS)} presets\n")
        return
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found - install it, or use Resolume Alley to convert")
    w, h = (int(v) for v in a.size.lower().split("x"))
    a.bpm = a.bpm or float(band.load("show.json", {}).get("tempo") or 120)
    S = Stage(w)
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    todo = [p for p in PRESETS if not only or p[0] in only]

    print(f"[loops] {w}x{h}, {S.n} fixtures, {a.bpm:g} bpm, {a.fps} fps -> {a.out}\n")
    for name, fn, bars, cat, what in todo:
        path, frames, seconds = render(name, fn, bars, S, h, a.fps, a.bpm, a.out, a.crf)
        card(name, fn, bars, S, a.out)
        print(f"  {cat:<8} {name:<14} {bars} bar(s)  {seconds:4.1f}s  {os.path.getsize(path) / 1024:6.0f} KB")

    lines = ["# Control-band presets", "",
             f"{w}x{h}, {S.n} fixtures, written at {a.bpm:g} bpm. Made in stage space from",
             "rig.json: re-run `uv run make_light_loops.py` after moving fixtures.", "",
             "White on black on purpose: colour comes from a Solid Color layer under",
             "them, or a Colorize on top. The Colour category carries its own.", ""]
    for cat in CATEGORIES:
        lines += [f"## {cat}", "", "| clip | bars | what |", "|---|---|---|"]
        lines += [f"| `{n}.mp4` | {b} | {what} |" for n, _, b, c, what in PRESETS if c == cat]
        lines.append("")
    lines += ["## Where the fixtures sample", "",
              "From `band.py` (run `python3 band.py` to print it). In the Lumiverse, put",
              "each par on its sample point, and stretch each bar's pixels from its first",
              "sample to its last:", "", "| fixture | cell | samples |", "|---|---|---|"]
    for c in S.cells:
        sm = c["samples"]
        lines.append(f"| {c['name']} | {c['x0']}–{c['x1']} | " +
                     (f"x {sm[0]}" if len(sm) == 1 else f"x {sm[0]} → {sm[-1]} ({len(sm)} pixels)") + " |")
    lines += ["", "Play `identify.mp4` and watch the previz (or the real rig): the fixtures",
              "should light one at a time in patch order. If they do not, the fixtures",
              "are in the wrong cells.", ""]
    open(os.path.join(a.out, "README.md"), "w").write("\n".join(lines))
    # for the floor plan's preset browser: what each is, how long, which category
    json.dump({"bpm": a.bpm, "fps": a.fps, "size": [w, h], "categories": CATEGORIES,
               "loops": [{"file": f"{n}.mp4", "name": n, "bars": b, "category": c, "what": wh,
                          "card": f"{n}.png", "colour": c in COLOUR}
                         for n, _, b, c, wh in PRESETS]},
              open(os.path.join(a.out, "loops.json"), "w"), indent=1)
    print(f"\n[loops] wrote {len(todo)} preset(s), their cards, loops.json and README.md")


if __name__ == "__main__":
    main()
