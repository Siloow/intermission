"""Play the visual plan against Live's position: cues.json -> OSC -> Resolume.

    python3 cue_player.py --dry-run          read the whole show as a cue list
    python3 cue_player.py --rehearse         run it on a fake clock, no Live needed
    python3 cue_player.py --follow           follow Live and fire for real

Resolume stays the only thing driving the rig. This never sends DMX: it tells
Resolume which clip to fire, and Resolume lights the room. The previz then sees
exactly what the real fixtures see.

The plan is `cues.json`, anchored to sections in bars, so it survives the music
changing. `osc_map.json` says what each cue means to Resolume: which layer and
clip, or any OSC message you like. A cue with no mapping is reported rather
than silently ignored - that is the whole point of --dry-run.

Following Live needs its position over OSC. With AbletonOSC installed and
enabled as a Control Surface, --follow subscribes by itself: it asks Live to
report every beat and re-asks if Live restarts. A Max for Live device sending
plain /position/beats works too. All of these are recognised:

    /live/song/get/current_song_time <beats>     AbletonOSC, streamed
    /live/song/get/beat              <beat>      AbletonOSC, once per beat
    /position/beats                  <beats>     anything custom

Standard library only.
"""
import argparse, json, os, re, select, socket, struct, sys, threading, time
import http.client, urllib.request
import arena_load                    # the composition, so cues can name clips

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = os.path.join(HERE, "show.json")
CUES = os.path.join(HERE, "cues.json")
LOOKS = os.path.join(HERE, "looks.json")
MAP = os.path.join(HERE, "osc_map.json")
PREVIEW = os.path.join(HERE, ".live", "preview.json")
PLAYER_STATE = os.path.join(HERE, ".live", "player.json")   # what the timeline mirrors
PANIC_FLAG = os.path.join(HERE, ".live", "panic")            # survives a player restart
CLEAR = "\r" + " " * 72 + "\r"      # wipe the running position line first


# -------------------------------------------------------------------- OSC ----
def osc_encode(address, args):
    """A single OSC message. Enough of the spec for Resolume: i, f, s."""
    def pad(b):
        return b + b"\0" * (4 - len(b) % 4)
    out = pad(address.encode())
    tags, body = ",", b""
    for a in args:
        if isinstance(a, bool):
            a = int(a)
        if isinstance(a, int):
            tags += "i"; body += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"; body += struct.pack(">f", a)
        else:
            tags += "s"; body += pad(str(a).encode())
    return out + pad(tags.encode()) + body


def osc_decode(data):
    """Yield (address, args) from a packet; walks bundles too."""
    if data[:8] == b"#bundle\0":
        i = 16
        while i + 4 <= len(data):
            size = struct.unpack_from(">i", data, i)[0]
            i += 4
            yield from osc_decode(data[i:i + size])
            i += size
        return
    end = data.find(b"\0")
    if end < 0:
        return
    address = data[:end].decode(errors="replace")
    i = (end + 4) & ~3
    if i >= len(data) or data[i:i + 1] != b",":
        yield address, []
        return
    end = data.find(b"\0", i)
    tags = data[i + 1:end].decode(errors="replace")
    i = (end + 4) & ~3
    args = []
    for t in tags:
        if t == "i":
            args.append(struct.unpack_from(">i", data, i)[0]); i += 4
        elif t == "f":
            args.append(struct.unpack_from(">f", data, i)[0]); i += 4
        elif t == "s":
            end = data.find(b"\0", i)
            args.append(data[i:end].decode(errors="replace"))
            i = (end + 4) & ~3
        elif t in "TF":
            args.append(t == "T")
    yield address, args


class Sender:
    def __init__(self, host, port, quiet=False):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.quiet = quiet

    def send(self, address, args):
        self.sock.sendto(osc_encode(address, args), self.addr)
        if not self.quiet:
            print(f"      -> {address} {args}")


# ------------------------------------------------------------------ fades ----
MAX_FADE = 10.0                      # seconds: the most a Resolume transition allows


def fade_seconds(cue, show):
    bars = float(cue.get("fade_bars") or 0)
    return min(MAX_FADE, bars * show.get("beats_per_bar", 4) * 60.0 / show["tempo"])


def layers_hit(messages, n_layers):
    """Which layers a cue's messages change: a clip's own, or all for a column."""
    out = set()
    for address, _ in messages or []:
        m = re.match(r"/composition/layers/(\d+)/", address)
        if m:
            out.add(int(m.group(1)))
        elif address.startswith("/composition/columns/"):
            out.update(range(1, n_layers + 1))
    return sorted(out)


def handover_layers(end, n_layers):
    """The layers an end entry clears: its cue's, less any the next cue plays on."""
    layers = layers_hit(end["end_of"]["messages"], n_layers)
    nxt = end.get("handover")
    if nxt:
        keep = set(layers_hit(nxt["messages"], n_layers)) if not nxt["problem"] else set()
        layers = [L for L in layers if L not in keep]
    return layers


class Fades:
    """Set each layer's transition time just before a cue fires on it.

    A fade is Resolume's own layer transition (a crossfade with the Alpha blend
    mode), so it runs on Resolume's clock, smooth, whatever the player is doing.
    It is set over the REST API because that takes seconds as seconds; a layer
    is only touched when its time has to change."""
    def __init__(self, base, n_layers):
        self.base, self.n_layers = base, n_layers
        self.now = {}                     # layer -> seconds it is set to
        self.warned = False

    def set(self, layers, seconds):
        for L in layers:
            if abs(self.now.get(L, -1) - seconds) < 0.01:
                continue
            body = json.dumps({"transition": {"duration": {"value": round(seconds, 3)}}}).encode()
            req = urllib.request.Request(f"{self.base}/api/v1/composition/layers/{L}", data=body,
                                         method="PUT", headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=0.3).close()
                self.now[L] = seconds
            except OSError:
                if not self.warned:
                    print(f"{CLEAR}   !! can't set fades: Resolume's web server isn't answering")
                    self.warned = True


