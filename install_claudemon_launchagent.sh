#!/bin/bash
# 安装并启动 macOS LaunchAgent，让 ClaudeMon 常驻后台。
set -e

cd "$(dirname "$0")"

LABEL="com.solarise.esp-pet.claudemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PWD/bridge/claudemon.log"
ERR="$PWD/bridge/claudemon.err.log"
PORT="${1:-/dev/cu.usbmodem11201}"
PYTHON="$(command -v python3)"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>$PWD/bridge/claudemon.py</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PWD</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$ERR</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "installed: $PLIST"
echo "log: $LOG"
echo "err: $ERR"
