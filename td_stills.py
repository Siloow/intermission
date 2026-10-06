#!/usr/bin/env python3
"""The show's TouchDesigner set, and stills of its scenes for the timeline.

The set lives in the show folder, so Dropbox shares it like the rest of the
show: by default td/liveset/ (its spec, assets and the built liveset.toe). A
project can name another one (project.json "td_set", relative to the show
folder; the Host's "TouchDesigner set"), and the Host opens it in
TouchDesigner with ▶ Test and ● The show.

Stills are asked of the running set over OSC, on the same port as its scene
changes (osc_map.json "td", default 127.0.0.1:10004):

    /stills <folder> [1]    the set saves every scene's own out1 (or with 1, only
                            the one on screen) as <folder>/<scene>.jpg, then
                            <folder>/grabbed.json

so it works with the plain .toe on either Mac, no bridge needed. They land
next to the set:

    <set folder>/stills/<scene>.jpg
    <set folder>/scenes.json      the scenes in the set's order, and when each was grabbed

Scenes that wait for the pad or the music stay dark when grabbed unshown:
show one on screen and grab it with --current.

    python3 td_stills.py              every scene
    python3 td_stills.py --current    only the scene on screen now
    python3 td_stills.py --where      the set this project uses
"""
import argparse, json, os, socket, subprocess, sys, time
import showfolder

DEFAULT_SET = os.path.join("td", "liveset", "liveset.toe")
TD_DEFAULT = {"host": "127.0.0.1", "port": 10004, "web": 9982}   # web: the set's live preview frames
WARM_SECONDS = 0.75                     # the set cooks an unshown scene 45 frames before saving it
WIDTH = 640                             # stills are kept this wide


def project_meta():
    """The current project's project.json, or {}."""
    try:
        name = open(showfolder.path("projects", ".current")).read().strip()
        return json.load(open(showfolder.path("projects", name, "project.json"))) if name else {}
    except (OSError, ValueError):
        return {}


def set_path(meta=None):
    """The .toe this project uses, absolute: its td_set, else td/liveset/liveset.toe.
    Stored relative to the show folder, so it is the same on both Macs."""
    rel = (meta if meta is not None else project_meta()).get("td_set") or DEFAULT_SET
    return rel if os.path.isabs(rel) else showfolder.path(rel)


def sets():
    """Every TouchDesigner set in the show folder's td/, relative to the show
    folder (TouchDesigner's own numbered backups and build leftovers left out)."""
    out = []
    root = showfolder.path("td")
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("stills", "Backup")]
        for f in files:
            stem = f[:-4]
            if f.endswith(".toe") and not f.startswith((".", "CrashAutoSave")) \
                    and not stem.rsplit(".", 1)[-1].isdigit():
                out.append(os.path.relpath(os.path.join(d, f), showfolder.root()))
    return sorted(out)


def stills_dir(meta=None):
    return os.path.join(os.path.dirname(set_path(meta)), "stills")


def list_path(meta=None):
    return os.path.join(os.path.dirname(set_path(meta)), "scenes.json")


def target():
    try:
        m = json.load(open(showfolder.path("osc_map.json")))
    except (OSError, ValueError):
        m = {}
    return {**TD_DEFAULT, **(m.get("td") or {})}


def send(address, args):
    """One OSC message to the set (cue_player's encoder: standard library only)."""
    from cue_player import osc_encode
    t = target()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(osc_encode(address, args), (t["host"], int(t["port"])))
    s.close()


def load(meta=None):
    try:
        with open(list_path(meta)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"scenes": []}


def grab(current=False, names=None, log=print):
    """Ask the set for stills and wait for them; returns the updated scenes.json.
    (`names` is accepted for the old callers; the set grabs every scene.)"""
    out_dir = stills_dir()
    os.makedirs(out_dir, exist_ok=True)
    done = os.path.join(out_dir, "grabbed.json")
    started = time.time()
    send("/stills", [out_dir, 1 if current else 0])

    # The set answers by writing grabbed.json last. Every scene takes WARM frames.
    deadline = started + (4 if current else 8 + 22 * WARM_SECONDS * 2)
    got = None
    while time.time() < deadline:
        try:
            if os.path.getmtime(done) >= started - 1:
                time.sleep(0.2)
                got = json.load(open(done))
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    if got is None:
        t = target()
        raise RuntimeError(f"no answer from TouchDesigner on {t['host']}:{t['port']}: "
                           f"is the set open ({os.path.relpath(set_path(), showfolder.root())})?")
    if current and not got.get("grabbed"):
        raise RuntimeError("TouchDesigner shows black now: no scene to grab")

    for name in got.get("grabbed", []):
        p = os.path.join(out_dir, name + ".jpg")
        if os.path.exists(p):
            subprocess.run(["sips", "-Z", str(WIDTH), p], capture_output=True)
            log(f"[td] {name}")

    data = load()
    old = {s["name"]: s for s in data.get("scenes", [])}
    stamp = time.strftime("%Y-%m-%d %H:%M")
    grabbed = set(got.get("grabbed", []))
    data["scenes"] = [{"index": i, "name": n,
                       "grabbed": stamp if n in grabbed else old.get(n, {}).get("grabbed")}
                      for i, n in enumerate(got.get("scenes", []))]
    data["//"] = "Written by td_stills.py: the set's scenes in d-pad order, stills in stills/."
    tmp = list_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, list_path())
    try:
        os.remove(done)
    except OSError:
        pass
    data["missed"] = []
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--current", action="store_true", help="only the scene on screen now")
    ap.add_argument("--where", action="store_true", help="the set this project uses, and the others")
    a = ap.parse_args()
    if a.where:
        print(f"this project: {os.path.relpath(set_path(), showfolder.root())}")
        for s in sets():
            print(f"  {s}")
        return
    try:
        grab(current=a.current)
        print(f"[td] stills in {stills_dir()}")
    except RuntimeError as e:
        sys.exit(f"[td] {e}")


if __name__ == "__main__":
    main()
