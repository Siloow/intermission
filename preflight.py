"""Check that everything a mode needs is up, and say plainly what isn't.

    python3 preflight.py test       at home: Resolume, Live, the plan
    python3 preflight.py live       on the night: the same, strictly, plus a checklist

The two launchers run this first. It changes nothing: it only asks Resolume,
Live and the plan files what state they are in. Exit code is the number of
things that are wrong, so a launcher can stop before the show on a bad one.

Standard library only.
"""
import json, os, socket, subprocess, sys, time
import arena_load
from cue_player import osc_encode, osc_decode, compile_cues, compile_panic, compile_automation

import showfolder

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = showfolder.root()                # stops here, with the fix, when this Mac has none
ARENA = "http://127.0.0.1:8080"
LIVE_IN, LIVE_OUT = 11000, 11001          # AbletonOSC listens / replies

OK, WARN, FAIL = "  ✓ ", "  ! ", "  ✗ "
problems = 0


def say(mark, text, fix=None):
    global problems
    if mark == FAIL:
        problems += 1
    print(mark + text)
    if fix:
        print("      " + fix)


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------- Resolume ----
def check_resolume(show, cues, mapping):
    snap, live = arena_load.current(ARENA)
    if not live:
        return say(FAIL, "Resolume: not answering on port 8080",
                   "Open Arena, and turn on Preferences → Webserver → Enable Webserver & REST API.")
    say(OK, f"Resolume: composition {snap['name']!r}, {len(snap['layers'])} layers")
    want = mapping.get("resolume", {}).get("port", 7000)
    osc = arena_load.osc_input()
    if osc is not None and not osc[0]:
        say(FAIL, "Resolume: OSC input is off — it will ignore every cue",
            f"Arena → Preferences → OSC → turn on OSC Input, port {want}.")
    elif osc is not None and osc[1] != want:
        say(FAIL, f"Resolume listens for OSC on {osc[1]}, the player sends to {want}",
            f"Set one to match: Arena → Preferences → OSC, or 'resolume.port' in osc_map.json.")
    elif osc is not None:
        say(OK, f"Resolume: OSC input on, port {osc[1]}")
    for lane, cfg in arena_load.lanes().items():
        n = cfg.get("layer")
        if isinstance(n, int) and not 1 <= n <= len(snap["layers"]):
            say(FAIL, f"the {lane} lane uses layer {n}, but this composition has {len(snap['layers'])}",
                "Open the show composition, or fix 'lanes' in osc_map.json.")
    if not show:
        return
    # the same lookup the player makes: every cue, by name, in this composition
    plan = compile_cues(show, cues, mapping, snap)
    bad = [e for e in plan if e["problem"] and e["beat"] is not None]
    if bad:
        say(FAIL, f"{len(bad)} cue(s) name something this composition doesn't have:")
        for e in bad[:8]:
            print(f"        bar {e['bar']:<4.0f} {e['cue']['lane']:<7} {e['cue'].get('value')!s:<16} {e['problem']}")
        print("      The timeline shows them striped with ✗; drag the right clip onto each.")
    else:
        say(OK, "every cue finds its clip or scene in Resolume, by name")
    lanes = arena_load.lanes()
    stray = [c for c in cues.get("cues", []) if c.get("layer") and c["lane"] in lanes
             and c["layer"] != lanes[c["lane"]].get("layer")]
    if stray:
        say(WARN, f"{len(stray)} cue(s) play from another layer than their lane's: no crossfade, "
                  "and that layer's effects instead of the lane's",
            "Drag the clip from the Resolume panel onto the cue again: it's copied into the lane's layer.")
    # automation lanes aimed at Resolume parameters, found by name the same way
    try:
        index = arena_load.params(arena_load.fetch(ARENA))
    except (OSError, ValueError):
        index = None
    lanes = compile_automation(show, cues, mapping, index)
    lost = [a for a in lanes if a["problem"] and a["problem"] != "no points"]
    for a in lost:
        say(FAIL, f"automation '{a['lane'].get('target')}': {a['problem']}",
            "Pick its target again in the lane's menu (＋ a Resolume parameter…).")
    osc = [a for a in lanes if a["spec"] and not a["spec"].get("resolume") and not a["problem"]]
    if osc:
        say(WARN, f"{len(osc)} automation lane(s) send raw OSC ({', '.join(a['lane'].get('target') for a in osc)})",
            "Fine if you set those addresses up; Resolume parameters picked from the lane menu need no setup.")
    elif lanes and not lost:
        say(OK, f"{len(lanes)} automation lane(s) find their Resolume parameters")
    panic = [e for e in compile_panic(mapping, snap) if e["problem"]]
    for e in panic:
        say(FAIL, f"the panic look doesn't resolve: {e['problem']}",
            "Set \"panic\" in osc_map.json to a clip you have loaded.")


