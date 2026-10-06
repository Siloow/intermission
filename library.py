"""The show's visual library: everything the timeline can paint with, in one place.

    python3 library.py --scan            list what the sources hold
    python3 library.py --list            what is in the show

The visuals live all over: Blender renders in each project's render folder,
image sequences, TouchDesigner renders, and TouchDesigner running live. This
gathers them:

  sources   this Mac's folders to look in (sources.json next to the tools, set on
            the Library page: my render folders are not my brother's); scanned for
            videos, image sequences and stills, drafts flagged by their names
  add       copies a chosen one into the show folder's library/, converted to one show
            format: 1920x1080, the frame rate it was made at, and a codec
            Resolume plays on the GPU: DXV, stills too. ffmpeg's DXV has no
            alpha, so anything really transparent goes to ProRes 4444 (video)
            or stays PNG (a still). Drafts stay where they are.
            --reconvert brings clips added before that up to it.
  live      a video source Resolume can see (TouchDesigner over Syphon, NDI),
            named and tagged like the rest
  install   puts library clips and live sources into a screen layer in
            Resolume, where the timeline paints with them by name

library.json is the list and library/ the media, both in the show folder
(shared through Dropbox; see showfolder.py), none of it in git. Scans, thumbnails
and hover previews are cached in .live/library/, per Mac.

Needs ffmpeg and ffprobe. Standard library otherwise.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse
import showfolder

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = showfolder.root()                            # the list and the media live with the show
LIB_FILE = os.path.join(SHOW, "library.json")
LIB_DIR = os.path.join(SHOW, "library")
THUMBS = os.path.join(LIB_DIR, ".thumbs")           # shared with the clips
CACHE = os.path.join(HERE, ".live", "library")      # this machine's scan, thumbs, previews
SOURCES_FILE = os.path.join(HERE, "sources.json")   # this machine's folders to look in: not shared, not in git
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
    cfg.setdefault("//", "clips and live are the show's visuals; the media sit in library/ next to this file. "
                         "Which folders a Mac scans for new ones is its own business: sources.json next to the tools.")
    cfg.setdefault("sequence_fps", 30)
    cfg.setdefault("clips", [])
    cfg.setdefault("live", [])
    return cfg


def save(cfg):
    with lock:
        tmp = LIB_FILE + ".tmp"
        json.dump(cfg, open(tmp, "w"), indent=2)
        os.replace(tmp, LIB_FILE)


# ----------------------------------------------------------------- sources --
# Where to look for candidates is this Mac's business: my render folders are not
# my brother's. sources.json sits next to the code, out of git; the Library page
# edits it. A library.json from before carried a "sources" list: that seeds it once.
def source_root(s):
    return os.path.normpath(os.path.join(HERE, os.path.expanduser(s)))


def _write_sources(src):
    tmp = SOURCES_FILE + ".tmp"
    json.dump({"//": "This Mac's folders the Library scans for visuals. Edit on the Library page "
                     "(Sources: Add folder…). Not shared: the other Mac has its own.",
               "sources": src}, open(tmp, "w"), indent=2)
    os.replace(tmp, SOURCES_FILE)


def local_sources():
    try:
        return list(json.load(open(SOURCES_FILE)).get("sources", []))
    except (OSError, ValueError):
        pass
    cfg = config()
    old = cfg.pop("sources", None)
    src = [source_root(x) for x in (old or []) if os.path.isdir(source_root(x))]
    _write_sources(src)
    if old is not None:
        save(cfg)                                   # the shared list no longer carries them
    return src


def add_source(path):
    path = (path or "").strip().replace("\\ ", " ")     # a path dragged into Terminal escapes its spaces
    root = source_root(path)
    if not path or not os.path.isdir(root):
        raise ValueError(f"no folder at {root or path!r}")
    if os.path.abspath(root).startswith(os.path.abspath(LIB_DIR)):
        raise ValueError("that is the show's own library; pick the folder the originals are in")
    src = local_sources()
    if root not in src:
        src.append(root)
        _write_sources(src)
    return root


def remove_source(path):
    _write_sources([x for x in local_sources() if x != path])


def sources_info(candidates=()):
    """For the page: each folder, whether it is there, how many candidates it holds."""
    out = []
    for x in local_sources():
        root = source_root(x)
        n = sum(1 for c in candidates if str(c.get("path", "")).startswith(root + os.sep))
        out.append({"path": x, "exists": os.path.isdir(root), "count": n})
    return out


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
    for rel in local_sources():
        root = source_root(rel)
        if not os.path.isdir(root):
            continue
        for d, dirs, files in os.walk(root):
            depth = os.path.relpath(d, root).count(os.sep)
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".") and depth < 6]
            if os.path.abspath(d).startswith((os.path.abspath(LIB_DIR), HERE)):
                continue                           # never the show's own library, nor the tools themselves
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


# ------------------------------------------------------------------- codecs --
ALPHA_FMT = re.compile(r"(^|[^a-z])(rgba|bgra|argb|abgr|ya|yuva|gbrap|pal8)")


def has_alpha(c):
    """Whether a candidate is really transparent somewhere: an alpha channel
    that isn't all opaque. Renders often carry one that is 255 everywhere."""
    first = c["first"] if c["kind"] == "sequence" else c["path"]
    try:
        fmt = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=pix_fmt", "-of", "csv=p=0", first],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    if not ALPHA_FMT.search(fmt):
        return False
    # the lowest alpha over the first frames (a sequence: its first image)
    src = ["-i", first] if c["kind"] != "video" else ["-i", c["path"], "-t", "2"]
    try:
        err = subprocess.run(["ffmpeg", "-hide_banner", *src, "-vf",
                              "format=rgba,alphaextract,signalstats,metadata=print:key=lavfi.signalstats.YMIN",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=60).stderr
    except (OSError, subprocess.SubprocessError):
        return True                            # can't tell: keep the alpha, to be safe
    lows = [int(v) for v in re.findall(r"YMIN=(\d+)", err)]
    return bool(lows) and min(lows) < 250


def codec_of(c, alpha):
    """(extension, ffmpeg output arguments, label) for a candidate."""
    if c["kind"] == "still":
        if alpha:
            return ".png", ["-frames:v", "1"], "PNG (transparent)"
        return ".mov", ["-frames:v", "1", "-c:v", "dxv", "-f", "mov"], "DXV"
    if alpha:
        return ".mov", ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                        "-alpha_bits", "16", "-f", "mov"], "ProRes 4444 (transparent)"
    return ".mov", ["-c:v", "dxv", "-f", "mov"], "DXV"


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


