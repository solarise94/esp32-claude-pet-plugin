#!/usr/bin/env python3
"""Forward one Claude Code hook event to the local pet bridge.

The hook must never block Claude Code. It reads Claude's hook JSON from stdin,
maps it to a pet state, sends a UDP packet to localhost, and exits 0 even when
the bridge is not running.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time


HOST = os.environ.get("CLAUDE_PET_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLAUDE_PET_PORT", "8765"))


def read_payload() -> dict:
    try:
        text = sys.stdin.read()
        if not text.strip():
            return {}
        value = json.loads(text)
        return value if isinstance(value, dict) else {"value": value}
    except Exception as exc:
        return {"hook_parse_error": str(exc)}


def map_event_to_state(event: str, payload: dict) -> str:
    if event == "SessionStart":
        return "idle"
    if event == "UserPromptSubmit":
        return "thinking"
    if event == "PreToolUse":
        return "working"
    if event == "PostToolUse":
        return "thinking"
    if event in ("PostToolUseFailure", "StopFailure"):
        return "error"
    if event == "Stop":
        return "idle"
    if event == "SessionEnd":
        return "sleeping"

    if event == "Notification":
        reason = str(payload.get("reason") or payload.get("notification_type") or "").lower()
        message = str(payload.get("message") or "").lower()
        text = f"{reason} {message}"
        if "permission" in text or "approval" in text or "input" in text:
            return "thinking"
        if "idle" in text or "done" in text:
            return "idle"
        return "thinking"

    return "thinking"


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "Unknown"
    payload = read_payload()
    state = map_event_to_state(event, payload)

    packet = {
        "source": "claude-code",
        "event": event,
        "state": state,
        "time": time.time(),
        "cwd": payload.get("cwd") or payload.get("project_dir") or os.getcwd(),
        "tool": payload.get("tool_name") or payload.get("tool"),
        "reason": payload.get("reason") or payload.get("notification_type"),
    }

    try:
        data = json.dumps(packet, ensure_ascii=False).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.05)
            sock.sendto(data, (HOST, PORT))
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
