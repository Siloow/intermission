"""Export the patch from venue.blend: Blender is the source of truth.

    /Applications/Blender.app/Contents/MacOS/Blender -b venue.blend -P export_patch.py

Writes into patch/ :

    patch.json      the whole rig, for any tool that wants to read it
    patch.csv       one row per fixture, for a spreadsheet or the venue
    patch.md        the contract: what to patch in Resolume, what to tape on the floor
    floorplan.svg   top-down plan with positions and addresses, printable

Everything comes from the objects in the .blend, so the previz, Resolume and
the real floor can't drift apart: change build_venue.py, rebuild, re-export.
"""
import bpy, csv, json, math, os

HERE = os.path.dirname(bpy.path.abspath("//"))
OUT = os.path.join(HERE, "patch")


def fixtures():
    out = []
    # real fixtures only: not the hidden spares, and not a bar's individual pixels
    for ob in sorted((o for o in bpy.data.objects
                      if o.get("in_rig") and o.get("kind") in ("par", "bar")),
                     key=lambda o: o.name):
        x, y, _ = ob.location
        x = -x                     # back to the floor plan's terms: +x is the audience's right
        layout = str(ob.get("dmx_layout", "r,g,b,w")).split(",")
        beam = bpy.data.objects.get(ob.name + "_beam")
        kind = ob.get("kind", "par")
        pixels = int(ob.get("pixels", 1))
        mode = str(ob.get("mode", "4ch"))
        footprint = 72 if mode == "72ch" else (6 if mode == "6ch" else
                                               (8 if mode == "8ch" else 4))
        out.append({
            "name": ob.name,
            "kind": kind,
            "profile": str(ob.get("profile", "")),
            "mode": mode,
            "pixels": pixels,
            "universe": int(ob.get("dmx_universe", 0)),
            "address": int(ob["dmx_address"]),
            "channels": layout,
            "footprint": footprint,
            # position relative to the performer, in metres
            "x": round(x, 3),
            "y": round(y, 3),
            "distance": round(math.hypot(x, y), 2),
            # 0 = toward the audience, negative = stage right (as the audience sees it)
            "angle": round(math.degrees(math.atan2(x, y)), 1),
            "beam_deg": round(math.degrees(beam.data.spot_size), 1) if beam else None,
            "rot_deg": round(float(ob.get("rot_deg", 0)), 1) if kind == "bar" else None,
        })
    return out


def side(f):
    return "centre" if abs(f["x"]) < 0.01 else ("stage right" if f["x"] < 0 else "stage left")


def write_csv(rows, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fixture", "kind", "mode", "universe", "address", "last_channel",
                    "pixels", "x_m", "y_m", "distance_m", "angle_deg", "side", "beam_deg"])
        for f in rows:
            w.writerow([f["name"], f["kind"], f["mode"], f["universe"], f["address"],
                        f["address"] + f["footprint"] - 1, f["pixels"],
                        f["x"], f["y"], f["distance"], f["angle"], side(f), f["beam_deg"]])


