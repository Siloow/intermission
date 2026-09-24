"""Build the Intermission venue previz: cinema hall, screen, 6 RGBW floor pars.

    blender -b -P build_venue.py            # -> venue.blend next to this file

Everything is generated from the CONFIG block below, so when real measurements
come in, change a number and rebuild. Nothing in venue.blend is hand-made; do
hand work in a copy or it will be overwritten.

Coordinates, in metres:
    origin  = the floor where the performer sits (stage floor, z = 0)
    +X      = across the room, stage right -> stage left as seen from the seats
    +Y      = from the screen toward the audience
    +Z      = up

The pars are driven the same way as the real ones: each PAR_nn empty carries
custom properties r g b w dim (0-255), and drivers turn those into light colour
and intensity. The live runtime (venue_live.py, embedded in the .blend) writes
those properties from incoming Art-Net, so Blender shows what Resolume sends.
"""
import bpy, json, math, os
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "venue.blend")
RIG = os.path.join(HERE, "rig.json")
FIXTURES = os.path.join(HERE, "fixtures.json")

# ---------------------------------------------------------------- CONFIG ----
# Room. Screen width is MEASURED; the rest is read off content/cinerama-full.MOV
# and still worth a tape measure.
ROOM_WIDTH = 15.0              # estimate: the screen plus ~1.7 m of wall each side
ROOM_HEIGHT = 8.5              # estimate: ~1.2 m of wall above the screen
ROOM_DEPTH = 20.0              # estimate: the stage plus ~14 rows plus the booth

# Screen. 11.5 m measured by hand; the height comes from the video, where the
# screen reads 1.93:1 in two frontal frames - near the 1.85:1 flat format.
SCREEN_WIDTH = 11.5
SCREEN_HEIGHT = 6.0
SCREEN_BOTTOM = 1.3            # bottom edge above the stage floor
MASKING = 0.6                  # black border around the screen
SCREEN_ASPECT_CONTENT = 16 / 9 # the content is letterboxed onto the screen

# Performer and stage strip
PERFORMER_FROM_SCREEN = 1.8    # screen plane -> where you sit
SCREEN_TO_FIRST_ROW = 4.0
STAGE_DEPTH = 3.0              # carpeted strip in front of the screen
STAGE_STEP = 0.35              # drop from the strip down to the seating floor

# Seating (a stepped block per row, not individual chairs)
ROW_PITCH = 0.95
ROW_RISE = 0.18
SEAT_WIDTH = ROOM_WIDTH - 3.0  # leaves side aisles
SEAT_HEIGHT = 0.45
EYE_HEIGHT = 1.15              # seated eye height above the row floor

# Pars. The positions live in rig.json, which the floor-plan editor writes and
# the previz follows live; the values here only seed that file the first time.
MAX_PARS = 16                  # par slots the scene holds; extras stay hidden
MAX_BARS = 6                   # bar slots
PAR_RADIUS = 2.2
PAR_ANGLES = [-150, -120, -90, -50, 50, 90, 120, 150]   # 8 pars, 4 per side
BAR_POSITIONS = [             # 4 bars across the stage, laid on the floor, aiming up
    {"x": -4.2, "y": -0.9, "rot_deg": 0},
    {"x": -1.6, "y": -0.9, "rot_deg": 0},
    {"x": 1.6, "y": -0.9, "rot_deg": 0},
    {"x": 4.2, "y": -0.9, "rot_deg": 0},
]
BAR_TILT = 80.0                # bars aim nearly straight up the screen
BAR_LIGHT_EVERY = 3            # one spot light per N pixels; the rest is emissive only
PAR_TILT = 70.0                # beam elevation above horizontal
PAR_PAN_OUT = 1.0              # 1 = beams lean outward away from you, 0 = straight up
PAR_BEAM = 25.0                # beam angle, deg (typical LED par lens)
PAR_WATTS = 1500.0             # Blender watts at dim=255, full white
WHITE_TINT = (1.0, 0.92, 0.82) # colour of the W LED
DMX_UNIVERSE = 0               # Art-Net universe (Resolume's first Lumiverse = 0)
DMX_START = 1                  # address of PAR_01
# Resolume drives the pars by pixel mapping: one 1x1 RGBW fixture per par, four
# channels, brightness carried in the colour. Set the real pars to a 4-channel
# RGBW mode to match. If you use a mode with its own dimmer, add "dim" to the
# layout and raise the footprint; the previz follows whatever is set here.
DMX_FOOTPRINT = 4              # channels per par
DMX_LAYOUT = ("r", "g", "b", "w")  # channel order inside the footprint

