#!/usr/bin/env python3
"""
ClaudeMon - Claude Code 状态桥接服务

运行后常驻后台，占用 ESP32 串口；Claude Code plugin hooks 通过 UDP
localhost:8765 或 HTTP POST /status 发送事件，本服务把事件映射成固件支持的
STATUS:* 指令。

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, SimpleQueue
from threading import Thread
from typing import Optional

import serial


SERIAL_BAUD = 115200
SERIAL_RETRY_INTERVAL = 3.0
UDP_HOST = "127.0.0.1"
UDP_PORT = 8765
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765
PUSH_INTERVAL = 0.25
SLEEP_TIMEOUT = 180.0
ACTIVE_STALE_TIMEOUT = 3600.0
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
    last_serial_retry: float = 0.0


class StatusHttpServer(ThreadingHTTPServer):
    def __init__(self, server_address, request_handler_class, event_queue: SimpleQueue):
        super().__init__(server_address, request_handler_class)
        self.event_queue = event_queue


class StatusRequestHandler(BaseHTTPRequestHandler):
    server: StatusHttpServer

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path not in ("/status", "/"):
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        body = self.rfile.read(min(length, 65535))
        try:
            packet = json.loads(body.decode("utf-8"))
            if not isinstance(packet, dict):
                packet = {"value": packet}
        except Exception as exc:
            packet = {"event": "MalformedHttpPacket", "state": "error", "reason": str(exc)}

        self.server.event_queue.put(packet)
        self.send_response(204)
        self.end_headers()


def find_serial_port(port: str) -> str:
    if port:
        return port

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
    return ports[0] if ports else ""


def try_open_serial(port: str) -> Optional[serial.Serial]:
    selected = find_serial_port(port)
    if not selected:
        print("[WARN] 未找到 ESP32 串口，将继续后台重试...")
        return None

    try:
        ser = serial.Serial(selected, SERIAL_BAUD, timeout=1)
        time.sleep(1.5)
        print(f"[OK] 串口已连接: {selected}")
        return ser
    except serial.SerialException as exc:
        print(f"[WARN] 串口连接失败: {exc}, 将继续后台重试...")
        return None


def push_state(ser: serial.Serial, state: str) -> None:
    ser.write(f"STATUS:{state}\n".encode("utf-8"))
    ser.flush()


def open_udp(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def open_http(host: str, port: int, event_queue: SimpleQueue) -> StatusHttpServer:
    server = StatusHttpServer((host, port), StatusRequestHandler, event_queue)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


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
            ser = None
    elif dry_run and runtime.state != runtime.last_printed_state:
        print(f"[{time.strftime('%H:%M:%S')}] dry-run STATUS:{runtime.state}")
        runtime.last_printed_state = runtime.state
    elif not dry_run and time.time() - runtime.last_serial_retry >= SERIAL_RETRY_INTERVAL:
        runtime.last_serial_retry = time.time()
        ser = try_open_serial(port)
        if ser:
            push_state(ser, runtime.state)
    return ser


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code 状态桥接服务")
    parser.add_argument("port", nargs="?", default="", help="ESP32 串口路径，默认自动检测 macOS/Linux USB 串口")
    parser.add_argument("--dry-run", "-n", action="store_true", help="只打印状态，不连接串口")
    parser.add_argument("--udp-host", default=UDP_HOST, help=f"UDP 监听地址，默认 {UDP_HOST}")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT, help=f"UDP 监听端口，默认 {UDP_PORT}")
    parser.add_argument("--http-host", default=HTTP_HOST, help=f"HTTP 监听地址，默认 {HTTP_HOST}")
    parser.add_argument("--http-port", type=int, default=HTTP_PORT, help=f"HTTP 监听端口，默认 {HTTP_PORT}")
    parser.add_argument("--no-http", action="store_true", help="禁用 HTTP /status 监听")
    parser.add_argument("--no-udp", action="store_true", help="禁用 UDP 监听")
    parser.add_argument("--sleep-timeout", type=float, default=SLEEP_TIMEOUT, help="idle 后多久没有事件进入 sleeping")
    parser.add_argument("--active-stale-timeout", type=float, default=ACTIVE_STALE_TIMEOUT, help="working/thinking/error 多久没有事件后兜底进入 sleeping")
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
        ser = try_open_serial(args.port)

    if args.no_udp and args.no_http:
        print("[ERROR] UDP 和 HTTP 不能同时禁用")
        return 2

    event_queue: SimpleQueue = SimpleQueue()
    sock: Optional[socket.socket] = None
    httpd: Optional[StatusHttpServer] = None
    if not args.no_udp:
        sock = open_udp(args.udp_host, args.udp_port)
    if not args.no_http:
        httpd = open_http(args.http_host, args.http_port, event_queue)
    runtime = RuntimeState(last_event=time.time())

    if sock:
        print(f"[INFO] ClaudeMon UDP: {args.udp_host}:{args.udp_port}")
    if httpd:
        print(f"[INFO] ClaudeMon HTTP: http://{args.http_host}:{args.http_port}/status")
    print("[INFO] 等待 Claude Code hook 事件...")
    print("-" * 72)

    while running:
        now = time.time()
        got_packet = False

        if sock:
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

        while True:
            try:
                packet = event_queue.get_nowait()
            except Empty:
                break

            got_packet = True
            runtime.last_event = now
            runtime.state = coerce_state(packet, runtime)
            print(f"[{time.strftime('%H:%M:%S')}] {describe_packet(packet, runtime.state)}")
            ser = emit_state(ser, runtime, args.dry_run, args.port)

        idle_stale = runtime.state == "idle" and now - runtime.last_event > args.sleep_timeout
        active_stale = runtime.state in ("working", "thinking", "error") and now - runtime.last_event > args.active_stale_timeout
        if not got_packet and (idle_stale or active_stale):
            runtime.state = "sleeping"

        if now - runtime.last_push >= PUSH_INTERVAL:
            ser = emit_state(ser, runtime, args.dry_run, args.port)

        time.sleep(0.05)

    if sock:
        sock.close()
    if httpd:
        httpd.shutdown()
        httpd.server_close()
    if ser:
        ser.close()
    print("[INFO] 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
