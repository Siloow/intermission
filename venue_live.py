"""Live runtime for venue.blend: Art-Net -> pars, Syphon bridge -> screen.

Embedded in venue.blend as a registered text block, so it loads with the file
when Blender is allowed to auto-run scripts. Otherwise open the Text Editor,
pick venue_live.py and press Run Script (Alt+P) once.

Adds a "Venue" tab to the 3D viewport sidebar (N):
  Live         listen for Art-Net and read the screen feed
  Test chase   animate the pars from inside Blender, no Resolume needed
  Haze         the scene's haze amount
  Cameras      jump between the audience views

Laptop keys (no numpad needed), while the mouse is over the 3D viewport:
  alt 1..6     seat / performer / plan cameras, in the order listed in the panel
  alt left/right   previous / next camera
  alt H        haze on or off
  alt L        live on or off
  alt C        test chase on or off

Pars: every object with a "dmx_address" property is a fixture. On each tick we
read its footprint out of the universe named by "dmx_universe" and write the
channels (layout in "dmx_layout", e.g. "r,g,b,w,dim") onto the object's custom
properties. Drivers built by build_venue.py turn those into light colour.

Screen: syphon_bridge.py writes frames into .live/screen.rgba next to the
.blend (16-byte header + RGBA rows, bottom-up). We copy each new frame into
the SCREEN_LIVE image and point the screen material at it.
"""
import bpy, blf, gpu, json, math, mmap, os, socket, struct, time
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
import numpy as np

ARTNET_PORT = 6454
TICK = 1 / 40
SCREEN_FILE = "//.live/screen.rgba"
STATUS_FILE = "//.live/status.json"
RIG_FILE = "//rig.json"
PREVIEW_FILE = "//.live/preview.json"

# Full is the default. Laptop is there if a weaker machine ever struggles.
QUALITY = {
    "LAPTOP": dict(
        tick=1 / 20,          # Art-Net and screen polls per second
        screen_max=640,       # subsample the incoming frame above this width
        taa_samples=8,        # viewport samples before the image settles
        use_raytracing=False, # screen glow on the room comes from SCREEN_SPILL
        volumetric_tile_size="8",
        volumetric_samples=24,
        use_volumetric_shadows=False,
        shadow_resolution_scale=0.5,
        shadow_ray_count=1,
        shadow_step_count=2,
    ),
    "FULL": dict(
        tick=1 / 40,
        screen_max=1920,
        taa_samples=32,
        use_raytracing=True,
        volumetric_tile_size="4",
        volumetric_samples=64,
        use_volumetric_shadows=True,
        shadow_resolution_scale=1.0,
        shadow_ray_count=2,
        shadow_step_count=4,
    ),
}
# Camera order for the alt-number keys and for cycling
CAMERAS = ["CAM_front_row", "CAM_middle", "CAM_back_row", "CAM_side_seat",
           "CAM_performer", "CAM_plan"]

HEADER = struct.Struct("<4sIII")  # magic, width, height, frame counter
MAGIC = b"VSCR"


class _State:
    socks = []
    sock_error = ""
    universes = {}        # universe -> bytes(512)
    packets = 0
    pps = 0.0
    last_sender = ""
    mm = None
    mm_size = 0
    screen_frame = -1
    screen_frames = 0
    screen_fps = 0.0
    screen_seen = 0.0
    stat_t = 0.0
    chase = False
    chase_t0 = 0.0
    live = False
    tick = 1 / 40
    screen_max = 1920
    preview_mtime = 0.0
    preview = None          # {"look": name, "fixtures": {...}, "hold": bool}
    preview_name = ""
    rig_mtime = 0.0
    rig_count = 0
    rig_error = ""


S = _State()


# ------------------------------------------------------------------- help ---
HELP_LINES = [
    ("Venue previz", ""),
    ("opt 1-6", "front row / middle / back row / side seat / your seat / plan"),
    ("opt left right", "previous / next camera"),
    ("opt H", "haze on / off"),
    ("opt L", "live on / off (Art-Net + screen)"),
    ("opt C", "test chase on / off"),
    ("opt K", "hide this list"),
    ("", ""),
    ("opt drag", "orbit    shift opt drag: pan    scroll: zoom"),
    ("shift `", "walk: W A S D, E/Q up-down, click to stop"),
    ("0 1 3 7", "camera / front / side / top     Z: shading    N: sidebar"),
]
_help_handle = None


