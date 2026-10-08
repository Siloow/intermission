#!/bin/zsh
# The show host. Double-click: the editors start (if they aren't running yet)
# and the Host page opens, where the rest is one click each:
#
#   Project   save, load, save as, new — the plan files, with the Live set and
#             Resolume composition that go with them
#   ▶ Test    Resolume, Live, the Blender previz, the screen feed and the player
#   ● Show    Resolume, Live and the player only; the Mac kept awake
#
#   ./Intermission.command         this Mac only
#   ./Intermission.command --lan   the editors shared on this network too
#                                  (starting and stopping stays on this Mac)
#
# Test.command and Live.command still work on their own, as before.

cd "$(dirname "$0")" || exit 1
mkdir -p .live
source ./showfolder.sh          # the show folder: plan, media, bounces
case "$PWD" in
  *Dropbox*|*"Google Drive"*|*OneDrive*|*iCloud*)
    xattr -w com.dropbox.ignored 1 .live 2>/dev/null
    xattr -w com.apple.fileprovider.ignore#P 1 .live 2>/dev/null ;;
esac

URL="http://localhost:8765"
# A host started before the tools were updated keeps running the old code: it
# runs detached, so closing this window doesn't stop it. If any of its files
# changed after it started, stop it, so the one started below is current. (A
# player it started keeps running: the new host finds it.)
PID=$(lsof -nP -iTCP:8765 -sTCP:LISTEN -t 2>/dev/null | head -1)
if [[ -n "$PID" ]]; then
  STARTED=$(LC_ALL=C date -j -f "%a %b %e %T %Y" "$(LC_ALL=C ps -o lstart= -p $PID | xargs)" +%s 2>/dev/null)
  NEWEST=$(stat -f %m *.py *.html lib/* resolume/* 2>/dev/null | sort -n | tail -1)
  if [[ -n "$STARTED" && -n "$NEWEST" ]] && (( NEWEST > STARTED )); then
    echo "  the host is older than the tools: restarting it"
    kill $PID 2>/dev/null
    for i in {1..20}; do lsof -nP -iTCP:8765 -sTCP:LISTEN -t >/dev/null 2>&1 || break; sleep 0.25; done
  fi
fi
if curl -s -m 1 -o /dev/null "$URL/health"; then
  echo "  the host is already running"
else
  LAN=""; [[ "$1" == "--lan" ]] && LAN="--lan"
  nohup python3 plan_server.py --no-open $LAN > .live/server.log 2>&1 &
  for i in {1..40}; do curl -s -m 1 -o /dev/null "$URL/health" && break; sleep 0.25; done
  echo "  the host is running (log: .live/server.log)"
fi
open "$URL/host"
echo "  $URL/host — this window can close."