# ------------------------------------------------------------------- plan ----
def load(path, fallback=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        if fallback is None:
            raise
        return fallback


def default_map():
    return {
        "resolume": {"host": "127.0.0.1", "port": 7000},
        "//": "One entry per cue value, as 'lane:value'. Either {layer, clip} for "
              "Resolume's connect message, or a list of raw OSC messages.",
        "cues": {
            "screen:example clip": {"layer": 1, "clip": 1},
            "lights:Amber wash": {"layer": 2, "clip": 1},
        },
    }


def resolve(lane, value, mapping, snap=None, layer=None):
    """What a lane:value means to Resolume: (messages, problem).

    With the composition known (`snap`), clips and scenes are found by NAME in
    it: a clip in the cue's layer (or its lane's), a scene as a column. That is
    what keeps a cue right when a clip moves slot in Resolume. A raw OSC list in
    osc_map.json always wins; the {layer, clip} positions there are only the
    fallback for when no composition is known at all."""
    key = f"{lane}:{value or ''}"
    entry = mapping.get("cues", {}).get(key)
    if lane == "note":
        return [], None
    if isinstance(entry, list):
        return [(m["address"], m.get("args", [])) for m in entry], None
    if snap and value:
        if lane == "scenes":
            col = arena_load.find_column(snap, value)
            n = col["index"] if col else mapping.get("scenes", {}).get(str(value).strip())
            if n is None:
                return None, f"no column called '{value}' in '{snap.get('name')}' — name one in Resolume"
            return [(f"/composition/columns/{n}/connect", [1])], None
        want = arena_load.layer_for(lane, layer)
        if want:
            L, clip = arena_load.find_clip(snap, want, value)
            if L is None:
                return None, f"no layer {want} in '{snap.get('name')}'"
            if clip is None:
                return None, f"no clip called '{value}' in layer {L} of '{snap.get('name')}'"
            return [(f"/composition/layers/{L}/clips/{clip['index']}/connect", [1])], None
    scene = None
    if lane == "scenes":
        v = str(value or "").strip()
        scene = mapping.get("scenes", {}).get(v)
        if scene is None and v.isdigit():
            scene = int(v)
    if lane == "scenes" and entry is None:
        if scene is None:
            return None, f"no scene '{value}' (a column number, or a name in osc_map.json)"
        return [(f"/composition/columns/{scene}/connect", [1])], None
    if not value:
        return None, "no value set"
    if entry is None:
        return None, f"nothing in osc_map.json for '{key}'"
    layer, clip = entry.get("layer", 1), entry.get("clip", 1)
    return [(f"/composition/layers/{layer}/clips/{clip}/connect", [1])], None


def compile_panic(mapping, snap=None):
    """The safe look from osc_map.json's "panic" block: a cue value per lane.
    Lanes it doesn't name are simply held where they are."""
    out = []
    for lane, value in (mapping.get("panic") or {}).items():
        if lane.startswith("/"):
            continue                           # a comment
        messages, problem = resolve(lane, value, mapping, snap)
        out.append({"cue": {"lane": lane, "value": value, "id": "panic"}, "beat": 0,
                    "bar": 0, "messages": messages, "problem": problem})
    return out


# what happens when a cue's length runs out and nothing on its lane takes over
DEFAULT_END = {"screen": "clear", "overlay": "clear", "lights": "clear", "td": "clear",
               "scenes": "hold", "note": "hold"}


def end_mode(cue):
    return cue.get("end") or DEFAULT_END.get(cue.get("lane"), "hold")


def compile_cues(show, cues, mapping, snap=None):
    """Turn the plan into a flat, sorted list of things to fire, in beats.

    A cue that ends with nothing after it on its lane gets an end entry too,
    which clears the layers it played on: the screen goes empty rather than
    holding a clip the plan says is over. end: "hold" on a cue keeps it."""
    bpb = show.get("beats_per_bar", 4)
    sections = {(g["name"], s["name"]): s for g in show["songs"] for s in g["sections"]}
    out = []
    for c in cues.get("cues", []):
        sec = sections.get((c.get("song"), c.get("section")))
        if not sec:
            out.append({"cue": c, "beat": None, "bar": None, "messages": None,
                        "problem": f"section {c.get('song')}/{c.get('section')} no longer exists"})
            continue
        bar = sec["bar"] + (c.get("offset_bars") or 0)
        messages, problem = resolve(c["lane"], c.get("value"), mapping, snap, c.get("layer"))
        out.append({"cue": c, "beat": (bar - 1) * bpb, "bar": bar,
                    "messages": messages, "problem": problem})
    ends = []
    for e in out:
        c = e["cue"]
        if e["beat"] is None or end_mode(c) != "clear":
            continue
        stop = e["beat"] + float(c.get("length_bars") or 8) * bpb
        after = sorted((o for o in out if o is not e and o["beat"] is not None
                        and o["cue"]["lane"] == c["lane"] and o["beat"] > e["beat"] - 1e-6),
                       key=lambda o: o["beat"])
        nxt = next((o for o in after if o["beat"] <= stop + 1e-6), None)
        if nxt:
            # the next cue takes over. On the same layer Resolume switches by
            # itself; a clip from another layer would leave this one playing
            # underneath, so that layer is cleared at the switch.
            if nxt["beat"] > e["beat"] + 1e-6:
                ends.append({"cue": c, "beat": nxt["beat"], "bar": nxt["beat"] / bpb + 1,
                             "messages": None, "problem": None, "end_of": e, "handover": nxt})
            continue
        ends.append({"cue": c, "beat": stop, "bar": stop / bpb + 1, "messages": None,
                     "problem": None, "end_of": e})
    out += ends
    # at the same beat an end goes first, so a cue starting there is not cleared
    # and a scene (a whole column) before the lanes, so their own clips land on top of it
    out.sort(key=lambda e: (e["beat"] is None, e["beat"] or 0, 0 if e.get("end_of") else 1,
                            0 if e["cue"].get("lane") == "scenes" else 1))
    return out


def compile_automation(show, cues, mapping, param_index=None):
    """Automation lanes: points anchored to sections like cues, one target each.

    A target is either an OSC address, or a Resolume parameter named by its
    path (["layer", 3, "effect", "Transform", "Scale"]); those are found in the
    composition by name, and sent by their id over the REST API."""
    bpb = show.get("beats_per_bar", 4)
    sections = {(g["name"], s["name"]): s for g in show["songs"] for s in g["sections"]}
    targets = {t["name"]: t for t in mapping.get("targets", [])}
    lanes = []
    for lane in cues.get("automation", []):
        spec = targets.get(lane.get("target"))
        points, orphans = [], 0
        for p in lane.get("points", []):
            sec = sections.get((p.get("song"), p.get("section")))
            if not sec:
                orphans += 1
                continue
            bar = sec["bar"] + float(p.get("offset_bars") or 0)
            points.append(((bar - 1) * bpb, max(0.0, min(1.0, float(p.get("value", 0)))),
                           p.get("shape", "linear"), float(p.get("curve") or 0)))
        points.sort(key=lambda q: q[0])
        problem, param = None, None
        if spec is None:
            problem = f"no target '{lane.get('target')}' in osc_map.json"
        elif spec.get("resolume"):
            param = arena_load.find_param(param_index or [], spec["resolume"])
            if param is None:
                problem = (f"'{spec['name']}' isn't in the open composition" if param_index
                           else "Resolume not answering: can't find its parameters")
        if not problem and not points:
            problem = "no points"
        lanes.append({"lane": lane, "spec": spec, "points": points, "param": param,
                      "orphans": orphans, "problem": problem})
    return lanes


def repoint_automation(lanes, param_index):
    """Find each Resolume target's parameter again (ids change when Arena reloads)."""
    for a in lanes:
        if a["spec"] and a["spec"].get("resolume"):
            a["param"] = arena_load.find_param(param_index, a["spec"]["resolume"])


class Rest:
    """Resolume parameters by id, over one kept-open HTTP connection: ~0.2 ms a set."""
    def __init__(self, host, port=8080):
        self.host, self.port, self.conn, self.warned = host, port, None, False

    by_id = True                 # Arena 7.19 has no /parameter/by-id: then through the owner

    def set(self, param, value):
        """Set a Resolume parameter: by its id where Arena can, else through the
        layer or composition that owns it (one parameter per request)."""
        if self.by_id:
            status = self.request("PUT", f"/api/v1/parameter/by-id/{param['id']}", json.dumps({"value": value}))
            if status != 404:
                return status
            self.by_id = False
            print(f"{CLEAR}   (this Arena sets parameters through their layer: fine)")
        path, body = arena_load.param_update(param, value)
        return self.request("PUT", "/api/v1" + path, json.dumps(body))

    def put(self, pid, value):
        return self.request("PUT", f"/api/v1/parameter/by-id/{pid}", json.dumps({"value": value}))

    def clear_layer(self, layer):
        # Resolume ignores /composition/layers/N/clear over OSC; over REST it works
        return self.request("POST", f"/api/v1/composition/layers/{layer}/clear", None)

    def request(self, method, path, body):
        for attempt in (1, 2):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=0.3)
                self.conn.request(method, path, body,
                                  {"Content-Type": "application/json"} if body else {})
                resp = self.conn.getresponse()
                resp.read()
                return resp.status
            except (OSError, http.client.HTTPException):
                self.conn = None                   # reconnect once, then give up this value
        if not self.warned:
            print(f"{CLEAR}   !! Resolume's web server isn't answering: automation to its parameters paused")
            self.warned = True
        return False