def _help_draw():
    """Overlay in the top-left of the viewport. Never appears in a render."""
    try:
        ctx = bpy.context
        if not ctx.scene.get("show_help", True) or ctx.space_data.region_3d is None:
            return
        ui = ctx.preferences.system.ui_scale
        pad, lh = 12 * ui, 19 * ui
        # clear of the toolbar on the left and the view name at the top
        x, y0 = 120 * ui, ctx.region.height - 120 * ui
        size, key_w = int(12 * ui), 118 * ui
        blf.size(0, size)
        w = key_w + max(blf.dimensions(0, t)[0] for _, t in HELP_LINES) + 3 * pad
        h = lh * len(HELP_LINES) + pad
        # backdrop
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        x0, y1 = x - pad, y0 + lh - pad / 2
        verts = [(x0, y1), (x0 + w, y1), (x0 + w, y1 - h), (x0, y1 - h)]
        batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=[(0, 1, 2), (0, 2, 3)])
        gpu.state.blend_set("ALPHA")
        shader.uniform_float("color", (0.05, 0.05, 0.06, 0.72))
        batch.draw(shader)
        gpu.state.blend_set("NONE")
        for i, (key, text) in enumerate(HELP_LINES):
            y = y0 - i * lh
            if not key and not text:
                continue
            if not text:                      # title row
                blf.color(0, 1, 1, 1, 1)
                blf.position(0, x, y, 0)
                blf.draw(0, key)
                continue
            blf.color(0, 0.62, 0.86, 1.0, 1)
            blf.position(0, x, y, 0)
            blf.draw(0, key)
            blf.color(0, 0.86, 0.86, 0.88, 1)
            blf.position(0, x + key_w, y, 0)
            blf.draw(0, text)
    except Exception:
        pass                                   # never break the viewport draw


def _help_enable(on):
    global _help_handle
    if on and _help_handle is None:
        _help_handle = bpy.types.SpaceView3D.draw_handler_add(_help_draw, (), "WINDOW", "POST_PIXEL")
    elif not on and _help_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_help_handle, "WINDOW")
        _help_handle = None


# ----------------------------------------------------------------- quality --
def apply_quality(name=None):
    """Trade viewport quality for frame rate. Settings Blender doesn't have in
    this version are skipped, so this stays safe across versions."""
    scene = bpy.context.scene
    name = (name or scene.get("quality") or "FULL").upper()
    if name not in QUALITY:
        name = "FULL"
    q = QUALITY[name]
    scene["quality"] = name
    S.tick, S.screen_max = q["tick"], q["screen_max"]
    for attr, val in q.items():
        if attr in ("tick", "screen_max"):
            continue
        if hasattr(scene.eevee, attr):
            try:
                setattr(scene.eevee, attr, val)
            except Exception:
                pass
    return name


# ------------------------------------------------------------------ Art-Net --
def _local_addresses():
    """Every local IPv4 worth listening on: the wildcard, loopback, and this
    machine's LAN address."""
    addrs = ["0.0.0.0", "127.0.0.1"]
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 53))    # no traffic; just asks the routing table
        addrs.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    out = []
    for a in addrs:
        if a not in out:
            out.append(a)
    return out


def _open_socket():
    """Bind one socket per local address, not just the wildcard.

    Resolume keeps its own Art-Net node on port 6454. When two sockets share a
    port, the kernel hands each packet to only one of them, so a wildcard
    socket alone loses most packets to Resolume. A socket bound to the exact
    destination address wins over Resolume's wildcard one, so we bind them all
    and read whichever receives."""
    if S.socks:
        return True
    errors = []
    for addr in _local_addresses():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind((addr, ARTNET_PORT))
            s.setblocking(False)
            S.socks.append(s)
        except OSError as e:
            errors.append(f"{addr}: {e.strerror or e}")
    S.sock_error = "" if S.socks else f"port {ARTNET_PORT}: " + "; ".join(errors)
    return bool(S.socks)


