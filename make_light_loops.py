# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Make the control-band loops the pars sample in Resolume.

    uv run make_light_loops.py                 # 1920x120, 120 bpm, into content/light-loops
    uv run make_light_loops.py --bpm 140
    uv run make_light_loops.py --size 1920x160

The band is not projected: it is a strip of the composition that only the
Lumiverse fixtures look at. Where each fixture sits on it comes from band.py
(patch order, left to right; a pixel bar is twice as wide as a par), so these
loops, the looks rendered as clips, and the Lumiverse patch all agree.

The movement clips are white on black on purpose. Colour comes from a Solid
Color layer underneath, or a Colorize on top, so one loop serves every mood.
`hue-sweep` is the exception, for when you want the colour to travel by itself.

Everything loops seamlessly and is written at the given tempo, so Resolume can
resync it to the composition. ffmpeg does the encoding.
"""
import argparse, json, math, os, shutil, subprocess, sys
import numpy as np
import band

HERE = os.path.dirname(os.path.abspath(__file__))


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def cell_mask(w, cells):
    """Which fixture's cell each pixel column belongs to (from band.py)."""
    idx = np.zeros(w, int)
    for i, c in enumerate(band.layout(width=w)):
        idx[c["x0"]:c["x1"]] = i
    return idx, None


# Each generator returns an (h, w, 3) float image in 0..1 for a phase 0..1
# through the loop. `bars` says how long the loop is, in bars.
def gen_wave(t, w, h, cells):
    x = np.linspace(0, 1, w)
    v = 0.5 + 0.5 * np.sin(2 * math.pi * (x * 1.0 - t))
    return np.repeat((v ** 1.6)[None, :, None], h, 0).repeat(3, 2)


def gen_chase(t, w, h, cells):
    x = np.linspace(0, 1, w)
    d = np.abs(((x - t + 0.5) % 1.0) - 0.5)          # distance to the moving head
    # wide enough that a par reaches full as the head passes its cell centre
    v = np.clip(1 - d / 0.22, 0, 1) ** 1.5
    return np.repeat(v[None, :, None], h, 0).repeat(3, 2)


def gen_pingpong(t, w, h, cells):
    pos = 1 - abs(2 * t - 1)                          # 0 -> 1 -> 0
    x = np.linspace(0, 1, w)
    v = np.clip(1 - np.abs(x - pos) / 0.22, 0, 1) ** 1.5
    return np.repeat(v[None, :, None], h, 0).repeat(3, 2)


def gen_breathe(t, w, h, cells):
    v = 0.5 - 0.5 * math.cos(2 * math.pi * t)
    return np.full((h, w, 3), v ** 1.4, np.float32)


def gen_pulse(t, w, h, cells, beats=4):
    phase = (t * beats) % 1.0
    v = math.exp(-phase * 6)
    return np.full((h, w, 3), v, np.float32)


def gen_strobe(t, w, h, cells, per_bar=8):
    v = 1.0 if (int(t * per_bar) % 2 == 0) else 0.0
    return np.full((h, w, 3), v, np.float32)


def gen_alternate(t, w, h, cells, beats=4):
    idx, _ = cell_mask(w, cells)
    odd = (idx % 2 == 0) if int(t * beats) % 2 == 0 else (idx % 2 == 1)
    v = odd.astype(np.float32)
    return np.repeat(v[None, :, None], h, 0).repeat(3, 2)


def gen_build(t, w, h, cells):
    """Gets brighter and busier across the loop: for the last bars of a build."""
    x = np.linspace(0, 1, w)
    speed = 2 + 14 * t
    flicker = 0.5 + 0.5 * np.sin(2 * math.pi * (x * 2 - t * speed))
    level = smoothstep(t) * 0.9 + 0.1
    return np.repeat((flicker * level)[None, :, None], h, 0).repeat(3, 2)


def hsv_to_rgb(hue, s=1.0, v=1.0):
    h6 = (hue % 1.0) * 6
    i = np.floor(h6).astype(int)
    f = h6 - i
    p, q, t_ = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    out = np.zeros(hue.shape + (3,), np.float32)
    for k, (r, g, b) in enumerate([(v, t_, p), (q, v, p), (p, v, t_),
                                   (p, q, v), (t_, p, v), (v, p, q)]):
        m = i % 6 == k
        out[m] = np.stack([np.broadcast_to(c, hue.shape)[m] if np.ndim(c) else
                           np.full(m.sum(), c) for c in (r, g, b)], -1)
    return out


def gen_hue_sweep(t, w, h, cells):
    x = np.linspace(0, 1, w)
    rgb = hsv_to_rgb((x * 0.8 - t) % 1.0)
    return np.repeat(rgb[None, :, :], h, 0)


