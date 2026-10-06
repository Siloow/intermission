#!/usr/bin/env python3
"""Stills of the TouchDesigner scenes, for the timeline's TD lane and preview.

Talks to the running TouchDesigner through the MCP bridge (td_mcp_host.toe,
127.0.0.1:9981) and saves each scene's own output (`<scene>/out1`, before the
set's post and label) as a JPEG in the show folder:

    <show>/td/stills/<scene>.jpg
    <show>/td/scenes.json        the scenes in the set's order, and when each was grabbed

The liveset's decks only cook the scene they show, so an unshown scene is
cooked by hand for a moment first (WARM frames each, one scene after another,
so the set doesn't stall). Scenes that wait for the pad or the music stay dark
that way: show one on screen and grab it with --current.

    python3 td_stills.py              every scene
    python3 td_stills.py --current    only the scene on screen now
    python3 td_stills.py --list       the scenes, grab nothing
"""
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.request
import showfolder

BRIDGE = "http://127.0.0.1:9981/api/td/server/exec"
SWITCH = "/project1/deck_a"             # one of the liveset's two decks: its inputs are the scenes, then black
INDEX = "/project1/scene_index"         # the scene on screen (-1: black), written by scene_ctl
WARM = 45                               # frames to cook an unshown scene before saving it
WIDTH = 640                             # stills are kept this wide

DIR = os.path.join(showfolder.root(), "td")
STILLS = os.path.join(DIR, "stills")
LIST = os.path.join(DIR, "scenes.json")


def run(script, timeout=20):
    """Run Python inside TouchDesigner; return its `result`. Raises when it can't."""
    req = urllib.request.Request(BRIDGE, data=json.dumps({"script": script}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("TouchDesigner isn't answering on 9981: open td_mcp_host.toe") from e
    if not body.get("success"):
        raise RuntimeError(f"TouchDesigner: {body.get('error')}")
    res = body["data"]["result"]
    return res.get("value", res) if isinstance(res, dict) else res


def scenes():
    """[{index, name, top}] in the switch's order, and the index on screen now."""
    out = run(f"""
import json
sw = op({SWITCH!r})
rows = []
for i, s in enumerate(sw.inputs if sw else []):
    t = s.par.top.eval() if s.OPType == 'selectTOP' else s
    t = op(t) if isinstance(t, str) else t
    if t is not None and t.name == 'out1':          # a scene; the deck's last input is black
        rows.append({{"index": i, "name": t.parent().name, "top": t.path}})
ix = op({INDEX!r})
on = int(round(ix[0].eval())) if ix else -1
result = json.dumps({{"scenes": rows, "on": on % len(rows) if rows and on >= 0 else None}})
""")
    return json.loads(out)


def load():
    try:
        with open(LIST) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"scenes": []}


def grab(current=False, names=None, log=print):
    """Save stills; returns the updated scenes.json content."""
    info = scenes()
    rows = info["scenes"]
    if not rows:
        raise RuntimeError(f"no scenes behind {SWITCH} in the running TouchDesigner")
    if current:
        todo = [r for r in rows if r["index"] == info["on"]]
        if not todo:
            raise RuntimeError("TouchDesigner shows black now: no scene to grab")
    else:
        todo = [r for r in rows if not names or r["name"] in names]
    os.makedirs(STILLS, exist_ok=True)
    started = time.time()
    lines = []
    for k, r in enumerate(todo):
        path = os.path.join(STILLS, r["name"] + ".jpg")
        top = f"op({r['top']!r})"
        save = f"{top}.save({path!r})"
        cook = f"{top}.cook(force=True)"
        base = k * WARM
        # the scene on screen is already running: save it now. Others cook for WARM
        # frames in their own turn, so only one extra scene cooks at a time.
        if current or r["index"] == info["on"]:
            lines.append(f"run({save!r}, delayFrames={base + 1})")
            continue
        lines.append(f"for f in range({base + 1}, {base + WARM}):\n    run({cook!r}, delayFrames=f)")
        lines.append(f"run({cook + '; ' + save!r}, delayFrames={base + WARM})")
    run("\n".join(lines) + "\nresult = 'scheduled'")

    # TouchDesigner saves them over the next frames; wait for each, then shrink it
    deadline = started + 10 + len(todo) * WARM / 20
    pending = {r["name"] for r in todo}
    while pending and time.time() < deadline:
        for name in list(pending):
            p = os.path.join(STILLS, name + ".jpg")
            if os.path.exists(p) and os.path.getmtime(p) >= started - 1:
                time.sleep(0.2)                     # let TouchDesigner finish writing it
                subprocess.run(["sips", "-Z", str(WIDTH), p], capture_output=True)
                pending.discard(name)
                log(f"[td] {name}")
        time.sleep(0.25)

    data = load()
    old = {s["name"]: s for s in data.get("scenes", [])}
    stamp = time.strftime("%Y-%m-%d %H:%M")
    data["scenes"] = [{"index": r["index"], "name": r["name"],
                       "grabbed": stamp if r in todo and r["name"] not in pending
                                  else old.get(r["name"], {}).get("grabbed")} for r in rows]
    data["//"] = "Written by td_stills.py: the liveset's scenes in d-pad order, stills in stills/."
    with open(LIST + ".tmp", "w") as f:
        json.dump(data, f, indent=2)
    os.replace(LIST + ".tmp", LIST)
    if pending:
        log(f"[td] no still came back for: {', '.join(sorted(pending))}")
    data["missed"] = sorted(pending)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--current", action="store_true", help="only the scene on screen now")
    ap.add_argument("--list", action="store_true", help="list the scenes, grab nothing")
    ap.add_argument("names", nargs="*", help="only these scenes")
    a = ap.parse_args()
    try:
        if a.list:
            info = scenes()
            for r in info["scenes"]:
                print(f"{'▶' if r['index'] == info['on'] else ' '} {r['index']:2d}  {r['name']}")
            return
        grab(current=a.current, names=a.names)
        print(f"[td] stills in {STILLS}")
    except RuntimeError as e:
        sys.exit(f"[td] {e}")


if __name__ == "__main__":
    main()