def _close_socket():
    for s in S.socks:
        try:
            s.close()
        except OSError:
            pass
    S.socks = []


def _drain_artnet():
    if not S.socks:
        return False
    got = False
    for sock in S.socks:
      while True:
        try:
            data, addr = sock.recvfrom(1024)
        except (BlockingIOError, InterruptedError):
            break
        except OSError:
            break
        # ArtDmx: "Art-Net\0", opcode 0x5000 (little endian), ... universe, length
        if len(data) < 18 or data[:8] != b"Art-Net\x00" or data[8:10] != b"\x00\x50":
            continue
        universe = data[14] | (data[15] << 8)
        length = (data[16] << 8) | data[17]
        S.universes[universe] = data[18:18 + length].ljust(512, b"\x00")
        S.packets += 1
        S.last_sender = addr[0]
        got = True
    return got


def _fixtures():
    """Real fixtures the rig uses - pars and bars. A bar's 18 pixels are their
    own little fixtures; they are addressed separately but listed under the bar."""
    return [ob for ob in bpy.data.objects
            if ob.get("in_rig", False) and ob.get("kind") in ("par", "bar")]


def _dmx_targets():
    """What actually reads DMX: pars, and each bar pixel. The bar itself shares
    its first pixel's address, so it must not read too."""
    return [ob for ob in bpy.data.objects
            if "dmx_address" in ob and ob.get("in_rig", False)
            and ob.get("kind") in ("par", "pixel")]


def _pixels_of(bar_name):
    return [ob for ob in bpy.data.objects if ob.get("of") == bar_name]


def _apply_dmx():
    changed = False
    for ob in _dmx_targets():
        dmx = S.universes.get(int(ob.get("dmx_universe", 0)))
        if dmx is None:
            continue
        start = int(ob["dmx_address"]) - 1
        layout = str(ob.get("dmx_layout", "r,g,b,w")).split(",")
        for i, ch in enumerate(layout):
            v = dmx[start + i] if 0 <= start + i < 512 else 0
            if ob.get(ch) != v:
                ob[ch] = v
                changed = True
        if "dim" not in layout and ob.get("dim") != 255:
            ob["dim"] = 255   # no dimmer channel: brightness is in the colour
            changed = True
    return changed


def _apply_chase():
    """Built-in test: slow rainbow around the semicircle with a breathing dim."""
    t = time.monotonic() - S.chase_t0
    pars = sorted(_fixtures(), key=lambda o: o.name)
    for i, ob in enumerate(pars):
        h = (t * 0.15 + i / max(1, len(pars))) % 1.0
        r = max(0.0, min(1.0, abs(h * 6 - 3) - 1))
        g = max(0.0, min(1.0, 2 - abs(h * 6 - 2)))
        b = max(0.0, min(1.0, 2 - abs(h * 6 - 4)))
        dim = 0.55 + 0.45 * math.sin(t * 2.0 + i * 0.9)
        ob["r"], ob["g"], ob["b"] = int(r * 255), int(g * 255), int(b * 255)
        ob["w"] = int(40 * max(0.0, math.sin(t * 0.7)))
        ob["dim"] = int(255 * dim)
    return True


def _refresh_fixtures():
    """Custom property writes from Python don't tag the depsgraph; do it here
    so the drivers on lights and lens materials re-evaluate."""
    for ob in _dmx_targets():
        ob.update_tag()
    for ld in bpy.data.lights:
        if ld.name.startswith(("PAR_", "BAR_")):
            ld.update_tag()
    for m in bpy.data.materials:
        if m.name.startswith(("PAR_", "BAR_")):
            m.update_tag()


# ---------------------------------------------------------------- rig file --
def _aim_euler(aim_deg, tilt_deg):
    a, t = math.radians(aim_deg), math.radians(tilt_deg)
    d = Vector((math.sin(a) * math.cos(t), math.cos(a) * math.cos(t), math.sin(t)))
    if d.length < 1e-6:
        d = Vector((0, 0, 1))
    return d.normalized().to_track_quat("Z", "Y").to_euler()


