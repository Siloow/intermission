"""The show host: projects, and starting the software, from the browser.

Projects
    A project is a folder in the show folder's projects/ (see showfolder.py),
    holding a saved copy of the plan files every tool works on there (show.json, cues.json, rig.json, looks.json,
    osc_map.json, library.json), and project.json: its name, and which Live set,
    Resolume composition, TouchDesigner set and Advanced Output preset go with it.
    The TouchDesigner set lives in the show folder (td/, shared through Dropbox)
    and is stored relative to it, so it is the same set on both Macs.

    The tools keep working on the files in the show folder, as they always have.
    Save copies them into the project; load copies a project's in, after
    putting what was here into projects/.autosave/ first, so nothing is ever
    lost by loading. The player and Blender follow the files as they change.

Software
    Each part the show needs, started and stopped from here: Resolume Arena and
    Live are opened with the project's composition and set, TouchDesigner with
    its TD set (never quit from here: they hold the show), Blender with the previz, the Syphon bridge, and
    the player, which the host keeps running (a crash restarts it, like
    Live.command does). Test runs everything; the show runs only what it needs,
    keeps the Mac awake, and leaves Blender and the bridge off the GPU.

Standard library only. plan_server.py serves it; only this Mac may start things.
"""
import glob, json, os, platform, plistlib, re, shutil, signal, socket, subprocess, sys, threading, time
import urllib.request
import showfolder
import td_stills                         # where the show's TouchDesigner set is
import version

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = showfolder.root()                # the plan files live here, with the show
PROJECTS = os.path.join(SHOW, "projects")
CURRENT = os.path.join(PROJECTS, ".current")
AUTOSAVE = os.path.join(PROJECTS, ".autosave")
PROJECT_FILES = ("show.json", "cues.json", "rig.json", "looks.json", "osc_map.json", "library.json")
KEEP_AUTOSAVES = 30
LIVE_DIR = os.path.join(HERE, ".live")
PLAYER_PORT = 11001                     # the player listens here (Live's replies, the timeline, us)

ARENA_APPS = ("/Applications/Resolume Arena/Arena.app",)      # 7.19, the licence; not 7.27
TD_APP = "/Applications/TouchDesigner.app"


def live_app():
    """The Live to open the set in: the one AbletonOSC is set up in. That's a
    release, not a beta (the beta keeps its own preferences, without it): the
    newest non-beta Live, unless $LIVE_APP says otherwise."""
    if os.environ.get("LIVE_APP") and os.path.isdir(os.environ["LIVE_APP"]):
        return os.environ["LIVE_APP"]
    apps = sorted(glob.glob("/Applications/Ableton Live*.app") + glob.glob(os.path.expanduser("~/Applications/Ableton Live*.app")))
    release = [a for a in apps if "beta" not in a.lower()]
    return (release or apps or [None])[-1]
COMPOSITIONS = os.path.expanduser("~/Documents/Resolume Arena/Compositions")


# ------------------------------------------------------------------ projects --
def slug(name):
    s = re.sub(r"[^\w\- ]+", "", str(name)).strip()
    if not s:
        raise ValueError("give the project a name")
    return s[:60]


def current():
    try:
        return open(CURRENT).read().strip() or None
    except OSError:
        return None


def _set_current(name):
    os.makedirs(PROJECTS, exist_ok=True)
    open(CURRENT, "w").write(name)


def _meta(name):
    try:
        return json.load(open(os.path.join(PROJECTS, name, "project.json")))
    except (OSError, ValueError):
        return {"name": name}


def _write_meta(name, meta):
    path = os.path.join(PROJECTS, name, "project.json")
    tmp = path + ".tmp"
    json.dump(meta, open(tmp, "w"), indent=2)
    os.replace(tmp, path)


def _same(a, b):
    try:
        return open(a, "rb").read() == open(b, "rb").read()
    except OSError:
        return not os.path.exists(a) and not os.path.exists(b)


def changed(name):
    """The plan files that differ from what the project has saved."""
    if not name or not os.path.isdir(os.path.join(PROJECTS, name)):
        return list(PROJECT_FILES)
    return [f for f in PROJECT_FILES
            if not _same(os.path.join(SHOW, f), os.path.join(PROJECTS, name, f))]


