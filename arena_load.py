"""Load clips into Resolume over its REST API, and write the cue mapping back.

    python3 arena_load.py --list
    python3 arena_load.py --layer "LIGHTS" --dir content/light-loops --lane lights
    python3 arena_load.py --layer 4 --dir content/screen --lane screen --dry-run

Resolume's own patching stays hand work, but the media does not: this fills a
layer's clip slots from a folder, in order, and then writes what it did into
`osc_map.json` so the show timeline can fire those clips by name. Load the
loops, and a Lights cue that says `chase` just works.

Re-run it whenever the files change - after regenerating the loops at a new
tempo, say. It loads into the same slots, so the cue mapping stays valid.

Needs the web server: Arena → Preferences → Webserver → Enable Webserver & REST
API, port 8080. Standard library only.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "osc_map.json")
MEDIA = (".mov", ".mp4", ".m4v", ".avi", ".mkv", ".dxv", ".png", ".jpg", ".jpeg", ".gif")
BPM_SYNC, ONE_BAR = 1, 5          # indices in the clip's transporttype / beatsnap lists


def lanes():
    """Which layer and folder each lane uses, from osc_map.json."""
    try:
        return json.load(open(MAP)).get("lanes", {})
    except (OSError, ValueError):
        return {}


def lane_dir(lane):
    d = (lanes().get(lane) or {}).get("dir")
    return os.path.join(HERE, d) if d else None


def media_in(folder):
    try:
        return sorted(f for f in os.listdir(folder) if f.lower().endswith(MEDIA))
    except OSError:
        return []


def api(base, path, method="GET", body=None, ctype="application/json"):
    url = f"{base}/api/v1{path}"
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and r.headers.get_content_type()
                              == "application/json" else raw.decode(errors="replace"))
    except urllib.error.URLError as e:
        raise SystemExit(f"[arena] cannot reach {url}: {e}\n"
                         f"        Is the web server on? Preferences → Webserver.")


def composition(base):
    status, comp = api(base, "/composition")
    if status != 200:
        raise SystemExit(f"[arena] composition request failed: {status}")
    return comp


def name_of(node):
    return ((node or {}).get("name") or {}).get("value") or ""


def find_layer(comp, which):
    layers = comp.get("layers", [])
    if str(which).isdigit():
        i = int(which)
        if not 1 <= i <= len(layers):
            raise SystemExit(f"[arena] no layer {i}; the composition has {len(layers)}")
        return i, layers[i - 1]
    for i, l in enumerate(layers, 1):
        if name_of(l).strip().lower() == str(which).strip().lower():
            return i, l
    names = ", ".join(f"{i}:{name_of(l)!r}" for i, l in enumerate(layers, 1))
    raise SystemExit(f"[arena] no layer called {which!r}. Layers are: {names}")


def file_url(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


def load_clip(base, clip_id, path, sync=True):
    status, body = api(base, f"/composition/clips/by-id/{clip_id}/open", "POST",
                       file_url(path), "text/plain")
    if status not in (200, 204) or (isinstance(body, str) and body.strip() == "mismatch"):
        raise RuntimeError(f"loading {os.path.basename(path)} failed: {status} {body}")
    if sync:
        # lock playback to the tempo, and start on a bar. With Ableton Link on in
        # Arena, that tempo follows Live, so a 2-bar loop stays in time.
        api(base, f"/composition/clips/by-id/{clip_id}",
            "PUT", json.dumps({"transporttype": BPM_SYNC, "beatsnap": ONE_BAR}))


def map_write(entries):
    """Record what a lane can now fire, by name."""
    try:
        m = json.load(open(MAP))
    except (OSError, ValueError):
        m = {"resolume": {"host": "127.0.0.1", "port": 7000}, "cues": {}}
    m.setdefault("cues", {}).update(entries)
    json.dump(m, open(MAP, "w"), indent=2)


def load_one(base, lane, filename, sync=True, folder=None):
    """Load a single file into the lane's layer, reusing the slot it already has.

    Returns (name, layer, clip). Used by the Load clip button in the timeline,
    and by Make clip for looks (with `folder` set to where the looks render)."""
    cfg = lanes().get(lane) or {}
    layer_ref = cfg.get("layer")
    if not layer_ref:
        raise RuntimeError(f"no layer set for the {lane} lane in osc_map.json")
    folder = folder or os.path.join(HERE, cfg.get("dir", ""))
    path = os.path.join(folder, filename)
    if not os.path.isfile(path):
        raise RuntimeError(f"no such file: {filename}")

    comp = composition(base)
    index, layer = find_layer(comp, layer_ref)
    clips = layer.get("clips", [])
    stem = os.path.splitext(filename)[0]
    slot = next((i for i, c in enumerate(clips, 1) if name_of(c) == stem), None)
    if slot is None:
        slot = next((i for i, c in enumerate(clips, 1) if not name_of(c)), None)
    if slot is None:
        raise RuntimeError(f"layer {index} has no free clip slot; add one in Resolume")
    load_clip(base, clips[slot - 1]["id"], path, sync)
    map_write({f"{lane}:{stem}": {"layer": index, "clip": slot}})
    return stem, index, slot


# ------------------------------------------------ the composition, by name --
# Resolume's OSC addresses are positions (layer 3, clip 6). The plan names
# things instead, and these turn a name into today's position, so dragging a
# clip to another slot in Resolume doesn't quietly break a cue.
CACHE = os.path.join(HERE, "composition.json")    # the last one seen, for when Arena is closed
DEFAULT_NAMES = ("Layer #", "Column #", "")


def choice(node):
    return (node or {}).get("value") if isinstance(node, dict) else None


def fetch(base="http://127.0.0.1:8080", timeout=1.0):
    """The whole composition, as Arena returns it."""
    with urllib.request.urlopen(f"{base}/api/v1/composition", timeout=timeout) as r:
        return json.loads(r.read())


def snapshot(base="http://127.0.0.1:8080", timeout=1.0, comp=None):
    """The composition, cut down to what the timeline and the player need."""
    comp = comp if comp is not None else fetch(base, timeout)
    layers = []
    for i, l in enumerate(comp.get("layers", []), 1):
        clips = []
        for j, c in enumerate(l.get("clips", []), 1):
            name = name_of(c)
            if not name:
                continue
            info = ((c.get("video") or {}).get("fileinfo")) or {}
            clips.append({
                "index": j, "name": name, "id": c.get("id"),
                "thumb": (c.get("thumbnail") or {}).get("last_update"),
                "state": choice(c.get("connected")),                 # Connected, Disconnected, ...
                "transport": choice(c.get("transporttype")),         # Timeline, BPM Sync, ...
                "beatsnap": choice(c.get("beatsnap")),
                "seconds": round((info.get("duration_ms") or 0) / 1000, 2) or None,
                "missing": info.get("exists") is False})
        raw = name_of(l)
        layers.append({"index": i, "name": raw if raw not in DEFAULT_NAMES else f"Layer {i}",
                       "clips": clips})
    columns = []
    for i, col in enumerate(comp.get("columns", []), 1):
        raw = name_of(col)
        columns.append({"index": i, "name": raw if raw not in DEFAULT_NAMES else f"Column {i}",
                        "named": raw not in DEFAULT_NAMES,
                        "state": choice(col.get("connected"))})
    return {"name": name_of(comp) or "untitled", "layers": layers, "columns": columns}


def save_cache(snap):
    """Keep the last composition on disk, but only rewrite it when its shape
    changed, not on every play state, so a synced folder stays quiet."""
    shape = lambda s: json.dumps({"name": s["name"],
        "layers": [[l["name"], [(c["index"], c["name"]) for c in l["clips"]]] for l in s["layers"]],
        "columns": [c["name"] for c in s["columns"]]})
    try:
        if shape(json.load(open(CACHE))) == shape(snap):
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    tmp = CACHE + ".tmp"
    json.dump(dict(snap, saved=time.strftime("%Y-%m-%d %H:%M")), open(tmp, "w"), indent=1)
    os.replace(tmp, CACHE)


def load_cache():
    try:
        return json.load(open(CACHE))
    except (OSError, ValueError):
        return None


def current(base="http://127.0.0.1:8080"):
    """(composition, live?) — Arena's if it answers, else the last one seen."""
    try:
        snap = snapshot(base)
        save_cache(snap)
        return snap, True
    except (OSError, ValueError):
        return load_cache(), False


