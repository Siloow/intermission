"""Make Blender's navigation work on a MacBook trackpad, with no numpad.

    /Applications/Blender.app/Contents/MacOS/Blender -b -P setup_input.py
    /Applications/Blender.app/Contents/MacOS/Blender -b -P setup_input.py -- --revert

This changes Blender's own Preferences, so it applies to every file, not just
the previz. The previous values are saved to .input_backup.json, and --revert
puts them back. You can also change any of it by hand in
Preferences -> Input, or undo everything with Preferences -> Load Factory Input
Settings (that drops other input tweaks too).

  Emulate Numpad       the number row does camera views: 0 = camera, 1 = front,
                       7 = top. The previz also has alt 1..6 for its own cameras.
  Emulate 3 Button     option + drag orbits, which is the trackpad stand-in for
                       a middle mouse button. Shift + option + drag pans.
  Zoom to Mouse        zooming goes toward the pointer instead of the centre
"""
import bpy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, ".input_backup.json")
WANT = {
    "use_emulate_numpad": True,
    "use_mouse_emulate_3_button": True,
    "mouse_emulate_3_button_modifier": "ALT",
    "use_zoom_to_mouse": True,
}
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def main():
    inp = bpy.context.preferences.inputs
    if "--revert" in ARGS:
        if not os.path.exists(BACKUP):
            print(f"[input] nothing to revert: no {BACKUP}")
            return
        old = json.load(open(BACKUP))
        for k, v in old.items():
            setattr(inp, k, v)
        print("[input] restored:", ", ".join(f"{k}={v}" for k, v in old.items()))
    else:
        if not os.path.exists(BACKUP):
            json.dump({k: getattr(inp, k) for k in WANT}, open(BACKUP, "w"), indent=2)
        for k, v in WANT.items():
            setattr(inp, k, v)
        print("[input] set:", ", ".join(f"{k}={v}" for k, v in WANT.items()))
        print(f"[input] previous values saved to {BACKUP} (--revert to put them back)")
    bpy.ops.wm.save_userpref()


main()
