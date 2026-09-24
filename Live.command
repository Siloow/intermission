#!/bin/zsh
# LIVE mode — show night. Double-click to start.
#
# Runs only what the show needs: cue_player, following Live and firing the plan
# at Resolume. No Blender, no screen feed, no editors — nothing that edits
# files, nothing extra on the GPU, and the Mac is kept awake.
#
# Open first, yourself: Resolume Arena with the show composition, and the show
# set in Live. Then double-click this. ctrl-C stops the player; Resolume and
# Live keep running and hold the last state.
#
# If the player ever dies, it is back within a second, and picks up where the
# music is. In its window:  p = PANIC (the safe look, cues held)   r = resume.

cd "$(dirname "$0")" || exit 1
mkdir -p .live

# nothing from a test session may be left fighting for the ports
pkill -f "cue_player.py|syphon_bridge.py|plan_server.py" 2>/dev/null && sleep 0.5
rm -f .live/panic                 # a new show starts following the plan

python3 preflight.py live
BAD=$?
if [[ $BAD -gt 0 ]]; then
  echo "  $BAD problem(s) above."
  read -q "?Start the show anyway? [y/N] " || { echo; read -k1 "?Press any key to close."; exit 1 }
  echo
else
  read "?Checklist done? Press Enter to start the show. "
fi

caffeinate -dims -w $$ &          # no sleep, no screen saver, until this closes

echo "\n  LIVE. Play the set in Live; cues follow the playhead. ctrl-C to stop.\n"

# ctrl-C is a clean stop (exit 0). Anything else is a crash: start again. A
# panic survives the restart, so a crash while holding keeps holding.
while true; do
  python3 cue_player.py --follow --live-only      # the timeline's ▶ can't drive the show
  CODE=$?
  stty sane 2>/dev/null
  [[ $CODE -eq 0 ]] && break
  echo "\n  !! the player stopped (exit $CODE) — restarting; it picks up where the music is\n"
  sleep 1
done
