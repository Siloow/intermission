# Sourced by the launchers, from the repo folder: make sure this Mac knows where
# the show folder is (see showfolder.py), and hand it to everything they start.
# The first time, it asks; dragging the folder into the Terminal window works.

if [[ -z "$INTERMISSION_SHOW" && -s .show ]]; then
  export INTERMISSION_SHOW="$(<.show)"
fi
if [[ -z "$INTERMISSION_SHOW" || ! -d "$INTERMISSION_SHOW" ]]; then
  echo "Where is the show folder? That is the shared 'Intermission Show' folder in"
  echo "Dropbox: the plan, the Library's media and the bounces, the same on both Macs."
  echo "Drag it into this window (or type its path) and press Enter. A path that"
  echo "doesn't exist yet is created, with the defaults."
  read "SHOWDIR?> "
  SHOWDIR=${(Q)SHOWDIR}                      # drag-and-drop escapes the spaces
  python3 showfolder.py --init "$SHOWDIR" || { read -k1 "?Press any key to close."; exit 1 }
  export INTERMISSION_SHOW="$(<.show)"
  echo
fi
