"""Read the Ableton set and write show.json: the musical structure the visual
plan hangs on.

    python3 sync_show.py path/to/Set.als        # extract, and diff what moved
    python3 sync_show.py --example              # a placeholder show, no Live needed
    python3 sync_show.py --als-dir ~/Music      # find the newest .als under here
    python3 sync_show.py Set.als --backing      # also stitch the Backing track into audio/

Two tracks are read by name, if the set has them. "Tracklist" holds one clip per
song named "Song | 120 bpm | 72 bars | 4/4": the song's own tempo and metre go
into show.json as "info" (the set itself runs at one tempo). "Backing" holds the
bounces; --backing renders them into one file from bar 1 for the timeline.

Locators are the contract. Name a locator ">> Track name" to start a song, and
everything after it is a section of that song until the next ">>":

    >> Intermission        bar 1     song starts
    Build 1                bar 17
    Drop 1                 bar 33
    >> Afterglow           bar 129   next song

A locator starting with "## " marks a chapter (a group of songs, e.g.
"## 1 · before"). It is not a section: it only lands in show.json's "chapters"
list. Put it a bar before the chapter's first ">>", because of the next rule.

Live allows only one locator per position, so a song marker and its first
section cannot share a bar. Whatever plays between the song marker and the
first named section becomes a section called "Start", so the timeline has no
gaps and cues can anchor there.

Sections are stored in beats and bars, never in seconds, so the plan survives
the music changing underneath it. Re-run this whenever the set changes: it
prints what moved, what was renamed and what disappeared, which is the bit that
matters when the visuals are being built in parallel with the music.

Standard library only; it reads the .als directly (gzipped XML), so Live does
not have to be open.
"""
import argparse, datetime, glob, gzip, json, os, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "show.json")
SONG_PREFIX = ">>"
CHAPTER_PREFIX = "##"
TRACKLIST_TRACK = "Tracklist"     # per-song info clips: "Song | 120 bpm | 72 bars | 4/4"
BACKING_TRACK = "Backing"         # the bounces the set plays, for the timeline's audio


# ----------------------------------------------------------------- reading --
def val(node, tag, default=None):
    el = node.find(tag)
    return el.get("Value") if el is not None else default


def read_als(path):
    with gzip.open(path, "rb") as fh:
        root = ET.parse(fh).getroot()

    tempo = 120.0
    for t in root.iter("Tempo"):                     # master tempo, manual value
        v = val(t, "Manual")
        if v:
            tempo = float(v)
            break
    sig_num, sig_den = 4, 4
    for t in root.iter("TimeSignature"):
        n, d = val(t, "Numerator"), val(t, "Denominator")
        if n and d:
            sig_num, sig_den = int(n), int(d)
            break

    locators = []
    for loc in root.iter("Locator"):
        t, name = val(loc, "Time"), val(loc, "Name")
        if t is None:
            continue
        locators.append({"beat": float(t), "name": (name or "").strip()})
    locators.sort(key=lambda l: l["beat"])

    end = 0.0
    for tag in ("CurrentEnd", "CurrentStart"):
        for el in root.iter(tag):
            try:
                end = max(end, float(el.get("Value")))
            except (TypeError, ValueError):
                pass
    return {"tempo": tempo, "signature": [sig_num, sig_den], "locators": locators, "end_beat": end,
            "tracklist": read_tracklist(root), "backing": read_backing(root, tempo)}


def track_named(root, name):
    tracks = root.find("LiveSet/Tracks")
    for tr in (tracks if tracks is not None else []):
        if val(tr, "Name/EffectiveName", "").strip().lower() == name.lower():
            return tr
    return None