def _live_set_of_show():
    try:
        return json.load(open(os.path.join(SHOW, "show.json"))).get("source")
    except (OSError, ValueError):
        return None


def listing():
    os.makedirs(PROJECTS, exist_ok=True)
    cur = current()
    out = []
    for d in sorted(os.listdir(PROJECTS)):
        if d.startswith(".") or not os.path.isdir(os.path.join(PROJECTS, d)):
            continue
        m = _meta(d)
        try:
            cues = json.load(open(os.path.join(PROJECTS, d, "cues.json")))
            n = len([c for c in cues.get("cues", []) if c.get("lane") != "note"])
        except (OSError, ValueError):
            n = 0
        out.append({"name": d, "saved": m.get("saved"), "created": m.get("created"),
                    "live_set": m.get("live_set"), "composition": m.get("composition"),
                    "td_set": m.get("td_set"),
                    "output_preset": m.get("output_preset"), "notes": m.get("notes", ""),
                    "cues": n, "current": d == cur})
    return {"current": cur, "changed": changed(cur) if cur else None, "projects": out, "show_dir": SHOW,
            "compositions": compositions(), "live_set_now": _live_set_of_show(),
            "td_sets": td_stills.sets(), "td_default": td_stills.DEFAULT_SET}


def _copy_in(src_dir, files=PROJECT_FILES):
    """Put a set of plan files in place here, one atomic replace each."""
    for f in files:
        src = os.path.join(src_dir, f)
        if not os.path.exists(src):
            continue
        tmp = os.path.join(SHOW, f + ".loading")
        shutil.copyfile(src, tmp)
        os.replace(tmp, os.path.join(SHOW, f))


def _autosave(label):
    stamp = time.strftime("%Y-%m-%d %H.%M.%S")
    dest = os.path.join(AUTOSAVE, f"{stamp} {label}")
    os.makedirs(dest, exist_ok=True)
    for f in PROJECT_FILES:
        if os.path.exists(os.path.join(SHOW, f)):
            shutil.copyfile(os.path.join(SHOW, f), os.path.join(dest, f))
    olds = sorted(glob.glob(os.path.join(AUTOSAVE, "*")))
    for old in olds[:-KEEP_AUTOSAVES]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def save(name=None):
    """Save what is here into the current project, or into `name` (save as)."""
    name = slug(name) if name else current()
    if not name:
        raise ValueError("no project yet: save as a new one, with a name")
    d = os.path.join(PROJECTS, name)
    os.makedirs(d, exist_ok=True)
    for f in PROJECT_FILES:
        if os.path.exists(os.path.join(SHOW, f)):
            shutil.copyfile(os.path.join(SHOW, f), os.path.join(d, f))
    meta = _meta(name)
    now = time.strftime("%Y-%m-%d %H:%M")
    meta.setdefault("created", now)
    meta.setdefault("live_set", _live_set_of_show())
    meta.update(name=name, saved=now)
    _write_meta(name, meta)
    _set_current(name)
    return name


def load(name):
    name = slug(name)
    d = os.path.join(PROJECTS, name)
    if not os.path.isdir(d):
        raise ValueError(f"no project called {name!r}")
    backup = _autosave(f"before loading {name}")
    _copy_in(d)
    _set_current(name)
    return {"name": name, "backup": os.path.relpath(backup, SHOW)}


def new(name, keep=True):
    """A new project from what is here: the rig, the lanes, the looks and the
    Library carry over; the timeline starts empty (keep=False: the song
    structure too, until Live's set is synced in)."""
    name = slug(name)
    if os.path.isdir(os.path.join(PROJECTS, name)):
        raise ValueError(f"there is already a project called {name!r}")
    _autosave(f"before new {name}")
    cues_path = os.path.join(SHOW, "cues.json")
    try:
        cues = json.load(open(cues_path))
    except (OSError, ValueError):
        cues = {}
    blank = {k: v for k, v in cues.items() if k not in ("cues", "automation")}
    blank.update(cues=[], automation=[])
    tmp = cues_path + ".tmp"
    json.dump(blank, open(tmp, "w"), indent=1)
    os.replace(tmp, cues_path)
    save(name)
    meta = _meta(name)
    meta["created"] = meta["saved"]
    _write_meta(name, meta)
    return name


