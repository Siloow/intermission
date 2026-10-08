#!/usr/bin/env python3
"""Make the show's Resolume composition, for this Mac.

A composition (.avc) is plain XML. This one is written from the templates in
resolume/, cut from a composition Arena 7.19 saved itself, and filled with what
the show already knows, at this Mac's own paths:

    layer 1  TD       TouchDesigner's liveset over Syphon (the live route), column 1
    layer 2  Base     every clip in the Library (Alpha blend, 100%)
    layer 3  Overlay  the Library clips the Overlay lane uses
    layer 4  Lights   the light presets (BPM Sync, no snap), then the looks
    layer 5  Light colour  the colour clips, then the looks: on the band in Multiply, colour for the white presets

The layers keep the template's size, lift and blends (the picture up 60 px, the
light band down 540). Column names, effects and anything else set by hand in
Arena are not carried over: the old composition is kept in Compositions/.backup/.

It is written to ~/Documents/Resolume Arena/Compositions/<name> (default
Intermission.avc). Arena must be closed: an open Arena would save its copy over
the new one.

    python3 make_composition.py              write Intermission.avc
    python3 make_composition.py --name X.avc write another
    python3 make_composition.py --dry-run    say what would go where
"""
import argparse, json, os, re, shutil, socket, string, subprocess, sys, time
import showfolder
import arena_load
import library

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "resolume")
COMPOSITIONS = os.path.expanduser("~/Documents/Resolume Arena/Compositions")
DEFAULT_NAME = "Intermission.avc"
SPARE_COLUMNS = 4                       # empty columns after the last clip, to drop things into
PHASE = 16384.0                         # Arena stores a clip's width/height also as value / 16384
LAYERS = {"td": 0, "screen": 1, "overlay": 2, "lights": 3, "colour": 4}   # the template's layers, bottom up


def tpl(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return string.Template(f.read())


def probe(path):
    """(width, height, seconds) of a video file, from ffprobe."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
                        "-of", "json", path], capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    return int(st.get("width") or 1920), int(st.get("height") or 1080), float((d.get("format") or {}).get("duration") or 4)


def ndi_name():
    """The liveset's NDI name as Arena lists it: "<HOST>.LOCAL (liveset)". osc_map.json
    td.ndi overrides it (TouchDesigner on another Mac)."""
    try:
        m = json.load(open(showfolder.path("osc_map.json")))
        if (m.get("td") or {}).get("ndi"):
            return m["td"]["ndi"]
    except (OSError, ValueError):
        pass
    host = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip() \
        or socket.gethostname().split(".")[0]
    return f"{host.upper()}.LOCAL (liveset)"


def td_source():
    """How TD reaches Arena: Syphon, the live route on this Mac (osc_map.json td.source
    "ndi" switches to the network feed, e.g. TouchDesigner on another Mac). Falls
    back to NDI while there is no Syphon clip template yet."""
    try:
        want = (json.load(open(showfolder.path("osc_map.json"))).get("td") or {}).get("source", "syphon")
    except (OSError, ValueError):
        want = "syphon"
    if want == "syphon" and not os.path.exists(os.path.join(TEMPLATES, "clip_syphon.xml")):
        return "ndi", "no Syphon clip template yet (resolume/clip_syphon.xml): NDI instead"
    return want, None


def syphon_name():
    """The liveset's Syphon server as Arena names it, "<app> - <server>" (osc_map.json
    td.syphon overrides). The set's syphon_out publishes "liveset"."""
    try:
        return (json.load(open(showfolder.path("osc_map.json"))).get("td") or {}).get("syphon") or "TouchDesigner - liveset"
    except (OSError, ValueError):
        return "TouchDesigner - liveset"


def plan():
    """What goes where: {layer index: [clip, ...]}, each clip a dict for its template."""
    out = {i: [] for i in LAYERS.values()}
    src, _ = td_source()
    out[LAYERS["td"]].append({"kind": src, "name": syphon_name() if src == "syphon" else ndi_name()})

    # Base: the Library. Overlay: what the Overlay lane plays.
    clips = [c for c in library.config()["clips"] if os.path.exists(showfolder.path(c["file"]))]
    try:
        cues = json.load(open(showfolder.path("cues.json"))).get("cues", [])
    except (OSError, ValueError):
        cues = []
    on_overlay = {c.get("value") for c in cues if c.get("lane") == "overlay"}
    for c in clips:
        item = {"kind": "free", "name": c["name"], "path": showfolder.path(c["file"])}
        out[LAYERS["screen"]].append(item)
        if c["name"] in on_overlay:
            out[LAYERS["overlay"]].append(item)

    # Lights: the presets, BPM-synced, then the looks rendered as band stills
    folder, files = arena_load.lane_files("lights")
    try:
        bpm = float(json.load(open(os.path.join(folder, "loops.json"))).get("bpm") or 120)
    except (OSError, ValueError):
        bpm = 120.0
    for f in files:
        out[LAYERS["lights"]].append({"kind": "synced", "name": os.path.splitext(f)[0],
                                      "path": os.path.join(folder, f), "bpm": bpm})
    # Light colour: the colour clips (make_colour_loops.py), BPM-synced like the presets
    folder, files = arena_load.lane_files("colour")
    try:
        bpm = float(json.load(open(os.path.join(folder, "loops.json"))).get("bpm") or 120)
    except (OSError, ValueError):
        bpm = 120.0
    for f in files:
        out[LAYERS["colour"]].append({"kind": "synced", "name": os.path.splitext(f)[0],
                                      "path": os.path.join(folder, f), "bpm": bpm})
    # Looks, as band stills, rendered fresh from looks.json: on Lights (a static look)
    # and on Light colour above it (Multiply: the colours the white presets take)
    import band
    try:
        all_looks = json.load(open(showfolder.path("looks.json"))).get("looks", [])
    except (OSError, ValueError):
        all_looks = []
    for look in all_looks:
        out[LAYERS["lights"]].append({"kind": "free", "name": look["name"], "path": band.render_look(look)})
        out[LAYERS["colour"]].append({"kind": "free", "name": look["name"],
                                      "path": band.render_look(look, colour=True)})
    return out