def clip_video(name):
    """A show clip as a small H.264 the browser can play (it can't play DXV), the
    whole clip, for the timeline's monitor. Remade when the clip's file changes."""
    clip = next((x for x in config()["clips"] if x["name"] == name), None)
    if not clip:
        return None
    src = os.path.join(SHOW, clip["file"])
    if not os.path.exists(src):
        return None
    key = hashlib.sha1(f"{src}{os.path.getmtime(src)}".encode()).hexdigest()[:12]
    out = os.path.join(CACHE, "clipvideo", key + ".mp4")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-t", "120",
                        "-vf", "scale=480:-2,format=yuv420p", "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "26", "-movflags", "+faststart", tmp],
                       capture_output=True, timeout=300)
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
    alpha = has_alpha(c)
    # letterbox bars are black, or see-through when the clip is
    frame = (f"scale={SHOW_W}:{SHOW_H}:force_original_aspect_ratio=increase,crop={SHOW_W}:{SHOW_H}"
             if fit == "fill" else
             f"scale={SHOW_W}:{SHOW_H}:force_original_aspect_ratio=decrease,format=rgba,"
             f"pad={SHOW_W}:{SHOW_H}:(ow-iw)/2:(oh-ih)/2:{'black@0' if alpha else 'black'}")
    ext, codec, label = codec_of(c, alpha)
    out = os.path.join(LIB_DIR, name + ext)
    try:
        if ext == ".png":
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", c["path"], "-vf", frame,
                                "-frames:v", "1", out], capture_output=True, text=True)
        else:
            total = 1.0 if c["kind"] == "still" else max(0.1, float(c.get("seconds") or 1))
            src = ["-i", c["path"]] if c["kind"] == "still" else _input(c)
            p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", *src, "-vf", frame + ",format=rgba",
                                  "-an", *codec, "-progress", "pipe:1", out + ".part"],
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
        entry = {"name": name, "file": os.path.relpath(out, SHOW), "source": c["path"],
                 "kind": c["kind"], "project": c["project"], "tags": tags, "song": song,
                 "who": who, "fit": fit, "fps": c.get("fps"), "seconds": c.get("seconds"),
                 "codec": label, "added": time.strftime("%Y-%m-%d %H:%M")}
        old = next((x for x in cfg["clips"] if x["name"] == name), None)
        if old:                                 # a reconvert: same name, new file
            for k in ("tags", "song", "who", "added"):
                entry[k] = old.get(k, entry[k])
            if old.get("file") and old["file"] != entry["file"]:
                try:
                    os.remove(os.path.join(SHOW, old["file"]))
                except OSError:
                    pass
            cfg["clips"] = [entry if x is old else x for x in cfg["clips"]]
        else:
            cfg["clips"].append(entry)
        save(cfg)
        jobs[job].update(state="done", progress=1.0)
    except (OSError, RuntimeError, ValueError) as e:
        jobs[job].update(state="failed", error=str(e))
        for leftover in (os.path.join(LIB_DIR, name + ".mov.part"),):
            if os.path.exists(leftover):
                os.remove(leftover)