def delete(name):
    """Remove a saved project. Nothing is lost: it moves to projects/.autosave/,
    like the copies made before a load. What is loaded stays as it is; if this
    was the current project, there is no current one afterwards."""
    name = slug(name)
    d = os.path.join(PROJECTS, name)
    if not os.path.isdir(d):
        raise ValueError(f"no project called {name!r}")
    os.makedirs(AUTOSAVE, exist_ok=True)
    dest = os.path.join(AUTOSAVE, f"{time.strftime('%Y-%m-%d %H.%M.%S')} deleted {name}")
    shutil.move(d, dest)
    if current() == name:
        try:
            os.remove(CURRENT)
        except OSError:
            pass
    return {"deleted": name, "backup": os.path.relpath(dest, SHOW)}


def td_status():
    """What the open set says about itself (its web server's /status): the scene
    on screen, and whether the NDI preview is on. {} when no set answers."""
    t = td_stills.target()
    try:
        with urllib.request.urlopen(f"http://{t['host']}:{int(t.get('web', 9982))}/status", timeout=0.3) as r:
            return {"answering": True, **json.load(r)}
    except (OSError, ValueError):
        return {"answering": False}


def composition_path(c):
    """A project's composition: a file name in Arena's Compositions folder (the
    same on both Macs, and what Make composition writes), or an absolute path."""
    return c if not c or os.path.isabs(c) else os.path.join(COMPOSITIONS, c)


def make_composition(name):
    """Write this Mac's composition from the show (make_composition.py) and make
    it the project's. Arena must be closed."""
    import make_composition as mc
    name = slug(name)
    meta = _meta(name)
    cur = meta.get("composition")
    target = os.path.basename(cur) if cur and os.path.dirname(composition_path(cur)) == COMPOSITIONS else mc.DEFAULT_NAME
    out = mc.make(target)
    meta["composition"] = os.path.basename(out["path"])
    _write_meta(name, meta)
    out["backup"] = out["backup"] and os.path.relpath(out["backup"], COMPOSITIONS)
    return out


def settings(name, **fields):
    name = slug(name)
    if not os.path.isdir(os.path.join(PROJECTS, name)):
        raise ValueError(f"no project called {name!r}")
    meta = _meta(name)
    c = fields.get("composition")
    if c and os.path.dirname(c) == COMPOSITIONS:
        fields["composition"] = os.path.basename(c)        # by name: the same on both Macs
    for k in ("live_set", "composition", "td_set", "output_preset", "notes"):
        if k in fields:
            meta[k] = fields[k] or None if k != "notes" else fields[k] or ""
    _write_meta(name, meta)
    return meta


def compositions():
    return sorted(glob.glob(os.path.join(COMPOSITIONS, "**", "*.avc"), recursive=True))


# ------------------------------------------------------------------ software --
def _pgrep(pattern):
    try:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    return [int(p) for p in out if int(p) != os.getpid()]


def _port_answers(port, path="/api/v1/product"):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3) as s:
            s.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
            return s.recv(12).startswith(b"HTTP/1.")
    except OSError:
        return False


