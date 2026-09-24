"""The show's visual library: everything the timeline can paint with, in one place.

    python3 library.py --scan            list what the sources hold
    python3 library.py --list            what is in the show

The visuals live all over: Blender renders in each project's render folder,
image sequences, TouchDesigner renders, and TouchDesigner running live. This
gathers them:

  sources   folders to look in (library.json "sources"); scanned for videos,
            image sequences and stills, drafts flagged by their names
  add       copies a chosen one into content/library/, converted to one show
            format: 1920x1080, Resolume's own DXV codec, the frame rate it was
            made at. Drafts stay where they are.
  live      a video source Resolume can see (TouchDesigner over Syphon, NDI),
            named and tagged like the rest
  install   puts library clips and live sources into a screen layer in
            Resolume, where the timeline paints with them by name

library.json is the list (small, shared, in git); content/library/ holds the
media (big: keep it in the shared folder, not in git). Scans, thumbnails and
hover previews are cached in .live/library/.

Needs ffmpeg and ffprobe. Standard library otherwise.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_FILE = os.path.join(HERE, "library.json")
LIB_DIR = os.path.join(HERE, "content", "library")
THUMBS = os.path.join(LIB_DIR, ".thumbs")           # shared with the clips
CACHE = os.path.join(HERE, ".live", "library")      # this machine's scan, thumbs, previews
VIDEO = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
IMAGE = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff")
SKIP = {".git", "__pycache__", "node_modules", ".live", ".Trash", "venue", "tools"}
DRAFT = re.compile(r"draft|preview|test|wip|insta|mesh|proxy|tmp|semi|lowres|low_res", re.I)
SEQ = re.compile(r"^(.*?)(\d{3,})\.([A-Za-z]+)$")
SHOW_W, SHOW_H = 1920, 1080
BYTES_PER_SECOND = 9_000_000                       # DXV at 1080p, roughly
lock = threading.Lock()
jobs = {}                                          # id -> {name, state, progress, error}


# ----------------------------------------------------------------- the list --
def config():
    try:
        cfg = json.load(open(LIB_FILE))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("//", "Sources are folders to look in, relative to this file. clips and live "
                         "are the show's visuals; the media sit in content/library/.")
    cfg.setdefault("sources", ["..", "../../TouchDesigner"])
    cfg.setdefault("sequence_fps", 30)
    cfg.setdefault("clips", [])
    cfg.setdefault("live", [])
    return cfg


def save(cfg):
    with lock:
        tmp = LIB_FILE + ".tmp"
        json.dump(cfg, open(tmp, "w"), indent=2)
        os.replace(tmp, LIB_FILE)


def safe_name(name):
    name = re.sub(r"[^\w\- ]+", "", name).strip()
    return re.sub(r"\s+", " ", name)[:60] or "clip"


GENERIC = {"render", "renders", "frames", "frame", "out", "output", "f", "sim", "seq", "img",
           "image", "images", "still", "stills", "v", "tmp"}


def nice_name(path, project=""):
    """A readable default: frost_0200_0343_semi.mp4 → frost; ballentent/…/lines/0001.png
    → ballentent lines (frame numbers and generic folder names don't count)."""
    clean = lambda t: re.sub(r"[_\-.]+", " ", DRAFT.sub("", re.sub(r"[_\-. ]*\d{3,}", "", t))).strip()
    stem = clean(os.path.splitext(os.path.basename(path))[0])
    if len(stem) >= 3 and stem.lower() not in GENERIC:
        return stem
    parts = [clean(x) for x in os.path.dirname(path).split(os.sep)[-3:]]
    parts = [x for x in parts if len(x) >= 2 and x.lower() not in GENERIC and x != project]
    return " ".join(([project] if project else []) + parts[-1:]) or project or "clip"


PASS = re.compile(r"depth|normal|mask|alpha|zpass|mist|crypto|\.exr$", re.I)   # render passes, not pictures


# ------------------------------------------------------------------ scanning --
def _probe(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height,r_frame_rate,nb_frames,codec_name:format=duration",
                              "-of", "json", path], capture_output=True, text=True, timeout=20).stdout
        d = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    st = (d.get("streams") or [{}])[0]
    try:
        num, den = (st.get("r_frame_rate") or "0/1").split("/")
        fps = round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        fps = 0
    dur = float((d.get("format") or {}).get("duration") or 0)
    return {"w": st.get("width"), "h": st.get("height"), "fps": fps, "seconds": round(dur, 2),
            "codec": st.get("codec_name")}


