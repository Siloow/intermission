"""The control band: where each fixture samples, and looks rendered onto it.

    python3 band.py                      print the layout, for patching the Lumiverse
    python3 band.py --look "Deep blue"   render one look to content/light-looks/

The band is a strip of the composition that only the Lumiverse fixtures look
at (1920x120 by default). This file is the one place that says which part of
it belongs to which fixture, so the loops, the looks and the patch agree.

Fixtures sit left to right in patch order (DMX address). A par is one unit
wide and samples its centre; a pixel bar is two units wide and samples each of
its pixels along a line across its cell. With 8 pars and 4 bars that is 16
units of 120 px.

Standard library only: the looks are written as PNG with zlib.
"""
import argparse, json, os, struct, zlib
import showfolder

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 120
LOOK_DIR = showfolder.path("light-looks")
UNITS = {"par": 1, "bar": 2}


def load(name, default):
    """A JSON file of the show's (rig, looks, show); fixtures.json is the tools' own."""
    where = HERE if name == "fixtures.json" else showfolder.root()
    try:
        return json.load(open(os.path.join(where, name)))
    except (OSError, ValueError):
        return default


def layout(rig=None, profiles=None, width=W):
    """[{name, kind, x0, x1, samples: [x, ...]}] in band pixels, left to right."""
    rig = rig or load("rig.json", {"fixtures": []})
    profiles = profiles or load("fixtures.json", {}).get("profiles", load("fixtures.json", {}))
    fx = sorted(rig.get("fixtures", []), key=lambda f: (f.get("address") or 9999, f["name"]))
    cells = []
    for f in fx:
        prof = profiles.get(f.get("profile"), {}) if isinstance(profiles, dict) else {}
        pixels = int(prof.get("pixels") or 1) if f.get("mode") != "6ch" else 1
        kind = "bar" if pixels > 1 else "par"
        cells.append((f["name"], kind, pixels))
    total = sum(UNITS[k] for _, k, _ in cells) or 1
    unit = width / total
    out, x = [], 0.0
    for name, kind, pixels in cells:
        w = UNITS[kind] * unit
        samples = [round(x + w * (i + 0.5) / pixels) for i in range(pixels)]
        out.append({"name": name, "kind": kind, "x0": round(x), "x1": round(x + w),
                    "samples": samples})
        x += w
    return out


def rgb_of(v):
    """A look's RGBW + dim, as the RGB the band has to carry (as the timeline shows it)."""
    k = (v.get("dim", 255) if v.get("dim") is not None else 255) / 255
    w = v.get("w", 0) or 0
    return tuple(int(min(255, c) * k) for c in
                 (v.get("r", 0) + w, v.get("g", 0) + w * 0.92, v.get("b", 0) + w * 0.82))


def png(width, height, rows):
    """rows: bytes of RGB per row."""
    raw = b"".join(b"\x00" + r for r in rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def safe_name(name):
    return "".join(ch for ch in name if ch not in '/\\:*?"<>|').strip() or "look"


def render_look(look, width=W, height=H, out_dir=LOOK_DIR):
    """Write a look as a still of the band. Returns the file path.

    Each fixture's whole cell gets its colour, so a sample that lands a pixel
    off still reads right. Fixtures the look leaves out are black."""
    row = bytearray(width * 3)
    for cell in layout(width=width):
        v = (look.get("fixtures") or {}).get(cell["name"])
        if not v:
            continue
        r, g, b = rgb_of(v)
        for x in range(cell["x0"], min(width, cell["x1"])):
            row[x * 3:x * 3 + 3] = bytes((r, g, b))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, safe_name(look["name"]) + ".png")
    tmp = path + ".tmp"
    open(tmp, "wb").write(png(width, height, [bytes(row)] * height))
    os.replace(tmp, path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--look", help="render this look (or 'all')")
    a = ap.parse_args()
    if a.look:
        looks = load("looks.json", {"looks": []})["looks"]
        chosen = looks if a.look == "all" else [l for l in looks if l["name"] == a.look]
        if not chosen:
            raise SystemExit(f"no look called {a.look!r}")
        for l in chosen:
            print("  " + os.path.relpath(render_look(l), showfolder.root()))
        return
    print(f"\n  control band {W}x{H}, left to right in patch order\n")
    for c in layout():
        s = c["samples"]
        where = f"x {s[0]}" if len(s) == 1 else f"x {s[0]} → {s[-1]}, {len(s)} pixels"
        print(f"  {c['name']:<8} {c['kind']:<4} cell {c['x0']:>4}-{c['x1']:<4}  samples {where}")
    print()


if __name__ == "__main__":
    main()
