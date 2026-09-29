# Changelog

What changed in Intermission, newest first. `python3 release.py x.y.z` adds a
section from the commits since the last release; edit it into sentences when a
release deserves them. The version shows next to the name in the top bar — click
it for this list, in the docs — and on the Host.

## 0.1.0 — 2026-09-29

The first numbered version: everything built so far, as one system.

- **Show timeline** — the visual plan against the music: cues anchored to the
  sections of the Ableton set (locators are the contract), fades and easing,
  automation at three levels, looks, a quick picker, Drive from the timeline.
  Waveform of the bounce, an overview strip, ruler zoom, chapters, sticky labels.
- **Player** — follows Live over AbletonOSC and fires Resolume over OSC; panic
  and resume; picks up plan edits while running; restarts itself on show night.
- **Floor plan** — place the pars in the browser with a 3D preview; looks as
  colours per par; 38 light presets on the control band; the Blender previz
  follows Resolume over Art-Net and Syphon.
- **Library** — gathers renders, image sequences and live sources, converts to
  DXV, installs into the screen layers. Which folders to look in is per Mac.
- **Host** — projects (save, load, new), one click to start everything for
  test or the show, and the versions of everything the show runs on.
- **Two Macs** — the code is this repo; the show is one folder in Dropbox
  (`showfolder.py`). `START_HERE.md` for the second Mac, `Update.command` to
  pull the tools.
- Launchers: `Test.command`, `Live.command`, `Intermission.command`, with
  `preflight.py` checks. Docs at `/docs`.
