#!/usr/bin/env python3
"""
KimiMon - Kimi Code CLI 状态监控桥接服务 (v2)

改进点:
  1. EMA 平滑 CPU，避免瞬时毛刺
  2. 子进程检测：发现工具调用子进程时判定为 working
  3. 内存变化率 + IO 活动辅助判断 thinking/working
  4. 网络连接活跃度检测（macOS 上可能需授权）

状态规则:
  working  - EMA CPU > 15% 或有活跃子进程/IO突增
  thinking - EMA CPU > 3% 或内存持续增长/网络等待
  idle     - 无明显活动
  sleeping - 连续 idle 超过 120 秒
  error    - Kimi 进程消失

用法:
  python3 kimimon.py
  python3 kimimon.py -n          # 仅打印状态，不连接串口
"""

import sys
import time
import signal
import argparse
import glob
from typing import Optional, Tuple

import psutil
import serial

# ==================== 配置 ====================
PROCESS_KEYWORDS = ["Kimi Code", "kimi"]
SERIAL_BAUD = 115200
PUSH_INTERVAL = 1.0        # 串口推送间隔 (秒)
WORKING_THRESHOLD = 15.0   # working CPU 阈值 (%)
THINKING_THRESHOLD = 3.0   # thinking CPU 阈值 (%)
SLEEP_TIMEOUT = 120.0      # sleeping 判定阈值 (秒)

EMA_ALPHA = 0.3            # CPU 指数滑动平均系数 (越大越敏感)
MEM_GROWTH_THRESHOLD = 1.0  # 内存增长判定 threshold (MB/s)
IO_BURST_THRESHOLD = 50    # IO 突增阈值 (KB/interval)

# 子进程名关键词，出现说明在做工具调用 / 代码执行
CHILD_TOOL_KEYWORDS = [
    "python", "python3", "node", "npm", "bash", "zsh", "sh",
    "rustc", "cargo", "go", "java", "javac", "gcc", "g++", "clang",
    "docker", "kubectl", "terraform", "ansible",
]

# ==================== 状态机 ====================
class StateMachine:
    def __init__(self):
        self.state = "idle"
        self.idle_since = time.time()
        self.last_push = 0.0
        self._prev_state = None

    def update(self, indicators: dict) -> str:
        cpu = indicators.get("cpu_ema", 0.0)
        has_active_children = indicators.get("has_active_children", False)
        io_burst = indicators.get("io_burst", 0)
        mem_growth = indicators.get("mem_growth", 0.0)
        net_connections = indicators.get("net_connections", 0)
        process_alive = indicators.get("process_alive", False)

        if not process_alive:
            new_state = "error"
        elif has_active_children or io_burst > IO_BURST_THRESHOLD or cpu > WORKING_THRESHOLD:
            new_state = "working"
        elif cpu > THINKING_THRESHOLD or mem_growth > MEM_GROWTH_THRESHOLD or net_connections > 0:
            new_state = "thinking"
        else:
            new_state = "idle"

        # sleeping: 持续 idle 超时
        if new_state == "idle":
            if self.state not in ("idle", "sleeping"):
                self.idle_since = time.time()
            if time.time() - self.idle_since > SLEEP_TIMEOUT:
                new_state = "sleeping"
        else:
            self.idle_since = time.time()

        self.state = new_state
        return new_state

    def should_push(self, interval: float) -> bool:
        now = time.time()
        if now - self.last_push >= interval or self.state != self._prev_state:
            self.last_push = now
            self._prev_state = self.state
            return True
        return False


# ==================== 进程监控 (psutil) ====================
def find_kimi_process() -> Optional[psutil.Process]:
    """查找 Kimi Code 进程"""
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent"]):
        try:
            name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            text = f"{name} {cmdline}"
            for kw in PROCESS_KEYWORDS:
                if kw.lower() in text.lower():
                    if proc.pid == psutil.Process().pid:
                        continue
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_kimi_cpu(proc: Optional[psutil.Process], prev_ema: float = 0.0) -> Tuple[float, float]:
    """获取 Kimi 进程的 CPU 使用率，并计算 EMA
    返回 (instant_cpu, ema_cpu)
    """
    if proc is None:
        return 0.0, prev_ema
    try:
        proc.cpu_percent(interval=None)
        time.sleep(0.3)
        instant = proc.cpu_percent(interval=None)
        ema = EMA_ALPHA * instant + (1 - EMA_ALPHA) * prev_ema
        return instant, ema
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0, prev_ema


