#!/bin/zsh
# TEST mode — at home, designing and rehearsing. Double-click to start.
#
# Starts everything that shows you the show without the room:
#   Blender previz      the hall, the screen and the pars, live from Resolume
#   Syphon bridge       carries Resolume's screen output into Blender
#   editors             floor plan + show timeline, in the browser
#   cue_player          follows Live and fires the plan at Resolume
#
# You open yourself, before or after: Resolume Arena, and the show set in Live.
# Quit Blender, or ctrl-C here, and everything this started stops.
#
#   ./Test.command              everything
#   ./Test.command --plan       only the editors (no Resolume or Blender needed)
#   ./Test.command --no-bridge  no screen feed (Art-Net only)
#   ./Test.command --rebuild    rebuild venue.blend from build_venue.py first

cd "$(dirname "$0")" || exit 1
setopt NULL_GLOB
mkdir -p .live

# In a shared folder, keep the runtime scratch out of the sync: .live is
# rewritten many times a second and would fight the syncing client.
case "$PWD" in
  *Dropbox*|*"Google Drive"*|*OneDrive*|*iCloud*)
    xattr -w com.dropbox.ignored 1 .live 2>/dev/null
    xattr -w com.apple.fileprovider.ignore#P 1 .live 2>/dev/null ;;
esac

REBUILD=0; BRIDGE=1; PLAN_ONLY=0; LAN_ASK=1; LAN=""
for a in "$@"; do
  case "$a" in
    --lan)       LAN="--lan"; LAN_ASK=0 ;;
    --no-bridge) BRIDGE=0 ;;
    --rebuild)   REBUILD=1 ;;
    --plan)      PLAN_ONLY=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

# a helper left over from an earlier run would hold its port
pkill -f "cue_player.py|syphon_bridge.py|plan_server.py" 2>/dev/null && sleep 0.5
rm -f .live/panic

if [[ $PLAN_ONLY -eq 1 ]]; then
  echo "Editors only. Floor plan: http://localhost:8765   Timeline: http://localhost:8765/show"
  exec python3 plan_server.py
fi

python3 preflight.py test     # warnings only: test mode starts regardless

# ---------------------------------------------------------------- Blender ---
find_blender() {
  [[ -n "$BLENDER" && -x "$BLENDER" ]] && { echo "$BLENDER"; return }
  local c
  for c in /Applications/Blender.app/Contents/MacOS/Blender \
           "$HOME/Applications/Blender.app/Contents/MacOS/Blender" \
           /Applications/Blender/Blender.app/Contents/MacOS/Blender; do
    [[ -x "$c" ]] && { echo "$c"; return }
  done
  c=$(command -v blender 2>/dev/null) && { echo "$c"; return }
  c=$(mdfind "kMDItemCFBundleIdentifier == 'org.blenderfoundation.blender'" 2>/dev/null | head -1)
  [[ -n "$c" && -x "$c/Contents/MacOS/Blender" ]] && { echo "$c/Contents/MacOS/Blender"; return }
  return 1
}
find_uv() {
  local c
  for c in ./tools/uv "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [[ -x "$c" ]] && { echo "$c"; return }
  done
  command -v uv 2>/dev/null
}

BL=$(find_blender) || {
  echo "Blender not found. Install it from blender.org, or set BLENDER=/path/to/Blender."
  read -k1 "?Press any key to close."; exit 1
}

if [[ $REBUILD -eq 1 || ! -f venue.blend ]]; then
  echo "Building venue.blend ..."
  "$BL" -b -P build_venue.py | grep "\[venue\]"
fi

# First run on this Mac: offer the trackpad / numpad preferences.
if [[ ! -f .input_backup.json ]]; then
  echo "Set up Blender's input for a laptop trackpad (Emulate Numpad, option-drag"
  echo "orbit, zoom to pointer)? This changes Blender's preferences for all files."
  if read -q "?Apply them? [y/N] "; then
    echo; "$BL" -b -P setup_input.py | grep "\[input\]"
  fi
  echo
fi

# ------------------------------------------------------------------ run ------
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  for p in $PIDS; do kill $p 2>/dev/null; done
  echo "\nStopped."
}
trap cleanup EXIT INT TERM

if [[ $BRIDGE -eq 1 ]]; then
  if UV=$(find_uv); then
    "$UV" run -q syphon_bridge.py > .live/bridge.log 2>&1 &
    PIDS+=$!
  else
    echo "  ! no screen feed: 'uv' is not installed (curl -LsSf https://astral.sh/uv/install.sh | sh)"
  fi
fi

# working together: let another laptop on this network open the editors too
# (no answer in 5 s is a no, so a restart never waits here; --lan says yes up front)
if [[ $LAN_ASK -eq 1 ]]; then
  if read -t 5 -q "?Share the editors on this network, for a second laptop? [y/N, 5 s] "; then
    LAN="--lan"
  fi
  echo
fi
python3 plan_server.py --no-open $LAN > .live/server.log 2>&1 &
PIDS+=$!

# a previz already open (from an earlier run) is reused, not doubled: two
# Blenders would split the Art-Net between them
BLENDER_PID=$(pgrep -f "Blender -y venue.blend" | head -1)
if [[ -n "$BLENDER_PID" ]]; then
  echo "  the previz is already open in Blender — using that one"
else
  "$BL" -y venue.blend --python-expr \
    "import bpy; bpy.app.timers.register(lambda: (bpy.ops.venue.live(), None)[1], first_interval=2.0)" \
    > .live/blender.log 2>&1 &
  BLENDER_PID=$!
  PIDS+=$BLENDER_PID
fi

sleep 1
open "http://localhost:8765/show"

echo "  running:  Blender previz · screen feed · editors · cue_player"
echo "  timeline  http://localhost:8765/show     floor plan  http://localhost:8765"
if [[ -n "$LAN" ]]; then
  sleep 0.5
  echo "  shared    $(grep -o 'http://[0-9.]*:8765/' .live/server.log | head -1)   ← open this on the other laptop"
fi
echo "  logs      .live/*.log"
echo "  Quit Blender or press ctrl-C to stop.  p = panic, r = resume (try them)\n"

# when Blender quits, stop the player too, and with it this whole session
( while kill -0 $BLENDER_PID 2>/dev/null; do sleep 1; done
  pkill -INT -f "cue_player.py --follow" ) &
PIDS+=$!

# the player runs here, in front, so its keys work. --preview lets lights cues
# show in the previz when Resolume isn't sending (live Art-Net always wins)
# If it crashes, it comes back by itself, like on show night, and the previz
# stays open; ctrl-C or quitting Blender still ends the session.
while true; do
  python3 cue_player.py --follow --preview
  code=$?
  stty sane 2>/dev/null
  [[ $code -eq 0 || $code -eq 130 ]] && break
  kill -0 $BLENDER_PID 2>/dev/null || break
  echo "\n  the player stopped (exit $code) — restarting it in 2 s"
  sleep 2
done