def read_tracklist(root):
    """Clips on the 'Tracklist' track, named 'Song | 120 bpm | 72 bars | 4/4': the
    song's own tempo and metre, which the set (one tempo) does not know."""
    tr, out = track_named(root, TRACKLIST_TRACK), []
    for c in (tr.iter("MidiClip") if tr is not None else []):
        parts = [p.strip() for p in (val(c, "Name") or "").split("|")]
        info = {"beat": float(c.get("Time")), "label": " | ".join(parts), "name": parts[0]}
        for p in parts[1:]:
            low = p.lower()
            if low.endswith("bpm"):
                info["bpm"] = p[:-3].strip()                 # keep "~62" as written
            elif low.endswith("bars"):
                info["bars"] = p[:-4].strip()
            elif "/" in p:
                info["signature"] = p
        out.append(info)
    return out


def read_backing(root, tempo):
    """Audio clips on the 'Backing' track: which file plays where, and how to cut it
    so it sounds as it does in Live (unwarped plays 1:1, warped is stretched)."""
    tr, out = track_named(root, BACKING_TRACK), []
    for c in (tr.iter("AudioClip") if tr is not None else []):
        path = c.find(".//SampleRef/FileRef/Path")
        if path is None:
            continue
        start, end = float(val(c, "CurrentStart")), float(val(c, "CurrentEnd"))
        loop_start = float(val(c, "Loop/LoopStart", 0))
        if val(c, "IsWarped") == "true":
            marks = [(float(w.get("SecTime")), float(w.get("BeatTime"))) for w in c.iter("WarpMarker")]
            (s0, b0), (s1, b1) = marks[0], marks[-1]
            sec_per_beat = (s1 - s0) / (b1 - b0) if b1 > b0 else 60 / tempo
            src_start = s0 + (loop_start - b0) * sec_per_beat   # warped: LoopStart is in beats
        else:
            sec_per_beat, src_start = 60 / tempo, loop_start       # unwarped: in seconds
        out.append({"beat": start, "end_beat": end, "file": path.get("Value"),
                    "src_start": src_start, "src_seconds": (end - start) * sec_per_beat})
    return out


def build_show(raw, source):
    beats_per_bar = raw["signature"][0] * 4 / raw["signature"][1]
    tempo = raw["tempo"]
    end = max(raw["end_beat"], max((l["beat"] for l in raw["locators"]), default=0) + beats_per_bar * 8)

    songs, chapters, current = [], [], None
    for loc in raw["locators"]:
        name = loc["name"]
        if name.startswith(CHAPTER_PREFIX):          # chapter: a label, never a section
            chapters.append({"name": name[len(CHAPTER_PREFIX):].strip(), "beat": loc["beat"],
                             "bar": round(loc["beat"] / beats_per_bar + 1, 2)})
            continue
        if name.startswith(SONG_PREFIX):
            current = {"name": name[len(SONG_PREFIX):].strip() or f"Song {len(songs) + 1}",
                       "start_beat": loc["beat"], "sections": []}
            songs.append(current)
            continue
        if current is None:                          # sections before any ">>"
            current = {"name": "Set", "start_beat": loc["beat"], "sections": []}
            songs.append(current)
        current["sections"].append({"name": name or "section", "start_beat": loc["beat"]})

    # close each section and song against whatever comes next
    edges = sorted({s["start_beat"] for g in songs for s in g["sections"]}
                   | {g["start_beat"] for g in songs} | {end})
    def next_edge(beat):
        return next((e for e in edges if e > beat + 1e-6), end)

    # a song marker cannot share a bar with its first section, so name the gap
    for g in songs:
        if not g["sections"] or g["sections"][0]["start_beat"] > g["start_beat"] + 1e-6:
            g["sections"].insert(0, {"name": "Start", "start_beat": g["start_beat"]})

    for i, g in enumerate(songs):
        g["end_beat"] = songs[i + 1]["start_beat"] if i + 1 < len(songs) else end
        for s in g["sections"]:
            s["end_beat"] = min(next_edge(s["start_beat"]), g["end_beat"])
            s["bars"] = round((s["end_beat"] - s["start_beat"]) / beats_per_bar, 2)
            s["bar"] = round(s["start_beat"] / beats_per_bar + 1, 2)
            s["seconds"] = round((s["end_beat"] - s["start_beat"]) * 60 / tempo, 1)
        g["bars"] = round((g["end_beat"] - g["start_beat"]) / beats_per_bar, 2)
        g["seconds"] = round((g["end_beat"] - g["start_beat"]) * 60 / tempo, 1)

    # clips belong to the song they start in (a bar of slack: the audio may start
    # just before the ">>" marker)
    def song_at(beat):
        hits = [g for g in songs if g["start_beat"] <= beat + beats_per_bar]
        return hits[-1] if hits else (songs[0] if songs else None)
    by_name = {g["name"].lower(): g for g in songs}
    for info in raw.get("tracklist", []):
        g = by_name.get(info["name"].lower()) or song_at(info["beat"])
        if g is not None and "info" not in g:
            g["info"] = {k: v for k, v in info.items() if k in ("label", "bpm", "bars", "signature")}
    for clip in raw.get("backing", []):
        g = song_at(clip["beat"])
        name = os.path.basename(clip["file"])
        if g is not None and name not in g.setdefault("backing", []):
            g["backing"].append(name)

    return {
        "source": source,
        "extracted": datetime.datetime.now().isoformat(timespec="seconds"),
        "tempo": tempo,
        "signature": raw["signature"],
        "beats_per_bar": beats_per_bar,
        "total_bars": round(end / beats_per_bar, 2),
        "total_seconds": round(end * 60 / tempo, 1),
        "songs": songs,
        "chapters": chapters,
    }