def write_md(rows, scene, path):
    chans = "R/G/B/W"
    last = max((f["address"] + f["footprint"] - 1) for f in rows) if rows else 0
    pars = [f for f in rows if f["kind"] == "par"]
    bars = [f for f in rows if f["kind"] == "bar"]
    L = [
        "# Lighting patch",
        "",
        "Generated from `venue.blend` by `export_patch.py`. This is the contract:",
        "Resolume, the real rig and the previz all follow this table. Change it in",
        "`build_venue.py`, rebuild, re-export.",
        "",
        f"- Universe **{rows[0]['universe'] if rows else 0}**, channels **1-{last}** of 512",
        f"- **{len(pars)} pars** (GM Light RGBW IP65 7x10, 25 deg, 4 channels each) and "
        f"**{len(bars)} bars** (Showtec Pixel Bar 18 Q4, 18 deg, 18 pixels in 72 channels each)",
        "- Positions are metres from where the performer sits, seen from above:",
        "  +X is stage left, +Y is toward the audience, 0 deg is facing the audience",
        "",
        "## Patch table",
        "",
        "| fixture | address | channels | side | distance | angle | x | y |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in rows:
        L.append(f"| {f['name']} | **{f['address']}** | "
                 f"{f['address']}-{f['address'] + f['footprint'] - 1} ({chans}) | {side(f)} | "
                 f"{f['distance']} m | {f['angle']:+.0f}° | {f['x']:+.2f} | {f['y']:+.2f} |")
    L += [
        "",
        "## On the fixtures",
        "",
        "**Pars** — GM Light LED PAR RGBW IP65 7x10: set each to the **4-channel**",
        "mode (R, G, B, W) and give it the address above. The 8-channel mode adds a",
        "master dimmer and strobe, which pixel mapping cannot reach.",
        "",
        "**Bars** — Showtec Pixel Bar 18 Q4 Tour: set each to the **72-channel** mode,",
        "which gives all 18 LEDs their own RGBW. The 6-channel mode makes the whole",
        "bar one colour; if you use it, change the mode in `rig.json` so the previz",
        "matches. Note the bars are IP20 - indoor only, unlike the IP65 pars.",
        "",
        "## In Resolume Arena",
        "",
        "Everything is pixel mapped, so each fixture is an area of the composition:",
        "",
        "1. **Output → Advanced** → add a **Lumiverse** (DMX), set it to **Art-Net**.",
        f"2. Target IP: the lighting node on the day. For previz at home use `127.0.0.1`, universe {rows[0]['universe'] if rows else 0}.",
        f"3. Add **{len(pars)} par fixtures**, each **1 x 1 pixel**, colour space RGBW,",
        "   at the addresses in the table.",
        f"4. Add **{len(bars)} bar fixtures**, each **18 x 1 pixels**, colour space RGBW,",
        "   at the addresses in the table. Resolume then feeds 18 colours down each bar,",
        "   which is what makes chases across a bar possible.",
        "5. Place each fixture over the part of the composition it should take its colour",
        "   from - a dedicated lighting strip is easier to control than the picture itself.",
        "",
        "## On the floor",
        "",
        "Measure from the middle of your seat. Angles are from the direction you face",
        "(the audience), positive toward stage left.",
        "",
    ]
    for f in rows:
        extra = f", turned {f['rot_deg']:.0f}°" if f["kind"] == "bar" and f.get("rot_deg") else ""
        L.append(f"- **{f['name']}** ({f['kind']}, address {f['address']}-"
                 f"{f['address'] + f['footprint'] - 1}): {f['distance']} m out, "
                 f"{abs(f['angle']):.0f}° to {side(f)}"
                 + (f", beam {f['beam_deg']:.0f}°" if f["beam_deg"] else "") + extra)
    L += ["", "See `floorplan.svg` for the same thing as a drawing.", ""]
    open(path, "w").write("\n".join(L))


def write_svg(rows, scene, path):
    """Top-down plan: screen, stage, seat, pars with addresses. 1 m = 40 px."""
    cfg = scene.get("venue_config", {})
    screen_w = cfg.get("screen", [16, 7, 1.2])[0]
    perf = cfg.get("performer_from_screen", 1.8)
    first_row = cfg.get("screen_to_first_row", 4.0)
    S, M = 40, 170          # margin leaves room for the fixture labels
    half = max(screen_w / 2 + 1, max((abs(f["x"]) for f in rows), default=3) + 2)
    top, bottom = -perf - 0.6, first_row - perf + 1.2
    W, H = int(half * 2 * S) + 2 * M, int((bottom - top) * S) + 2 * M

    def X(x): return M + (x + half) * S
    def Y(y): return M + (y - top) * S

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="Helvetica,Arial" font-size="13">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="20" y="34" font-size="17" font-weight="bold">Floor plan - view from above</text>',
         f'<text x="20" y="56" fill="#666">metres from the performer; the audience is at the bottom</text>']
    # screen
    p.append(f'<line x1="{X(-screen_w/2)}" y1="{Y(-perf)}" x2="{X(screen_w/2)}" y2="{Y(-perf)}" '
             f'stroke="#111" stroke-width="6"/>')
    p.append(f'<text x="{X(0)}" y="{Y(-perf) - 12}" text-anchor="middle">screen ({screen_w:.0f} m)</text>')
    # first row of seats
    p.append(f'<line x1="{X(-half+0.5)}" y1="{Y(first_row - perf)}" x2="{X(half-0.5)}" '
             f'y2="{Y(first_row - perf)}" stroke="#aaa" stroke-width="3" stroke-dasharray="8 6"/>')
    p.append(f'<text x="{X(0)}" y="{Y(first_row - perf) + 20}" text-anchor="middle" fill="#888">'
             f'first row of seats ({first_row:.1f} m from the screen)</text>')
    # metre grid
    for m in range(int(-half), int(half) + 1):
        p.append(f'<line x1="{X(m)}" y1="{Y(top)}" x2="{X(m)}" y2="{Y(bottom)}" stroke="#eee"/>')
    # performer
    p.append(f'<circle cx="{X(0)}" cy="{Y(0)}" r="11" fill="#222"/>')
    p.append(f'<text x="{X(0)} " y="{Y(0) + 28}" text-anchor="middle">you</text>')
    # bars first, drawn as their real length
    for f in [r for r in rows if r["kind"] == "bar"]:
        cx, cy = X(f["x"]), Y(f["y"])
        half = 1.04 / 2 * S
        a = math.radians(f.get("rot_deg") or 0)
        dx, dy = math.cos(a) * half, math.sin(a) * half
        p.append(f'<line x1="{cx - dx}" y1="{cy - dy}" x2="{cx + dx}" y2="{cy + dy}" '
                 f'stroke="#333" stroke-width="10" stroke-linecap="round"/>')
        p.append(f'<line x1="{cx - dx}" y1="{cy - dy}" x2="{cx + dx}" y2="{cy + dy}" '
                 f'stroke="#6fd3e0" stroke-width="5" stroke-linecap="round"/>')
        p.append(f'<text x="{cx}" y="{cy - 12}" text-anchor="middle" font-size="11">'
                 f'{f["name"]} @{f["address"]}</text>')

    # pars
    for f in [r for r in rows if r["kind"] != "bar"]:
        cx, cy = X(f["x"]), Y(f["y"])
        p.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{cx}" y2="{cy}" stroke="#ddd"/>')
        p.append(f'<circle cx="{cx}" cy="{cy}" r="13" fill="#ffd54a" stroke="#333" stroke-width="2"/>')
        p.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="11" font-weight="bold">'
                 f'{f["address"]}</text>')
        lx = cx + (26 if f["x"] >= 0 else -26)
        p.append(f'<text x="{lx}" y="{cy + 4}" text-anchor="{"start" if f["x"] >= 0 else "end"}">'
                 f'{f["name"]}  {f["distance"]:.1f} m  {f["angle"]:+.0f}°</text>')
    p.append(f'<text x="20" y="{H - 20}" fill="#666">numbers in the circles are DMX addresses '
             f'(universe {rows[0]["universe"] if rows else 0})</text>')
    p.append("</svg>")
    open(path, "w").write("\n".join(p))


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = fixtures()
    scene = bpy.context.scene
    # venue_config holds Blender ID property arrays; make them plain lists
    venue = {k: (list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)
             for k, v in dict(scene.get("venue_config", {})).items()}
    json.dump({"venue": venue, "fixtures": rows},
              open(os.path.join(OUT, "patch.json"), "w"), indent=2)
    write_csv(rows, os.path.join(OUT, "patch.csv"))
    write_md(rows, scene, os.path.join(OUT, "patch.md"))
    write_svg(rows, scene, os.path.join(OUT, "floorplan.svg"))
    print(f"[patch] {len(rows)} fixtures -> {OUT} "
          f"(addresses {', '.join(str(f['address']) for f in rows)})")


main()