def reresolve(entries, mapping, snap):
    """Look every name up again, in place, against a fresh composition."""
    for e in entries:
        if e.get("end_of"):
            continue                           # an end follows its cue's messages
        if e["beat"] is None and e["cue"].get("id") != "panic":
            continue                           # orphans stay orphans
        c = e["cue"]
        e["messages"], e["problem"] = resolve(c["lane"], c.get("value"), mapping, snap,
                                              c.get("layer"))


def watch_composition(player, mapping, base, every=5.0):
    """Keep the names current while playing: a clip moved or renamed in
    Resolume is picked up within a few seconds, without a restart."""
    def run():
        last = None
        while True:
            time.sleep(every)
            try:
                comp = arena_load.fetch(base)
            except (OSError, ValueError):
                continue                       # keep the last good one
            snap = arena_load.snapshot(comp=comp)
            index = arena_load.params(comp)
            shape = json.dumps([[c["name"], c["index"]] for l in snap["layers"] for c in l["clips"]]
                               + [c["name"] for c in snap["columns"]]
                               + [[p["path"], p["id"]] for p in index])
            if shape != last:
                last = shape
                player.snap, player.param_index = snap, index
                reresolve(player.plan + player.panic_plan, mapping, snap)
                repoint_automation(player.automation, index)
                arena_load.save_cache(snap)
    threading.Thread(target=run, daemon=True).start()


