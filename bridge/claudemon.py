#!/usr/bin/env python3
"""
ClaudeMon - Claude Code 状态桥接服务

运行后常驻后台，占用 ESP32 串口；Claude Code plugin hooks 通过 UDP
localhost:8765 发送事件，本服务把事件映射成固件支持的 STATUS:* 指令。

用法:
  python3 claudemon.py
  python3 claudemon.py /dev/cu.usbmodem11201
  python3 claudemon.py -n          # dry-run，只打印不连串口
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Optional

import serial


SERIAL_BAUD = 115200
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765
PUSH_INTERVAL = 0.25
SLEEP_TIMEOUT = 180.0
ERROR_HOLD = 5.0
VALID_STATES = {"idle", "working", "thinking", "sleeping", "error"}


def has_word(text: str, words: tuple[str, ...]) -> bool:
    for word in words:
        if re.search(rf"(^|[^a-z0-9]){re.escape(word)}([^a-z0-9]|$)", text):
            return True
    return False


@dataclass
class RuntimeState:
    state: str = "idle"
    last_event: float = 0.0
    last_push: float = 0.0
    error_until: float = 0.0
    last_printed_state: str = ""


def open_serial(port: str) -> serial.Serial:
    while True:
        selected = port
        if not selected:
            patterns = (
                "/dev/cu.usbmodem*",
                "/dev/tty.usbmodem*",
                "/dev/ttyACM*",
                "/dev/ttyUSB*",
            )
            ports = []
            for pattern in patterns:
                ports.extend(glob.glob(pattern))
            ports = sorted(dict.fromkeys(ports))
            selected = ports[0] if ports else ""

        if not selected:
            print("[WARN] 未找到 ESP32 串口，3 秒后重试...")
            time.sleep(3)
            continue

        try:
            ser = serial.Serial(selected, SERIAL_BAUD, timeout=1)
            time.sleep(1.5)
            print(f"[OK] 串口已连接: {selected}")
            return ser
        except serial.SerialException as exc:
            print(f"[WARN] 串口连接失败: {exc}, 3 秒后重试...")
            time.sleep(3)


def push_state(ser: serial.Serial, state: str) -> None:
    ser.write(f"STATUS:{state}\n".encode("utf-8"))
    ser.flush()


def open_udp(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def coerce_state(packet: dict, current: RuntimeState) -> str:
    now = time.time()
    state = str(packet.get("state") or "").lower()
    event = str(packet.get("event") or "")
    reason = str(packet.get("reason") or packet.get("notification_type") or "").lower()
    message = str(packet.get("message") or "").lower()
    notification_text = f"{reason} {message}"

    if state not in VALID_STATES:
        if event == "SessionStart":
            state = "idle"
        elif event == "PreToolUse":
            state = "working"
        elif event == "PostToolUse":
            state = "working"
        elif event in ("PostToolUseFailure", "StopFailure"):
            state = "error"
        elif event == "Stop":
            state = "idle"
        elif event == "SessionEnd":
            state = "sleeping"
        elif event == "Notification":
            if has_word(notification_text, ("idle", "done")):
                state = "idle"
            elif has_word(notification_text, ("permission", "approval", "input")):
                state = "error"
            else:
                state = "thinking"
        else:
            state = "thinking"

    if state == "error":
        current.error_until = now + ERROR_HOLD
    elif state in ("idle", "sleeping"):
        current.error_until = 0.0
    elif current.error_until > now:
        return "error"

    return state


def describe_packet(packet: dict, state: str) -> str:
    event = packet.get("event") or "Unknown"
    tool = packet.get("tool") or "-"
    reason = packet.get("reason") or "-"
    return f"event={event} tool={tool} reason={reason} -> {state.upper()}"


def emit_state(ser: Optional[serial.Serial], runtime: RuntimeState, dry_run: bool, port: str) -> Optional[serial.Serial]:
    runtime.last_push = time.time()
    if ser:
        try:
            push_state(ser, runtime.state)
        except serial.SerialException:
            print("[WARN] 串口断开，尝试重连...")
            try:
                ser.close()
            except Exception:
                pass
            ser = open_serial(port)
    elif dry_run and runtime.state != runtime.last_printed_state:
        print(f"[{time.strftime('%H:%M:%S')}] dry-run STATUS:{runtime.state}")
        runtime.last_printed_state = runtime.state
    return ser


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code 状态桥接服务")
    parser.add_argument("port", nargs="?", default="", help="ESP32 串口路径，默认自动检测 macOS/Linux USB 串口")
    parser.add_argument("--dry-run", "-n", action="store_true", help="只打印状态，不连接串口")
    parser.add_argument("--udp-host", default=UDP_HOST, help=f"UDP 监听地址，默认 {UDP_HOST}")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT, help=f"UDP 监听端口，默认 {UDP_PORT}")
    parser.add_argument("--sleep-timeout", type=float, default=SLEEP_TIMEOUT, help="多久没有事件后进入 sleeping")
    args = parser.parse_args()

    running = True

    def on_signal(signum, _frame):
      nonlocal running
      print(f"\n[INFO] 收到信号 {signum}, 正在退出...")
      running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    env_port = os.environ.get("CLAUDE_PET_SERIAL_PORT", "")
    if not args.port and env_port:
        args.port = env_port

    ser: Optional[serial.Serial] = None
    if not args.dry_run:
        ser = open_serial(args.port)

    sock = open_udp(args.udp_host, args.udp_port)
    runtime = RuntimeState(last_event=time.time())

    print(f"[INFO] ClaudeMon UDP: {args.udp_host}:{args.udp_port}")
    print("[INFO] 等待 Claude Code hook 事件...")
    print("-" * 72)

    while running:
        now = time.time()
        got_packet = False

        while True:
            try:
                data, _addr = sock.recvfrom(65535)
            except BlockingIOError:
                break

            got_packet = True
            runtime.last_event = now
            try:
                packet = json.loads(data.decode("utf-8"))
                if not isinstance(packet, dict):
                    packet = {"value": packet}
            except Exception as exc:
                packet = {"event": "MalformedPacket", "state": "error", "reason": str(exc)}

            runtime.state = coerce_state(packet, runtime)
            print(f"[{time.strftime('%H:%M:%S')}] {describe_packet(packet, runtime.state)}")
            ser = emit_state(ser, runtime, args.dry_run, args.port)

        if not got_packet and now - runtime.last_event > args.sleep_timeout:
            runtime.state = "sleeping"

        if now - runtime.last_push >= PUSH_INTERVAL:
            ser = emit_state(ser, runtime, args.dry_run, args.port)

        time.sleep(0.05)

    sock.close()
    if ser:
        ser.close()
    print("[INFO] 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