def scan():
    """Every candidate in the sources: videos, image sequences, stills."""
    cfg = config()
    os.makedirs(CACHE, exist_ok=True)
    cache_path = os.path.join(CACHE, "scan.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    in_show = {c.get("source") for c in cfg["clips"]}
    out, seen = [], set()
    for rel in cfg["sources"]:
        root = os.path.normpath(os.path.join(HERE, rel))
        if not os.path.isdir(root):
            continue
        for d, dirs, files in os.walk(root):
            depth = os.path.relpath(d, root).count(os.sep)
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".") and depth < 6]
            if os.path.abspath(d).startswith(os.path.abspath(LIB_DIR)):
                continue
            project = os.path.relpath(d, root).split(os.sep)[0]
            project = os.path.basename(root) if project == "." else project
            seqs = {}
            for f in files:
                if f.startswith("."):
                    continue
                p = os.path.join(d, f)
                ext = os.path.splitext(f)[1].lower()
                if ext in VIDEO:
                    out.append(_candidate(p, "video", project, cache, in_show))
                elif ext in IMAGE:
                    m = SEQ.match(f)
                    key = (m.group(1), m.group(3).lower(), len(m.group(2))) if m else None
                    seqs.setdefault(key, []).append((int(m.group(2)) if m else 0, p))
            for key, frames in seqs.items():
                if key and len(frames) >= 8:
                    frames.sort()
                    prefix, ext, digits = key
                    pattern = os.path.join(d, f"{prefix}%0{digits}d.{ext}")
                    c = _candidate(pattern, "sequence", project, cache, in_show,
                                   frames=len(frames), first=frames[0][1], start=frames[0][0],
                                   fps=cfg["sequence_fps"])
                    out.append(c)
                else:
                    for _, p in frames:
                        if os.path.getsize(p) > 60_000:          # skip icons and tiny crops
                            out.append(_candidate(p, "still", project, cache, in_show))
    for c in out:
        seen.add(c["path"])
    json.dump({k: v for k, v in cache.items() if k in seen}, open(cache_path, "w"))
    out.sort(key=lambda c: (c["project"].lower(), c["name"].lower()))
    return out


def _candidate(path, kind, project, cache, in_show, frames=None, first=None, start=None, fps=None):
    probe_path = first or path
    try:
        st = os.stat(probe_path)
    except OSError:
        st = None
    key = f"{st.st_mtime:.0f}:{st.st_size}" if st else ""
    hit = cache.get(path)
    if hit and hit.get("key") == key:
        info = hit["info"]
    else:
        info = _probe(probe_path)
        cache[path] = {"key": key, "info": info}
    c = {"id": hashlib.sha1(path.encode()).hexdigest()[:12], "path": path, "kind": kind,
         "project": project, "name": os.path.basename(path).replace("%0", "#").split("d.")[0]
         if kind == "sequence" else os.path.basename(path),
         "suggest": nice_name(first or path, project),
         "draft": bool(DRAFT.search(path)) or bool(PASS.search(first or path)),
         "in_show": path in in_show, "bytes": 0, **info}
    if kind == "sequence":
        c.update(frames=frames, first=first, start=start, fps=fps,
                 seconds=round(frames / max(1, fps), 2), name=os.path.basename(first))
        c["bytes"] = frames * (st.st_size if st else 0)
    elif st:
        c["bytes"] = st.st_size
    if kind == "still":
        c["seconds"] = None
    c["show_bytes"] = int((c.get("seconds") or 0) * BYTES_PER_SECOND) if kind != "still" else 4_000_000
    return c