def bend(t, shape, curve):
    """How far along a segment the value is, 0..1, at t (0..1) through it.

    The same formula as the timeline draws. curve is -1..1: positive starts
    slow and rushes at the end (ease in), negative the reverse (ease out). An
    "s" segment eases both ends, steeper as |curve| grows."""
    if shape == "hold":
        return 0.0
    t = max(0.0, min(1.0, t))
    if shape == "s":
        k = 1 + 3 * (abs(curve) if curve else 0.5)
        return 0.5 * (2 * t) ** k if t < 0.5 else 1 - 0.5 * (2 - 2 * t) ** k
    return t ** (6 ** curve) if curve else t


def value_at(points, beat):
    """The lane's value (0..1) at a beat: linear or hold between points."""
    if not points:
        return None
    if beat <= points[0][0]:
        return points[0][1]
    for (b0, v0, shape, curve), (b1, v1, _, _) in zip(points, points[1:]):
        if b0 <= beat < b1:
            if b1 == b0:
                return v1
            return v0 + (v1 - v0) * bend((beat - b0) / (b1 - b0), shape, curve)
    return points[-1][1]


def scaled(spec, v):
    """0..1 -> the target's range, through its curve (0 straight, +1 slow start)."""
    exp = 4 ** float(spec.get("curve", 0))
    lo, hi = float(spec.get("min", 0)), float(spec.get("max", 1))
    return lo + (hi - lo) * (v ** exp)


def timecode(beat, tempo):
    secs = beat * 60 / tempo
    return f"{int(secs // 60):d}:{secs % 60:04.1f}"


def where(show, beat):
    """Which song and section a beat falls in."""
    bpb = show.get("beats_per_bar", 4)
    bar = beat / bpb + 1
    best = None
    for g in show["songs"]:
        for s in g["sections"]:
            if s["bar"] <= bar + 1e-6 and (not best or s["bar"] > best[1]["bar"]):
                best = (g, s)
    return best


