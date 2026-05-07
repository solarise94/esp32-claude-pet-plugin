# Claude Code 桌宠桥接

这个目录包含一个本地 Claude Code plugin 和一个常驻串口桥接服务。

## 启动桥接

```bash
cd /Users/solarise/Ranalysis/ESP/esp-pet-monitor
./run_claudemon.sh
```

后台运行：

```bash
./run_claudemon.sh --daemon
tail -f bridge/claudemon.log
```

macOS 常驻后台：

```bash
./install_claudemon_launchagent.sh
tail -f bridge/claudemon.log
```

停止并移除常驻服务：

```bash
./uninstall_claudemon_launchagent.sh
```

Linux systemd user service：

```bash
./install_claudemon_systemd_user.sh /dev/ttyACM0
journalctl --user -u claudemon -f
```

Linux 串口权限不足时：

```bash
sudo usermod -aG dialout "$USER"
```

桥接服务会占用 ESP32 串口，监听 `127.0.0.1:8765` 的 Claude hook 事件，并向固件发送：

```text
STATUS:idle
STATUS:working
STATUS:thinking
STATUS:sleeping
STATUS:error
```

## 安装 Claude Code 插件

本项目已经提供本地 marketplace。安装后直接运行普通 `claude` 即可自动加载桌宠插件。

```bash
cd /Users/solarise/Ranalysis/ESP/esp-pet-monitor
claude plugin marketplace add /Users/solarise/Ranalysis/ESP/esp-pet-monitor
claude plugin install warfarin-pet-status@esp-pet-tools --scope user
```

检查插件状态：

```bash
claude plugin list
```

看到 `warfarin-pet-status@esp-pet-tools` 为 `enabled` 后，直接运行 `claude` 即可。

## 状态映射

| Claude Code hook | 桌宠状态 |
| --- | --- |
| `SessionStart` | `idle` |
| `UserPromptSubmit` | `thinking` |
| `PreToolUse` | `working` |
| `PostToolUse` | `thinking` |
| `Notification` | `thinking` 或 `idle` |
| `Stop` | `idle` |
| `SessionEnd` | `sleeping` |
| `PostToolUseFailure` / `StopFailure` | `error` |

## 测试

```bash
./bridge/claudemon.py -n
printf '{"tool_name":"ManualTest"}' | ./claude-pet-plugin/scripts/claude_pet_hook.py PreToolUse
```