# Haze - is a haze machine allowed in the cinema? Toggle on the Scene: "haze"
HAZE_DENSITY = 0.035
HAZE_TOP = 8.0                 # haze fills the hall up to here

# Screen brightness as seen by the room (emission strength)
SCREEN_NITS = 3.0
# ----------------------------------------------------------------------------

SCREEN_Y = -PERFORMER_FROM_SCREEN
FIRST_ROW_Y = SCREEN_Y + SCREEN_TO_FIRST_ROW
STAGE_FRONT_Y = SCREEN_Y + STAGE_DEPTH
BACK_Y = SCREEN_Y + ROOM_DEPTH
AUD_FLOOR = -STAGE_STEP
SCREEN_CENTRE = Vector((0, SCREEN_Y, SCREEN_BOTTOM + SCREEN_HEIGHT / 2))


def load_profiles():
    return json.load(open(FIXTURES))["profiles"]


def default_rig():
    """The starting rig, used only when rig.json does not exist yet:
    8 pars in a semicircle and 4 bars across the stage."""
    profiles = load_profiles()
    par_p, bar_p = profiles["gm-par-rgbw-7x10"], profiles["showtec-pixelbar-18-q4"]
    par_fp = par_p["modes"][par_p["default_mode"]]["footprint"]
    bar_fp = bar_p["modes"][bar_p["default_mode"]]["footprint"]

    fixtures, addr = [], DMX_START
    for i, ang in enumerate(PAR_ANGLES):
        a = math.radians(ang)
        fixtures.append({
            "name": f"PAR_{i + 1:02d}", "profile": "gm-par-rgbw-7x10",
            "mode": par_p["default_mode"], "address": addr,
            "x": round(math.sin(a) * PAR_RADIUS, 3),
            "y": round(math.cos(a) * PAR_RADIUS, 3),
            "z": 0.18,
            "aim_deg": round(ang, 1),      # direction the beam leans, 0 = toward the audience
            "tilt_deg": PAR_TILT,          # elevation above horizontal, 90 = straight up
            "beam_deg": par_p["beam_deg"],
        })
        addr += par_fp
    for i, b in enumerate(BAR_POSITIONS):
        fixtures.append({
            "name": f"BAR_{i + 1:02d}", "profile": "showtec-pixelbar-18-q4",
            "mode": bar_p["default_mode"], "address": addr,
            "x": b["x"], "y": b["y"], "z": 0.07,
            "rot_deg": b["rot_deg"],       # the bar's long axis, 0 = across the room
            "aim_deg": 180.0,              # leaning toward the screen
            "tilt_deg": BAR_TILT,
            "beam_deg": bar_p["beam_deg"],
        })
        addr += bar_fp
    return {"units": "metres",
            "origin": "where the performer sits; +x stage left, +y toward the audience",
            "universe": DMX_UNIVERSE,
            "layout": ",".join(DMX_LAYOUT),
            "venue": venue_block(),
            "fixtures": fixtures}


def venue_block():
    """Room numbers the floor-plan editor draws to scale. Written on every
    build, so the plan follows the CONFIG above."""
    return {"screen_width": SCREEN_WIDTH,
            "screen_height": SCREEN_HEIGHT,
            "screen_bottom": SCREEN_BOTTOM,
            "screen_from_performer": PERFORMER_FROM_SCREEN,
            "first_row_from_screen": SCREEN_TO_FIRST_ROW,
            "room_width": ROOM_WIDTH,
            "room_height": ROOM_HEIGHT,
            "room_depth": ROOM_DEPTH}


def load_rig():
    if os.path.exists(RIG):
        try:
            rig = json.load(open(RIG))
            if rig.get("fixtures"):
                rig["venue"] = venue_block()     # keep the plan's room in step
                json.dump(rig, open(RIG, "w"), indent=2)
                return rig
        except (ValueError, OSError) as e:
            print(f"[venue] rig.json unreadable ({e}); using defaults")
    rig = default_rig()
    json.dump(rig, open(RIG, "w"), indent=2)
    print(f"[venue] wrote starting {RIG}")
    return rig