# ------------------------------------------------------------------ player ---
class Player:
    def __init__(self, show, plan, sender, looks=None, preview=False, quiet=False,
                 automation=None, senders=None, panic=None, fades=None, rest=None):
        self.show, self.plan, self.sender = show, plan, sender
        self.fades, self.rest = fades, rest
        self.panic_plan = panic or []
        self.panicked = os.path.exists(PANIC_FLAG)   # a restart keeps holding
        self.looks = {l["name"]: l for l in (looks or {}).get("looks", [])}
        self.preview, self.quiet = preview, quiet
        self.pos = None
        self.fired = set()
        # a Resolume target that is missing now may appear when the composition does
        self.automation = [a for a in (automation or [])
                           if not a["problem"] or (a["spec"] and a["spec"].get("resolume") and a["points"])]
        self.senders = senders or {}
        self.sent = {}               # lane id -> last value sent (0..1)
        self.recent = []             # last few fired cues, for the timeline
        self.state_t = 0.0
        self.moved_t = 0.0           # when the position last changed
        self.heard_t = 0.0           # when Live last answered at all

    def clear(self, layer):
        """Empty a layer: over the REST API, since Resolume ignores it over OSC."""
        if not (self.rest and self.rest.clear_layer(layer)):
            self.sender.send(f"/composition/layers/{layer}/clear", [1])

    def sender_for(self, spec):
        key = (spec.get("host"), spec.get("port"))
        if key == (None, None):
            return self.sender
        if key not in self.senders:
            self.senders[key] = Sender(spec.get("host") or self.sender.addr[0],
                                       int(spec.get("port") or self.sender.addr[1]),
                                       quiet=True)
        return self.senders[key]

    def automate(self, beat, force=False):
        """Send each lane's value at this beat, but only when it has moved."""
        for a in self.automation:
            v = value_at(a["points"], beat)
            if v is None:
                continue
            lid = a["lane"].get("id") or a["lane"].get("target")
            last = self.sent.get(lid)
            if force or last is None or abs(v - last) > 0.002:
                self.sent[lid] = v
                if a["spec"].get("resolume"):
                    if a.get("param") and self.rest:
                        self.rest.set(a["param"], float(scaled(a["spec"], v)))
                    continue
                self.sender_for(a["spec"]).sock.sendto(
                    osc_encode(a["spec"]["address"], [float(scaled(a["spec"], v))]),
                    self.sender_for(a["spec"]).addr)

    def write_state(self, beat, force=False):
        """What the player is doing, for the timeline to mirror. ~20 times a second
        while Live plays, and a heartbeat while it is stopped, so the timeline can
        tell 'Live is stopped' from 'the player isn't running'."""
        now = time.monotonic()
        if not force and now - self.state_t < 0.05:
            return
        self.state_t = now
        bpb = self.show.get("beats_per_bar", 4)
        try:
            os.makedirs(os.path.dirname(PLAYER_STATE), exist_ok=True)
            tmp = PLAYER_STATE + ".tmp"
            json.dump({"t": time.time(), "beat": beat, "bar": beat / bpb + 1,
                       "playing": now - self.moved_t < 0.6,
                       "live_connected": now - self.heard_t < 6,
                       "panic": self.panicked,
                       "source": getattr(self, "source", "live"),
                       "values": self.sent, "recent": self.recent[-6:]}, open(tmp, "w"))
            os.replace(tmp, PLAYER_STATE)
        except OSError:
            pass

    def fire(self, entry, why=""):
        c = entry["cue"]
        if entry.get("end_of"):
            src = entry["end_of"]
            if src["problem"] or not src["messages"]:
                return
            n = self.fades.n_layers if self.fades else 8
            layers = handover_layers(entry, n)
            if not layers:
                return
            print(f"{CLEAR}   >> bar {entry['bar']:.0f}  {c['lane']:<6} ({c.get('value')} ends)   "
                  f"clear layer {', '.join(map(str, layers))}{'   (' + why + ')' if why else ''}")
            for L in layers:
                self.clear(L)
            return
        at = "PANIC " if c.get("id") == "panic" else f"bar {entry['bar']:.0f}"
        tag = f"{at}  {c['lane']:<6} {c.get('value') or '-'}"
        if entry["problem"]:
            print(f"{CLEAR}   !! {tag}   {entry['problem']}")
            return
        # a fade only when the cue is played into; a restate or a panic snaps
        secs = fade_seconds(c, self.show) if not why else 0.0
        if self.fades and entry["messages"]:
            self.fades.set(layers_hit(entry["messages"], self.fades.n_layers), secs)
        print(f"{CLEAR}   >> {tag}{'   (' + why + ')' if why else ''}"
              f"{f'   fade {secs:g}s' if secs else ''}")
        for address, args in entry["messages"]:
            self.sender.send(address, args)
        self.recent.append({"bar": entry["bar"], "lane": c["lane"], "value": c.get("value"),
                            "id": c.get("id")})
        if self.preview and c["lane"] == "lights":
            self.write_preview(c.get("value"))

    def write_preview(self, look_name):
        """Rehearsing without Resolume: let the previz show the look itself."""
        look = self.looks.get(look_name)
        os.makedirs(os.path.dirname(PREVIEW), exist_ok=True)
        json.dump({"look": look_name, "fixtures": (look or {}).get("fixtures", {}),
                   "hold": True, "t": time.time()}, open(PREVIEW, "w"))

    def goto(self, beat):
        """Position moved. Fire what was crossed; on a jump, restate each lane."""
        if self.pos is None or abs(beat - self.pos) > 1e-4:
            self.moved_t = time.monotonic()
        jumped = self.pos is None or beat < self.pos - 1.0 or beat > self.pos + 8
        if self.panicked:
            # holding the safe look: keep track of where we are, fire nothing
            self.fired |= {id(e) for e in self.plan if e["beat"] is not None and e["beat"] <= beat}
            self.write_state(beat, force=jumped)
            self.pos = beat
            return
        if jumped:
            self.restate(beat)
        else:
            for entry in self.plan:
                if entry["beat"] is None:
                    continue
                if self.pos < entry["beat"] <= beat and id(entry) not in self.fired:
                    self.fired.add(id(entry))
                    self.fire(entry)
        self.automate(beat, force=jumped)
        self.write_state(beat, force=jumped)
        self.pos = beat

    def panic(self):
        """Put the rig in the safe look and stop following the plan until resume."""
        if self.panicked:
            return
        self.panicked = True
        open(PANIC_FLAG, "w").close()
        print(f"{CLEAR}\n   ##### PANIC — safe look, cues held.  r to resume #####")
        if not self.panic_plan:
            print("   (no \"panic\" block in osc_map.json: everything just holds)")
        for entry in self.panic_plan:
            self.fire(entry, "panic")
        self.write_state(self.pos or 0.0, force=True)

    def resume(self):
        """Back to the plan, exactly where the music is now."""
        if not self.panicked:
            return
        self.panicked = False
        try:
            os.remove(PANIC_FLAG)
        except OSError:
            pass
        print(f"{CLEAR}   ----- resumed -----")
        if self.pos is not None:
            self.restate(self.pos)
            self.automate(self.pos, force=True)
        self.write_state(self.pos or 0.0, force=True)

    def key(self, k):
        if k in ("p", "P"):
            self.panic()
        elif k in ("r", "R"):
            self.resume()

    def latest(self, beat, plan=None):
        """Per lane, the last entry at or before `beat`: what that lane shows there."""
        out = {}
        for entry in (self.plan if plan is None else plan):
            if entry["beat"] is None or entry["beat"] > beat:
                continue
            out[entry["cue"]["lane"]] = entry          # an end counts: that lane is empty now
        return out

    def reload(self, show, plan, automation):
        """The plan was edited while running: take the new one, and change only
        the lanes whose clip right here is different now. A cue added ahead of
        the playhead just waits to be crossed."""
        def sig(e):
            if e is None or e.get("end_of"):
                return None
            return (repr(e["messages"]), e["problem"])
        pos = self.pos
        before = self.latest(pos) if pos is not None else {}
        self.show, self.plan = show, plan
        self.automation = [a for a in (automation or [])
                           if not a["problem"] or (a["spec"] and a["spec"].get("resolume") and a["points"])]
        if pos is None:
            return []
        self.fired = {id(e) for e in plan if e["beat"] is not None and e["beat"] <= pos}
        after = self.latest(pos)
        changed = [l for l in dict.fromkeys(list(before) + list(after))
                   if sig(before.get(l)) != sig(after.get(l))]
        if changed and not self.panicked:
            self.restate(pos, only=changed, old=before)
        self.automate(pos, force=True)
        return changed

    def restate(self, beat, only=None, old=None):
        """After a jump: put every lane where it would be if we had played here.
        With `only`, just those lanes (after an edit); `old` is what they showed."""
        if only is None:
            print(f"{CLEAR}   .. jump to bar {beat / self.show.get('beats_per_bar', 4) + 1:.0f}")
        self.fired = {id(e) for e in self.plan if e["beat"] is not None and e["beat"] <= beat}
        latest = self.latest(beat)
        # every layer the plan uses shows what the plan says here, and that
        # includes nothing: a layer no current cue plays on is cleared first
        n = self.fades.n_layers if self.fades else 8
        hit = lambda e: layers_hit(e["messages"], n) if e["messages"] and not e["problem"] else []
        claimed = {L for e in latest.values() if not e.get("end_of") for L in hit(e)}
        if only is None:
            managed = {L for e in self.plan if not e.get("end_of") for L in hit(e)}
        else:                                  # only what the edited lanes were playing
            managed = {L for l in only for e in [(old or {}).get(l)] if e and not e.get("end_of") for L in hit(e)}
        stale = sorted(managed - claimed)
        if stale:
            print(f"{CLEAR}   >> nothing plays on layer {', '.join(map(str, stale))} here: cleared")
            for L in stale:
                self.clear(L)
        for lane in ("scenes", "screen", "overlay", "lights", "td"):
            if only is not None and lane not in only:
                continue
            if lane in latest and not latest[lane].get("end_of"):
                self.fire(latest[lane], "restate" if only is None else "edited")


