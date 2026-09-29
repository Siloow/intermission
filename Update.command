#!/bin/zsh
# Update the tools: fetch what changed on GitHub. Double-click.
# The show folder (plan, media, bounces) is not touched: Dropbox keeps that in sync.

cd "$(dirname "$0")" || exit 1
echo "  updating the tools from GitHub …\n"
if git pull --ff-only; then
  echo "\n  up to date. If Intermission.command was running, start it again."
else
  echo "\n  that didn't work — send Sil a screenshot of this window."
fi
read -k1 "?Press any key to close."
