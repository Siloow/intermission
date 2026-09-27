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
case "$PWD" in
  *Dropbox*|*"Google Drive"*|*OneDrive*|*iCloud*)
    xattr -w com.dropbox.ignored 1 .live 2>/dev/null
    xattr -w com.apple.fileprovider.ignore#P 1 .live 2>/dev/null ;;
esac

URL="http://localhost:8765"
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