# -------------------------------------------------------------------- diff --
def diff(old, new):
    """What changed since last time, in the terms the visual plan cares about."""
    def flat(show):
        out = {}
        for g in show.get("songs", []):
            for s in g.get("sections", []):
                out[(g["name"], s["name"])] = s
        return out
    a, b = flat(old), flat(new)
    lines = []
    for key in sorted(set(a) | set(b)):
        song, name = key
        was, now = a.get(key), b.get(key)
        if was and not now:
            lines.append(f"  gone     {song} / {name}  (cues pointing here are orphaned)")
        elif now and not was:
            lines.append(f"  new      {song} / {name}  at bar {now['bar']:.0f}")
        elif abs(was["bar"] - now["bar"]) > 0.01 or abs(was["bars"] - now["bars"]) > 0.01:
            moved = f"bar {was['bar']:.0f} -> {now['bar']:.0f}" if abs(was["bar"] - now["bar"]) > 0.01 else ""
            grew = f"{was['bars']:.0f} -> {now['bars']:.0f} bars" if abs(was["bars"] - now["bars"]) > 0.01 else ""
            lines.append(f"  moved    {song} / {name}  " + ", ".join(x for x in (moved, grew) if x))
    old_songs = [g["name"] for g in old.get("songs", [])]
    new_songs = [g["name"] for g in new.get("songs", [])]
    if old_songs != new_songs:
        lines.insert(0, f"  setlist  {' , '.join(old_songs)}  ->  {' , '.join(new_songs)}")
    return lines


# ----------------------------------------------------------------- example --
def example():
    """A placeholder set, so the visual plan can start before the music exists."""
    plan = [("Intermission", [("Intro", 16), ("Build 1", 16), ("Drop 1", 32), ("Breakdown", 24),
                              ("Build 2", 16), ("Drop 2", 32), ("Outro", 16)]),
            ("Analogue", [("Intro", 16), ("Verse", 32), ("Lift", 16), ("Drop", 32), ("Outro", 16)]),
            ("Afterglow", [("Intro", 24), ("Swell", 32), ("Peak", 32), ("Fade", 32)])]
    beat, locators = 0.0, []
    for song, sections in plan:
        locators.append({"beat": beat, "name": f"{SONG_PREFIX} {song}"})
        for name, bars in sections:
            locators.append({"beat": beat, "name": name})
            beat += bars * 4
    return {"tempo": 124.0, "signature": [4, 4], "locators": locators, "end_beat": beat}