def aim_euler(x, y, aim_deg, tilt_deg):
    """Rotation for a fixture leaning toward aim_deg at tilt_deg above horizontal."""
    a, t = math.radians(aim_deg), math.radians(tilt_deg)
    d = Vector((math.sin(a) * math.cos(t), math.cos(a) * math.cos(t), math.sin(t)))
    if d.length < 1e-6:
        d = Vector((0, 0, 1))
    return d.normalized().to_track_quat("Z", "Y").to_euler()


# ------------------------------------------------------------- helpers ------
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def link(obj, coll):
    coll.objects.link(obj)
    return obj


def mat_basic(name, color, rough=0.9, emission=None, strength=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return m


def box(name, coll, lo, hi, mat):
    """Axis-aligned box from corner lo to corner hi."""
    lo, hi = Vector(lo), Vector(hi)
    size = hi - lo
    me = bpy.data.meshes.new(name)
    v = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    v = [(lo.x + a * size.x, lo.y + b * size.y, lo.z + c * size.z) for a, b, c in v]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    return link(ob, coll)


def plane_xz(name, coll, cx, y, cz, w, h, mat, facing=+1):
    """Vertical plane in XZ at depth y, normal toward +Y (facing=+1)."""
    me = bpy.data.meshes.new(name)
    x0, x1, z0, z1 = cx - w / 2, cx + w / 2, cz - h / 2, cz + h / 2
    me.from_pydata([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], [],
                   [(0, 1, 2, 3) if facing > 0 else (3, 2, 1, 0)])
    me.uv_layers.new(name="UVMap")
    uv = me.uv_layers[0].data
    for i, co in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)] if facing > 0 else [(0, 1), (1, 1), (1, 0), (0, 0)]):
        uv[i].uv = co
    me.materials.append(mat)
    return link(bpy.data.objects.new(name, me), coll)


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def add_driver(id_owner, path, index, expr, vars_):
    fc = id_owner.driver_add(path, index) if index is not None else id_owner.driver_add(path)
    drv = fc.driver
    drv.type = "SCRIPTED"
    for name, target_id, dpath in vars_:
        v = drv.variables.new()
        v.name = name
        v.type = "SINGLE_PROP"
        v.targets[0].id_type = "OBJECT" if isinstance(target_id, bpy.types.Object) else "SCENE"
        v.targets[0].id = target_id
        v.targets[0].data_path = dpath
    drv.expression = expr  # simple expression: evaluates without "Auto Run Scripts"
    return fc


