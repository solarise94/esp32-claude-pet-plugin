#!/bin/bash
# 停止并移除 SSH 反向端口 LaunchAgent。
set -e

LABEL="com.solarise.esp-pet.remote-tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "removed: $PLIST"
