#!/bin/bash
# 停止并移除 ClaudeMon LaunchAgent。
set -e

LABEL="com.solarise.esp-pet.claudemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
echo "removed: $PLIST"
