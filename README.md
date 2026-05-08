# Warfarin Claude Pet Plugin

Claude Code lifecycle hooks for an ESP32 desktop pet.

This package forwards Claude Code events to a local bridge process. The bridge
sends `STATUS:*` commands over USB serial to the ESP32 firmware.

## Supported Systems

- macOS: LaunchAgent service
- Linux: systemd user service

## Requirements

- Claude Code installed and available as `claude`
- Python 3
- `pyserial` (the installer can install it with `pip --user`)
- ESP32 firmware that accepts:

```text
STATUS:idle
STATUS:working
STATUS:thinking
STATUS:sleeping
STATUS:error
```

## Install

Plug in the ESP32, then run:

```bash
./install_portable_claude_pet.sh
```

The bridge auto-detects common macOS and Linux USB serial ports. If you want to
pin a specific port:

```bash
./install_portable_claude_pet.sh /dev/cu.usbmodem11201  # macOS
./install_portable_claude_pet.sh /dev/ttyACM0           # Linux
```

Then use Claude Code normally:

```bash
claude
```

## Remote SSH / frp

For a remote Claude Code session, keep `claudemon.py` running on the local
machine connected to the ESP32. Forward remote TCP `127.0.0.1:8765` back to the
local machine's `127.0.0.1:8765`, then make the remote Claude hook use HTTP.

SSH reverse forwarding example:

```bash
# Run this from the local machine connected to the ESP32.
ssh -R 8765:127.0.0.1:8765 user@remote

# On the remote machine before running claude:
export CLAUDE_PET_URL=http://127.0.0.1:8765/status
claude
```

With frp, expose the local bridge's TCP `127.0.0.1:8765` to the remote machine
as `127.0.0.1:8765`, then use the same `CLAUDE_PET_URL`. The bridge listens on
both UDP `127.0.0.1:8765` and HTTP `http://127.0.0.1:8765/status`; `/health`
returns `ok`.

## Logs

macOS:

```bash
tail -f bridge/claudemon.log
```

Linux:

```bash
journalctl --user -u claudemon -f
```

## Linux Serial Permission

If the bridge cannot open `/dev/ttyACM0` or `/dev/ttyUSB0`, add your user to
the serial group and re-login:

```bash
sudo usermod -aG dialout "$USER"
```

## Uninstall Service

macOS:

```bash
./uninstall_claudemon_launchagent.sh
```

Linux:

```bash
./uninstall_claudemon_systemd_user.sh
```

The Claude plugin can be removed with:

```bash
claude plugin uninstall warfarin-pet-status
claude plugin marketplace remove esp-pet-tools
```

## State Mapping

| Claude Code hook | Pet state |
| --- | --- |
| `SessionStart` | `idle` |
| `UserPromptSubmit` | `thinking` |
| `PreToolUse` | `working` |
| `PostToolUse` | `working` |
| `Notification` | `error` for permission/input/approval, `idle` for idle/done, otherwise `thinking` |
| `Stop` | `idle` |
| `SessionEnd` | `sleeping` |
| `PostToolUseFailure` / `StopFailure` | `error` |
