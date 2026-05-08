# Warfarin ESP Pet Claude Plugin Package

这个包用于把 Claude Code 状态接到 ESP32 桌宠，支持 macOS 和 systemd Linux。

## 包含内容

- `claude-pet-plugin/`：Claude Code plugin
- `.claude-plugin/marketplace.json`：本地 Claude marketplace
- `bridge/claudemon.py`：常驻串口桥接服务
- `install_portable_claude_pet.sh`：一键安装脚本
- `install_claudemon_launchagent.sh`：安装 macOS LaunchAgent
- `uninstall_claudemon_launchagent.sh`：卸载 macOS LaunchAgent
- `install_remote_tunnel_launchagent.sh`：安装 macOS SSH 反向端口 LaunchAgent
- `uninstall_remote_tunnel_launchagent.sh`：卸载 macOS SSH 反向端口 LaunchAgent
- `install_claudemon_systemd_user.sh`：安装 Linux systemd user service
- `uninstall_claudemon_systemd_user.sh`：卸载 Linux systemd user service

## 在另一台机器上安装

1. 解压这个包。
2. 插上 ESP32-C6-LCD-1.47。
3. 在包目录运行：

```bash
./install_portable_claude_pet.sh
```

如果串口不是默认端口，传入端口：

```bash
./install_portable_claude_pet.sh /dev/cu.usbmodemXXXXX  # macOS
./install_portable_claude_pet.sh /dev/ttyACM0           # Linux 常见
```

Linux 如果无法打开串口，通常需要加入 `dialout` 组并重新登录：

```bash
sudo usermod -aG dialout "$USER"
```

## 使用

安装完成后正常运行：

```bash
claude
```

## Remote SSH / frp

For remote Claude Code sessions, set the hook to send HTTP instead of local UDP:

```bash
export CLAUDE_PET_URL=http://127.0.0.1:8765/status
```

Then forward remote TCP `127.0.0.1:8765` back to the local machine running
`claudemon.py`, for example with SSH reverse forwarding:

```bash
ssh -R 8765:127.0.0.1:8765 user@remote
```

The bridge listens on both UDP `127.0.0.1:8765` and HTTP
`http://127.0.0.1:8765/status`.

macOS 可以用 LaunchAgent 常驻 SSH 反向端口：

```bash
./install_remote_tunnel_launchagent.sh frp 8765 8765
```

查看桥接日志：

```bash
tail -f bridge/claudemon.log
```

Linux 日志：

```bash
journalctl --user -u claudemon -f
```

检查插件：

```bash
claude plugin list
```

## 状态映射

- `SessionStart` -> `idle`
- `UserPromptSubmit` -> `thinking`
- `PreToolUse` -> `working`
- `PostToolUse` -> `working`
- `Notification` -> `error` for permission/input/approval, `idle` for idle/done, otherwise `thinking`
- `Stop` -> `idle`
- `SessionEnd` -> `sleeping`
- `PostToolUseFailure` / `StopFailure` -> `error`
