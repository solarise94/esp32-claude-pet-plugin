# esp32 Claude Pet Plugin

Claude Code lifecycle hooks for an ESP32 desktop pet.
This package forwards Claude Code events to a local bridge process. The bridge
sends `STATUS:*` commands over USB serial to the ESP32 firmware.
不懂代码纯vib别骂我 (ó﹏ò｡) 

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

If the serial port is not auto-detected or differs from the default:

```bash
./install_portable_claude_pet.sh /dev/cu.usbmodem11201  # macOS
./install_portable_claude_pet.sh /dev/ttyACM0           # Linux
```

Then use Claude Code normally:

```bash
claude
```

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