def find(cid):
    for c in scan():
        if c["id"] == cid:
            return c
    return None


# -------------------------------------------------------- thumbs and previews --
def _input(c, seconds=None):
    """ffmpeg input arguments for a candidate."""
    if c["kind"] == "sequence":
        return ["-framerate", str(c["fps"]), "-start_number", str(c["start"]), "-i", c["path"]]
    if c["kind"] == "still":
        return ["-loop", "1", "-t", str(seconds or 1), "-i", c["path"]]
    return ["-i", c["path"]]


def thumb(c):
    out = os.path.join(CACHE, "thumbs", c["id"] + ".jpg")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        seek = []
        if c["kind"] == "video" and c.get("seconds"):
            seek = ["-ss", f"{c['seconds'] * 0.3:.2f}"]
        src = ["-i", c["first"]] if c["kind"] == "sequence" and c["frames"] < 3 else _input(c)
        if c["kind"] == "sequence":
            src = ["-i", c["first"]]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, *src, "-frames:v", "1",
                        "-vf", "scale=320:-2", out], capture_output=True, timeout=60)
    return out if os.path.exists(out) else None


def preview(c):
    """A small, quick H.264 of the first seconds, for hovering a card."""
    out = os.path.join(CACHE, "previews", c["id"] + ".mp4")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *_input(c, 3), "-t", "6",
                        "-vf", "scale=320:-2,fps=24,format=yuv420p", "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "28", "-movflags", "+faststart", tmp],
                       capture_output=True, timeout=120)
        if os.path.exists(tmp):
            os.replace(tmp, out)
    return out if os.path.exists(out) else None


# -------------------------------------------------------------- adding them --
def add(cid, name, tags=(), who="", song="", fit="fit"):
    """Start converting a candidate into the show. Returns a job id."""
    c = find(cid)
    if not c:
        raise ValueError("that source is gone: rescan")
    name = safe_name(name or c["suggest"])
    cfg = config()
    taken = {x["name"] for x in cfg["clips"]} | {x["name"] for x in cfg["live"]}
    base, n = name, 2
    while name in taken:
        name, n = f"{base} {n}", n + 1
    job = hashlib.sha1(f"{cid}{time.time()}".encode()).hexdigest()[:10]
    jobs[job] = {"name": name, "state": "converting", "progress": 0.0, "error": None}
    threading.Thread(target=_convert, args=(job, c, name, list(tags), who, song, fit), daemon=True).start()
    return job


def _convert(job, c, name, tags, who, song, fit):
    os.makedirs(LIB_DIR, exist_ok=True)
    os.makedirs(THUMBS, exist_ok=True)
    frame = (f"scale={SHOW_W}:{SHOW_H}:force_original_aspect_ratio=increase,crop={SHOW_W}:{SHOW_H}"
             if fit == "fill" else
             f"scale={SHOW_W}:{SHOW_H}:force_original_aspect_ratio=decrease,"
             f"pad={SHOW_W}:{SHOW_H}:(ow-iw)/2:(oh-ih)/2:black")
    try:
        if c["kind"] == "still":
            out = os.path.join(LIB_DIR, name + ".png")
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", c["path"], "-vf", frame,
                                "-frames:v", "1", out], capture_output=True, text=True)
        else:
            out = os.path.join(LIB_DIR, name + ".mov")
            total = max(0.1, float(c.get("seconds") or 1))
            p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", *_input(c), "-vf", frame + ",format=rgba",
                                  "-an", "-c:v", "dxv", "-f", "mov", "-progress", "pipe:1", out + ".part"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in p.stdout:
                if line.startswith("out_time_ms="):
                    try:
                        jobs[job]["progress"] = min(0.99, int(line.split("=")[1]) / 1e6 / total)
                    except ValueError:
                        pass
            err = p.stderr.read()
            r = subprocess.CompletedProcess(p.args, p.wait(), "", err)
            if r.returncode == 0:
                os.replace(out + ".part", out)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError((r.stderr or "ffmpeg failed").strip().splitlines()[-1][:200])
        t = thumb(c)
        if t:
            shutil.copy(t, os.path.join(THUMBS, name + ".jpg"))
        cfg = config()
        cfg["clips"].append({"name": name, "file": os.path.relpath(out, HERE), "source": c["path"],
                             "kind": c["kind"], "project": c["project"], "tags": tags, "song": song,
                             "who": who, "fit": fit, "fps": c.get("fps"), "seconds": c.get("seconds"),
                             "added": time.strftime("%Y-%m-%d %H:%M")})
        save(cfg)
        jobs[job].update(state="done", progress=1.0)
    except (OSError, RuntimeError, ValueError) as e:
        jobs[job].update(state="failed", error=str(e))
        for leftover in (os.path.join(LIB_DIR, name + ".mov.part"),):
            if os.path.exists(leftover):
                os.remove(leftover)