def layer_for(lane, layer=None):
    """Which layer a cue looks in: its own, else its lane's."""
    if layer:
        return layer
    return (lanes().get(lane) or {}).get("layer")


def find_clip(snap, layer, name):
    """(layer index, clip) for a clip called `name`, or (layer index, None)."""
    L = next((l for l in snap.get("layers", [])
              if l["index"] == layer or (isinstance(layer, str) and l["name"].lower() == layer.lower())),
             None)
    if not L:
        return None, None
    hits = [c for c in L["clips"] if c["name"] == name]
    return L["index"], (hits[0] if hits else None)


def find_column(snap, name):
    v = str(name).strip()
    for c in snap.get("columns", []):
        if c["name"].lower() == v.lower():
            return c
    if v.isdigit():
        return next((c for c in snap.get("columns", []) if c["index"] == int(v)), None)
    return None


# ------------------------------------------- parameters, for automation --
# A Resolume target is a path of names, not an id: ids change every time Arena
# loads the composition. ["layer", 3, "effect", "Transform", "Scale"] is looked
# up again whenever the composition is read.
def _range(node):
    return (isinstance(node, dict) and node.get("valuetype") == "ParamRange"
            and node.get("id") is not None)


def _effects(fx_list, prefix, label, out):
    seen = {}
    for fx in fx_list or []:
        name = fx.get("name") or "effect"
        seen[name] = seen.get(name, 0) + 1
        key = name if seen[name] == 1 else f"{name} #{seen[name]}"
        for pname, node in (fx.get("params") or {}).items():
            if _range(node):
                out.append({"path": prefix + ["effect", key, pname],
                            "label": f"{label} · {key} · {pname}", "group": label,
                            "id": node["id"], "min": node.get("min", 0), "max": node.get("max", 1),
                            "value": node.get("value")})


