#!/bin/bash
# 在一台新的 macOS 机器上安装 Claude Code 桌宠插件和桥接服务。
set -e

cd "$(dirname "$0")"

PORT="${1:-/dev/cu.usbmodem11201}"

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 未找到 claude 命令。请先安装 Claude Code。"
  exit 1
fi

if ! python3 -c "import serial" >/dev/null 2>&1; then
  echo "Installing Python dependency: pyserial"
  python3 -m pip install --user pyserial
fi

echo "Adding local Claude marketplace..."
claude plugin marketplace add "$PWD" >/dev/null 2>&1 || true
claude plugin marketplace update esp-pet-tools

echo "Installing Claude plugin..."
claude plugin install warfarin-pet-status@esp-pet-tools --scope user >/dev/null 2>&1 || true
claude plugin update warfarin-pet-status@esp-pet-tools >/dev/null 2>&1 || true

echo "Installing ClaudeMon LaunchAgent..."
case "$(uname -s)" in
  Darwin)
    ./install_claudemon_launchagent.sh "$PORT"
    ;;
  Linux)
    ./install_claudemon_systemd_user.sh "$PORT"
    ;;
  *)
    echo "WARN: unsupported OS for service install: $(uname -s)"
    echo "Run bridge manually with: ./bridge/claudemon.py \"$PORT\""
    ;;
esac

echo
echo "Done."
echo "Check plugin status with: claude plugin list"
if [ "$(uname -s)" = "Darwin" ]; then
  echo "Check bridge log with: tail -f \"$PWD/bridge/claudemon.log\""
elif [ "$(uname -s)" = "Linux" ]; then
  echo "Check bridge log with: journalctl --user -u claudemon -f"
fi
