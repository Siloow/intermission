"""Serve the floor-plan editor and save what it draws to rig.json.

    python3 plan_server.py            http://localhost:8765
    python3 plan_server.py --port 9000 --no-open

Standard library only, so it runs on any Mac with Python 3. It serves two pages: the floor plan at / (writes rig.json, which Blender
watches, so dragging a par in the browser moves it in the previz) and the show
timeline at /show (writes cues.json, the visual plan, against show.json which
sync_show.py extracts from the Ableton set).

It listens on localhost only: nothing here is reachable from the network.
"""
import argparse, html, http.server, json, os, re, shutil, socketserver, subprocess, tempfile, threading, time
import urllib.parse, urllib.request
import showfolder                    # where the show folder is on this Mac
import version                       # Intermission's version, from VERSION
import arena_load                    # talks to Resolume's REST API
import band                          # the control band: looks rendered as clips
import library                       # the show's visuals, gathered from everywhere
import host                          # projects, and starting the software
import td_stills                     # stills of the TouchDesigner scenes
import hashlib
import socket
from cue_player import osc_encode    # to hand the timeline's playhead to the player
PLAYER_PORT = 11001                  # where cue_player listens (AbletonOSC replies there too)
_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = showfolder.root()             # the plan, media and bounces: shared, not next to the code
RIG = os.path.join(SHOW, "rig.json")
MAP = os.path.join(SHOW, "osc_map.json")
LOOKS = os.path.join(SHOW, "looks.json")
# files the editors may read and write, by name
DATA = {"/rig.json": RIG,
        "/cues.json": os.path.join(SHOW, "cues.json"),
        "/looks.json": LOOKS,
        # what the previz should show right now while a look is being designed
        "/preview.json": os.path.join(HERE, ".live", "preview.json")}
READONLY = {"/show.json": os.path.join(SHOW, "show.json"),
            "/fixtures.json": os.path.join(HERE, "fixtures.json"),
            "/osc_map.json": MAP,
            # what cue_player is doing right now, for the timeline to mirror
            "/player.json": os.path.join(HERE, ".live", "player.json")}
PAGE = os.path.join(HERE, "plan_editor.html")
SHOW_PAGE = os.path.join(HERE, "show_editor.html")
DOCS_PAGE = os.path.join(HERE, "docs.html")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")
LIBRARY_PAGE = os.path.join(HERE, "library.html")
HOST_PAGE = os.path.join(HERE, "host.html")
_scan = {"t": 0.0, "v": None}


def changelog_html():
    """CHANGELOG.md as HTML, for the docs page. Only the little Markdown the file
    uses: ## headings, paragraphs, - lists (an item may wrap onto indented lines),
    **bold**, `code` and [links](url)."""
    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    try:
        lines = open(CHANGELOG).read().splitlines()
    except OSError:
        return "<p>There is no CHANGELOG.md next to the tools.</p>"
    first = next((i for i, l in enumerate(lines) if l.startswith("## ")), 0)
    lines = lines[first:]                              # the file's own preamble is for the repo, not the page
    out, para, items = [], [], []
    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>"); para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>"); items.clear()
    for line in lines:
        if line.startswith("# "):                       # the page has its own heading
            continue
        if line.startswith("## "):
            flush()
            ver = line[3:].strip()
            out.append(f'<h3 id="v{re.sub(r"[^0-9.]", "", ver.split()[0])}">{inline(ver)}</h3>')
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:].strip())
        elif line.startswith("  ") and items and line.strip():
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(out)


def library_scan(force=False):
    """The candidates, rescanned at most every 20 s unless asked."""
    if force or not _scan["v"] or time.time() - _scan["t"] > 20:
        _scan.update(t=time.time(), v=library.scan())
    return _scan["v"]


def library_candidate(cid):
    return next((c for c in library_scan() if c["id"] == cid), None)
# folders the Band view may play from, by the name in the URL
CONTENT = {"light-loops": os.path.join(HERE, "content", "light-loops"),
           "light-looks": os.path.join(SHOW, "light-looks")}
LIB = os.path.join(HERE, "lib")
AUDIO = os.path.join(SHOW, "audio")
STATUS = os.path.join(HERE, ".live", "status.json")
BACKUP_EVERY = 300          # seconds between keeping a spare copy of the rig
PLAYER = READONLY["/player.json"]
ARENA = "http://127.0.0.1:8080"
FRESH = 3.0                 # seconds: older than this and a writer is gone


PEAKS_RATE = 50             # waveform values per second of the bounce
PEAKS_SR = 6000             # decode rate for them: plenty for a picture, quick to scan
_peaks_lock = threading.Lock()   # one waveform build at a time: a second tab waits, then finds the cache


