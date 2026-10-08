# Start here

The short version: planning the visuals from your own Mac. About ten minutes to
set up, then it's one double-click.

## Once

1. **Dropbox** — accept the invitation to the **Intermission Show** folder. Then in
   Finder, right-click that folder → **Make available offline**. This folder *is*
   the show: the music, the plan, the clips. Don't move or rename things inside it
   by hand.

2. **Homebrew** — open Terminal (⌘-space, type `Terminal`) and paste the one line
   from [brew.sh](https://brew.sh). When it finishes it shows two more lines to
   paste; do that too.

3. **Python and ffmpeg** — in the same Terminal window:

       brew install python ffmpeg

4. **The tools** — still in Terminal. This makes a folder called `intermission`
   in your home folder:

       cd ~ && git clone https://github.com/Siloow/intermission.git

5. **First start** — in Finder, open that `intermission` folder and double-click
   **Intermission.command**. A Terminal window asks where the show folder is: drag
   the **Intermission Show** folder from Finder into that window and press Enter.
   Your browser opens on the Host page; click **Show timeline** at the top.

6. **Your renders** — in the browser, open **Library**. Under **Sources** on the
   right, **Add folder…** and pick where your renders are. That list is yours
   alone; only what you **Add to the show** is copied into the shared folder.

## Every time

- Double-click **Intermission.command**. In the browser, go to **Show timeline**.
- Press **space** to hear the set. The playhead runs along the plan.
- Double-click a lane to add a cue. **How it works** (top of the page) explains
  the rest — lanes, fades, the Library.
- Done? Close the browser tab. The Terminal window can stay open or be closed.

## Now and then

- **Update the tools** — double-click **Update.command** in the `intermission`
  folder. Do this when Sil says something changed.
- **New layers or clips in Resolume** (Sil will say so, like the Light colour
  layer and its colour clips) — after Update.command: quit Resolume, double-click
  **Intermission.command**, and on the Host press **Make composition**. It rebuilds
  your composition with everything in it (the old one is kept in Arena's
  Compositions/.backup). Then press **Test**: Resolume opens with it.
- **New music** — nothing to do. When Sil syncs the set, the new `show.json` and
  bounce appear in the show folder on their own; reload the timeline.

## Two rules

- **Not at the same time.** One person plans while the other writes music. If the
  timeline says *changed elsewhere — reload*, reload: the other side saved.
- **Only the show folder goes in Dropbox.** Keep the `intermission` folder out of
  it.

## If something's off

- The timeline says *no bounce in audio/* — the show folder isn't synced yet, or
  isn't set. In Finder, is there an `audio` folder with an mp3 inside
  **Intermission Show**? If yes, start **Intermission.command** again.
- The Terminal says *no show folder set on this Mac* — start
  **Intermission.command** again; it asks.
- Anything else — send Sil a screenshot of the Terminal window.