# ----------------------------------------------------------------- backing --
def render_backing(raw, out_path):
    """Stitch the Backing track's clips into one file that starts at bar 1, so the
    timeline plays along with the set. Uses ffmpeg; Live does not have to be open."""
    import shutil, subprocess
    if not shutil.which("ffmpeg"):
        print("[backing] ffmpeg not found (brew install ffmpeg)")
        return 1
    spb = 60 / raw["tempo"]
    args, chains = ["ffmpeg", "-y", "-loglevel", "error"], []
    for clip in raw.get("backing", []):
        if not os.path.exists(clip["file"]):
            print(f"[backing] missing, left silent: {clip['file']}")
            continue
        out_secs = (clip["end_beat"] - clip["beat"]) * spb
        args += ["-ss", f"{clip['src_start']:.4f}", "-t", f"{clip['src_seconds']:.4f}", "-i", clip["file"]]
        n = len(chains)
        speed = clip["src_seconds"] / out_secs if out_secs else 1
        tempo = f"atempo={speed:.6f}," if abs(speed - 1) > 1e-3 else ""
        chains.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,{tempo}"
                      f"adelay={clip['beat'] * spb * 1000:.0f}:all=1[a{n}]")
    if not chains:
        print("[backing] no clips on a track named 'Backing'")
        return 1
    mix = "".join(f"[a{i}]" for i in range(len(chains)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(chains)}:normalize=0:dropout_transition=0[out]"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    r = subprocess.run(args + ["-filter_complex", graph, "-map", "[out]", "-b:a", "192k", out_path])
    if r.returncode:
        return r.returncode
    print(f"[backing] {len(chains)} clips -> {out_path}  (starts at bar 1: offset 0)")
    return 0


# -------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als", nargs="?", help="path to the .als file")
    ap.add_argument("--als-dir", help="search this folder for the newest .als")
    ap.add_argument("--example", action="store_true", help="write a placeholder show")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--backing", action="store_true",
                    help="also render the Backing track into audio/, for the timeline")
    a = ap.parse_args()

    if a.example:
        raw, source = example(), "example (no Live set yet)"
    else:
        path = a.als
        if not path and a.als_dir:
            found = sorted(glob.glob(os.path.join(os.path.expanduser(a.als_dir), "**", "*.als"),
                                     recursive=True),
                           key=os.path.getmtime, reverse=True)
            found = [p for p in found if "Backup" not in p]
            path = found[0] if found else None
            if path:
                print(f"[show] newest set: {path}")
        if not path:
            ap.error("give a .als path, or --als-dir to search, or --example")
        try:
            raw, source = read_als(path), os.path.abspath(path)
        except (OSError, ET.ParseError, EOFError) as e:
            print(f"[show] could not read {path}: {e}")
            return 1

    show = build_show(raw, source)
    if not show["songs"]:
        print("[show] no locators found. Name a locator '>> Track name' to start a song, "
              "and plain names for its sections.")
        return 1

    if os.path.exists(a.out):
        try:
            changes = diff(json.load(open(a.out)), show)
            print("[show] changes since last sync:" if changes else "[show] nothing moved")
            print("\n".join(changes))
        except (ValueError, OSError):
            pass

    json.dump(show, open(a.out, "w"), indent=2)
    print(f"[show] {len(show['songs'])} songs, "
          f"{sum(len(g['sections']) for g in show['songs'])} sections, "
          f"{show['total_bars']:.0f} bars, {show['total_seconds'] / 60:.1f} min -> {a.out}")
    for g in show["songs"]:
        info = g.get("info", {})
        own = f"{info.get('bpm', '?')} bpm {info.get('signature', '')}" if info else ""
        print(f"    {g['name']:<20} {g['bars']:>5.0f} bars  {g['seconds'] / 60:>4.1f} min  "
              f"{own:<16} {', '.join(s['name'] for s in g['sections'])}")
    if a.backing and not a.example:
        name = os.path.splitext(os.path.basename(source))[0] + " (backing).mp3"
        return render_backing(raw, os.path.join(HERE, "audio", name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