def write_peaks(src, cache):
    import array, base64, math
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", str(PEAKS_SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    pcm = array.array("h"); pcm.frombytes(raw[: len(raw) // 2 * 2])
    win = PEAKS_SR // PEAKS_RATE
    peak, rms = bytearray(), bytearray()
    for i in range(0, len(pcm), win):
        w = pcm[i:i + win]
        peak.append(min(255, max(max(w), -min(w)) * 255 // 32767))
        rms.append(min(255, int(math.sqrt(sum(v * v for v in w) / len(w)) * 255 / 32767 * 1.4)))
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    tmp = cache + ".tmp"                 # whole or not at all: a reader never sees a half-written file
    with open(tmp, "w") as fh:
        json.dump({"rate": PEAKS_RATE, "seconds": len(pcm) / PEAKS_SR,
                   "peak": base64.b64encode(peak).decode(), "rms": base64.b64encode(rms).decode()}, fh)
    os.replace(tmp, cache)


def age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


_arena = {"t": 0.0, "v": None}


def arena_state():
    """Is Resolume answering, and with which composition. Asked at most every 3 s."""
    if time.time() - _arena["t"] < 3:
        return _arena["v"]
    try:
        with urllib.request.urlopen(ARENA + "/api/v1/composition", timeout=0.6) as r:
            comp = json.loads(r.read())
        v = {"ok": True, "text": f"{arena_load.name_of(comp) or 'untitled'} · "
                                 f"{len(comp.get('layers', []))} layers"}
        osc = arena_load.osc_input()
        try:
            want = json.load(open(MAP)).get("resolume", {}).get("port", 7000)
        except (OSError, ValueError):
            want = 7000
        if osc is not None and not osc[0]:
            v = {"ok": False, "text": "OSC input is off — cues are ignored",
                 "fix": f"Arena → Preferences → OSC → turn on OSC Input, port {want}"}
        elif osc is not None and osc[1] != want:
            v = {"ok": False, "text": f"OSC on port {osc[1]}, the player sends to {want}",
                 "fix": "Match them in Arena → Preferences → OSC, or resolume.port in osc_map.json"}
    except (OSError, ValueError):
        v = {"ok": False, "text": "not answering",
             "fix": "Open Arena; Preferences → Webserver → Enable Webserver & REST API (port 8080)"}
    _arena.update(t=time.time(), v=v)
    return v


_comp = {"t": 0.0, "v": None}
_thumbs = {}                 # clip id -> (last_update, png)


def composition():
    """The composition for the Resolume panel: Arena's, or the last one seen.
    Asked at most every 0.8 s however many tabs are polling."""
    if time.time() - _comp["t"] < 0.8 and _comp["v"]:
        return _comp["v"]
    snap, live = arena_load.current(ARENA)
    v = dict(snap or {"name": None, "layers": [], "columns": []}, live=live)
    _comp.update(t=time.time(), v=v)
    return v


def thumbnail(clip_id, version):
    got = _thumbs.get(clip_id)
    if got and got[0] == version:
        return got[1]
    with urllib.request.urlopen(f"{ARENA}/api/v1/composition/clips/by-id/{clip_id}/thumbnail",
                                timeout=1.5) as r:
        png = r.read()
    _thumbs[clip_id] = (version, png)
    return png


def health():
    """One look at every moving part, for the status strip on each page."""
    out = {"resolume": arena_state(), "version": version.read()}

    pa = age(PLAYER)
    try:
        ps = json.load(open(PLAYER))
    except (OSError, ValueError):
        ps = {}
    if pa is None or pa > FRESH:
        out["player"] = {"ok": False, "text": "not running",
                         "fix": "Test.command starts it (or: python3 cue_player.py --follow --preview)"}
        out["live"] = {"ok": None, "text": "unknown — the player asks Live",
                       "fix": "Start the player first"}
    else:
        out["player"] = {"ok": not ps.get("panic"), "warn": bool(ps.get("panic")),
                         "text": "PANIC — cues held: Resume on the Host page (or r)" if ps.get("panic")
                         else f"bar {ps.get('bar', 1):.0f}" + (" · driven by the timeline"
                                                            if ps.get("source") == "timeline" else "")}
        if not ps.get("live_connected"):
            out["live"] = {"ok": False, "text": "not answering",
                           "fix": "Open the show set; Preferences → Link/Tempo/MIDI → Control Surface: AbletonOSC"}
        else:
            out["live"] = {"ok": True, "text": "playing" if ps.get("playing") else "stopped",
                           "warn": not ps.get("playing")}

    ba = age(STATUS)
    try:
        bs = json.load(open(STATUS))
    except (OSError, ValueError):
        bs = {}
    if ba is None or ba > FRESH:
        out["blender"] = {"ok": False, "text": "not running", "fix": "Test.command opens it"}
        out["artnet"] = out["screen"] = {"ok": None, "text": "unknown — Blender measures it"}
    else:
        out["blender"] = {"ok": True, "text": f"{bs.get('rig_fixtures', 0)} fixtures"
                          + (f" · look {bs['look']}" if bs.get("look") else "")}
        pps = bs.get("artnet_pps") or 0
        out["artnet"] = ({"ok": True, "text": f"{pps:.0f} pkt/s from {bs.get('artnet_from', '?')}"}
                         if pps >= 1 else
                         {"ok": False, "text": bs.get("artnet_error") or "nothing arriving",
                          "fix": "Resolume → Output → Advanced Output: Lumiverse on Art-Net to 127.0.0.1"})
        fps = bs.get("screen_fps") or 0
        out["screen"] = ({"ok": True, "text": f"{fps:.0f} fps"} if fps >= 1 else
                         {"ok": False, "text": "no frames",
                          "fix": "Resolume → Output → Syphon on; the bridge runs with Test.command (log: .live/bridge.log)"})
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    last_backup = 0.0

    def _send(self, code, body=b"", ctype="application/json", mtime=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if mtime is not None:
            self.send_header("X-File-Mtime", f"{mtime:.3f}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/plan_editor.html"):
            try:
                body = open(PAGE, "rb").read()
            except OSError:
                return self._send(404, b"plan_editor.html is missing", "text/plain")
            return self._send(200, body, "text/html; charset=utf-8")
        if path in ("/show", "/show_editor.html"):
            try:
                body = open(SHOW_PAGE, "rb").read()
            except OSError:
                return self._send(404, b"show_editor.html is missing", "text/plain")
            return self._send(200, body, "text/html; charset=utf-8")
        if path in ("/docs", "/docs.html"):
            try:
                body = open(DOCS_PAGE, "rb").read()
            except OSError:
                return self._send(404, b"docs.html is missing", "text/plain")
            body = body.replace(b"<!--CHANGELOG-->", changelog_html().encode())   # What changed, from CHANGELOG.md
            return self._send(200, body, "text/html; charset=utf-8")
        if path in ("/host", "/host.html"):
            try:
                body = open(HOST_PAGE, "rb").read()
            except OSError:
                return self._send(404, b"host.html is missing", "text/plain")
            return self._send(200, body, "text/html; charset=utf-8")
        if path == "/host/status":
            return self._send(200, json.dumps({**host.HOST.status(), "health": health(),
                                               "local": self.is_local()}).encode())
        if path == "/host/log":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            name = (q.get("name") or ["player.log"])[0]
            return self._send(200, json.dumps({"name": name, "text": host.tail(name)}).encode())
        if path == "/projects":
            return self._send(200, json.dumps(host.listing()).encode())
        if path in ("/library", "/library.html"):
            try:
                body = open(LIBRARY_PAGE, "rb").read()
            except OSError:
                return self._send(404, b"library.html is missing", "text/plain")
            return self._send(200, body, "text/html; charset=utf-8")
        if path == "/library/scan":
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            cands = library_scan(force=bool(q.get("force")))
            cfg = library.config()
            for x in cfg["clips"]:          # where each clip came from, for its hover preview
                x["source_id"] = hashlib.sha1(x.get("source", "").encode()).hexdigest()[:12]
            return self._send(200, json.dumps({"candidates": cands, "clips": cfg["clips"],
                                               "live": cfg["live"], "sources": library.sources_info(cands)}).encode())
        if path.startswith("/library/thumb/") or path.startswith("/library/preview/"):
            c = library_candidate(os.path.basename(path))
            if not c:
                return self._send(404, b"", "text/plain")
            out = library.thumb(c) if "/thumb/" in path else library.preview(c)
            return self.send_file(out) if out else self._send(404, b"", "text/plain")
        if path.startswith("/library/clipthumb/"):
            name = os.path.basename(urllib.parse.unquote(path))
            return self.send_file(os.path.join(library.THUMBS, name + ".jpg"))
        if path.startswith("/library/clipvideo/"):
            # a show clip the browser can play, for the timeline's monitor
            out = library.clip_video(os.path.basename(urllib.parse.unquote(path)))
            return self.send_file(out) if out else self._send(404, b"", "text/plain")
        if path == "/td/list":
            # the TouchDesigner scenes, as td_stills.py last grabbed them
            return self._send(200, json.dumps(td_stills.load()).encode())
        if path.startswith("/td/still/"):
            name = os.path.basename(urllib.parse.unquote(path))
            return self.send_file(os.path.join(td_stills.stills_dir(), name + ".jpg"))
        if path == "/library/list":
            # just the show's visuals, for the timeline's quick picker (no rescan)
            cfg = library.config()
            return self._send(200, json.dumps({
                "clips": [{"name": x["name"], "song": x.get("song"), "tags": x.get("tags", []),
                           "seconds": x.get("seconds")} for x in cfg["clips"]],
                "live": [{"name": x["name"], "source": x["source"], "tags": x.get("tags", [])}
                         for x in cfg["live"]]}).encode())
        if path == "/library/jobs":
            return self._send(200, json.dumps(library.jobs).encode())
        if path == "/library/live-sources":
            try:
                return self._send(200, json.dumps({"live": True, "sources": library.live_sources(ARENA)}).encode())
            except (SystemExit, OSError, ValueError):
                return self._send(200, json.dumps({"live": False, "sources": []}).encode())
        if path == "/library/status":
            # which library entries are clips in each screen layer
            snap, live = arena_load.current(ARENA)
            out = {"live": live, "composition": snap and snap.get("name"), "lanes": {}}
            for lane in ("screen", "overlay"):
                ref = (arena_load.lanes().get(lane) or {}).get("layer")
                L, _ = arena_load.find_clip(snap or {"layers": []}, ref, "")
                layer = next((l for l in (snap or {}).get("layers", []) if l["index"] == L), None)
                out["lanes"][lane] = {"layer": L, "name": layer and layer["name"],
                                      "clips": [c["name"] for c in (layer or {}).get("clips", [])]}
            return self._send(200, json.dumps(out).encode())
        if path in ("/band", "/band_view.html"):
            # the Band view became the floor plan's Loop mode
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            dest = "/?room=loop&band=1" + (f"&clip={urllib.parse.quote(q['clip'][0])}" if q.get("clip") else "")
            self.send_response(302)
            self.send_header("Location", dest)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/band/layout":
            # where each fixture samples the band, and where it stands in the room
            rig = json.load(open(RIG))
            profiles = json.load(open(os.path.join(HERE, "fixtures.json"))).get("profiles", {})
            cells = band.layout(rig, profiles)
            where = {f["name"]: f for f in rig.get("fixtures", [])}
            for c in cells:
                f = where.get(c["name"], {})
                prof = profiles.get(f.get("profile"), {})
                c.update({k: f.get(k) for k in ("x", "y", "rot_deg", "aim_deg", "tilt_deg", "beam_deg")})
                c["length"] = (prof.get("body") or {}).get("length")
            return self._send(200, json.dumps({"width": band.W, "height": band.H, "cells": cells,
                                               "venue": rig.get("venue", {})}).encode())
        if path == "/band/clips":
            loops = {}
            try:
                loops = json.load(open(os.path.join(CONTENT["light-loops"], "loops.json")))
            except (OSError, ValueError):
                pass
            have = set(os.listdir(CONTENT["light-loops"])) if os.path.isdir(CONTENT["light-loops"]) else set()
            listed = [l for l in loops.get("loops", []) if l["file"] in have]
            extra = sorted(f for f in have if f.lower().endswith((".mp4", ".mov", ".m4v"))
                           and f not in {l["file"] for l in listed})
            listed += [{"file": f, "name": os.path.splitext(f)[0], "bars": None, "what": "",
                        "category": "Other"} for f in extra]
            try:
                looks = json.load(open(LOOKS)).get("looks", [])
            except (OSError, ValueError):
                looks = []
            show = {}
            try:
                show = json.load(open(READONLY["/show.json"]))
            except (OSError, ValueError):
                pass
            cats = loops.get("categories") or []
            if extra:
                cats = cats + ["Other"]
            return self._send(200, json.dumps({"loops": listed, "loop_bpm": loops.get("bpm"),
                                               "categories": cats,
                                               "looks": looks, "tempo": show.get("tempo")}).encode())
        if path.startswith("/content/"):
            parts = path.split("/")
            folder = CONTENT.get(parts[2] if len(parts) > 3 else "")
            if not folder:
                return self._send(404, b"not found", "text/plain")
            name = os.path.basename(urllib.parse.unquote(path))
            return self.send_file(os.path.join(folder, name))
        if path.startswith("/lib/"):
            name = os.path.basename(path)          # no traversal: basename only
            try:
                body = open(os.path.join(LIB, name), "rb").read()
            except OSError:
                return self._send(404, b"not found", "text/plain")
            ext = os.path.splitext(name)[1].lower()
            ctype = {".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
                     ".ico": "image/x-icon"}.get(ext, "application/javascript")
            return self._send(200, body, ctype if ext in (".png", ".ico") else ctype + "; charset=utf-8")
        if path == "/favicon.ico":                 # a browser asking on its own: the same mark, as PNG
            try:
                return self._send(200, open(os.path.join(LIB, "favicon-32.png"), "rb").read(), "image/png")
            except OSError:
                return self._send(404, b"not found", "text/plain")
        if path == "/arena/params":
            # every automatable parameter in the open composition, for the target picker
            try:
                index = arena_load.params(arena_load.fetch(ARENA))
            except (OSError, ValueError):
                return self._send(200, json.dumps({"live": False, "params": []}).encode())
            # not the Transforms that put the band where the fixtures read: the Lights
            # layer's, and the composition's (it moves everything, band included)
            lights = (arena_load.lanes().get("lights") or {}).get("layer")
            index = [p for p in index if p["path"][:4] != ["layer", lights, "effect", "Transform"]
                     and p["path"][:3] != ["composition", "effect", "Transform"]]
            return self._send(200, json.dumps({"live": True, "params": [
                {k: p[k] for k in ("path", "label", "group", "min", "max", "value")} for p in index]}).encode())
        if path == "/presets/status":
            # which presets are already clips in the lights layer
            snap, live = arena_load.current(ARENA)
            ref = (arena_load.lanes().get("lights") or {}).get("layer")
            L, _ = arena_load.find_clip(snap or {"layers": []}, ref, "")
            layer = next((l for l in (snap or {}).get("layers", []) if l["index"] == L), None)
            return self._send(200, json.dumps({
                "live": live, "layer": L, "layer_name": layer and layer["name"],
                "composition": snap and snap.get("name"),
                "installed": [c["name"] for c in (layer or {}).get("clips", [])]}).encode())
        if path == "/arena/composition":
            return self._send(200, json.dumps(composition()).encode())
        if path.startswith("/arena/thumb/"):
            clip_id = os.path.basename(path)
            if not clip_id.isdigit():
                return self._send(404, b"", "text/plain")
            version = urllib.parse.parse_qs(self.path.partition("?")[2]).get("v", [""])[0]
            try:
                png = thumbnail(clip_id, version)
            except OSError:
                return self._send(404, b"", "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "max-age=3600")    # the ?v= changes when it does
            self.end_headers()
            return self.wfile.write(png)
        if path == "/health":
            return self._send(200, json.dumps(health()).encode())
        if path == "/media/list":
            # what the Load clip picker offers for a lane
            lane = urllib.parse.parse_qs(self.path.partition("?")[2]).get("lane", ["lights"])[0]
            cfg = arena_load.lanes().get(lane) or {}
            folder = arena_load.lane_dir(lane) or ""
            return self._send(200, json.dumps({
                "lane": lane, "layer": cfg.get("layer"), "dir": cfg.get("dir"),
                "files": arena_load.media_in(folder)}).encode())
        if path == "/audio/list":
            try:
                names = sorted(f for f in os.listdir(AUDIO)
                               if f.lower().endswith((".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")))
            except OSError:
                names = []
            return self._send(200, json.dumps({"files": names}).encode())
        if path.startswith("/audio/peaks/"):
            return self.send_peaks(os.path.basename(urllib.parse.unquote(path)))
        if path.startswith("/audio/"):
            return self.send_audio(os.path.basename(urllib.parse.unquote(path)))
        if path == "/status.json":
            # what Blender is seeing right now, for live colours in the preview
            try:
                return self._send(200, open(STATUS, "rb").read())
            except OSError:
                return self._send(200, b'{"live":false}')
        if path in DATA or path in READONLY:
            target = DATA.get(path) or READONLY[path]
            try:
                # the mtime goes out with the file so an editor can prove, when it
                # saves, that it is writing over the version it actually loaded
                return self._send(200, open(target, "rb").read(),
                                  mtime=os.path.getmtime(target))
            except OSError:
                if path == "/cues.json":
                    return self._send(200, b'{"cues":[]}')
                if path == "/looks.json":
                    return self._send(200, b'{"looks":[]}')
                if path == "/preview.json":
                    return self._send(200, b'{"fixtures":{}}')
                if path == "/player.json":
                    return self._send(200, b'{"t":0}')
                return self._send(404, json.dumps(
                    {"error": f"no {os.path.basename(target)} yet"}).encode())
        self._send(404, b'{"error":"not found"}')

    def send_audio(self, name):
        """Serve a bounce, honouring Range requests so the browser can seek."""
        return self.send_file(os.path.join(AUDIO, name))

    def send_peaks(self, name):
        """The bounce's waveform for the timeline: peak and RMS, PEAKS_RATE per second,
        each a byte (0-255) in base64. Made once with ffmpeg, then cached next to it."""
        src = os.path.join(AUDIO, name)
        cache = os.path.join(AUDIO, ".peaks", name + ".json")
        try:
            with _peaks_lock:
                if not (os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(src)):
                    write_peaks(src, cache)
            return self._send(200, open(cache, "rb").read())
        except (OSError, subprocess.CalledProcessError) as e:
            return self._send(404, json.dumps({"error": str(e)}).encode())

    def send_file(self, path):
        """Serve a media file, honouring Range requests so the browser can seek."""
        types = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
                 ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg",
                 ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
                 ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        name = os.path.basename(path)
        ctype = types.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
        try:
            size = os.path.getsize(path)
            fh = open(path, "rb")
        except OSError:
            return self._send(404, b"no such audio", "text/plain")
        with fh:
            rng = self.headers.get("Range", "")
            start, end = 0, size - 1
            partial = rng.startswith("bytes=")
            if partial:
                first, _, last = rng[6:].partition("-")
                start = int(first) if first else 0
                end = int(last) if last else size - 1
                start, end = max(0, start), min(end, size - 1)
            fh.seek(start)
            body = fh.read(end - start + 1)
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/media/load":
            return self.media_load()
        if path == "/looks/clip":
            return self.look_clip()
        if path == "/presets/install":
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                report = arena_load.install(ARENA, "lights", names=req.get("names"),
                                            refresh=bool(req.get("refresh")))
            except (ValueError, TypeError, OSError, RuntimeError, SystemExit) as e:
                return self._send(502, json.dumps({"error": str(e)}).encode())
            _comp["t"] = 0                                  # the timeline sees them on its next poll
            return self._send(200, json.dumps(report).encode())
        if path == "/arena/copy":
            # a clip dropped on a lane from another layer: the same file into the
            # lane's layer, so a lane switches inside one layer (crossfades, the
            # layer's effects and automation all apply). A live source has no file.
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                comp = arena_load.fetch(ARENA)
                _, src = arena_load.find_layer(comp, int(req["from"]))
                clip = next((c for c in src.get("clips", []) if arena_load.name_of(c) == req["name"]), None)
                info = ((clip or {}).get("video") or {}).get("fileinfo") or {}
                if not info.get("path"):
                    return self._send(409, json.dumps({"error": f"{req['name']} has no file to copy (a live source?)"}).encode())
                lane = req["lane"]
                layer = (arena_load.lanes().get(lane) or {}).get("layer")
                report = arena_load.install_items(ARENA, layer, [{"name": req["name"], "url": arena_load.file_url(info["path"])}],
                                                  lane=lane, sync=lane == "lights")
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, SystemExit) as e:
                return self._send(502, json.dumps({"error": str(e)}).encode())
            _comp["t"] = 0
            return self._send(200, json.dumps(report).encode())
        if path.startswith("/library/"):
            return self.library_post(path)
        if path == "/td/grab":
            # stills of the TouchDesigner scenes: every scene, or the one on screen
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                out = td_stills.grab(current=bool(req.get("current")), names=req.get("names"),
                                     log=lambda *a: None)
            except (ValueError, TypeError, OSError, RuntimeError) as e:
                return self._send(502, json.dumps({"error": str(e)}).encode())
            return self._send(200, json.dumps(out).encode())
        if path.startswith("/host/") or path.startswith("/projects/"):
            return self.host_post(path)
        if path == "/transport":
            # the timeline's playhead, for the player to follow when Live isn't playing.
            # The browser never talks to Resolume: it only says where it is.
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                if req.get("release"):             # hand the show back to Live
                    _udp.sendto(osc_encode("/timeline/release", [1]), ("127.0.0.1", PLAYER_PORT))
                    return self._send(204)
                beat = float(req["beat"])
                _udp.sendto(osc_encode("/timeline/beats", [beat]), ("127.0.0.1", PLAYER_PORT))
            except (ValueError, KeyError, TypeError, OSError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
            return self._send(204)
        if path == "/targets/add":
            return self.target_add()
        if path == "/targets/range":
            return self.target_range()
        target = DATA.get(path)
        if not target:
            return self._send(404, b'{"error":"not found"}')
        key = {"/rig.json": "fixtures", "/cues.json": "cues",
               "/looks.json": "looks", "/preview.json": "fixtures"}[path]
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            # a preview is a map of fixture -> values; everything else is a list
            wanted = dict if path == "/preview.json" else list
            if not isinstance(data.get(key), wanted):
                raise ValueError(f"no {key}")
        except (ValueError, TypeError) as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())

        # refuse to overwrite a file that changed since this editor loaded it:
        # a stale tab must not throw away someone else's work
        want = self.headers.get("X-If-Mtime")
        if want and path != "/preview.json" and os.path.exists(target):
            have = os.path.getmtime(target)
            if abs(have - float(want)) > 0.002:
                return self._send(409, json.dumps({
                    "error": "changed on disk since you loaded it — reload the page",
                    "mtime": have}).encode(), mtime=have)

        os.makedirs(os.path.dirname(target), exist_ok=True)
        now = time.time()
        if path != "/preview.json" and os.path.exists(target) and now - Handler.last_backup > BACKUP_EVERY:
            shutil.copy2(target, target + ".bak")   # one step back, in case of a slip
            Handler.last_backup = now
        # write to a temporary file and move it into place, so nothing ever
        # reads a half-written file
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, target)
        self._send(200, json.dumps({"saved": len(data[key])}).encode(),
                   mtime=os.path.getmtime(target))

    def media_load(self):
        """Load one file into its lane's Resolume layer, and map it to its name."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            lane, filename = req.get("lane", "lights"), req.get("file")
            if not filename:
                raise ValueError("no file given")
            name, layer, clip = arena_load.load_one(
                req.get("host") or "http://127.0.0.1:8080", lane, filename)
        except (ValueError, TypeError, RuntimeError, SystemExit) as e:
            return self._send(502, json.dumps({"error": str(e)}).encode())
        return self._send(200, json.dumps({"name": name, "layer": layer, "clip": clip}).encode())

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def host_post(self, path):
        """Projects (anyone the editors are shared with), and starting and
        stopping software (only this Mac: it's this Mac's software)."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if path.startswith("/host/") and not self.is_local():
                return self._send(403, json.dumps({"error": "only the show Mac can start or stop things"}).encode())
            H = host.HOST
            if path == "/projects/save":
                out = {"name": host.save(req.get("name"))}
            elif path == "/projects/load":
                out = host.load(req["name"])
            elif path == "/projects/new":
                out = {"name": host.new(req["name"])}
            elif path == "/projects/settings":
                out = host.settings(req["name"], **{k: v for k, v in req.items() if k != "name"})
            elif path == "/projects/delete":
                out = host.delete(req["name"])
            elif path == "/host/start":
                H.start("show" if req.get("mode") == "show" else "test", host.current())
                out = H.status()
            elif path == "/host/stop":
                H.stop()
                out = H.status()
            elif path == "/host/part":
                part, action = req["part"], req["action"]
                meta = host._meta(host.current()) if host.current() else {}
                if part == "arena" and action == "start":
                    H.open_arena(meta.get("composition"))
                elif part == "live" and action == "start":
                    H.open_live(meta.get("live_set") or host._live_set_of_show())
                elif part == "td" and action == "start":
                    H.open_td(meta)
                elif part == "blender":
                    H.start_blender() if action == "start" else H.stop_blender()
                elif part == "bridge":
                    H.start_bridge() if action == "start" else H.stop_bridge()
                elif part == "player":
                    if action == "start":
                        H.start_player("show" if req.get("mode") == "show" else "test")
                    else:
                        H.stop_player()
                else:
                    raise ValueError(f"can't {action} {part} from here")
                out = H.status()
            elif path in ("/host/panic", "/host/resume"):
                H.player_osc("/player/" + path.rsplit("/", 1)[1])
                out = {"ok": True}
            elif path == "/host/preflight":
                out = host.preflight(req.get("mode", "test"))
            else:
                return self._send(404, b'{"error":"not found"}')
        except (KeyError, ValueError, RuntimeError, OSError) as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())
        return self._send(200, json.dumps(out).encode())

    def library_post(self, path):
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if path == "/library/add":
                out = {"job": library.add(req["id"], req.get("name"), req.get("tags") or [],
                                          req.get("who", ""), req.get("song", ""), req.get("fit", "fit"))}
                _scan["t"] = 0
            elif path == "/library/update":
                out = library.update(req["name"], **{k: req[k] for k in ("tags", "song", "who", "note") if k in req})
            elif path == "/library/remove":
                library.remove(req["name"]); out = {"removed": req["name"]}; _scan["t"] = 0
            elif path == "/library/live":
                out = {"name": library.add_live(req["source"], req.get("name"), req.get("tags") or [], req.get("who", ""))}
            elif path == "/library/adopt":
                # a live source dragged into a slot by hand: name the selected clip
                out = arena_load.adopt_selected(ARENA, req["name"]); _comp["t"] = 0
            elif path == "/library/install":
                out = library.install(ARENA, req["names"], req.get("lane", "screen"))
                _comp["t"] = 0
            elif path == "/library/sources/add":
                # this Mac's folders to look in. pick: the Mac's own folder dialog (only
                # from this Mac: the dialog opens on its screen); otherwise a typed path
                if req.get("pick"):
                    if not self.is_local():
                        raise RuntimeError("the folder dialog opens on the show Mac only; paste the path instead")
                    r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt '
                                        '"A folder the Library should look in for visuals")'],
                                       capture_output=True, text=True, timeout=600)
                    if r.returncode or not r.stdout.strip():
                        out = {"cancelled": True}
                    else:
                        out = {"added": library.add_source(r.stdout.strip())}; _scan["t"] = 0
                else:
                    out = {"added": library.add_source(req.get("path", ""))}; _scan["t"] = 0
            elif path == "/library/sources/remove":
                library.remove_source(req["path"]); out = {"removed": req["path"]}; _scan["t"] = 0
            else:
                return self._send(404, b'{"error":"not found"}')
        except (KeyError, ValueError, TypeError, OSError, RuntimeError, SystemExit, subprocess.TimeoutExpired) as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())
        return self._send(200, json.dumps(out).encode())

    def target_add(self):
        """Add a Resolume parameter to osc_map.json's targets, by its path of
        names, and say what the lane should call it."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            want = json.loads(self.rfile.read(n) or b"{}").get("path")
            index = arena_load.params(arena_load.fetch(ARENA))
            param = arena_load.find_param(index, want)
            if not param:
                raise ValueError("that parameter isn't in the open composition")
            mp = MAP
            m = json.load(open(mp))
            targets = m.setdefault("targets", [])
            have = next((t for t in targets if t.get("resolume") == param["path"]), None)
            if not have:
                have = {"name": param["label"], "resolume": param["path"],
                        "min": param["min"], "max": param["max"], "curve": 0}
                names = {t["name"] for t in targets}
                while have["name"] in names:
                    have["name"] += "'"
                targets.append(have)
                tmp = mp + ".tmp"
                json.dump(m, open(tmp, "w"), indent=2)
                os.replace(tmp, mp)
        except (ValueError, TypeError, OSError) as e:
            return self._send(502, json.dumps({"error": str(e)}).encode())
        return self._send(200, json.dumps({"name": have["name"]}).encode())

    def target_range(self):
        """Set the part of a target's range that 0..100% of its lane covers."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            lo, hi = float(req["min"]), float(req["max"])
            mp = MAP
            m = json.load(open(mp))
            t = next((t for t in m.get("targets", []) if t["name"] == req.get("name")), None)
            if not t:
                raise ValueError(f"no target called {req.get('name')!r}")
            t["min"], t["max"] = lo, hi
            tmp = mp + ".tmp"
            json.dump(m, open(tmp, "w"), indent=2)
            os.replace(tmp, mp)
        except (ValueError, TypeError, KeyError, OSError) as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())
        return self._send(200, json.dumps({"name": t["name"], "min": lo, "max": hi}).encode())

    def look_clip(self):
        """Render looks onto the control band and load them into the lights
        layer, named after the look, so a Lights cue naming it just fires."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            looks = json.load(open(LOOKS)).get("looks", [])
            names = req.get("looks") or [req.get("look")]
            chosen = [l for l in looks if l["name"] in names]
            if not chosen:
                raise ValueError(f"no look called {names[0]!r} in looks.json")
            done = []
            for look in chosen:
                path = band.render_look(look)
                # a look is a still: no tempo to sync to
                name, layer, clip = arena_load.load_one(
                    ARENA, "lights", os.path.basename(path), sync=False, folder=band.LOOK_DIR)
                done.append({"look": look["name"], "name": name, "layer": layer, "clip": clip})
        except (ValueError, TypeError, OSError, RuntimeError, SystemExit) as e:
            return self._send(502, json.dumps({"error": str(e)}).encode())
        _comp["t"] = 0                          # show the new clip on the next poll
        return self._send(200, json.dumps({"made": done}).encode())

    def log_message(self, *a):
        pass                                    # quiet; the editor shows its own status


def lan_address():
    """This Mac's address on the local network, for another laptop to open."""
    import socket as _s
    probe = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        probe.connect(("192.168.0.1", 9))      # no packet is sent; it only picks the interface
        return probe.getsockname()[0]
    except OSError:
        return "this-mac.local"
    finally:
        probe.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    ap.add_argument("--lan", action="store_true",
                    help="also answer other computers on this network (to work together)")
    a = ap.parse_args()

    url = f"http://localhost:{a.port}/"
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    with Server((host, a.port), Handler) as httpd:
        print(f"[plan] floor-plan editor at {url}  (ctrl-c to stop)")
        if a.lan:
            ip = lan_address()
            print(f"[plan] shared on this network: http://{ip}:{a.port}/  (anyone on it can edit)")
        print(f"[plan] saving to {RIG}")
        if not a.no_open:
            subprocess.run(["open", url], check=False)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[plan] stopped")


if __name__ == "__main__":
    main()