# ------------------------------------------------------------------- modes ---
def dry_run_automation(show, lanes):
    if not lanes:
        return 0
    bpb = show.get("beats_per_bar", 4)
    print("  automation")
    print("  " + "-" * 96)
    bad = 0
    for a in lanes:
        name = a["lane"].get("target")
        if a["problem"]:
            print(f"  !! {name:<22} {a['problem']}")
            bad += 1
            continue
        spec = a["spec"]
        span = f"bars {a['points'][0][0] / bpb + 1:.0f}-{a['points'][-1][0] / bpb + 1:.0f}"
        where = (f"Resolume {' / '.join(map(str, spec['resolume']))} (id {a['param']['id']})"
                 if spec.get("resolume") else spec["address"])
        curved = sum(1 for p in a["points"] if p[3] or p[2] == "s")
        print(f"     {name:<22} {len(a['points']):>3} points  {span:<14} -> "
              f"{where}  [{spec.get('min', 0)}..{spec.get('max', 1)}]"
              + (f"  {curved} curved" if curved else ""))
        if a["orphans"]:
            print(f"     {'':22} {a['orphans']} point(s) sit in a section that is gone")
            bad += 1
    print()
    return bad


def dry_run(show, plan, mapping):
    tempo = show["tempo"]
    print(f"\n{show['songs'][0]['name'] if show['songs'] else ''} … "
          f"{len(show['songs'])} songs, {show['total_bars']:.0f} bars, "
          f"{show['total_seconds'] / 60:.1f} min at {tempo} bpm")
    print(f"  source: {show['source']}\n")
    print(f"  {'time':>6}  {'bar':>5}  {'where':<28} {'lane':<7} {'what':<22} osc")
    print("  " + "-" * 96)
    missing = 0
    for e in plan:
        c = e["cue"]
        if e["beat"] is None:
            print(f"  {'':>6}  {'--':>5}  {'ORPHAN':<28} {c['lane']:<7} "
                  f"{(c.get('value') or '-'):<22} {e['problem']}")
            missing += 1
            continue
        g_s = where(show, e["beat"])
        place = f"{g_s[0]['name']} / {g_s[1]['name']}" if g_s else ""
        if e.get("end_of"):
            src = e["end_of"]
            if src["problem"] or not src["messages"]:
                osc = "(its cue does nothing)"
            elif not handover_layers(e, 8):
                continue                       # the next clip plays on the same layer
            else:
                osc = "clear layer " + ", ".join(map(str, handover_layers(e, 8)))
            print(f"  {timecode(e['beat'], tempo):>6}  {e['bar']:>5.0f}  {place:<28} "
                  f"{c['lane']:<7} {'(' + str(c.get('value')) + ' ends)':<22} {osc}")
            continue
        if e["problem"]:
            osc = f"!! {e['problem']}"
            missing += 1
        elif not e["messages"]:
            osc = "(note)"
        else:
            osc = "  ".join(f"{a} {args}" for a, args in e["messages"])
            if c.get("fade_bars"):
                secs = fade_seconds(c, show)
                full = float(c["fade_bars"]) * show.get("beats_per_bar", 4) * 60 / show["tempo"]
                osc = f"fade {c['fade_bars']:g} bar(s) = {secs:g}s" + \
                      (f" (Resolume's max; wanted {full:g}s)" if full > MAX_FADE else "") + "  " + osc
        print(f"  {timecode(e['beat'], tempo):>6}  {e['bar']:>5.0f}  {place:<28} "
              f"{c['lane']:<7} {(c.get('value') or '-'):<22} {osc}")
        if c.get("note"):
            print(f"  {'':>6}  {'':>5}  {'':28} {'':7} note: {c['note']}")
    print()
    if missing:
        print(f"  {missing} cue(s) would do nothing. In the timeline they're striped with ✗: "
              f"drag the right clip onto each (or re-point its section) before the show.\n")
    else:
        print("  every cue maps to something.\n")
    return 1 if missing else 0


def rehearse(show, player, speed, start_bar):
    bpb = show.get("beats_per_bar", 4)
    beat = (start_bar - 1) * bpb
    end = show["total_bars"] * bpb
    per_beat = 60.0 / show["tempo"] / max(0.01, speed)
    print(f"\n  rehearsing at {speed}x from bar {start_bar:.0f}  (ctrl-c to stop)\n")
    last = time.monotonic()
    try:
        while beat < end:
            time.sleep(min(0.05, per_beat))
            now = time.monotonic()
            beat += (now - last) / per_beat
            last = now
            player.goto(beat)
            g_s = where(show, beat)
            if g_s:
                print(f"\r   bar {beat / bpb + 1:6.0f}   {g_s[0]['name']} / {g_s[1]['name']:<18}",
                      end="", flush=True)
    except KeyboardInterrupt:
        pass
    print("\n  done\n")