def build(layout):
    """The composition's XML for a layout from plan()."""
    ids = iter(range(int(time.time() * 1000), 10 ** 14))
    nid = lambda: str(next(ids))
    templates = {"synced": tpl("clip_synced.xml"), "free": tpl("clip_free.xml"), "ndi": tpl("clip_ndi.xml")}
    if os.path.exists(os.path.join(TEMPLATES, "clip_syphon.xml")):
        templates["syphon"] = tpl("clip_syphon.xml")
    columns = max(len(v) for v in layout.values()) + SPARE_COLUMNS
    cols_xml = "\n".join(f'\t\t<Column uniqueId="{nid()}" columnIndex="{i}"/>' for i in range(columns))
    clips = []
    for col in range(columns):
        for layer in sorted(layout):
            items = layout[layer]
            if col >= len(items):
                clips.append(f'\t\t<Clip name="Clip" uniqueId="{nid()}" layerIndex="{layer}" columnIndex="{col}"/>')
                continue
            it = items[col]
            v = {"id": nid(), "layer": layer, "column": col, "name": xml_attr(it["name"])}
            v.update({f"id{k}": nid() for k in range(1, 6)})
            if it["kind"] == "ndi":
                v["ndi"] = xml_attr(it["name"])
            elif it["kind"] == "syphon":
                v["syphon"] = xml_attr(it["name"])
            else:
                w, h, secs = probe(it["path"])
                beats = round(secs * it.get("bpm", 120) / 60.0, 6)
                v.update(path=xml_attr(it["path"]), w=w, h=h, wphase=repr(w / PHASE), hphase=repr(h / PHASE),
                         seconds=repr(secs), ms=repr(secs * 1000.0), beats=f"{beats:g}")
            clips.append(templates[it["kind"]].substitute(v).rstrip("\n"))
    used_cols = max(len(v) for v in layout.values())
    return tpl("template.avc").substitute(
        columns=columns, columns_with_content=used_cols,
        layers_with_content=sum(1 for v in layout.values() if v),
        columns_xml=cols_xml, clips_xml="\n".join(clips))


def xml_attr(s):
    return (str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"))


def arena_running():
    return subprocess.run(["pgrep", "-f", "Resolume Arena.*/Arena.app/Contents/MacOS/Arena"],
                          capture_output=True).returncode == 0


def make(name=DEFAULT_NAME, force=False):
    """Write the composition; returns {path, backup, layers: {name: count}, ndi}."""
    if arena_running() and not force:
        raise RuntimeError("close Arena first: it would save its own copy over the new composition")
    layout = plan()
    text = build(layout)
    from xml.dom import minidom
    minidom.parseString(text.encode("utf-8"))                  # never write a file Arena can't read
    os.makedirs(COMPOSITIONS, exist_ok=True)
    out = os.path.join(COMPOSITIONS, os.path.basename(name))
    backup = None
    if os.path.exists(out):
        os.makedirs(os.path.join(COMPOSITIONS, ".backup"), exist_ok=True)
        backup = os.path.join(COMPOSITIONS, ".backup",
                              f"{os.path.splitext(os.path.basename(out))[0]} {time.strftime('%Y-%m-%d %H.%M.%S')}.avc")
        shutil.copy2(out, backup)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(out + ".tmp", out)
    names = {v: k for k, v in LAYERS.items()}
    src, note = td_source()
    return {"path": out, "backup": backup, "td": f"{src}: {layout[LAYERS['td']][0]['name']}", "note": note,
            "layers": {names[i]: len(layout[i]) for i in sorted(layout)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DEFAULT_NAME, help="file name in Arena's Compositions folder")
    ap.add_argument("--dry-run", action="store_true", help="say what would go where, write nothing")
    ap.add_argument("--force", action="store_true", help="write even while Arena runs")
    a = ap.parse_args()
    if a.dry_run:
        for layer, items in sorted(plan().items()):
            label = {0: "TD", 1: "Base", 2: "Overlay", 3: "Lights", 4: "Light colour"}[layer]
            print(f"layer {layer + 1} {label:8} {len(items):3}  " + ", ".join(i["name"] for i in items[:6])
                  + (" …" if len(items) > 6 else ""))
        return
    try:
        r = make(a.name, a.force)
    except RuntimeError as e:
        sys.exit(f"[composition] {e}")
    print(f"[composition] {r['path']}")
    print("  " + " · ".join(f"{k} {n}" for k, n in r["layers"].items()) + f" · TD over {r['td']}")
    if r["note"]:
        print(f"  note: {r['note']}")
    if r["backup"]:
        print(f"  the old one: {r['backup']}")


if __name__ == "__main__":
    main()