def _lay_out_bar(bar, f):
    """A bar can be turned on the floor and re-addressed; its pixels follow."""
    spin = math.radians(float(f.get("rot_deg", bar.get("rot_deg", 0))))
    bar["rot_deg"] = math.degrees(spin)
    length = float(bar.get("length", 1.04))
    pixels = int(bar.get("pixels", 18))
    step = length / pixels
    base = int(f.get("address", bar.get("dmx_address", 1)))
    per_pixel = str(f.get("mode", bar.get("mode", "72ch"))) == "72ch"
    body = bpy.data.objects.get(bar.name + "_body")
    if body:
        body.rotation_euler = (0, 0, spin)
    for px in _pixels_of(bar.name):
        i = int(px.get("pixel", 1)) - 1
        along = -length / 2 + step * (i + 0.5)
        px.location = (math.cos(spin) * along, math.sin(spin) * along, px.location.z)
        px.rotation_euler = (0, 0, spin)
        px["dmx_address"] = base + (i * 4 if per_pixel else 0)


def _show(ob, visible):
    if ob and (ob.hide_viewport != (not visible) or ob.hide_render != (not visible)):
        ob.hide_viewport = ob.hide_render = not visible


def _read_rig(force=False):
    """Follow rig.json, which the floor-plan editor writes. Fixtures the file
    doesn't mention are hidden, so pars can be added and removed live."""
    path = bpy.path.abspath(RIG_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    if mtime == S.rig_mtime and not force:
        return False
    S.rig_mtime = mtime
    try:
        rig = json.load(open(path))
        fixtures = rig["fixtures"]
    except (ValueError, OSError, KeyError) as e:
        S.rig_error = f"rig.json: {e}"
        return False
    S.rig_error = ""

    wanted = {}
    for i, f in enumerate(fixtures):
        wanted[f.get("name") or f"PAR_{i + 1:02d}"] = f
    n = 0
    for ob in bpy.data.objects:
        if ob.type != "EMPTY" or ob.get("kind") not in ("par", "bar"):
            continue
        f = wanted.get(ob.name)
        in_rig = f is not None
        ob["in_rig"] = in_rig
        for child in [ob] + list(ob.children_recursive):
            _show(child, in_rig)
            if child is not ob and "in_rig" in child:
                child["in_rig"] = in_rig
        if not in_rig:
            continue
        n += 1
        default_z = 0.07 if ob.get("kind") == "bar" else 0.18
        ob.location = (float(f.get("x", 0)), float(f.get("y", 0)),
                       float(f.get("z", default_z)))
        ob.rotation_euler = _aim_euler(float(f.get("aim_deg", 0)), float(f.get("tilt_deg", 70)))
        if ob.get("kind") == "bar":
            _lay_out_bar(ob, f)
        ob["dmx_address"] = int(f.get("address", 1))
        ob["dmx_universe"] = int(rig.get("universe", 0))
        ob["dmx_layout"] = str(rig.get("layout", "r,g,b,w"))
        beam = bpy.data.objects.get(ob.name + "_beam")
        if beam:
            beam.data.spot_size = math.radians(float(f.get("beam_deg", 25)))
            beam.data.update_tag()
        ob.update_tag()
    S.rig_count = n
    return True


def _read_preview():
    """The look being designed in the floor-plan editor. It drives the pars when
    no DMX is coming in, so looks can be built with Resolume closed."""
    path = bpy.path.abspath(PREVIEW_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    if mtime == S.preview_mtime:
        return False
    S.preview_mtime = mtime
    try:
        S.preview = json.load(open(path))
        S.preview_name = str(S.preview.get("look") or "")
    except (ValueError, OSError):
        return False
    return _apply_preview()


def _apply_preview():
    p = S.preview
    if not p:
        return False
    fixtures = p.get("fixtures") or {}
    changed = False
    for ob in _dmx_targets():
        # a look names a par or a bar; a bar's value applies to all its pixels
        v = fixtures.get(ob.name) or fixtures.get(ob.get("of", "")) or {}
        for ch in ("r", "g", "b", "w", "dim"):
            new = int(v.get(ch, 0))
            if ob.get(ch) != new:
                ob[ch] = new
                changed = True
    return changed


# ------------------------------------------------------------------- screen --
def _screen_path():
    return bpy.path.abspath(SCREEN_FILE)


def _open_screen():
    path = _screen_path()
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if S.mm and S.mm_size == size:
        return True
    _close_screen()
    try:
        with open(path, "rb") as f:
            S.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        S.mm_size = size
        return True
    except (OSError, ValueError):
        S.mm = None
        return False


def _close_screen():
    if S.mm:
        S.mm.close()
    S.mm, S.mm_size, S.screen_frame = None, 0, -1


def _live_image(w, h):
    im = bpy.data.images.get("SCREEN_LIVE")
    if im is None:
        im = bpy.data.images.new("SCREEN_LIVE", w, h, alpha=False)
    elif tuple(im.size) != (w, h):
        im.scale(w, h)
    return im


def _set_screen_image(im):
    m = bpy.data.materials.get("screen")
    node = m and m.node_tree.nodes.get("SCREEN_TEX")
    if node and node.image != im:
        node.image = im


def _read_screen():
    if not _open_screen():
        return False
    magic, w, h, frame = HEADER.unpack_from(S.mm, 0)
    if magic != MAGIC or S.mm_size < HEADER.size + w * h * 4 or frame == S.screen_frame:
        return False
    S.screen_frame = frame
    S.screen_frames += 1
    S.screen_seen = time.monotonic()
    px = np.frombuffer(S.mm, np.uint8, count=w * h * 4, offset=HEADER.size)
    step = max(1, -(-w // S.screen_max))     # subsample wide frames on a laptop
    if step > 1:
        px = px.reshape(h, w, 4)[::step, ::step].reshape(-1)
        w, h = len(range(0, w, step)), len(range(0, h, step))
    im = _live_image(w, h)
    im.pixels.foreach_set(px.astype(np.float32) * (1 / 255))
    im.update()
    _set_screen_image(im)

    # screen spill light follows the average colour of the frame
    spill = bpy.data.lights.get("SCREEN_SPILL")
    if spill:
        avg = px.reshape(-1, 4)[::97, :3].mean(axis=0) / 255
        lum = float(avg @ np.array([0.2126, 0.7152, 0.0722]))
        spill.color = tuple(float(c) / max(1e-3, avg.max()) for c in avg)
        spill.energy = 6000 * lum
    return True


def _screen_to_testcard():
    card = bpy.data.images.get("SCREEN_TESTCARD")
    if card:
        _set_screen_image(card)
    spill = bpy.data.lights.get("SCREEN_SPILL")
    if spill:
        spill.color, spill.energy = (0.55, 0.5, 0.65), 2500


# --------------------------------------------------------------------- tick --
def _fixture_state(ob):
    """What the browser needs to draw a fixture: where it is, and its colour.
    For a bar that means all 18 pixels, so a chase shows up in the preview."""
    out = {k: ob.get(k) for k in ("dmx_address", "r", "g", "b", "w", "dim")}
    out.update(kind=ob.get("kind", "par"),
               x=round(ob.location.x, 3), y=round(ob.location.y, 3))
    if ob.get("kind") == "bar":
        px = sorted(_pixels_of(ob.name), key=lambda o: int(o.get("pixel", 0)))
        out["pixels"] = [[int(p.get(c, 0)) for c in ("r", "g", "b", "w")] for p in px]
        out["rot_deg"] = round(float(ob.get("rot_deg", 0)), 1)
        lit = [p for p in px if max(int(p.get(c, 0)) for c in ("r", "g", "b", "w")) > 0]
        if lit:      # the bar's own swatch is the average of its lit pixels
            for c in ("r", "g", "b", "w"):
                out[c] = int(sum(int(p.get(c, 0)) for p in lit) / len(lit))
    return out


def _write_status():
    """A small file the outside world can read: is anything arriving, and what
    are the pars doing right now."""
    try:
        data = {
            "live": S.live,
            "artnet_pps": round(S.pps, 1),
            "artnet_from": S.last_sender,
            "artnet_bound": [s.getsockname()[0] for s in S.socks],
            "artnet_error": S.sock_error,
            "screen_fps": round(S.screen_fps, 1),
            "screen_rgb": [round(c, 3) for c in bpy.data.lights["SCREEN_SPILL"].color]
            if "SCREEN_SPILL" in bpy.data.lights else None,
            "look": S.preview_name,
            "rig_fixtures": S.rig_count,
            "rig_error": S.rig_error,
            "screen_size": list(bpy.data.images["SCREEN_LIVE"].size)
            if "SCREEN_LIVE" in bpy.data.images else None,
            "universes": {str(u): [b for b in d[:32]] for u, d in S.universes.items()},
            "pars": {ob.name: _fixture_state(ob) for ob in _fixtures()},
            "t": time.time(),
        }
        with open(bpy.path.abspath(STATUS_FILE), "w") as fh:
            json.dump(data, fh, indent=1)
    except Exception:
        pass


def _redraw():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in ("VIEW_3D", "IMAGE_EDITOR"):
                area.tag_redraw()


def _tick():
    if not (S.live or S.chase):
        return None
    dirty = False
    now0 = time.monotonic()
    if now0 - S.stat_t >= 0.5 or S.rig_mtime == 0.0:
        dirty |= _read_rig()
    got_dmx = False
    if S.live:
        got_dmx = _drain_artnet()
        if got_dmx:
            dirty |= _apply_dmx()
        dirty |= _read_screen()
        if S.screen_seen and time.monotonic() - S.screen_seen > 2.0:
            _screen_to_testcard()   # bridge stopped: fall back, keep polling
            S.screen_seen = 0.0
            dirty = True
    if S.chase:
        dirty |= _apply_chase()
    elif not got_dmx and S.pps < 1:
        dirty |= _read_preview() or _apply_preview()
    else:
        _read_preview()          # keep it current, but live DMX has the pars
    if dirty:
        _refresh_fixtures()
        _redraw()

    now = time.monotonic()
    if now - S.stat_t >= 1.0:
        dt = now - S.stat_t if S.stat_t else 1.0
        S.pps, S.screen_fps = S.packets / dt, S.screen_frames / dt
        S.packets = S.screen_frames = 0
        S.stat_t = now
        _write_status()
        _redraw()
    return S.tick


def _ensure_timer():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=S.tick, persistent=True)


# ---------------------------------------------------------------------- UI ---
class VENUE_OT_live(bpy.types.Operator):
    bl_idname = "venue.live"
    bl_label = "Live"
    bl_description = "Listen for Art-Net on port 6454 and show the Syphon bridge feed on the screen"

    def execute(self, context):
        if S.live:
            S.live = False
            _close_socket()
            _close_screen()
            _screen_to_testcard()
        else:
            S.live = True
            S.chase = False
            _open_socket()
            _ensure_timer()
        _redraw()
        return {"FINISHED"}


class VENUE_OT_chase(bpy.types.Operator):
    bl_idname = "venue.chase"
    bl_label = "Test chase"
    bl_description = "Animate the pars from inside Blender (no Resolume needed)"

    def execute(self, context):
        S.chase = not S.chase
        S.chase_t0 = time.monotonic()
        if S.chase:
            _ensure_timer()
        return {"FINISHED"}


def _set_camera(context, cam):
    if not cam:
        return
    context.scene.camera = cam
    for area in getattr(context.screen, "areas", ()):
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_perspective = "CAMERA"
    _redraw()


def _camera_names():
    """Cameras in CAMERAS order first, then anything else in the file."""
    have = [n for n in CAMERAS if n in bpy.data.objects]
    return have + sorted(o.name for o in bpy.data.objects
                         if o.type == "CAMERA" and o.name not in have)


class VENUE_OT_camera(bpy.types.Operator):
    bl_idname = "venue.camera"
    bl_label = "Camera"
    bl_description = "Look through this camera"
    name: bpy.props.StringProperty()
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        name = self.name
        if self.index >= 0:
            names = _camera_names()
            if self.index >= len(names):
                return {"CANCELLED"}
            name = names[self.index]
        _set_camera(context, bpy.data.objects.get(name))
        return {"FINISHED"}


class VENUE_OT_camera_cycle(bpy.types.Operator):
    bl_idname = "venue.camera_cycle"
    bl_label = "Next / previous camera"
    step: bpy.props.IntProperty(default=1)

    def execute(self, context):
        names = _camera_names()
        if not names:
            return {"CANCELLED"}
        cur = context.scene.camera.name if context.scene.camera else names[0]
        i = names.index(cur) if cur in names else 0
        _set_camera(context, bpy.data.objects[names[(i + self.step) % len(names)]])
        return {"FINISHED"}


class VENUE_OT_haze(bpy.types.Operator):
    bl_idname = "venue.haze"
    bl_label = "Haze on / off"
    bl_description = "Toggle the haze, keeping the amount you last set"

    def execute(self, context):
        scene = context.scene
        if scene.get("haze", 0.0) > 0:
            scene["haze_last"] = scene["haze"]
            scene["haze"] = 0.0
        else:
            scene["haze"] = scene.get("haze_last", 1.0)
        _redraw()
        return {"FINISHED"}


class VENUE_OT_help(bpy.types.Operator):
    bl_idname = "venue.help"
    bl_label = "Controls"
    bl_description = "Show or hide the list of controls in the viewport"

    def execute(self, context):
        context.scene["show_help"] = not context.scene.get("show_help", True)
        _redraw()
        return {"FINISHED"}


class VENUE_OT_quality(bpy.types.Operator):
    bl_idname = "venue.quality"
    bl_label = "Quality"
    bl_description = "Laptop trades viewport quality for frame rate; Full is for mains power"
    name: bpy.props.StringProperty()

    def execute(self, context):
        apply_quality(self.name)
        _redraw()
        return {"FINISHED"}


class VENUE_PT_panel(bpy.types.Panel):
    bl_label = "Venue previz"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Venue"

    def draw(self, context):
        lay = self.layout
        row = lay.row(align=True)
        row.scale_y = 1.4
        row.operator("venue.live", text="Stop live" if S.live else "Go live",
                     icon="PAUSE" if S.live else "PLAY", depress=S.live)
        row.operator("venue.chase", text="Chase", icon="LIGHT_SPOT", depress=S.chase)

        box = lay.box()
        col = box.column(align=True)
        if S.live:
            if S.sock_error:
                col.label(text=f"Art-Net: {S.sock_error}", icon="ERROR")
            elif S.pps:
                col.label(text=f"Art-Net: {S.pps:.0f} pkt/s from {S.last_sender}", icon="CHECKMARK")
            else:
                col.label(text="Art-Net: waiting on :6454", icon="TIME")
            if S.screen_fps:
                col.label(text=f"Screen: {S.screen_fps:.0f} fps from bridge", icon="CHECKMARK")
            else:
                col.label(text="Screen: test card (bridge not running)", icon="TIME")
        else:
            col.label(text="Idle", icon="RADIOBUT_OFF")

        lay.operator("venue.help", icon="QUESTION",
                     text="Hide controls" if context.scene.get("show_help", True)
                     else "Show controls (opt K)",
                     depress=context.scene.get("show_help", True))

        row = lay.row(align=True)
        row.label(text="Quality")
        cur = str(context.scene.get("quality", "FULL"))
        for q in ("LAPTOP", "FULL"):
            op = row.operator("venue.quality", text=q.capitalize(), depress=cur == q)
            op.name = q

        if "haze" in context.scene:
            row = lay.row(align=True)
            row.prop(context.scene, '["haze"]', text="Haze", slider=True)
            row.operator("venue.haze", text="", icon="OUTLINER_OB_VOLUME",
                         depress=context.scene["haze"] > 0)

        if S.live and S.universes:
            box = lay.box()
            box.label(text="DMX in (channel: value)")
            col = box.column(align=True)
            for uni in sorted(S.universes)[:2]:
                data = S.universes[uni]
                active = [(i + 1, v) for i, v in enumerate(data[:64]) if v]
                col.label(text=f"universe {uni}: " +
                          (", ".join(f"{c}:{v}" for c, v in active[:10]) or "all zero"))
                if len(active) > 10:
                    col.label(text=f"    ... and {len(active) - 10} more channels")

        lay.label(text="Cameras  (alt 1-6, alt left/right)")
        grid = lay.grid_flow(columns=2, align=True)
        for i, name in enumerate(_camera_names()):
            ob = bpy.data.objects.get(name)
            op = grid.operator("venue.camera",
                               text=f"{i + 1}  " + name.replace("CAM_", "").replace("_", " "),
                               depress=context.scene.camera == ob)
            op.name = name
            op.index = -1

        if S.preview_name and S.pps < 1:
            lay.label(text=f"Look: {S.preview_name}", icon="LIGHT_DATA")
        if S.rig_error:
            lay.label(text=S.rig_error, icon="ERROR")
        else:
            lay.label(text=f"Rig: {S.rig_count} fixtures from rig.json", icon="FILE_REFRESH")

        lay.label(text="Pars (name / address / level)")
        col = lay.column(align=True)
        for ob in sorted((o for o in _fixtures() if o.get("in_rig", True)), key=lambda o: o.name):
            r = col.row(align=True)
            r.label(text=ob.name.replace("PAR_", "par ").replace("BAR_", "bar "))
            r.prop(ob, '["dmx_address"]', text="")
            r.prop(ob, '["dim"]', text="")


CLASSES = (VENUE_OT_live, VENUE_OT_chase, VENUE_OT_camera, VENUE_OT_camera_cycle,
           VENUE_OT_haze, VENUE_OT_help, VENUE_OT_quality, VENUE_PT_panel)

# alt + key shortcuts, live only while the file is open (nothing global changes)
# Both the number row and the numpad names: with Preferences -> Input ->
# Emulate Numpad on, Blender rewrites number-row keys to numpad ones before
# shortcuts are matched, so binding only "ONE" would never fire.
KEYMAP = [
    ("venue.camera", "ONE", {"index": 0}),
    ("venue.camera", "TWO", {"index": 1}),
    ("venue.camera", "THREE", {"index": 2}),
    ("venue.camera", "FOUR", {"index": 3}),
    ("venue.camera", "FIVE", {"index": 4}),
    ("venue.camera", "SIX", {"index": 5}),
    ("venue.camera", "NUMPAD_1", {"index": 0}),
    ("venue.camera", "NUMPAD_2", {"index": 1}),
    ("venue.camera", "NUMPAD_3", {"index": 2}),
    ("venue.camera", "NUMPAD_4", {"index": 3}),
    ("venue.camera", "NUMPAD_5", {"index": 4}),
    ("venue.camera", "NUMPAD_6", {"index": 5}),
    ("venue.camera_cycle", "RIGHT_ARROW", {"step": 1}),
    ("venue.camera_cycle", "LEFT_ARROW", {"step": -1}),
    ("venue.haze", "H", {}),
    ("venue.help", "K", {}),
    ("venue.live", "L", {}),
    ("venue.chase", "C", {}),
]
_keymap_items = []


def _register_keymap():
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    for idname, key, props in KEYMAP:
        kmi = km.keymap_items.new(idname, key, "PRESS", alt=True)
        for k, v in props.items():
            setattr(kmi.properties, k, v)
        _keymap_items.append((km, kmi))


def _unregister_keymap():
    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymap_items.clear()


def _first_view():
    """Put every 3D viewport in camera view on the scene's camera."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space.region_3d:
                space.region_3d.view_perspective = "CAMERA"
            space.shading.type = "MATERIAL"
            space.shading.use_scene_lights = True
            space.shading.use_scene_world = True
            # fit the camera frame to the viewport, so it isn't a small rectangle
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region:
                try:
                    with bpy.context.temp_override(window=win, area=area, region=region):
                        bpy.ops.view3d.view_center_camera()
                except Exception:
                    pass
                # the fit can drop the view out of camera view; put it back
                if space.region_3d:
                    space.region_3d.view_perspective = "CAMERA"
            area.tag_redraw()
    return None


def register():
    apply_quality()
    _help_enable(True)
    bpy.app.timers.register(_first_view, first_interval=0.5)
    _unregister_keymap()
    for c in CLASSES:
        try:
            bpy.utils.register_class(c)
        except ValueError:          # already registered (script re-run)
            bpy.utils.unregister_class(c)
            bpy.utils.register_class(c)
    _register_keymap()


def unregister():
    S.live = S.chase = False
    _help_enable(False)
    _unregister_keymap()
    _close_socket()
    _close_screen()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