def find_blender():
    for c in (os.environ.get("BLENDER"), "/Applications/Blender.app/Contents/MacOS/Blender",
              os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender")):
        if c and os.access(c, os.X_OK):
            return c
    return shutil.which("blender")


def find_uv():
    for c in (os.path.join(HERE, "tools", "uv"), os.path.expanduser("~/.local/bin/uv"),
              "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if os.access(c, os.X_OK):
            return c
    return shutil.which("uv")


# ---------------------------------------------------------------- versions --
def _bundle_version(app):
    """An app's version from its Info.plist, or None."""
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as fh:
            info = plistlib.load(fh)
        return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def _cmd_version(args, pattern=r"(\d+(?:\.\d+)+)"):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5)
        m = re.search(pattern, out.stdout + out.stderr)
        return m.group(1) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


_versions = None
def versions():
    """What this Mac runs the show with, read once per server start: the apps from
    their bundles (so it works with them closed), the tools from git."""
    global _versions
    if _versions is not None:
        return {**_versions, "intermission": version.read()}     # VERSION may change under a running server
    arena = next((a for a in ARENA_APPS if os.path.isdir(a)), None)
    other = sorted(glob.glob("/Applications/Resolume Arena [0-9.]*/Arena.app"))
    live = live_app()
    bl = find_blender()
    bl_app = bl.split("/Contents/MacOS/")[0] if bl and "/Contents/MacOS/" in bl else None
    uv = find_uv()
    try:
        rev = subprocess.run(["git", "log", "-1", "--format=%h %cs"], cwd=HERE, capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=HERE,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        tools = (rev + (" · edited since" if dirty else "")) if rev else None
    except OSError:
        tools = None
    _versions = {
        "intermission": version.read(),
        "arena": _bundle_version(arena) if arena else None,
        "arena_others": [v for v in (_bundle_version(a) for a in other) if v],
        "live": _bundle_version(live) if live else None,
        "live_app": os.path.basename(live)[:-4] if live else None,
        "blender": _bundle_version(bl_app) if bl_app else None,
        "touchdesigner": _bundle_version(TD_APP) if os.path.isdir(TD_APP) else None,
        "python": platform.python_version(),
        "ffmpeg": _cmd_version(["ffmpeg", "-version"], r"ffmpeg version (\S+)"),
        "uv": _cmd_version([uv, "--version"]) if uv else None,
        "macos": platform.mac_ver()[0] or None,
        "tools": tools,
    }
    return _versions


class Host:
    """What this server started, and a view of what runs however it started."""

    def __init__(self):
        self.lock = threading.Lock()
        self.procs = {}                    # part -> Popen we started
        self.mode = None                   # "test" or "show", once started from here
        self.player_mode = None
        self.player_stop = threading.Event()
        self.player_thread = None
        self.restarts = 0
        self.awake = None                  # caffeinate, in show mode
        self.events = []                   # what happened, for the page

    def note(self, text):
        self.events.append({"t": time.strftime("%H:%M:%S"), "text": text})
        del self.events[:-40]

    # ---- status
    def status(self):
        def ours(k):
            p = self.procs.get(k)
            return p is not None and p.poll() is None
        arena_pids = _pgrep("Resolume Arena/Arena.app/Contents/MacOS/Arena")         # 7.19
        other_arena = [p for p in _pgrep("Resolume Arena [0-9.]+/Arena.app/Contents/MacOS/Arena")]
        live_pids = _pgrep(r"Ableton Live.*\.app/Contents/MacOS/Live")
        live_which = ""
        if live_pids:
            try:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", str(live_pids[0])], capture_output=True, text=True).stdout
                live_which = re.search(r"(Ableton Live[^/]*)\.app", cmd).group(1)
            except (OSError, AttributeError):
                pass
        parts = {
            "arena": {"running": bool(arena_pids) or bool(other_arena), "answering": _port_answers(8080),
                      "other_version": bool(other_arena) and not arena_pids},
            "live": {"running": bool(live_pids), "app": live_which,
                     "wrong_app": bool(live_which) and live_app() is not None
                                  and not live_app().endswith(live_which + ".app")},
            "td": {**td_status(), "running": bool(_pgrep("TouchDesigner.app/Contents/MacOS/TouchDesigner")),
                   "set": os.path.relpath(td_stills.set_path(_meta(current()) if current() else {}), SHOW),
                   "set_exists": os.path.exists(td_stills.set_path(_meta(current()) if current() else {}))},
            "blender": {"running": bool(_pgrep("Blender -y venue.blend")), "ours": ours("blender")},
            "bridge": {"running": bool(_pgrep("syphon_bridge.py")), "ours": ours("bridge")},
            "player": {"running": bool(_pgrep("cue_player.py --follow")),
                       "ours": self.player_thread is not None and self.player_thread.is_alive(),
                       "mode": self.player_mode, "restarts": self.restarts},
        }
        return {"mode": self.mode, "awake": self.awake is not None and self.awake.poll() is None,
                "parts": parts, "events": self.events[-12:], "versions": versions()}

    # ---- the apps that hold the show: opened, never quit from here
    def open_arena(self, composition=None):
        app = next((a for a in ARENA_APPS if os.path.isdir(a)), None)
        if not app:
            raise RuntimeError("Resolume Arena isn't in /Applications/Resolume Arena")
        composition = composition_path(composition)
        args = ["open", "-a", app] + ([composition] if composition and os.path.exists(composition) else [])
        subprocess.run(args, check=False)
        self.note("opened Resolume Arena" + (f" with {os.path.basename(composition)}" if composition else ""))

    def open_live(self, live_set=None):
        app = live_app()
        if not app:
            raise RuntimeError("no Ableton Live in /Applications")
        name = os.path.basename(app).replace(".app", "")
        if live_set and os.path.exists(live_set):
            subprocess.run(["open", "-a", app, live_set], check=False)
            self.note(f"opened {os.path.basename(live_set)} in {name}")
        else:
            subprocess.run(["open", "-a", app], check=False)
            self.note(f"opened {name} (no set chosen for this project)")

    def open_td(self, meta=None):
        """TouchDesigner with the project's set. One TouchDesigner at a time: if one
        is open already (the set, or td_mcp_host.toe with it pushed in), it's left be."""
        if not os.path.isdir(TD_APP):
            raise RuntimeError("TouchDesigner isn't in /Applications")
        toe = td_stills.set_path(meta or {})
        if _pgrep("TouchDesigner.app/Contents/MacOS/TouchDesigner"):
            self.note("TouchDesigner is open already: left as it is")
            return
        if not os.path.exists(toe):
            raise RuntimeError(f"no TouchDesigner set at {os.path.relpath(toe, SHOW)}: build it "
                               f"(td-pipeline: ./tdgen build liveset) or pick one in the project")
        subprocess.run(["open", "-a", TD_APP, toe], check=False)
        self.note(f"opened {os.path.relpath(toe, SHOW)} in TouchDesigner")

    # ---- what we run
    def _spawn(self, key, args, log):
        os.makedirs(LIVE_DIR, exist_ok=True)
        lf = open(os.path.join(LIVE_DIR, log), "a")
        # A server started in the background (nohup … &) has SIGINT ignored, and a
        # child inherits that: the player would never hear a stop. Give it back.
        p = subprocess.Popen(args, cwd=HERE, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True,
                             preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        self.procs[key] = p
        return p

    def start_blender(self):
        if _pgrep("Blender -y venue.blend"):
            return
        bl = find_blender()
        if not bl:
            raise RuntimeError("Blender isn't installed (blender.org), or set BLENDER=/path/to/Blender")
        self._spawn("blender", [bl, "-y", "venue.blend", "--python-expr",
                                "import bpy; bpy.app.timers.register(lambda: (bpy.ops.venue.live(), None)[1], first_interval=2.0)"],
                    "blender.log")
        self.note("started the Blender previz")

    def start_bridge(self):
        if _pgrep("syphon_bridge.py"):
            return
        uv = find_uv()
        if not uv:
            raise RuntimeError("no screen feed: 'uv' isn't installed (curl -LsSf https://astral.sh/uv/install.sh | sh)")
        self._spawn("bridge", [uv, "run", "-q", "syphon_bridge.py"], "bridge.log")
        self.note("started the screen feed (Syphon → Blender)")

    def _stop_pattern(self, key, pattern, sig=signal.SIGTERM, wait=3.0):
        """Ask politely (sig), then insist: one that ignores the ask is terminated,
        then killed, so nothing is left holding a port."""
        p = self.procs.pop(key, None)
        if p and p.poll() is None:
            p.send_signal(sig)
        for pid in _pgrep(pattern):
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        for then in (signal.SIGTERM, signal.SIGKILL):
            end = time.time() + wait
            while time.time() < end and _pgrep(pattern):
                time.sleep(0.1)
            left = _pgrep(pattern)
            if not left:
                return
            for pid in left:
                try:
                    os.kill(pid, then)
                except OSError:
                    pass

    def stop_blender(self):
        self._stop_pattern("blender", "Blender -y venue.blend")
        self.note("stopped the Blender previz")

    def stop_bridge(self):
        self._stop_pattern("bridge", "syphon_bridge.py")
        self.note("stopped the screen feed")

    def start_player(self, mode):
        """Run the player, and keep it running: exit 0 is a stop, anything else a
        crash, restarted in a second (a panic survives it)."""
        if self.player_thread and self.player_thread.is_alive():
            if self.player_mode == mode:
                return
            self.stop_player()
        if _pgrep("cue_player.py --follow"):     # one from Test.command, Live.command, an earlier host
            self._stop_pattern("player", "cue_player.py --follow", signal.SIGINT)
        self.player_stop.clear()
        self.player_mode = mode
        self.restarts = 0
        flags = ["--preview"] if mode == "test" else ["--live-only"]

        def run():
            quick = 0                              # crashes within seconds of starting, in a row
            while not self.player_stop.is_set():
                t0 = time.time()
                p = self._spawn("player", [sys.executable, "-u", "cue_player.py", "--follow", *flags], "player.log")
                code = p.wait()
                if self.player_stop.is_set() or code == 0:
                    break
                self.restarts += 1
                quick = quick + 1 if time.time() - t0 < 5 else 0
                if quick >= 5:
                    # it can't start at all (a port taken, a broken file): stop trying,
                    # and say where to look, rather than restart every second forever
                    self.note(f"the player can't start (exit {code}, 5 times in a row): see player.log")
                    break
                self.note(f"the player stopped (exit {code}): restarted")
                time.sleep(1.0 + quick)
        self.player_thread = threading.Thread(target=run, daemon=True)
        self.player_thread.start()
        self.note(f"started the player ({'follows Live and the timeline' if mode == 'test' else 'follows Live only'})")

    def stop_player(self):
        self.player_stop.set()
        self._stop_pattern("player", "cue_player.py --follow", signal.SIGINT)
        self.player_mode = None
        self.note("stopped the player")

    def player_osc(self, address):
        pad = lambda b: b + b"\0" * (4 - len(b) % 4)
        msg = pad(address.encode()) + pad(b",i") + (1).to_bytes(4, "big")
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(msg, ("127.0.0.1", PLAYER_PORT))
        self.note("PANIC: safe look, cues held" if address.endswith("panic") else "resumed the plan")

    # ---- the two ways to run it
    def start(self, mode, project):
        meta = _meta(project) if project else {}
        with self.lock:
            if self.mode is None and not _pgrep("cue_player.py --follow"):
                # a new session follows the plan, as the launchers do: a panic from
                # before is let go (one held while a player runs is left alone)
                try:
                    os.remove(os.path.join(LIVE_DIR, "panic"))
                except OSError:
                    pass
            self.mode = mode
            st = self.status()["parts"]
            if not st["arena"]["running"]:
                self.open_arena(meta.get("composition"))
            if not st["live"]["running"]:
                self.open_live(meta.get("live_set") or _live_set_of_show())
            if not st["td"]["running"]:
                try:
                    self.open_td(meta)
                except RuntimeError as e:
                    self.note(str(e))
            if mode == "test":
                self.start_blender()
                self.start_bridge()
                if self.awake is not None:
                    self.awake.terminate()
                    self.awake = None
            else:
                # the show: nothing extra on the GPU, and no sleeping
                if st["blender"]["running"]:
                    self.stop_blender()
                if st["bridge"]["running"]:
                    self.stop_bridge()
                if self.awake is None or self.awake.poll() is not None:
                    self.awake = subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())])
                    self.note("keeping the Mac awake")
            self.start_player(mode)

    def stop(self):
        with self.lock:
            self.stop_player()
            if _pgrep("syphon_bridge.py"):
                self.stop_bridge()
            if _pgrep("Blender -y venue.blend"):
                self.stop_blender()
            if self.awake is not None:
                self.awake.terminate()
                self.awake = None
            self.mode = None
            self.note("stopped: Resolume and Live keep running and hold the last state")


def preflight(mode):
    """The same check the launchers run, as text for the page."""
    try:
        r = subprocess.run([sys.executable, "preflight.py", "live" if mode == "show" else "test"],
                           cwd=HERE, capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.SubprocessError) as e:
        return {"problems": 1, "text": str(e)}
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", r.stdout + r.stderr)
    return {"problems": r.returncode, "text": text.strip()}


def tail(log, n=60):
    try:
        lines = open(os.path.join(LIVE_DIR, os.path.basename(log)), errors="replace").read().splitlines()
    except OSError:
        return ""
    clean = [re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\r", "", l).strip() for l in lines[-400:]]
    return "\n".join([l for l in clean if l][-n:])


HOST = Host()