def candidate_for(x):
    """A library clip's source, described the way scan() would, to convert again."""
    path = x["source"]
    if x["kind"] == "sequence":
        folder = os.path.dirname(path)
        pat = re.compile("^" + re.escape(os.path.basename(path)).replace(re.escape("%04d"), r"(\d{4})") + "$")
        nums = sorted(int(m.group(1)) for f in os.listdir(folder) if (m := pat.match(f)))
        if not nums:
            raise ValueError(f"{x['name']}: its frames are gone from {folder}")
        first = os.path.join(folder, os.path.basename(path) % nums[0])
        return {"id": hashlib.sha1(path.encode()).hexdigest()[:12],
                "path": path, "kind": "sequence", "first": first, "start": nums[0],
                "fps": x.get("fps") or config().get("sequence_fps", 30), "frames": len(nums),
                "seconds": x.get("seconds"), "project": x.get("project", "")}
    if not os.path.exists(path):
        raise ValueError(f"{x['name']}: {path} is gone")
    return {"id": hashlib.sha1(path.encode()).hexdigest()[:12],
            "path": path, "kind": x["kind"], "first": path, "fps": x.get("fps"),
            "seconds": x.get("seconds"), "project": x.get("project", "")}


def wants_reconvert(x):
    """Whether a clip was made before every clip went to a GPU codec."""
    if x.get("codec"):
        return False
    return x["kind"] == "still" and x["file"].lower().endswith(".png") or \
        not x["file"].lower().endswith(".mov")


def reconvert(names=None, wait=True):
    """Convert library clips again from their sources, under the same names."""
    cfg = config()
    todo = [x for x in cfg["clips"] if (x["name"] in names if names else wants_reconvert(x))]
    done = []
    for x in todo:
        c = candidate_for(x)
        job = hashlib.sha1(f"re{x['name']}{time.time()}".encode()).hexdigest()[:10]
        jobs[job] = {"name": x["name"], "state": "converting", "progress": 0.0, "error": None}
        _convert(job, c, x["name"], x.get("tags", []), x.get("who", ""), x.get("song", ""), x.get("fit", "fit"))
        done.append((x["name"], jobs[job]["state"], jobs[job]["error"]))
    return done


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
            for p in (os.path.join(SHOW, x["file"]), os.path.join(THUMBS, name + ".jpg")):
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
            items.append({"name": x["name"], "url": arena_load.file_url(os.path.join(SHOW, x["file"]))})
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
    ap.add_argument("--reconvert", nargs="*", metavar="NAME",
                    help="convert clips again from their sources: the named ones, or every one "
                         "made before stills went to DXV too")
    a = ap.parse_args()
    if a.reconvert is not None:
        for name, state, err in reconvert(a.reconvert or None):
            x = next(c for c in config()["clips"] if c["name"] == name)
            print(f"  {name:<24} {state:<8} {x.get('codec') or ''} {x['file']}{'  ' + err if err else ''}")
        return
    if a.scan:
        for c in scan():
            print(f"  {c['project']:<14} {c['kind']:<8} {'draft ' if c['draft'] else '      '}"
                  f"{c.get('w')}x{c.get('h')} {c.get('seconds') or '':>6}s  {c['name']}")
    else:
        cfg = config()
        for x in cfg["clips"]:
            print(f"  clip  {x['name']:<24} {x.get('seconds') or '':>6}s  {x.get('codec') or os.path.splitext(x['file'])[1]:<10} "
                  f"{', '.join(x.get('tags') or [])}")
        for x in cfg["live"]:
            print(f"  live  {x['name']:<24} {x['source']}")


if __name__ == "__main__":
    main()