# ----------------------------------------------------------------- Live ----
def running_player():
    """The player's own report, if one is running right now."""
    path = os.path.join(HERE, ".live", "player.json")
    try:
        if time.time() - os.path.getmtime(path) < 3:
            return json.load(open(path))
    except (OSError, ValueError):
        pass
    return None


def check_live(show):
    ps = running_player()
    if ps is not None:
        # the player holds Live's reply port, so ask it rather than Live
        if ps.get("panic"):
            say(WARN, "player: running, in PANIC — press r in its window to resume")
        else:
            say(OK, f"player: running, at bar {ps.get('bar', 1):.0f}")
        if ps.get("live_connected"):
            return say(OK, "Ableton Live: answering the player" +
                       ("" if ps.get("playing") else " (stopped)"))
        return say(FAIL, "Ableton Live: not answering the player",
                   "Open the show set, and check Preferences → Link/Tempo/MIDI → Control Surface: AbletonOSC.")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", LIVE_OUT))
    except OSError:
        s.close()
        return say(WARN, f"Live: port {LIVE_OUT} is taken by something that isn't reporting",
                   "pkill -f cue_player.py")
    s.settimeout(0.4)
    tempo = None
    try:
        for _ in range(3):                           # Live can be slow to answer the first time
            s.sendto(osc_encode("/live/song/get/tempo", []), ("127.0.0.1", LIVE_IN))
            try:
                for addr, args in osc_decode(s.recv(4096)):
                    if addr == "/live/song/get/tempo" and args:
                        tempo = float(args[0])
            except (socket.timeout, ValueError):
                pass
            if tempo is not None:
                break
    finally:
        s.close()
    if tempo is None:
        return say(FAIL, "Ableton Live: no answer from AbletonOSC",
                   "Open the show set, and check Preferences → Link/Tempo/MIDI → Control Surface: AbletonOSC.")
    planned = (show or {}).get("tempo") or ((show or {}).get("songs") or [{}])[0].get("tempo")
    note = f" (show.json says {planned:g})" if planned and abs(planned - tempo) > 0.01 else ""
    say(OK if not note else WARN, f"Ableton Live: answering, {tempo:g} bpm{note}",
        "The set's tempo differs from the last sync — run sync_show.py if the music changed." if note else None)


# ----------------------------------------------------------------- plan ----
def check_plan(show, cues):
    if not show:
        return say(FAIL, "no show.json yet", "python3 sync_show.py /path/to/Set.als")
    n = len(cues.get("cues", []))
    gone = [c for c in cues.get("cues", []) if not any(
        g["name"] == c.get("song") and any(x["name"] == c.get("section") for x in g["sections"])
        for g in show["songs"])]
    if gone:
        say(FAIL, f"plan: {len(gone)} of {n} cues point at a section that no longer exists",
            "The timeline lists them in the sidebar; one click re-points each.")
    else:
        say(OK, f"plan: {n} cues, all on sections that exist")
    age = (time.time() - os.path.getmtime(os.path.join(SHOW, "show.json"))) / 86400
    if age > 7:
        say(WARN, f"show.json was synced {age:.0f} days ago",
            "If the arrangement changed since: python3 sync_show.py --als-dir ~/Music")


# ---------------------------------------------------------------- stale ----
def check_stale():
    if running_player() is not None:
        return                                   # a session is up, not leftovers
    r = subprocess.run(["pgrep", "-f", "cue_player.py|syphon_bridge.py|plan_server.py"],
                       capture_output=True, text=True)
    pids = [p for p in r.stdout.split() if p and int(p) != os.getpid()]
    if pids:
        say(WARN, f"{len(pids)} helper(s) from an earlier run still going (the launcher stops them)")


def main():
    mode = (sys.argv[1:] or ["test"])[0]
    show = load(os.path.join(SHOW, "show.json"), None)
    cues = load(os.path.join(SHOW, "cues.json"), {"cues": []})
    mapping = load(os.path.join(SHOW, "osc_map.json"), {})

    print(f"\n  {'LIVE — show night' if mode == 'live' else 'TEST — previz at home'}\n")
    say(OK, f"show folder: {SHOW}")
    check_stale()
    check_plan(show, cues)
    check_resolume(show, cues, mapping)
    check_live(show)

    if mode == "live":
        print("\n  by hand, once, in Resolume:")
        print("    □ Lumiverse Art-Net goes to the venue's node, not 127.0.0.1")
        print("    □ the screen output is on the projector, fullscreen")
        print("    □ Ableton Link is on (clips stay in tempo)")
        print("    □ fire identify on the lights layer: pars light 1 → 6 in order")
    print()
    return problems


if __name__ == "__main__":
    sys.exit(main())