def update(name, **fields):
    cfg = config()
    for group in ("clips", "live"):
        for x in cfg[group]:
            if x["name"] == name:
                x.update({k: v for k, v in fields.items() if k in ("tags", "song", "who", "note")})
                save(cfg)
                return x
    raise ValueError(f"nothing called {name!r} in the library")


def remove(name):
    cfg = config()
    for x in cfg["clips"]:
        if x["name"] == name:
            for p in (os.path.join(HERE, x["file"]), os.path.join(THUMBS, name + ".jpg")):
                if os.path.exists(p):
                    os.remove(p)
    cfg["clips"] = [x for x in cfg["clips"] if x["name"] != name]
    cfg["live"] = [x for x in cfg["live"] if x["name"] != name]
    save(cfg)


# ------------------------------------------------------------- live sources --
def live_sources(base):
    """Video sources Resolume can see that come from outside it: Syphon, NDI."""
    import arena_load
    status, d = arena_load.api(base, "/sources")
    out = []
    for s in (d or {}).get("video", []) if isinstance(d, dict) else []:
        blob = " ".join(str(s.get(k, "")) for k in ("name", "category", "description", "idstring")).lower()
        if any(w in blob for w in ("syphon", "ndi", "spout", "touch")):
            out.append({"name": s.get("name"), "category": s.get("category")})
    return out


def add_live(source, name, tags=(), who=""):
    cfg = config()
    name = safe_name(name or source)
    cfg["live"] = [x for x in cfg["live"] if x["name"] != name]
    cfg["live"].append({"name": name, "source": source, "tags": list(tags), "who": who,
                        "added": time.strftime("%Y-%m-%d %H:%M")})
    save(cfg)
    return name


# ------------------------------------------------------------------ install --
def install(base, names, lane):
    """Put library clips and live sources into a lane's layer in Resolume."""
    import arena_load
    cfg = config()
    items = []
    for x in cfg["clips"]:
        if x["name"] in names:
            items.append({"name": x["name"], "url": arena_load.file_url(os.path.join(HERE, x["file"]))})
    for x in cfg["live"]:
        if x["name"] in names:
            items.append({"name": x["name"], "url": "source:///video/" + urllib.parse.quote(x["source"])})
    if not items:
        raise ValueError("none of those are in the library")
    ref = (arena_load.lanes().get(lane) or {}).get("layer")
    if not ref:
        raise ValueError(f"no layer set for the {lane} lane in osc_map.json")
    return arena_load.install_items(base, ref, items, lane=lane)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.scan:
        for c in scan():
            print(f"  {c['project']:<14} {c['kind']:<8} {'draft ' if c['draft'] else '      '}"
                  f"{c.get('w')}x{c.get('h')} {c.get('seconds') or '':>6}s  {c['name']}")
    else:
        cfg = config()
        for x in cfg["clips"]:
            print(f"  clip  {x['name']:<24} {x.get('seconds') or '':>6}s  {', '.join(x.get('tags') or [])}")
        for x in cfg["live"]:
            print(f"  live  {x['name']:<24} {x['source']}")


if __name__ == "__main__":
    main()