# ------------------------------------------------------------- content ------
def test_card(w=1920, h=1080):
    """A grid test card so screen proportions and letterboxing are readable."""
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 4), np.float32)
    u, v = x / w, y / h
    img[..., 0] = 0.15 + 0.35 * u
    img[..., 1] = 0.12 + 0.25 * v
    img[..., 2] = 0.35 + 0.3 * (1 - u)
    grid = ((x % (w // 16)) < 3) | ((y % (h // 9)) < 3)
    img[grid, :3] = 0.9
    cx, cy = w / 2, h / 2
    r = np.hypot(x - cx, y - cy)
    img[np.abs(r - h * 0.4) < 4, :3] = 1.0
    img[(np.abs(x - cx) < 3) | (np.abs(y - cy) < 3), :3] = 1.0
    img[..., 3] = 1
    im = bpy.data.images.new("SCREEN_TESTCARD", w, h, alpha=False)
    im.pixels.foreach_set(img[::-1].ravel())  # Blender rows run bottom-up
    im.pack()
    return im


def build_screen(coll):
    live = bpy.data.images.new("SCREEN_LIVE", 960, 540, alpha=False)
    live.generated_color = (0, 0, 0, 1)
    card = test_card()

    m = bpy.data.materials.new("screen")
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.name = "SCREEN_TEX"
    tex.image = card
    tex.extension = "CLIP"  # outside the 16:9 content area -> black (letterbox)
    # Map the plane's UV into the content's aspect so content isn't stretched.
    mapping = nt.nodes.new("ShaderNodeMapping")
    uvn = nt.nodes.new("ShaderNodeTexCoord")
    screen_aspect = SCREEN_WIDTH / SCREEN_HEIGHT
    if screen_aspect > SCREEN_ASPECT_CONTENT:   # pillarbox
        sx = screen_aspect / SCREEN_ASPECT_CONTENT
        mapping.inputs["Scale"].default_value = (sx, 1, 1)
        mapping.inputs["Location"].default_value = (-(sx - 1) / 2, 0, 0)
    else:                                         # letterbox
        sy = SCREEN_ASPECT_CONTENT / screen_aspect
        mapping.inputs["Scale"].default_value = (1, sy, 1)
        mapping.inputs["Location"].default_value = (0, -(sy - 1) / 2, 0)
    nt.links.new(uvn.outputs["UV"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    emit.inputs["Strength"].default_value = SCREEN_NITS
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

    screen = plane_xz("SCREEN", coll, 0, SCREEN_Y + 0.02, SCREEN_CENTRE.z,
                      SCREEN_WIDTH, SCREEN_HEIGHT, m)

    black = mat_basic("masking", (0.005, 0.005, 0.005), rough=1.0)
    t, b = SCREEN_BOTTOM + SCREEN_HEIGHT, SCREEN_BOTTOM
    hw = SCREEN_WIDTH / 2
    y0, y1 = SCREEN_Y, SCREEN_Y + 0.05
    box("MASK_top", coll, (-hw - MASKING, y0, t), (hw + MASKING, y1, t + MASKING), black)
    box("MASK_bottom", coll, (-hw - MASKING, y0, b - MASKING), (hw + MASKING, y1, b), black)
    box("MASK_left", coll, (-hw - MASKING, y0, b), (-hw, y1, t), black)
    box("MASK_right", coll, (hw, y0, b), (hw + MASKING, y1, t), black)

    # The emission plane lights the room in Cycles. EEVEE's viewport is weaker
    # at that, so an area light in front of the screen stands in for the spill.
    # venue_live.py sets its colour to the average of the live frame.
    sd = bpy.data.lights.new("SCREEN_SPILL", "AREA")
    sd.shape = "RECTANGLE"
    sd.size, sd.size_y = SCREEN_WIDTH, SCREEN_HEIGHT
    sd.energy = 2500
    sd.color = (0.55, 0.5, 0.65)
    spill = link(bpy.data.objects.new("SCREEN_SPILL", sd), coll)
    spill.location = (0, SCREEN_Y + 0.15, SCREEN_CENTRE.z)
    spill.rotation_euler = (math.radians(-90), 0, 0)  # face +Y, toward the room
    return screen


def build_room(coll):
    wall = mat_basic("wall", (0.035, 0.035, 0.04), rough=0.95)
    carpet = mat_basic("stage_carpet", (0.02, 0.03, 0.05), rough=1.0)
    floor = mat_basic("floor", (0.06, 0.055, 0.05), rough=0.9)
    seat = mat_basic("seats", (0.09, 0.02, 0.025), rough=0.8)
    hw = ROOM_WIDTH / 2
    th = 0.2

    # stage strip at z=0, audience floor a step lower
    box("STAGE", coll, (-hw, SCREEN_Y, -STAGE_STEP), (hw, STAGE_FRONT_Y, 0), carpet)
    box("FLOOR", coll, (-hw, STAGE_FRONT_Y, AUD_FLOOR - th), (hw, BACK_Y, AUD_FLOOR), floor)
    box("WALL_screen", coll, (-hw, SCREEN_Y - th, AUD_FLOOR), (hw, SCREEN_Y, ROOM_HEIGHT), wall)
    box("WALL_back", coll, (-hw, BACK_Y, AUD_FLOOR), (hw, BACK_Y + th, ROOM_HEIGHT), wall)
    box("WALL_left", coll, (-hw - th, SCREEN_Y, AUD_FLOOR), (-hw, BACK_Y, ROOM_HEIGHT), wall)
    box("WALL_right", coll, (hw, SCREEN_Y, AUD_FLOOR), (hw + th, BACK_Y, ROOM_HEIGHT), wall)
    box("CEILING", coll, (-hw, SCREEN_Y, ROOM_HEIGHT), (hw, BACK_Y, ROOM_HEIGHT + th), wall)

    # raked seating: each row is a riser + a seat block
    rows = []
    y, z, i = FIRST_ROW_Y, AUD_FLOOR, 0
    while y + ROW_PITCH < BACK_Y - 1.0:
        box(f"RISER_{i:02d}", coll, (-hw, y, AUD_FLOOR), (hw, y + ROW_PITCH, z), floor) if z > AUD_FLOOR else None
        box(f"ROW_{i:02d}", coll, (-SEAT_WIDTH / 2, y + 0.35, z),
            (SEAT_WIDTH / 2, y + 0.85, z + SEAT_HEIGHT), seat)
        rows.append((y + 0.6, z))
        y += ROW_PITCH
        z += ROW_RISE
        i += 1
    return rows


def build_performer(coll):
    m = mat_basic("performer", (0.25, 0.25, 0.27), rough=0.7)
    metal = mat_basic("chair", (0.1, 0.1, 0.1), rough=0.4)
    box("CHAIR", coll, (-0.22, -0.2, 0.0), (0.22, 0.2, 0.46), metal)
    box("TABLE", coll, (-0.45, 0.35, 0.0), (0.45, 0.85, 0.75), metal)
    box("LAPTOP", coll, (-0.17, 0.45, 0.75), (0.17, 0.7, 0.77), metal)
    # seated figure: torso box + head sphere, enough to judge silhouette & lighting
    box("PERFORMER_torso", coll, (-0.2, -0.12, 0.46), (0.2, 0.12, 1.15), m)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, 1.3))
    head = bpy.context.active_object
    head.name = "PERFORMER_head"
    head.data.materials.append(m)
    for c in head.users_collection:
        c.objects.unlink(head)
    coll.objects.link(head)


def emissive(name):
    """A material whose colour and strength are driven from custom properties."""
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m, em


def channel_drivers(owner_obj, light_data, emission_node, watts, glow=40):
    """r g b w dim (0-255) on owner_obj -> light colour and power, and lens glow."""
    vars_ = [(ch, owner_obj, f'["{ch}"]') for ch in ("r", "g", "b", "w", "dim")]
    wr, wg, wb = WHITE_TINT
    exprs = [f"min(1.0, (r + w * {wr}) / 255)",
             f"min(1.0, (g + w * {wg}) / 255)",
             f"min(1.0, (b + w * {wb}) / 255)"]
    for k, e in enumerate(exprs):
        if light_data:
            add_driver(light_data, "color", k, e, vars_)
        if emission_node:
            add_driver(emission_node.inputs["Color"], "default_value", k, e, vars_)
    if light_data:
        add_driver(light_data, "energy", None, f"dim / 255 * {watts}", vars_)
    if emission_node:
        add_driver(emission_node.inputs["Strength"], "default_value", None,
                   f"dim / 255 * {glow}", vars_)


def dmx_props(ob, address, universe, layout, in_rig, profile=None, mode=None, pixel=None):
    ob["dmx_universe"] = int(universe)
    ob["dmx_address"] = int(address)
    ob["dmx_layout"] = layout
    ob["in_rig"] = bool(in_rig)
    if profile:
        ob["profile"] = profile
    if mode:
        ob["mode"] = mode
    if pixel is not None:
        ob["pixel"] = int(pixel)
    for ch in ("r", "g", "b", "w", "dim"):
        # neither the pars' 4ch nor the bars' 72ch mode has a dimmer channel, so
        # brightness rides in the colour: dim starts at full and stays there
        ob[ch] = 255 if ch == "dim" else 0
        ob.id_properties_ui(ch).update(min=0, max=255, soft_min=0, soft_max=255)


def build_par(coll, name, f, rig_data, profile, body_mat):
    """A can with seven emitters and one beam - the GM Light RGBW par."""
    bod = profile["body"]
    fp = profile["modes"][f.get("mode", profile["default_mode"])]["footprint"] if f else 4
    rig = link(bpy.data.objects.new(name, None), coll)
    rig.empty_display_type = "SINGLE_ARROW"
    rig.empty_display_size = 0.35
    rig.location = (f["x"], f["y"], f.get("z", 0.18)) if f else (0, 0, 0.18)
    rig.rotation_euler = aim_euler(rig.location.x, rig.location.y,
                                   f["aim_deg"] if f else 0.0,
                                   f["tilt_deg"] if f else PAR_TILT)
    dmx_props(rig, f["address"] if f else 1, rig_data.get("universe", DMX_UNIVERSE),
              ",".join(DMX_LAYOUT), bool(f),
              f.get("profile") if f else None, f.get("mode") if f else None)
    rig["kind"] = "par"
    parts = [rig]

    bpy.ops.mesh.primitive_cylinder_add(radius=bod["diameter"] / 2, depth=bod["depth"], vertices=28)
    can = bpy.context.active_object
    can.name = f"{name}_body"
    can.data.materials.append(body_mat)
    for c in can.users_collection:
        c.objects.unlink(can)
    coll.objects.link(can)
    can.parent = rig
    parts.append(can)

    # the seven LEDs, in a ring of six around one
    lens_m, em = emissive(f"{name}_lens")
    for k in range(profile["leds"]):
        r = 0 if k == 0 else bod["diameter"] * 0.27
        a = 2 * math.pi * (k - 1) / max(1, profile["leds"] - 1)
        bpy.ops.mesh.primitive_circle_add(radius=bod["diameter"] * 0.12, vertices=16,
                                          fill_type="NGON")
        led = bpy.context.active_object
        led.name = f"{name}_led{k + 1}"
        led.data.materials.append(lens_m)
        for c in led.users_collection:
            c.objects.unlink(led)
        coll.objects.link(led)
        led.parent = rig
        led.location = (math.cos(a) * r, math.sin(a) * r, bod["depth"] / 2 + 0.002)
        parts.append(led)

    ld = bpy.data.lights.new(name, "SPOT")
    ld.spot_size = math.radians(f["beam_deg"] if f else profile["beam_deg"])
    ld.spot_blend = 0.35
    ld.shadow_soft_size = 0.05
    ld.energy = 0
    beam = link(bpy.data.objects.new(f"{name}_beam", ld), coll)
    beam.parent = rig
    beam.location = (0, 0, bod["depth"] / 2)
    beam.rotation_euler = (math.pi, 0, 0)        # spots shine along -Z; flip to the rig's +Z
    parts.append(beam)

    channel_drivers(rig, ld, em, PAR_WATTS)
    return rig, parts, fp


def build_bar(coll, name, f, rig_data, profile, body_mat):
    """The Showtec Pixel Bar: one body, 18 pixels, each its own RGBW fixture."""
    bod = profile["body"]
    pixels = profile["pixels"]
    mode = f.get("mode", profile["default_mode"]) if f else profile["default_mode"]
    per_pixel = "per_pixel" in profile["modes"][mode]
    fp = profile["modes"][mode]["footprint"]

    rig = link(bpy.data.objects.new(name, None), coll)
    rig.empty_display_type = "SINGLE_ARROW"
    rig.empty_display_size = 0.35
    rig.location = (f["x"], f["y"], f.get("z", 0.07)) if f else (0, 0, 0.07)
    rig.rotation_euler = aim_euler(rig.location.x, rig.location.y,
                                   f["aim_deg"] if f else 180.0,
                                   f["tilt_deg"] if f else BAR_TILT)
    dmx_props(rig, f["address"] if f else 1, rig_data.get("universe", DMX_UNIVERSE),
              ",".join(DMX_LAYOUT), bool(f),
              f.get("profile") if f else None, mode)
    rig["kind"] = "bar"
    rig["pixels"] = pixels
    rig["length"] = bod["length"]
    rig["rot_deg"] = float(f.get("rot_deg", 0)) if f else 0.0
    parts = [rig]

    spin = math.radians(rig["rot_deg"])          # the bar's long axis, around its own aim
    housing = box(f"{name}_body", coll,
                  (-bod["length"] / 2, -bod["width"] / 2, -bod["height"] / 2),
                  (bod["length"] / 2, bod["width"] / 2, bod["height"] / 2), body_mat)
    housing.parent = rig
    housing.rotation_euler = (0, 0, spin)
    parts.append(housing)

    step = bod["length"] / pixels
    for i in range(pixels):
        along = -bod["length"] / 2 + step * (i + 0.5)
        pm, em = emissive(f"{name}_px{i + 1:02d}")
        me = bpy.data.meshes.new(f"{name}_px{i + 1:02d}")
        hw, hh = step * 0.36, bod["width"] * 0.34
        me.from_pydata([(-hw, -hh, 0), (hw, -hh, 0), (hw, hh, 0), (-hw, hh, 0)], [], [(0, 1, 2, 3)])
        me.materials.append(pm)
        px = link(bpy.data.objects.new(f"{name}_px{i + 1:02d}", me), coll)
        px.parent = rig
        px.location = (math.cos(spin) * along, math.sin(spin) * along, bod["height"] / 2 + 0.002)
        px.rotation_euler = (0, 0, spin)
        parts.append(px)

        # every pixel is its own little fixture, addressed inside the bar's footprint
        addr = (f["address"] if f else 1) + (i * 4 if per_pixel else 0)
        dmx_props(px, addr, rig_data.get("universe", DMX_UNIVERSE), "r,g,b,w", bool(f),
                  f.get("profile") if f else None, mode, pixel=i + 1)
        px["kind"] = "pixel"
        px["of"] = name

        ld = None
        if i % BAR_LIGHT_EVERY == BAR_LIGHT_EVERY // 2:   # a beam every few pixels
            ld = bpy.data.lights.new(f"{name}_px{i + 1:02d}", "SPOT")
            ld.spot_size = math.radians(f["beam_deg"] if f else profile["beam_deg"])
            ld.spot_blend = 0.5
            ld.shadow_soft_size = 0.04
            ld.energy = 0
            beam = link(bpy.data.objects.new(f"{name}_beam{i + 1:02d}", ld), coll)
            beam.parent = px
            beam.location = (0, 0, 0.01)
            beam.rotation_euler = (math.pi, 0, 0)
            parts.append(beam)

        watts = PAR_WATTS * (profile["watts"] / 70.0) / pixels * BAR_LIGHT_EVERY
        channel_drivers(px, ld, em, watts, glow=25)
    return rig, parts, fp


def build_fixtures(coll, rig_data):
    """Build every slot the scene can hold; the ones the rig file doesn't use are
    hidden, so the editor can add and remove fixtures live without a rebuild."""
    profiles = load_profiles()
    body_mat = mat_basic("fixture_body", (0.02, 0.02, 0.02), rough=0.5)
    used = {f.get("name"): f for f in rig_data["fixtures"]}
    made = []

    def slot(name, kind, default_profile):
        f = used.get(name)
        prof_key = (f or {}).get("profile", default_profile)
        profile = profiles.get(prof_key, profiles[default_profile])
        builder = build_bar if profile["kind"] == "bar" else build_par
        rig, parts, _ = builder(coll, name, f, rig_data, profile, body_mat)
        if not f:
            for ob in parts:
                ob.hide_viewport = ob.hide_render = True
        made.append(rig)

    for i in range(MAX_PARS):
        slot(f"PAR_{i + 1:02d}", "par", "gm-par-rgbw-7x10")
    for i in range(MAX_BARS):
        slot(f"BAR_{i + 1:02d}", "bar", "showtec-pixelbar-18-q4")
    return made


def build_haze(coll):
    scene = bpy.context.scene
    scene["haze"] = 1.0
    ui = scene.id_properties_ui("haze")
    ui.update(min=0.0, max=3.0, soft_min=0, soft_max=2, description="Haze amount (0 = off)")
    m = bpy.data.materials.new("haze")
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1)
    vol.inputs["Anisotropy"].default_value = 0.3
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    add_driver(vol.inputs["Density"], "default_value", None, f"haze * {HAZE_DENSITY}",
               [("haze", scene, '["haze"]')])
    hw = ROOM_WIDTH / 2 - 0.05
    ob = box("HAZE", coll, (-hw, SCREEN_Y + 0.1, AUD_FLOOR), (hw, BACK_Y - 0.1, HAZE_TOP), m)
    ob.display_type = "BOUNDS"
    ob.hide_select = True
    return ob


def build_cameras(coll, rows):
    target = SCREEN_CENTRE + Vector((0, 0, -1.2))
    views = [
        ("CAM_front_row", rows[0], 0.0, 14),
        ("CAM_middle", rows[len(rows) // 2], 0.0, 35),
        ("CAM_back_row", rows[-1], 0.0, 40),
        ("CAM_side_seat", rows[len(rows) // 3], SEAT_WIDTH / 2 - 1.0, 30),
    ]
    cams = []
    for name, (ry, rz), x, lens in views:
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cd.clip_end = 200
        cam = link(bpy.data.objects.new(name, cd), coll)
        cam.location = (x, ry, rz + SEAT_HEIGHT + EYE_HEIGHT - 0.45)
        look_at(cam, target)
        cams.append(cam)
    # your own view: sitting at the laptop, looking at the screen
    cd = bpy.data.cameras.new("CAM_performer")
    cd.lens = 24
    cd.clip_end = 200
    me = link(bpy.data.objects.new("CAM_performer", cd), coll)
    me.location = (0, -0.25, 1.35)   # just in front of the head proxy
    look_at(me, SCREEN_CENTRE + Vector((0, 0, -1.0)))
    cams.append(me)

    # top-down plan, for placing pars
    cd = bpy.data.cameras.new("CAM_plan")
    cd.type = "ORTHO"
    cd.ortho_scale = 9
    plan = link(bpy.data.objects.new("CAM_plan", cd), coll)
    plan.location = (0, 0.5, ROOM_HEIGHT - 0.5)
    cams.append(plan)
    return cams


def setup_render(cam):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = eng
            break
        except TypeError:
            pass
    # Full quality by default; venue_live.py's Quality buttons can drop to
    # Laptop if another machine ever struggles.
    scene["quality"] = "FULL"
    ee = scene.eevee
    for attr, val in (("use_raytracing", True), ("volumetric_tile_size", "4"),
                      ("volumetric_samples", 64), ("use_volumetric_shadows", True),
                      ("shadow_resolution_scale", 1.0), ("taa_samples", 32),
                      ("use_volume_custom_range", True), ("volumetric_start", 0.3),
                      ("volumetric_end", 40.0), ("use_shadows", True)):
        if hasattr(ee, attr):
            try:
                setattr(ee, attr, val)
            except Exception:
                pass
    world = bpy.data.worlds.new("black")
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy" if "AgX - Punchy" in [
        i.identifier for i in scene.view_settings.bl_rna.properties["look"].enum_items] else "None"
    scene.render.fps = 30


def embed_live_runtime():
    path = os.path.join(HERE, "venue_live.py")
    txt = bpy.data.texts.new("venue_live.py")
    txt.from_string(open(path).read())
    txt.use_module = True  # registers on file open when Auto Run Scripts is allowed


def set_viewport(cam):
    """Material-preview shading looking through the front-row camera."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = "MATERIAL"
                        space.shading.use_scene_lights = True
                        space.shading.use_scene_world = True
                        space.region_3d.view_perspective = "CAMERA"


def main():
    reset()
    scene = bpy.context.scene
    scene.name = "Intermission venue"
    c_room = collection("ROOM")
    c_screen = collection("SCREEN")
    c_rig = collection("RIG")
    c_perf = collection("PERFORMER")
    c_cam = collection("CAMERAS")
    c_fx = collection("ATMOSPHERE")

    rig_data = load_rig()
    rows = build_room(c_room)
    build_screen(c_screen)
    build_performer(c_perf)
    pars = build_fixtures(c_rig, rig_data)
    build_haze(c_fx)
    cams = build_cameras(c_cam, rows)
    setup_render(cams[0])
    embed_live_runtime()
    set_viewport(cams[0])

    # a gentle default look so the scene isn't black before any DMX arrives
    for i, p in enumerate([p for p in pars if p.get("in_rig") and p.get("kind") == "par"]):
        p["r"], p["g"], p["b"], p["w"], p["dim"] = (255, 60, 20, 0, 160) if i % 2 else (40, 60, 255, 0, 160)

    scene["venue_config"] = {
        "room": [ROOM_WIDTH, ROOM_DEPTH, ROOM_HEIGHT],
        "screen": [SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_BOTTOM],
        "performer_from_screen": PERFORMER_FROM_SCREEN,
        "screen_to_first_row": SCREEN_TO_FIRST_ROW,
    }
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    active = [p for p in pars if p.get("in_rig")]
    kinds = {}
    for p in active:
        kinds[p.get("kind", "?")] = kinds.get(p.get("kind", "?"), 0) + 1
    print(f"[venue] wrote {OUT}: {len(rows)} seat rows, "
          + ", ".join(f"{n} {k}s" for k, n in sorted(kinds.items()))
          + f" ({len(pars) - len(active)} spare slots), addresses "
          + ", ".join(str(p["dmx_address"]) for p in active))


if __name__ == "__main__":
    main()
