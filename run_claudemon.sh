#!/bin/bash
# 启动 Claude Code -> ESP32 桌宠状态桥接。
set -e

cd "$(dirname "$0")"
PORT="${1:-}"
LOG="$PWD/bridge/claudemon.log"
PIDFILE="$PWD/bridge/claudemon.pid"

if [ "$1" = "--daemon" ] || [ "$1" = "-d" ]; then
  PORT="${2:-}"
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "claudemon already running: PID $(cat "$PIDFILE")"
    exit 0
  fi
  : > "$LOG"
  nohup python3 -u ./bridge/claudemon.py "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  sleep 0.5
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "claudemon started: PID $(cat "$PIDFILE"), log: $LOG"
  else
    echo "claudemon failed to start; log: $LOG"
    tail -n 40 "$LOG" || true
    exit 1
  fi
  exit 0
fi

exec ./bridge/claudemon.py "$PORT"
