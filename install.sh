#!/bin/sh
# ember installer for macOS.
#   ./install.sh              set up, then start the mind in this window
#   ./install.sh --no-start   set up only
#   ./install.sh --autostart  set up, and start the mind every time you log in (see README: untested)
set -eu
cd "$(dirname "$0")"
HERE="$(pwd)"

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "Installing uv (it looks after Python so you don't have to)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

echo "Getting the mind ready (the first time takes a minute)..."
"$UV" sync --no-dev --quiet
"$UV" run --no-dev ember --setup

case "${1:-}" in
--no-start)
    echo "Set up. To start the mind:  $UV run --project \"$HERE\" --no-dev ember"
    ;;
--autostart)
    PLIST="$HOME/Library/LaunchAgents/local.ember.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.ember</string>
  <key>ProgramArguments</key><array>
    <string>$UV</string><string>run</string><string>--project</string><string>$HERE</string>
    <string>--no-dev</string><string>ember</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
PLIST_END
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "The mind now starts by itself when you log in. To undo:  launchctl unload \"$PLIST\" && rm \"$PLIST\""
    echo "Open http://127.0.0.1:8971/ to look at what it keeps. Next: GUIDE-HUMAN.md, step 3."
    ;;
*)
    echo "Starting the mind. Leave this window open. Press Ctrl+C to stop it."
    echo "Next: GUIDE-HUMAN.md, step 3."
    exec "$UV" run --no-dev ember
    ;;
esac