def get_process_indicators(proc: Optional[psutil.Process]) -> dict:
    """收集多维度进程指标"""
    indicators = {
        "process_alive": proc is not None,
        "cpu_instant": 0.0,
        "cpu_ema": 0.0,
        "has_active_children": False,
        "mem_rss": 0,
        "mem_growth": 0.0,
        "io_read": 0,
        "io_write": 0,
        "io_burst": 0,
        "net_connections": 0,
        "child_count": 0,
    }

    if proc is None:
        return indicators

    try:
        # CPU (需要在主循环里做 EMA，这里只返回 instant)
        proc.cpu_percent(interval=None)
        time.sleep(0.2)
        indicators["cpu_instant"] = proc.cpu_percent(interval=None)

        # 内存
        mem = proc.memory_info()
        indicators["mem_rss"] = mem.rss // (1024 * 1024)  # MB

        # 子进程检测
        children = proc.children(recursive=True)
        indicators["child_count"] = len(children)
        for child in children:
            try:
                if child.status() == psutil.STATUS_RUNNING:
                    name = (child.name() or "").lower()
                    if any(kw in name for kw in CHILD_TOOL_KEYWORDS):
                        indicators["has_active_children"] = True
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # IO 计数器 (macOS 可能需要授权，捕获异常)
        try:
            io1 = proc.io_counters()
            time.sleep(0.3)
            io2 = proc.io_counters()
            indicators["io_read"] = (io2.read_bytes - io1.read_bytes) // 1024
            indicators["io_write"] = (io2.write_bytes - io1.write_bytes) // 1024
            indicators["io_burst"] = indicators["io_read"] + indicators["io_write"]
        except (AttributeError, psutil.AccessDenied):
            indicators["io_burst"] = 0

        # 网络连接 (macOS 通常需要 root，捕获异常)
        try:
            conns = proc.connections(kind="inet")
            indicators["net_connections"] = len([c for c in conns if c.status == psutil.CONN_ESTABLISHED])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            indicators["net_connections"] = 0

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        indicators["process_alive"] = False

    return indicators


# ==================== 串口通信 ====================
def open_serial(port: str) -> serial.Serial:
    while True:
        if not port:
            ports = sorted(glob.glob("/dev/cu.usbmodem*"))
            if ports:
                port = ports[0]
            else:
                print("[WARN] 未找到 ESP32 串口，3秒后重试...")
                time.sleep(3)
                continue
        try:
            s = serial.Serial(port, SERIAL_BAUD, timeout=1)
            time.sleep(1.5)
            print(f"[OK] 串口已连接: {port}")
            return s
        except serial.SerialException as e:
            print(f"[WARN] 串口连接失败: {e}, 3秒后重试...")
            time.sleep(3)
            port = ""


def push_state(ser: serial.Serial, state: str):
    msg = f"STATUS:{state}\n".encode("utf-8")
    ser.write(msg)
    ser.flush()


# ==================== 主循环 ====================
def main():
    parser = argparse.ArgumentParser(description="Kimi Code 状态监控桥接 v2")
    parser.add_argument(
        "port", nargs="?", default="",
        help="ESP32 串口设备路径 (默认自动检测)"
    )
    parser.add_argument(
        "--interval", "-i", type=float, default=PUSH_INTERVAL,
        help=f"状态推送间隔秒数 (默认 {PUSH_INTERVAL})"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="仅打印状态，不连接串口"
    )
    args = parser.parse_args()

    sm = StateMachine()
    ser: Optional[serial.Serial] = None
    running = True

    def on_signal(signum, _frame):
        nonlocal running
        print(f"\n[INFO] 收到信号 {signum}, 正在退出...")
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    if not args.dry_run:
        ser = open_serial(args.port)

    print(f"[INFO] 开始监控进程 (关键词: {PROCESS_KEYWORDS})")
    print(f"[INFO] 阈值: working>{WORKING_THRESHOLD}% | thinking>{THINKING_THRESHOLD}% | sleep>{SLEEP_TIMEOUT}s")
    print(f"[INFO] 子进程工具关键词: {CHILD_TOOL_KEYWORDS}")
    print("-" * 65)

    cpu_ema = 0.0
    prev_mem = 0
    prev_proc: Optional[psutil.Process] = None

    while running:
        proc = find_kimi_process()
        alive = proc is not None

        if alive and proc != prev_proc:
            # 进程切换时重置 EMA
            cpu_ema = 0.0
            prev_mem = 0
        prev_proc = proc

        # 获取指标
        indicators = get_process_indicators(proc)
        indicators["process_alive"] = alive

        # 计算 EMA CPU
        instant = indicators["cpu_instant"]
        if alive:
            cpu_ema = EMA_ALPHA * instant + (1 - EMA_ALPHA) * cpu_ema
        else:
            cpu_ema = 0.0
        indicators["cpu_ema"] = cpu_ema

        # 计算内存增长率 (MB/s，按 ~0.5s 采样估算)
        mem_now = indicators["mem_rss"]
        if prev_mem > 0 and alive:
            indicators["mem_growth"] = max(0.0, (mem_now - prev_mem) / 0.5)
        prev_mem = mem_now

        state = sm.update(indicators)

        if sm.should_push(args.interval):
            pid_str = str(proc.pid) if proc else "N/A"
            child_str = f"C={indicators['child_count']}" if indicators['child_count'] else "C=0"
            tool_flag = "[TOOL]" if indicators['has_active_children'] else ""
            line = (
                f"[{time.strftime('%H:%M:%S')}] PID={pid_str:>6} "
                f"CPU={instant:5.1f}% EMA={cpu_ema:5.1f}% MEM={mem_now:4d}MB "
                f"{child_str} IO={indicators['io_burst']:3d}K NET={indicators['net_connections']} "
                f"-> {state.upper():8s} {tool_flag}"
            )
            print(line)
            if ser:
                try:
                    push_state(ser, state)
                except serial.SerialException:
                    print("[WARN] 串口断开，尝试重连...")
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = open_serial(args.port)

        time.sleep(0.3)

    if ser:
        ser.close()
    print("[INFO] 已退出")


if __name__ == "__main__":
    main()
