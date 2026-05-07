#!/bin/bash
# 安装并启动 Linux systemd user service，让 ClaudeMon 常驻后台。
set -e

cd "$(dirname "$0")"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "ERROR: 未找到 systemctl；此脚本仅适用于 systemd Linux。"
  exit 1
fi

PYTHON="$(command -v python3)"
PORT="${1:-}"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/claudemon.service"
LOG_HINT="journalctl --user -u claudemon -f"

mkdir -p "$UNIT_DIR"

cat > "$UNIT" <<EOF
[Unit]
Description=Claude Code ESP32 pet bridge
After=default.target

[Service]
Type=simple
WorkingDirectory=$PWD
Environment=PYTHONUNBUFFERED=1
Environment=CLAUDE_PET_SERIAL_PORT=$PORT
ExecStart=$PYTHON -u $PWD/bridge/claudemon.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now claudemon.service

echo "installed: $UNIT"
echo "status: systemctl --user status claudemon"
echo "log: $LOG_HINT"
echo
echo "If the service cannot open /dev/ttyACM* or /dev/ttyUSB*, add your user to the dialout group and re-login:"
echo "  sudo usermod -aG dialout \"$USER\""
