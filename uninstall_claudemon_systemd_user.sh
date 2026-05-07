#!/bin/bash
# 停止并移除 Linux systemd user service。
set -e

UNIT="$HOME/.config/systemd/user/claudemon.service"

systemctl --user disable --now claudemon.service >/dev/null 2>&1 || true
rm -f "$UNIT"
systemctl --user daemon-reload >/dev/null 2>&1 || true
echo "removed: $UNIT"