def gen_identify(t, w, h, cells):
    """One cell at a time, in order, with the rest dark: check the patch with it."""
    idx, _ = cell_mask(w, cells)
    step = int(t * (cells + 2))                        # a beat per cell, then two dark
    v = (idx == step).astype(np.float32)
    img = np.repeat(v[None, :, None], h, 0).repeat(3, 2)
    edges = (np.diff(idx, prepend=idx[0]) != 0)
    img[:, edges] = np.maximum(img[:, edges], 0.12)    # faint cell dividers
    return img


LOOPS = [
    # name, generator, bars, what it is for
    ("wave",      gen_wave,      2, "a smooth sine travelling left to right"),
    ("chase",     gen_chase,     2, "a soft head sweeping left to right"),
    ("pingpong",  gen_pingpong,  4, "a head sweeping out and back"),
    ("breathe",   gen_breathe,   4, "the whole rig swelling and falling"),
    ("pulse",     gen_pulse,     1, "a hit on every beat, decaying"),
    ("strobe",    gen_strobe,    1, "eighth-note strobe"),
    ("alternate", gen_alternate, 1, "odd and even pars flipping each beat"),
    ("build",     gen_build,     4, "brighter and busier toward the end"),
    ("hue-sweep", gen_hue_sweep, 4, "colour travelling across the pars"),
    ("identify",  gen_identify,  4, "one fixture at a time, in patch order, to check it"),
]


def render(name, fn, bars, w, h, fps, bpm, out_dir, cells, crf):
    seconds = bars * 4 * 60 / bpm
    frames = max(1, round(seconds * fps))
    path = os.path.join(out_dir, f"{name}.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(frames):
        img = fn(i / frames, w, h, cells)             # phase 0..1, never reaching 1
        p.stdin.write((np.clip(img, 0, 1) * 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg failed on {name}")
    return path, frames, seconds


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", default="1920x120", help="the control band, WxH")
    ap.add_argument("--bpm", type=float, help="default: the tempo in show.json")
    # 60 fps so eighth notes land on whole frames at any sensible tempo
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--cells", type=int, help=argparse.SUPPRESS)   # now from band.py
    ap.add_argument("--crf", type=int, default=14, help="lower is better quality")
    ap.add_argument("--out", default=os.path.join(HERE, "content", "light-loops"))
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found - install it, or use Resolume Alley to convert")
    w, h = (int(v) for v in a.size.lower().split("x"))
    a.bpm = a.bpm or float(band.load("show.json", {}).get("tempo") or 120)
    cells = band.layout(width=w)
    a.cells = len(cells)
    os.makedirs(a.out, exist_ok=True)

    print(f"[loops] {w}x{h}, {a.cells} fixtures, {a.bpm:g} bpm, {a.fps} fps -> {a.out}\n")
    lines = [f"# Control-band loops",
             "",
             f"{w}x{h}, {a.cells} fixtures left to right in patch order, "
             f"written at {a.bpm:g} bpm.",
             "",
             "White on black on purpose: colour comes from a Solid Color layer under",
             "them, or a Colorize on top. `hue-sweep` is the one exception.",
             "",
             "| clip | bars | what |",
             "|---|---|---|"]
    for name, fn, bars, what in LOOPS:
        path, frames, seconds = render(name, fn, bars, w, h, a.fps, a.bpm, a.out,
                                       a.cells, a.crf)
        size_kb = os.path.getsize(path) / 1024
        print(f"  {name:<10} {bars} bar(s)  {seconds:4.1f}s  {frames:3d} frames  {size_kb:6.0f} KB")
        lines.append(f"| `{name}.mp4` | {bars} | {what} |")

    lines += ["",
              "## Where the fixtures sample",
              "",
              "From `band.py` (run `python3 band.py` to print it). In the Lumiverse, put",
              "each par on its sample point, and stretch each bar's pixels from its first",
              "sample to its last:",
              "",
              "| fixture | cell | samples |", "|---|---|---|"]
    for c in cells:
        sm = c["samples"]
        lines.append(f"| {c['name']} | {c['x0']}–{c['x1']} | " +
                     (f"x {sm[0]}" if len(sm) == 1 else f"x {sm[0]} → {sm[-1]} ({len(sm)} pixels)") + " |")
    lines += ["",
              "Play `identify.mp4` and watch the previz (or the real rig): the pars",
              "should light one at a time, left to right, in patch order. If they do not,",
              "the fixtures are in the wrong cells.",
              ""]
    open(os.path.join(a.out, "README.md"), "w").write("\n".join(lines))
    # the same, for the Band view: how long each loop is, and at what tempo
    json.dump({"bpm": a.bpm, "fps": a.fps, "size": [w, h],
               "loops": [{"file": f"{n}.mp4", "name": n, "bars": b, "what": wh}
                         for n, _, b, wh in LOOPS]},
              open(os.path.join(a.out, "loops.json"), "w"), indent=1)
    print(f"\n[loops] wrote {len(LOOPS)} clips and README.md")


if __name__ == "__main__":
    main()
