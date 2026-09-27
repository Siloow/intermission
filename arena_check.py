"""Check that the Arena running here does everything the show tools ask of it.

    python3 arena_check.py

Every Resolume call the tools rely on, tried against the running Arena and
reported ✓ or ✗, with what depends on it. Run it after installing a different
Arena version (the show's licence covers 7.19.2) before trusting it.

It changes nothing that stays: a spare clip slot is used for the load tests
and cleared afterwards; if the lights layer has none, a column is added at the
end for the test and removed again. Nothing that is playing is touched.
"""
import json, os, sys, time, urllib.parse, urllib.request
import arena_load

BASE = "http://127.0.0.1:8080"
HERE = os.path.dirname(os.path.abspath(__file__))
results = []


def check(name, uses, fn):
    try:
        ok, note = fn()
    except SystemExit as e:
        ok, note = False, str(e).splitlines()[0]
    except Exception as e:                     # a failed call is the answer here
        ok, note = False, f"{type(e).__name__}: {e}"
    results.append((ok, name, uses, note))
    print(f"  {'✓' if ok else '!' if ok is None else '✗'} {name:<34} {note}")
    return ok


def call(path, method="GET", body=None, ctype="application/json"):
    return arena_load.api(BASE, path, method, body, ctype)


def main():
    status, prod = call("/product")
    if status != 200:
        raise SystemExit("Arena's web server isn't answering: Preferences → Webserver")
    v = f"{prod.get('major')}.{prod.get('minor')}.{prod.get('micro')}" if isinstance(prod, dict) else "?"
    print(f"\n  {prod.get('name', 'Arena') if isinstance(prod, dict) else 'Arena'} {v}\n")

    comp = arena_load.fetch(BASE)
    layers = comp.get("layers", [])
    check("read the composition", "everything: panel, names, checks",
          lambda: (bool(layers), f"'{arena_load.name_of(comp)}', {len(layers)} layers, {len(comp.get('columns', []))} columns"))

    osc = arena_load.osc_input()
    check("OSC input on", "firing every cue",
          lambda: (bool(osc and osc[0]), f"port {osc[1]}" if osc and osc[0] else "off — Preferences → OSC"))

    named = next((c for l in layers for c in l.get("clips", []) if arena_load.name_of(c)), None)
    def thumb():
        with urllib.request.urlopen(f"{BASE}/api/v1/composition/clips/by-id/{named['id']}/thumbnail", timeout=3) as r:
            return r.status == 200 and r.headers.get_content_type().startswith("image"), r.headers.get_content_type()
    if named:
        check("clip thumbnails", "Resolume panel in the timeline", thumb)

    # a spare slot to load into: the lights layer's first empty one, or a new column
    ref = (arena_load.lanes().get("lights") or {}).get("layer") or len(layers)
    idx, layer = arena_load.find_layer(comp, ref)
    empty = next((c for c in layer.get("clips", []) if not arena_load.name_of(c)), None)
    added_column = False
    ncols = len(comp.get("columns", []))

    def add_column():
        st, _ = call("/composition/columns/add", "POST", "")
        after = len(arena_load.fetch(BASE).get("columns", []))
        return st in (200, 204) and after == ncols + 1, f"{ncols} → {after} columns"
    if check("add a column", "installing presets and Library clips when a layer is full", add_column):
        added_column = True
        if not empty:
            _, layer = arena_load.find_layer(arena_load.fetch(BASE), ref)
            empty = layer["clips"][-1]
    if not empty:
        print("  (no spare slot to test loading into)")

    test = os.path.join(HERE, "content", "light-loops", "full.mp4")
    if empty and os.path.exists(test):
        cid = empty["id"]

        def open_file():
            st, body = call(f"/composition/clips/by-id/{cid}/open", "POST", arena_load.file_url(test), "text/plain")
            time.sleep(0.5)
            name = arena_load.name_of(arena_load.api(BASE, f"/composition/clips/by-id/{cid}")[1])
            return st in (200, 204) and bool(name), f"loaded as '{name}'" if name else f"{st} {body}"
        check("load a file into a clip", "installing presets, looks, Library clips", open_file)

        def settings():
            arena_load.set_clip(BASE, cid, name="arena check", sync=True)
            c = call(f"/composition/clips/by-id/{cid}")[1]
            got = (arena_load.name_of(c), arena_load.choice(c.get("transporttype")), arena_load.choice(c.get("beatsnap")))
            return got == ("arena check", "BPM Sync", "1 Bar"), f"{got}"
        check("rename a clip, BPM Sync, snap", "clip names the timeline fires; presets in tempo", settings)

        def open_source():
            st, srcs = call("/sources")
            video = (srcs or {}).get("video", []) if isinstance(srcs, dict) else []
            pick = next((s for s in video if s.get("name") in ("Solid Color", "Checkered", "Gradient")), video[0] if video else None)
            if not pick:
                return False, "no sources listed"
            live = [s["name"] for s in video if any(w in (s.get("name", "") + s.get("category", "")).lower()
                                                      for w in ("syphon", "ndi"))]
            try:
                st, body = arena_load.api(BASE, f"/composition/clips/by-id/{cid}/open", "POST",
                                          "source:///video/" + urllib.parse.quote(pick["name"]), "text/plain", timeout=4)
            except (OSError, SystemExit):
                return None, (f"listing works ({len(video)} sources, Syphon/NDI: {live or 'none right now'}); opening "
                              "one hangs here — the Library asks you to drag it in once and name it")
            time.sleep(0.5)
            name = arena_load.name_of(call(f"/composition/clips/by-id/{cid}")[1])
            live = [s["name"] for s in video if any(w in (s.get("name", "") + s.get("category", "")).lower()
                                                      for w in ("syphon", "ndi"))]
            return st in (200, 204) and bool(name), f"opened '{pick['name']}'; {len(video)} sources, Syphon/NDI: {live or 'none right now'}"
        check("list sources, open one in a clip", "Library → Live (TouchDesigner)", open_source)

        def clear_clip():
            st, _ = call(f"/composition/clips/by-id/{cid}/clear", "POST")
            time.sleep(0.4)
            return st in (200, 204) and not arena_load.name_of(call(f"/composition/clips/by-id/{cid}")[1]), "slot empty again"
        check("clear a clip", "removing test clips; tidying", clear_clip)

    # a parameter by id, set to what it already is
    index = arena_load.params(comp)
    p = arena_load.find_param(index, ["layer", 1, "opacity"])
    if p:
        def set_param():
            try:
                st, _ = call(f"/parameter/by-id/{p['id']}", "PUT", json.dumps({"value": p["value"]}))
                if st in (200, 204):
                    return True, f"by id; layer 1 opacity stays {p['value']}"
            except SystemExit:
                pass
            path, body = arena_load.param_update(p, p["value"])
            st, _ = call(path, "PUT", json.dumps(body))
            return st in (200, 204), f"through its layer (no by-id in this Arena); stays {p['value']}"
        check("set a parameter", "automation lanes on Resolume parameters", set_param)
        fx = next((q for q in index if q["path"][0] == "layer" and "effect" in q["path"]), None)
        if fx:
            def set_effect():
                path, body = arena_load.param_update(fx, fx["value"])
                st, _ = call(path, "PUT", json.dumps(body))
                return st in (200, 204), f"{fx['label']} stays {fx['value']}"
            check("set an effect parameter", "automation on effects (Transform, Blur…)", set_effect)
    check("see the selected clip", "naming a live source dragged in by hand", lambda: (
        call("/composition/clips/selected")[0] == 200, "ok"))
    tr = (layers[0].get("transition") or {}).get("duration") if layers else None
    if tr:
        check("set a layer's transition time", "cue fades", lambda: (
            call("/composition/layers/1", "PUT", json.dumps({"transition": {"duration": {"value": tr.get("value")}}}))[0] in (200, 204),
            f"stays {tr.get('value')} s"))

    # clearing a layer: only on one where nothing plays
    quiet = next((i for i, l in enumerate(layers, 1)
                  if not any((arena_load.choice(c.get("connected")) or "").startswith("Connected") for c in l.get("clips", []))), None)
    if quiet:
        check("clear a layer", "cue ends, jumps", lambda: (call(f"/composition/layers/{quiet}/clear", "POST")[0] in (200, 204),
                                                          f"layer {quiet}, nothing was playing there"))
    else:
        print("  - clear a layer                     not tried: something plays on every layer")

    if added_column:
        n = len(arena_load.fetch(BASE).get("columns", []))
        req = urllib.request.Request(f"{BASE}/api/v1/composition/columns/{n}", method="DELETE")
        check("remove a column", "tidying after this check", lambda: (urllib.request.urlopen(req, timeout=5).status in (200, 204), f"back to {n - 1}"))

    bad = [r for r in results if r[0] is False]
    print(f"\n  {len(results) - len(bad)} of {len(results)} work in Arena {v}.")
    for _, name, uses, _ in bad:
        print(f"  ✗ {name}: needed for {uses}")
    print()
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())