class Keys:
    """Single keypresses from the terminal, without Enter, when there is one."""
    def __init__(self):
        self.fd, self.saved = None, None
        try:
            import termios, tty
            fd = sys.stdin.fileno()
            if os.isatty(fd) and os.tcgetpgrp(fd) == os.getpgrp():
                self.saved = termios.tcgetattr(fd)
                tty.setcbreak(fd)              # ctrl-c still works
                self.fd = fd
        except (ImportError, OSError, ValueError):
            pass

    @property
    def fds(self):
        return [self.fd] if self.fd is not None else []

    def read(self):
        try:
            return os.read(self.fd, 16).decode(errors="ignore")[-1:]
        except OSError:
            return ""

    def close(self):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


class PlanWatch:
    """Notice when the timeline (or anyone) saves cues.json, show.json or
    osc_map.json, and hand the player the new plan: no restart needed."""
    FILES = (SHOW, CUES, MAP)                  # in the order check() unpacks them

    def __init__(self, player, every=0.5):
        self.player, self.every, self.t = player, every, 0.0
        self.stamp = self.stamps()

    def stamps(self):
        out = []
        for f in self.FILES:
            try:
                out.append(os.stat(f).st_mtime_ns)
            except OSError:
                out.append(None)
        return out

    def check(self):
        now = time.monotonic()
        if now - self.t < self.every:
            return
        self.t = now
        stamp = self.stamps()
        if stamp == self.stamp:
            return
        try:
            show, cues, mapping = (json.load(open(f)) for f in self.FILES)
        except (OSError, ValueError):
            return                             # caught mid-save: try again next time
        self.stamp = stamp
        p = self.player
        try:
            plan = compile_cues(show, cues, mapping, getattr(p, "snap", None))
            automation = compile_automation(show, cues, mapping, getattr(p, "param_index", None))
            p.mapping = mapping
            changed = p.reload(show, plan, automation)
        except Exception as e:                 # a bad edit must never stop the show
            print(f"{CLEAR}   !! couldn't take the edited plan ({type(e).__name__}: {e}); "
                  "still playing the last good one")
            return
        n = sum(1 for e in plan if not e.get("end_of") and e["beat"] is not None)
        print(f"{CLEAR}   .. plan edited: {n} cue(s)"
              + (f", now showing the new {', '.join(changed)} here" if changed else ""))


def follow(show, player, port, live_host, live_port, timeline=True):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    bpb = show.get("beats_per_bar", 4)

    def subscribe():
        """Ask AbletonOSC to stream the playhead, and for its position right now.

        It answers on /live/song/get/... rather than the address you subscribe
        with, and the fine-grained one is current_song_time; beat is the
        once-per-beat fallback."""
        for address, args in (("/live/song/start_listen/current_song_time", []),
                              ("/live/song/start_listen/beat", []),
                              ("/live/song/get/current_song_time", [])):
            try:
                sock.sendto(osc_encode(address, args), (live_host, live_port))
            except OSError:
                pass

    print(f"\n  following Live: listening on {port}, asking AbletonOSC on "
          f"{live_host}:{live_port}  (ctrl-c to stop)")
    keys = Keys()
    if keys.fds:
        print("  keys: p = PANIC (safe look, hold)   r = resume the plan")
    if player.panicked:
        print("   ##### still in PANIC from before the restart.  r to resume #####")
    subscribe()
    seen, last_ask = False, time.monotonic()
    last_fine = 0.0          # when the streamed position last arrived
    live_moved = 0.0         # when Live's position last changed: Live playing beats the timeline
    live_last = None
    player.source = "live"   # who is driving: "live", or "timeline" once the browser's ▶ takes over
    if timeline:
        print("  the timeline's ▶ can drive this too (Drive, in the timeline); Live wins when it plays")
    plan_watch = PlanWatch(player)
    try:
        while True:
            plan_watch.check()
            show = player.show
            ready = select.select([sock] + keys.fds, [], [], 0.5)[0]
            if keys.fds and keys.fd in ready:
                player.key(keys.read())
                if sock not in ready:
                    continue
            try:
                if sock not in ready:
                    raise socket.timeout
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                player.write_state(player.pos or 0.0, force=True)     # heartbeat
                # Silence. Either Live is stopped (it still answers a query), or it
                # was restarted and dropped our subscription, or it is gone. Ask
                # again every couple of seconds: that re-subscribes a restarted
                # Live, and the query's answer tells stopped apart from gone.
                now = time.monotonic()
                if now - last_ask > 2:
                    subscribe()
                    last_ask = now
                    if now - player.heard_t < 6:
                        msg = "Live is stopped - press play"
                    else:
                        msg = ("waiting for Live … is it open, with AbletonOSC enabled "
                               "as a Control Surface?")
                    print(f"{CLEAR}   {msg}", end="", flush=True)
                continue
            for address, args in osc_decode(data):
                if address.startswith("/live/"):
                    player.heard_t = time.monotonic()
                if not args:
                    continue
                if address == "/timeline/release":
                    # Drive switched off, Follow Live on, or the tab closed: back to Live, now
                    if player.source != "live":
                        print(f"{CLEAR}   the timeline let go: following Live again")
                        player.source = "live"
                        live_last = None           # take Live's next answer, parked or not
                        subscribe(); last_ask = time.monotonic()
                    continue
                if address == "/timeline/beats":
                    if not timeline or time.monotonic() - live_moved < 1.5:
                        continue       # Live mode, or Live is playing: ignore the browser
                    if player.source != "timeline":
                        print(f"{CLEAR}   the timeline is driving (Live is stopped)")
                        player.source = "timeline"
                    beat = float(args[0])
                    if not seen:
                        print("   got position from the timeline")
                        seen = True
                    player.goto(beat)
                    g_s = where(show, beat)
                    if g_s:
                        print(f"\r   bar {beat / bpb + 1:6.0f}   {g_s[0]['name']} / {g_s[1]['name']:<18}"
                              f"  (timeline)", end="", flush=True)
                    continue
                fine = address in ("/live/song/get/current_song_time",
                                   "/position/beats", "/position")
                coarse = address in ("/live/song/get/beat", "/live/song/beat")
                if fine or coarse:
                    now = time.monotonic()
                    if coarse and now - last_fine < 2.0:
                        continue       # the streamed position is better; ignore beats
                    if fine:
                        last_fine = now
                    beat = float(args[0])
                    moved = live_last is not None and abs(beat - live_last) > 1e-4
                    if moved:
                        live_moved = now
                    live_last = beat
                    if player.source == "timeline":
                        if not moved:
                            continue   # Live parked somewhere: it doesn't pull the show back
                        print(f"{CLEAR}   Live is playing: it drives again")
                        player.source = "live"
                    if not seen:
                        print(f"   got position from {address}")
                        seen = True
                    player.goto(beat)
                    g_s = where(show, beat)
                    if g_s:
                        print(f"\r   bar {beat / bpb + 1:6.0f}   "
                              f"{g_s[0]['name']} / {g_s[1]['name']:<18}", end="", flush=True)
    except KeyboardInterrupt:
        # leave Live quiet again rather than streaming to nobody
        for address in ("/live/song/stop_listen/current_song_time",
                        "/live/song/stop_listen/beat"):
            try:
                sock.sendto(osc_encode(address, []), (live_host, live_port))
            except OSError:
                pass
        print("\n  stopped\n")
    finally:
        keys.close()                 # never leave the terminal in cbreak, even on a crash


# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the cue list and exit")
    mode.add_argument("--rehearse", action="store_true", help="run on a fake clock")
    mode.add_argument("--follow", action="store_true", help="follow Live's position")
    ap.add_argument("--speed", type=float, default=1.0, help="rehearsal speed (4 = four times)")
    ap.add_argument("--from-bar", type=float, default=1, help="rehearse from this bar")
    ap.add_argument("--listen-port", type=int, default=11001,
                    help="OSC port Live sends to (AbletonOSC replies on 11001)")
    ap.add_argument("--live-host", default="127.0.0.1", help="where Live is")
    ap.add_argument("--live-port", type=int, default=11000,
                    help="AbletonOSC's input port")
    ap.add_argument("--host", help="Resolume host (default from osc_map.json)")
    ap.add_argument("--port", type=int, help="Resolume OSC port")
    ap.add_argument("--live-only", action="store_true",
                    help="follow Live only, never the timeline's ▶ (Live.command uses this)")
    ap.add_argument("--preview", action="store_true",
                    help="also show lights cues in the previz (for rehearsing without Resolume)")
    a = ap.parse_args()

    show = load(SHOW, None)
    cues = load(CUES, {"cues": []})
    looks = load(LOOKS, {"looks": []})
    if not os.path.exists(MAP):
        json.dump(default_map(), open(MAP, "w"), indent=2)
        print(f"[cues] wrote a starting {MAP} - fill in your Resolume layers and clips")
    mapping = load(MAP, default_map())

    res = mapping.get("resolume", {})
    base = f"http://{a.host or res.get('host', '127.0.0.1')}:8080"
    try:
        raw = arena_load.fetch(base)
        snap, live_comp, param_index = arena_load.snapshot(comp=raw), True, arena_load.params(raw)
        arena_load.save_cache(snap)
    except (OSError, ValueError):
        snap, live_comp, param_index = arena_load.load_cache(), False, None
    if live_comp:
        print(f"  clips by name, from Resolume's '{snap['name']}'")
    elif snap:
        print(f"  Resolume isn't answering: names from the composition as last seen "
              f"('{snap['name']}', {snap.get('saved', '?')})")
    else:
        print("  no composition known: using the positions in osc_map.json")
    plan = compile_cues(show, cues, mapping, snap)
    automation = compile_automation(show, cues, mapping, param_index)
    if not plan and not automation:
        print("[cues] nothing planned yet: add cues in the show timeline"
              + (" first" if a.dry_run else " — they're picked up as you add them"))
        if a.dry_run:
            return 1

    if a.dry_run:
        bad = dry_run(show, plan, mapping)
        return max(bad, dry_run_automation(show, automation))

    sender = Sender(a.host or res.get("host", "127.0.0.1"),
                    a.port or res.get("port", 7000))
    player = Player(show, plan, sender, looks, preview=a.preview, automation=automation,
                    panic=compile_panic(mapping, snap),
                    fades=Fades(f"http://{sender.addr[0]}:8080", len(snap["layers"])) if snap else None,
                    rest=Rest(sender.addr[0]))
    player.snap, player.param_index, player.mapping = snap, param_index, mapping
    if snap and not a.rehearse:
        watch_composition(player, mapping, f"http://{sender.addr[0]}:8080")
    live_lanes = [x for x in automation if not x["problem"]]
    if live_lanes:
        print(f"  automation: {', '.join(x['lane'].get('target') for x in live_lanes)}")
    print(f"  cues -> Resolume at {sender.addr[0]}:{sender.addr[1]}"
          + ("  (lights also shown in the previz)" if a.preview else ""))
    if a.rehearse:
        rehearse(show, player, a.speed, a.from_bar)
    else:
        follow(show, player, a.listen_port, a.live_host, a.live_port, timeline=not a.live_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
