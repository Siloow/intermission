"""Where the show lives.

One folder holds everything that *is* the show and travels between the two of
us: the plan files, the Library's media, the bounces, Arena's composition names
and the Host's saved projects. That folder sits in a shared Dropbox folder. The
tools in this repo are code only, and find it through a one-line file next to
them:

    .show                     the folder's path on this Mac (differs per Mac, so not in git)

or $INTERMISSION_SHOW, which wins when set. The launchers ask the first time.
By hand:

    python3 showfolder.py                       where is it
    python3 showfolder.py /path/to/Show         use this folder
    python3 showfolder.py --init /path/to/Show  lay out a new one, with the defaults, and use it

The folder:

    show.json cues.json rig.json looks.json osc_map.json library.json
    composition.json          Resolume's composition as last seen (names only)
    audio/                    the bounces, and .peaks/ with their waveforms
    library/                  the Library's media, .thumbs/ inside
    light-looks/              looks rendered as band stills, for the lights layer
    projects/                 saved versions of the plan (the Host's save / load)

What stays next to the code: fixtures.json (the fixture profiles), the light-loop
presets in content/, and .live/ (this Mac's runtime scratch).
"""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
POINTER = os.path.join(HERE, ".show")
DEFAULTS = os.path.join(HERE, "defaults")
PLAN_FILES = ("show.json", "cues.json", "rig.json", "looks.json", "osc_map.json", "library.json")
SUBDIRS = ("audio", os.path.join("library", ".thumbs"), "light-looks", "projects")
_root = None


def _clean(p):
    p = (p or "").strip().replace("\\ ", " ")      # a path dragged into Terminal escapes its spaces
    return os.path.abspath(os.path.expanduser(p)) if p else None


def configured():
    """The path as set on this Mac, or None: $INTERMISSION_SHOW, else .show."""
    p = os.environ.get("INTERMISSION_SHOW", "")
    if not p.strip():
        try:
            p = open(POINTER).read()
        except OSError:
            p = ""
    return _clean(p)


def find():
    """The show folder, or None when it isn't set up (or not there) on this Mac."""
    p = configured()
    return p if p and os.path.isdir(p) else None


def root():
    """The show folder. Tools call this at import, so a missing one stops them
    early, with the fix, rather than half way through."""
    global _root
    if _root is None:
        _root = find()
        if _root is None:
            have = configured()
            why = f"the show folder is set to {have}, which isn't there" if have \
                  else "no show folder set on this Mac yet"
            sys.exit(f"[show] {why}.\n"
                     f"       Double-click Test.command to pick it, or: python3 showfolder.py /path/to/the/show")
    return _root


def path(*parts):
    return os.path.join(root(), *parts)


def content_dir(d):
    """A lane's folder from osc_map.json: absolute as is, content/… next to the
    code (the light-loop presets), anything else inside the show folder."""
    if not d:
        return None
    if os.path.isabs(d):
        return d
    if d.startswith("content/") or d == "content":
        return os.path.join(HERE, d)
    return path(d)


# ------------------------------------------------------------------ set up --
def use(p):
    """Point this Mac at an existing show folder."""
    p = _clean(p)
    if not p or not os.path.isdir(p):
        sys.exit(f"[show] no folder at {p}")
    open(POINTER, "w").write(p + "\n")
    print(f"[show] this Mac uses {p}")
    return p


def init(p):
    """Lay out a show folder (an existing one is completed, never overwritten) and
    point this Mac at it. Missing plan files come from defaults/: the rig for the
    hall, the lanes and looks. show.json comes from sync_show.py, cues from the
    timeline, the Library's list from its first add."""
    p = _clean(p)
    if not p:
        sys.exit("[show] give the folder's path")
    os.makedirs(p, exist_ok=True)
    for d in SUBDIRS:
        os.makedirs(os.path.join(p, d), exist_ok=True)
    seeded = []
    for f in sorted(os.listdir(DEFAULTS)) if os.path.isdir(DEFAULTS) else []:
        if f.endswith(".json") and not os.path.exists(os.path.join(p, f)):
            shutil.copyfile(os.path.join(DEFAULTS, f), os.path.join(p, f))
            seeded.append(f)
    if seeded:
        print(f"[show] started {', '.join(seeded)} from defaults/")
    return use(p)


def main(argv):
    if not argv:
        p = configured()
        if not p:
            print("[show] no show folder set on this Mac. python3 showfolder.py /path/to/the/show")
            return 1
        print(f"{p}" + ("" if os.path.isdir(p) else "   (not there!)"))
        return 0 if os.path.isdir(p) else 1
    if argv[0] == "--init":
        init(" ".join(argv[1:]))
    else:
        use(" ".join(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