def params(comp):
    """Every automatable (range) parameter: composition, layers, their effects."""
    out = []
    for key, label in (("master", "Composition master"),):
        if _range(comp.get(key)):
            out.append({"path": ["composition", key], "label": label, "group": "Composition",
                        "id": comp[key]["id"], "min": comp[key].get("min", 0),
                        "max": comp[key].get("max", 1), "value": comp[key].get("value")})
    video = comp.get("video") or {}
    if _range(video.get("opacity")):
        out.append({"path": ["composition", "opacity"], "label": "Composition opacity",
                    "group": "Composition", "id": video["opacity"]["id"],
                    "min": video["opacity"].get("min", 0), "max": video["opacity"].get("max", 1),
                    "value": video["opacity"].get("value")})
    _effects(video.get("effects"), ["composition"], "Composition", out)
    for i, l in enumerate(comp.get("layers", []), 1):
        raw = name_of(l)
        label = raw if raw not in DEFAULT_NAMES else f"Layer {i}"
        for key, pname in (("master", "master"),):
            if _range(l.get(key)):
                out.append({"path": ["layer", i, key], "label": f"{label} · {pname}", "group": label,
                            "id": l[key]["id"], "min": l[key].get("min", 0),
                            "max": l[key].get("max", 1), "value": l[key].get("value")})
        lv = l.get("video") or {}
        if _range(lv.get("opacity")):
            out.append({"path": ["layer", i, "opacity"], "label": f"{label} · opacity", "group": label,
                        "id": lv["opacity"]["id"], "min": lv["opacity"].get("min", 0),
                        "max": lv["opacity"].get("max", 1), "value": lv["opacity"].get("value")})
        _effects(lv.get("effects"), ["layer", i], label, out)
    return out


def find_param(index, path):
    want = json.dumps(path)
    return next((p for p in index if json.dumps(p["path"]) == want), None)


