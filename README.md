# Intermission

**New here, planning from your own Mac?** Read [START_HERE.md](START_HERE.md) — the
short version: set up once, then one double-click.

The version is in [`VERSION`](VERSION), the history in [`CHANGELOG.md`](CHANGELOG.md).
A release is `python3 release.py 0.2.0`: it writes both, commits, tags `v0.2.0` and
pushes; `Update.command` on the other Mac brings it in. The version shows next to
the name in the top bar and on the Host.

The cinema hall in Blender: the screen, 6 RGBW floor pars around the performer,
haze, and audience cameras. At home it plays what Resolume sends, live:

    Resolume ──Syphon──► syphon_bridge.py ──.live/screen.rgba──► Blender screen
    Resolume ──Art-Net (127.0.0.1:6454)────────────────────────► Blender pars

## Files

| file | what |
|---|---|
| **the show folder** | everything that *is* the show, in one folder shared through Dropbox: the plan files below marked *(show folder)*, `composition.json`, `audio/` (bounces), `library/` (the Library's media), `light-looks/`, `projects/`. `showfolder.py` says where it is on this Mac; `.show` remembers it (per Mac, not in git) |
| `showfolder.py`, `showfolder.sh` | find the show folder; `--init` lays out a new one from `defaults/` |
| `VERSION`, `CHANGELOG.md`, `release.py`, `version.py` | the version, its history, and the one command that bumps both, tags and pushes |
| `START_HERE.md` | the short how-to for the other Mac: set up once, then one double-click |
| `Test.command` | **test mode**: double-click at home — previz, screen feed, editors, player |
| `Live.command` | **live mode**: double-click on show night — checks, then only the player |
| `preflight.py` | what both launchers check first: plan, Resolume, Live |
| `build_venue.py` | builds `venue.blend` from the CONFIG block (room, screen, pars, DMX patch) |
| `venue_live.py` | runtime inside the .blend: Art-Net listener, screen feed, **Venue** sidebar tab |
| `syphon_bridge.py` | Syphon receiver, run with `uv` (Blender's Python can't load Syphon) |
| `plan_editor.html` | the floor-plan editor: place the pars in a browser, with a 3D preview |
| `lib/` | three.js and the 3D preview, kept local so the editor works offline |
| `plan_server.py` | serves the editor and saves `rig.json` (standard library only) |
| `rig.json` *(show folder)* | **where the fixtures live**: positions, addresses, aim, tilt, beam |
| `fixtures.json` | the two fixture profiles, from the manufacturers' sheets |
| `sync_show.py` | reads the Ableton set into `show.json`, and says what moved |
| `show_editor.html` | the show timeline: plan the visual set against the music |
| `docs.html` | **how it all works** — served at `/docs`, read this first |
| `make_composition.py`, `resolume/` | **Make composition** on the Host: writes the Resolume composition from the show for this Mac (TD over Syphon — NDI is only an optional preview for other machines — the Library on Base, the Overlay lane's clips, the light presets), from templates cut from one Arena 7.19 saved |
| `shell.html` | the one top bar every page sits under: each page loads in its own frame, so switching pages never unloads one — the timeline keeps playing (audio, Drive, playhead). `/show?embed=1` etc. is a page on its own |
| `show.json` *(show folder)* | the music: setlist, tempo, sections in bars (generated, don't edit) |
| `cues.json` *(show folder)* | **the visual plan**: what happens at which section |
| `looks.json` *(show folder)* | named lighting looks — a colour and level per par |
| `cue_player.py` | plays the plan: follows Live, fires cues at Resolume over OSC |
| `osc_map.json` *(show folder)* | lanes → Resolume layers, automation targets, the panic look, raw-OSC cues |
| `composition.json` *(show folder)* | Resolume's composition as last seen (names only), for when Arena is closed |
| `Update.command` | double-click: `git pull` the tools |
| `Intermission.command`, `host.py`, `host.html` | the **Host**: one click to open everything for test or the show, projects (save, load, new), and the versions of everything the show runs on |
| `library.html`, `library.py` | the **Library**: gathers renders, sequences and live sources, converts to DXV, installs into the screen layers. Which folders it looks in is per Mac (`sources.json`, set on the page) |
| `library.json` *(show folder)* | what's in the show (the media: `library/` beside it) |
| `td/` *(show folder)* | **the TouchDesigner set**: `td/liveset/` holds its spec, assets and the built `liveset.toe`, its `stills/` and `scenes.json`. Shared through Dropbox; a project picks its set (`td_set`, default `td/liveset/liveset.toe`) and the Host opens it. Edit it with td-pipeline, where `projects/liveset` is a link to this folder (`./tdgen live liveset`, `./tdgen build liveset`) |
| `td_stills.py` | where the project's TouchDesigner set is, and stills of its scenes for the timeline's TD lane and Preview strip, asked of the running set over OSC (`/stills`; also the View tab's Grab buttons). The monitor's **TD live** reads the set's own output from its web server (`osc_map.json` → `td.web`, 9982; the server passes it through as `/td/frame`) |

The **TD lane** switches the liveset for real: `cue_player` sends each TD cue as OSC
`/scene <name> <fade s>` to `osc_map.json` → `td` (default `127.0.0.1:10004`), and the
liveset's `scene_ctl` crossfades straight to that scene. The fade is the cue's own (1 bar
unless set; 0 is a cut), a jump in the timeline cuts, and a scene holds until the next
TD cue. `black` fades TD to black.
| `lib/band.js` | plays a loop or look onto the band in the browser, for the floor plan's **Loop** mode |
| `band.py` | **where each fixture sits on the control band**; renders looks as band stills |
| `make_light_loops.py` | builds the control-band loops the pars sample |
| `content/light-looks/` | looks rendered as band stills by Make clip, loaded into the lights layer |
| `arena_load.py` | loads clips into Resolume over its REST API, and maps them to cue names |
| `content/light-loops/` | the 38 presets (1920x120), their pattern cards, `loops.json` and a README |
| `artnet_test.py` | fake Resolume: sends a chase or a fixed look over Art-Net |

## Run it — two modes

Open Resolume and the show set in Live yourself. Then double-click one:

| | **Test.command** (at home) | **Live.command** (show night) |
|---|---|---|
| Blender previz | ✓ | — |
| Syphon bridge | ✓ | — |
| editors in the browser | ✓ | — |
| cue_player following Live | ✓ | ✓ |
| Resolume Art-Net goes to | `127.0.0.1` (Blender) | the venue's node |

The first time on a Mac, both ask where the **show folder** is: the shared
`Intermission Show` folder in Dropbox with the plan, the Library's media and the
bounces. Drag it into the window. `python3 showfolder.py` says what it's set to.

Both run `preflight.py` first and say what's missing. Test starts anyway;
Live asks before starting if anything is wrong, prints a hand checklist, and
keeps the Mac awake. Both stop leftovers from an earlier run.

    ./Test.command              everything
    ./Test.command --plan       only the editors (no Resolume or Blender needed)
    ./Test.command --no-bridge  no screen feed (Art-Net only)
    ./Test.command --rebuild    rebuild venue.blend first
    python3 preflight.py live   just the checks

Every page shows status dots for Resolume, Live, the player, Blender, Art-Net
and the screen feed; hover one for the fix. In the player's terminal, **p** is
panic (the safe look from `"panic"` in `osc_map.json`, cues held) and **r**
resumes where the music is. Live mode restarts a crashed player within a
second; a panic survives the restart.

## Cues name clips

Cues name a clip (or a column, for scenes) exactly as Resolume calls it, and the
player finds it **by name** in the open composition, in the lane's layer. A clip
moved to another slot keeps its cues; a renamed one turns ✗ in the timeline and
in `preflight.py`. The timeline's **Resolume panel** shows the composition with
thumbnails: drag a clip onto a lane, a column onto Columns, or onto a cue to swap
it. Fold a lane open (▸) to see each cue's thumbnail, target and ✓/✗; a cue
glows green while Resolume is playing it.

## Fades, looks as clips, the quick picker

- **Fades**: every cue can fade in, in bars (drag the ▾ on its top edge). The
  player sets the layer's transition time in Resolume just before firing, so
  Resolume crossfades on its own clock. Max 10 s; jumps and panic always cut.
- **Looks as clips**: *Make clip* renders a floor-plan look onto the control band
  (`band.py`) and loads it into the lights layer, named after the look.
- **Quick picker**: double-click a lane (or press enter on a cue) to pick its
  clip, fade and note right on the cue.

## Automation

Points anchor to sections. Between two points: straight, ease in/out (alt-drag
the line to bend it), S-curve, or hold — the timeline and the player share one
formula. ∿ draws sine / saw / square / random shapes over a stretch; ⌘-drag draws
freehand; shift-drag is fine. A lane can drive **any Resolume parameter** — pick
it from the lane menu (＋ a Resolume parameter…); it's stored by name and sent by
id over the REST API. Set its useful range with the button by the lane's value.

## Planning the show

Two files, two jobs. `show.json` is the music — extracted from Live, never
edited by hand. `cues.json` is the plan — what the visuals do, anchored to the
music by **section name and an offset in bars**, never by seconds. That is what
lets the visual set be built while the music is still changing.

### The locator convention

Locators in the Ableton arrangement are the contract. A locator named
`>> Track name` starts a song; plain names after it are that song's sections:

    ## 1 · before       bar 1     a chapter: a label over the songs that follow
    >> Intermission     bar 2     a song
    Build 1             bar 17    its sections
    Drop 1              bar 33
    >> Afterglow        bar 129

Nothing else in Live matters to the visuals. Rewrite a section, stretch it,
replace every sound in it — as long as the locator keeps its name, the plan
still points at the right moment.

A locator starting with `## ` names a **chapter** — a group of songs. Chapters
are labels only: they show as a band above the song row, in the strip above
the timeline and in the setlist, and no cue anchors to them. Put the chapter
locator a bar before its first `>>` (Live allows one locator per position).

### Syncing

    python3 sync_show.py ~/Music/…/Set.als     # extract, and report what moved
    python3 sync_show.py --als-dir ~/Music     # find the newest set under here
    python3 sync_show.py --example             # placeholder, before the music exists
    python3 sync_show.py …/Set.als --backing   # also stitch the set's Backing track into audio/

It reads the `.als` directly (gzipped XML), so Live doesn't need to be open, and
it prints a diff against the last sync:

    moved    Intermission / Drop 1   bar 33 -> 41
    moved    Intermission / Breakdown   32 -> 40 bars
    gone     Intermission / Build 2  (cues pointing here are orphaned)

Run it after every session where the arrangement changed. Cues whose section
disappeared turn red in the timeline and can be re-pointed in one click.

### The timeline

<http://localhost:8765/show>, next to the floor plan. Songs and sections across
the top, four lanes below:

| lane | holds |
|---|---|
| Screen | the Resolume clip or deck |
| Lights | the look for the pars |
| TD | the TouchDesigner scene, when there is one |
| Notes | intent in words — "hold this too long on purpose" |

It works like Live's arrangement:

| | |
|---|---|
| double-click a lane | add a cue there |
| double-click a cue | remove it |
| drag | move it — sideways in time, up and down between lanes |
| drag either edge | change how long it runs |
| alt-drag | leave a copy behind |
| drag on empty space | box-select across lanes |
| shift-click | add or remove one from the selection |
| drag the song, section or waveform rows | scrub the playhead; a click on the ruler jumps there |
| `space` | play / pause |
| `⌘Z` / `⇧⌘Z` | undo / redo |
| `⌘C` `⌘V` | copy, paste at the playhead, keeping the spacing |
| `⌘D` | duplicate after itself |
| `⌘A`, `esc` | select all, deselect |
| `⌫` | delete the selection |
| arrows | nudge by the grid; shift for one bar; up/down changes lane |
| `⌘`-scroll, or drag the ruler down / up | zoom in / out, keeping the bar under the pointer |
| the strip above the timeline | the whole set: drag the frame to move, its edges to zoom, click to jump |

The **snap** box at the top sets the grid: 1, 2, 4, 8, 16 bars, or off. Dragging
several cues moves them together, and the sidebar's What, Lane, Length and note
fields apply to everything selected.

### Looks

A look is a colour and level per par, with a name. Build them in the **Looks**
panel on the floor-plan page:

1. **New**, and give it a name.
2. Select the pars it should light (box-select, or shift-click for a few).
3. Pick the colour, white and level. The previz follows while you slide.
4. **Set selected pars**, **Set all**, or **Selected off** to fix the values.

Whatever look you are editing is shown live: Blender lights the room with it,
and the 3D pane in the editor shows it too, so looks can be designed with
Resolume closed and the room dark.

Incoming DMX always wins. While Resolume is sending, the pars follow Resolume;
when it stops, the previz falls back to the look you are working on. The Venue
sidebar in Blender says which look it is showing.

In the show timeline, a **Lights** cue's *What* field is a dropdown of these
names, and selecting the cue shows its look in the previz — so you can walk the
plan cue by cue and watch the room change. If a cue names a look that no longer
exists, the sidebar says so.

### Hearing the music while planning

Bounce the set to audio after a writing session and drop the file in the show
folder's `audio/`.
The timeline finds it, plays it, and the playhead runs along the plan in time
with the music — so whoever is planning the visuals can listen without Live.

The set's own **Backing** track is the quickest bounce: `python3 sync_show.py
…/Set.als --backing` stitches its clips into the show folder's `audio/<Set> (backing).mp3`, from
bar 1 (offset 0). It overwrites that one file each run, so the timeline's choice
sticks. The bounce's waveform runs under the section row, and the strip above
the timeline shows the whole set with the current view framed.

- **Space** plays and pauses; click the song, section or waveform rows to seek.
- The clock shows time, bar and which section you are in.
- **Room now** in the sidebar shows the pars as they would be at the playhead,
  and sends that look to the previz, so Blender follows the music too.
- **offset** is for a bounce that does not start exactly at bar 1. Normally 0.

Bouncing, in Live: Export Audio/Video, the whole arrangement from bar 1, and
**keep the same settings every time** — no normalising, since a bounce that is
louder than the last one is confusing rather than helpful. MP3 at 192-256 kbps
is plenty; the few milliseconds an encoder adds at the start do not matter for
planning. Name it with a date, `Set_2026-09-21.mp3`, and keep the last few so
it is clear which is current.

Audio files are not in the project zip - they are big, and they change often.

### Playing it

`cue_player.py` reads the plan and fires it at Resolume. It never sends DMX:
Resolume stays the only thing driving the rig, so the previz sees exactly what
the real fixtures see.

    python3 cue_player.py --dry-run     the whole show as a timed cue list
    python3 cue_player.py --rehearse    run it on a fake clock, no Live needed
    python3 cue_player.py --follow      follow Live and fire for real

`osc_map.json` says what a cue means. Either the short form, which becomes
Resolume's connect message:

    "lights:White snap": {"layer": 2, "clip": 3}

or raw OSC when you need more than one thing to happen:

    "lights:Sides only": [{"address": "/composition/layers/2/clips/4/connect", "args": [1]},
                          {"address": "/composition/layers/2/video/opacity", "args": [0.8]}]

**Start with `--dry-run`.** It prints every cue with its time, bar, section and
the exact OSC it will send, and it names any cue that maps to nothing. A cue
with no mapping is reported, never silently skipped — that is what makes the
plan trustworthy.

**`--rehearse`** plays the whole show against a simulated clock: `--speed 20`
to skim it, `--from-bar 65` to start in the middle, `--preview` to show the
lighting looks in the previz while Resolume is closed.

**`--follow`** needs Live's position over OSC, on port 9001. Install
[AbletonOSC](https://github.com/ideoforms/AbletonOSC) (a Live remote script) or
use a small Max for Live device on the master. It accepts `/live/song/beat`,
`/live/song/get/current_song_time` or a plain `/position/beats`.

**Jumps are handled.** Jump to a locator and the player doesn't replay
everything in between: it works out what each lane should be showing at that
point and restates it. Rehearsing a single drop puts the room in the right state.

### Automation lanes

The timeline also holds automation: one OSC target per lane, drawn as a curve.
Double-click to add a point, drag it, double-click to remove it; box-select and
delete work as for cues. Each point either ramps to the next or holds until it.
Points are anchored to sections in bars, so a build-up stretches with its
section when the music changes.

Targets live in `osc_map.json` under `targets` — address, min, max, curve, and
optionally host and port — the same rows as Ableton's OSC Send device, but in
one file that travels with the project. The ones there now are placeholders.

`cue_player.py` plays the curves along with the cues, sending a value only when
it moves, and restating every lane on a jump. **Follow Live** in the timeline
mirrors the player: its playhead, each lane's current value, cues glowing as
they fire. The browser never sends OSC itself — a tab can be throttled in the
background or closed by accident; the player can't.

The **Columns** lane fires Resolume columns: a number, or a name from `scenes` in
`osc_map.json`.

Automation tracks Live about 60 times a second — smooth for fades and builds,
not beat-accurate. For beat-locked effects, use Resolume's BPM sync over Ableton
Link and automate how much of them you want.

## Placing the pars

`rig.json` holds the rig, and everything follows it: `build_venue.py` builds
from it, the previz tracks it **live**, and `export_patch.py` exports it as the
patch table and printable floor plan. You never place a light inside Blender.

`Test.command` opens the editor at <http://localhost:8765> alongside Blender.
Or run it on its own:

    ./Test.command --plan

In the editor, seen from above with you at the centre and the screen at the top:

- **drag a par** to move it; the label shows distance and angle as you go
- **drag a box** on empty space to select several; **shift-click** adds or removes
  one; `⌘A` selects all, `esc` clears. Dragging one moves the whole selection,
  and height, aim, tilt and beam apply to all of them at once
- **alt-drag** (or hold space) pans the plan; scroll zooms
- **drag the handle** on its beam to aim it
- snapping to a grid and to angles is on by default; hold `S` to flip it off, or
  change the steps in the sidebar
- the sidebar edits exact numbers: address, distance, angle, x, y, height, aim,
  tilt, beam angle
- **Add par**, **Duplicate**, **Mirror to other side**, **Delete**
- **Renumber addresses** re-patches everything in order, left to right
- **Arrange on an arc** asks for a distance and a spread and lays them out
- arrow keys nudge the selection (hold shift for 1 cm), `⌘Z` undoes

Every change saves straight away, and Blender picks it up within half a second —
move a par in the browser and watch it move in the room. Adding and removing
fixtures works live too, up to `MAX_PARS` in `build_venue.py` (12 by default);
past that, rebuild.

### The 3D preview

Under the plan is a live 3D view of the room built from the same rig: the
screen, the seating, you, and a cone for each beam. Drag to orbit, scroll to
zoom, shift-drag to pan, and **from my seat** / **from above** jump to a view.
Click a par to select it there, shift-click to add it.

The camera stays inside the room: it cannot go under the floor, through a wall
or behind the screen, however far you drag. If a move would take it outside, it
slides in along its own line of sight and keeps looking at the same spot.

While the previz is running, the beams take their colour from what Resolume is
actually sending, and the screen takes the colour of the live feed — the panel
says "live from the previz" when that is happening.

It is a sanity check for aim and coverage, not a render. Blender stays the place
you judge how the room looks: it has the haze, the shadows and the light spill
that the browser only approximates.

The editor listens on localhost only, so nothing is reachable from the network.
A copy of the previous rig is kept as `rig.json.bak`.

## Working on this together

The code is this repo, on GitHub. The show is one folder in Dropbox —
`Intermission Show`, shared between you. Everything that *is* the show lives
there: the plan files, the Library's media, the bounces, Arena's composition
names and the Host's saved projects. Each Mac clones the repo and, the first
time a launcher runs, points it at the show folder (`.show`, per Mac, not in
git). Your own render folders never leave your disk: **Add** in the Library
copies the chosen clip, converted, into the show folder, and that is what syncs.

- **You** write music and, after a session, run `sync_show.py … --backing`.
  That refreshes `show.json` and the bounce in the show folder; he has both a
  minute later.
- **He** opens the editor, hears the bounce, and plans against the real
  arrangement. Cues stay anchored in bars, so your next session moves them
  rather than breaking them.
- Blender, Resolume and Live are only needed by whoever is doing that part. The
  editor and the bounce are enough to plan.
- Tool updates are `git pull`, on both Macs.

Three things to agree on:

- **Set the show folder to "Make available offline"** in Dropbox, on both Macs.
  Resolume must never meet a placeholder file mid-show.

- **Don't both edit the same file at the same time.** The editors save whole
  files, so simultaneous edits to `cues.json` will produce a conflicted copy.
  In practice one of you plans while the other writes, which is fine. An editor
  that has gone stale refuses to save over newer work and says *changed
  elsewhere — reload*; reloading picks up what the other person did.
- **Don't put the repo itself in Dropbox.** Git and a sync client fight over
  `.git/`; the show folder is the shared part. `.live/` stays with the code and
  is never synced (the launchers still tell a sync client to ignore it, should
  the code end up in a synced folder).

## Taking it to another machine

Clone the repo (or copy this folder) and share the show folder with that Mac in
Dropbox; the first launcher run asks where it is. `venue.blend` carries its own
scripts and textures, so nothing else needs fixing up.

What the other Mac needs:

- **Blender** (any recent version; built and tested on 5.2). `Test.command`
  looks in /Applications, your own Applications folder, your PATH, and finally
  asks Spotlight. Set `BLENDER=/path/to/Blender` to override.
- **Resolume**, for anything to feed it.
- **`uv`**, only for the screen feed. If it's missing, `Test.command` says so
  and carries on: Art-Net and the pars work, and the screen shows the test card.
  Install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`, or drop a
  `uv` binary in a `tools/` folder next to this file and it will be used.
- **Python 3**, for the floor-plan editor. macOS ships it; if it's missing, the
  editor is skipped and everything else still runs.
- **Internet, once.** The first bridge run downloads the Syphon library and a
  Python to run it. After that it's cached on that machine and works offline.

The first run on a new Mac also offers to apply the trackpad / numpad
preferences (see below). Say no and nothing about that Blender changes.

Three things that do *not* travel, because they belong to the machine: Blender's
own Preferences, Resolume's composition and Lumiverse, and `.show` (where the show
folder is on that Mac).

## Build

    /Applications/Blender.app/Contents/MacOS/Blender -b -P build_venue.py

Rebuild whenever a measurement changes. `venue.blend` is generated, so don't
hand-edit it (it gets overwritten); save your own camera moves in a copy.

## Run a live session

1. Open `venue.blend`. If Blender asks, click **Allow Execution**, or run
   `venue_live.py` once from the Text Editor (Alt+P). Press **N** in the viewport,
   go to the **Venue** tab and click **Go live**.
2. Screen: start the bridge in a terminal:

       uv run syphon_bridge.py            # picks the Syphon server called "Arena"
       uv run syphon_bridge.py --list     # see what's being published

   In Resolume, turn on Syphon output for the composition. With no Resolume,
   `uv run syphon_bridge.py --demo` sends a moving test pattern.
3. Pars: in Resolume, send Art-Net DMX to `127.0.0.1`, universe 0. With no
   Resolume, `python3 artnet_test.py` (chase) or `--look red|blue|white|warm|off`.
   The **Chase** button animates the pars from inside Blender, with nothing else running.

Viewport shading should be **Material Preview**, or **Rendered** for beams in the haze.

## On a laptop (trackpad, no numpad)

Shortcuts this file adds, with the pointer over the 3D viewport. They live in
the file only: nothing about your other Blender projects changes.

| key | does |
|---|---|
| `alt 1` … `alt 6` | front row, middle, back row, side seat, your own seat, plan |
| `alt left` / `alt right` | previous / next camera |
| `alt H` | haze on / off (keeps the amount you set) |
| `alt L` | live on / off |
| `alt C` | test chase on / off |

The same cameras are buttons in the **Venue** sidebar (press **N**), numbered to
match the keys.

For Blender's own navigation, `setup_input.py` sets three Preferences → Input
options that make a trackpad workable:

    /Applications/Blender.app/Contents/MacOS/Blender -b -P setup_input.py
    /Applications/Blender.app/Contents/MacOS/Blender -b -P setup_input.py -- --revert

- **Emulate Numpad** — the number row does Blender's own views: `0` camera,
  `1` front, `7` top. (The previz's own cameras stay on alt + number.)
- **Emulate 3 Button Mouse** — `option` + drag orbits, `shift option` + drag pans.
  This is the trackpad stand-in for a middle mouse button.
- **Zoom to Mouse** — zoom goes toward the pointer instead of the view centre.

These are Blender-wide, not per file. The old values are saved to
`.input_backup.json` and `--revert` puts them back. Close Blender before running
it, or Blender may write its in-memory preferences back over the change when it quits.

Also worth knowing on a trackpad:

- Two-finger scroll zooms. `shift` + two-finger scroll pans.
- `` shift ` `` (backtick) starts walk navigation: W A S D to walk the room,
  mouse to look, `E`/`Q` up and down, left click to stop where you are. This is
  the quickest way to check a sightline from somewhere that has no camera.
- **Frame everything** is `home`. **Frame the selected object** is `.` on the
  number row once Emulate Numpad is on.

## Patch

The rig is 8 pars and 4 bars, 320 channels in one universe:

| fixture | model | mode | channels each |
|---|---|---|---|
| PAR_01–08 | GM Light LED PAR RGBW IP65 7x10, 25° | 4ch R/G/B/W | 4, from 1 |
| BAR_01–04 | Showtec Pixel Bar 18 Q4 Tour, 18°, 1.04 m | 72ch, 18 pixels × RGBW | 72, from 33 |

Set each par to its 4-channel mode and each bar to 72-channel; the previz,
`patch/patch.md` and Resolume all follow `rig.json`. In Resolume a par is a
1 × 1 pixel fixture and a bar is 18 × 1, which is what lets a chase run along a
bar. The bars are IP20, indoor only; the pars are IP65.

`export_patch.py` writes the table, a CSV and a printable floor plan with the
bars drawn at their real length.

## Estimates to replace

- **Screen width: 11.5 m — measured.** The height, 6 m, is derived: the screen
  reads 1.93:1 in `content/cinerama-full.MOV`, which is about the 1.85:1 flat
  format. Worth confirming with a tape.
- Room 15 × 20 m and 8.5 m high, read off the same video. The screen plus about
  1.7 m of wall each side gives the width.
- Room depth (24 m), stage strip (3 m) and step (0.35 m), row pitch and rake
- Where you sit (1.8 m from the screen), par radius and angles, beam angle (25°)
- Haze: only matters if a haze machine is allowed in the cinema

## Notes

- Art-Net: if Blender shows `port 6454: Address already in use`, another app
  (often Resolume's own DMX input, or TouchDesigner) holds the port. Turn off
  that app's Art-Net input while you run the previz.
- The screen feed is scaled to 960×540 (`--size` to change). The previz shows
  what's on the screen; it isn't a colour-accurate monitor.
- In EEVEE, the screen's light on the room comes from an area light that
  follows the average colour of each frame. Cycles renders the real spill from
  the screen itself.
