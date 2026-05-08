#!/bin/bash
# 安装并启动 macOS LaunchAgent，维持本机到远程 Claude 机器的 SSH 反向端口。
set -e

cd "$(dirname "$0")"

REMOTE="${1:-frp}"
REMOTE_PORT="${2:-8765}"
LOCAL_PORT="${3:-8765}"
LABEL="com.solarise.esp-pet.remote-tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PWD/bridge/remote-tunnel.log"
ERR="$PWD/bridge/remote-tunnel.err.log"
SSH="$(command -v ssh)"

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
    <string>$SSH</string>
    <string>-N</string>
    <string>-o</string>
    <string>BatchMode=yes</string>
    <string>-o</string>
    <string>ExitOnForwardFailure=yes</string>
    <string>-o</string>
    <string>ServerAliveInterval=30</string>
    <string>-o</string>
    <string>ServerAliveCountMax=3</string>
    <string>-R</string>
    <string>127.0.0.1:$REMOTE_PORT:127.0.0.1:$LOCAL_PORT</string>
    <string>$REMOTE</string>
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
echo "remote: $REMOTE"
echo "forward: remote 127.0.0.1:$REMOTE_PORT -> local 127.0.0.1:$LOCAL_PORT"
echo "log: $LOG"
echo "err: $ERR"