def osc_input():
    """Whether Arena listens for OSC, and on which port, from its own preferences.

    The REST API can be on while OSC input is off, and then every cue the
    player sends is ignored without a sound. None when the file can't be read
    (another Mac, another user)."""
    import re
    path = os.path.expanduser("~/Documents/Resolume Arena/Preferences/osc.xml")
    try:
        text = open(path).read()
    except OSError:
        return None
    m = re.search(r'<Input\s+Enabled="(\d)"\s+Port="(\d+)"', text)
    return (m.group(1) == "1", int(m.group(2))) if m else None


def list_composition(base):
    comp = composition(base)
    print(f"\n  composition: {name_of(comp)!r}\n")
    for i, l in enumerate(comp.get("layers", []), 1):
        clips = l.get("clips", [])
        used = [f"{j}:{name_of(c)}" for j, c in enumerate(clips, 1) if name_of(c)]
        print(f"  layer {i:<2} {name_of(l)!r:<24} {len(clips)} slots   " +
              (", ".join(used[:6]) + (" …" if len(used) > 6 else "") if used else "empty"))
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="http://127.0.0.1:8080")
    ap.add_argument("--list", action="store_true", help="show layers and their clips, then stop")
    ap.add_argument("--layer", help="layer name, or its number")
    ap.add_argument("--dir", help="folder to load from (default: the lane's, from osc_map.json)")
    ap.add_argument("--lane", default="lights", choices=["lights", "screen", "td", "scenes"],
                    help="which timeline lane these clips belong to")
    ap.add_argument("--from-slot", type=int, default=1, help="first clip slot to fill")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen")
    ap.add_argument("--no-map", action="store_true", help="don't touch osc_map.json")
    ap.add_argument("--no-sync", action="store_true",
                    help="leave clip transport alone (default: BPM Sync, snap to 1 bar)")
    a = ap.parse_args()

    if not a.layer and not a.list:
        a.layer = (lanes().get(a.lane) or {}).get("layer")     # the lane knows its layer
    if a.list or not a.layer:
        list_composition(a.host)
        if not a.layer:
            print("  Pick one with --layer, e.g.  --layer \"LIGHTS\"\n")
        return 0

    a.dir = a.dir or lane_dir(a.lane) or os.path.join(HERE, "content", "light-loops")
    files = media_in(a.dir)
    if not files:
        raise SystemExit(f"[arena] nothing to load in {a.dir}")

    comp = composition(a.host)
    index, layer = find_layer(comp, a.layer)
    clips = layer.get("clips", [])
    room = len(clips) - (a.from_slot - 1)
    if room < len(files):
        print(f"[arena] layer {index} has {len(clips)} slots and {len(files)} files to load; "
              f"loading the first {max(0, room)}. Add slots in Resolume for the rest.")
    print(f"\n  layer {index} {name_of(layer)!r} ← {len(files)} file(s) from {a.dir}\n")

    mapping = {}
    for n, fname in enumerate(files):
        slot = a.from_slot + n
        if slot > len(clips):
            break
        clip = clips[slot - 1]
        stem = os.path.splitext(fname)[0]
        was = name_of(clip)
        if a.dry_run:
            print(f"   slot {slot:<3} {fname:<20} (now: {was or 'empty'})")
        else:
            load_clip(a.host, clip["id"], os.path.join(a.dir, fname), sync=not a.no_sync)
            print(f"   slot {slot:<3} {fname:<20} loaded" +
                  (f", replacing {was!r}" if was and was != stem else ""))
        mapping[f"{a.lane}:{stem}"] = {"layer": index, "clip": slot}

    if a.no_map or a.dry_run:
        print(f"\n  {'(dry run)' if a.dry_run else 'osc_map.json untouched'}\n")
        return 0

    map_write(mapping)
    print(f"\n  osc_map.json: {len(mapping)} cue name(s) now point at layer {index}")
    print(f"  the timeline's {a.lane} lane can fire them by name: "
          f"{', '.join(sorted(k.split(':', 1)[1] for k in mapping))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
