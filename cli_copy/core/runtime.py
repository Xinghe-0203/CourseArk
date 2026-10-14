"""
WebUI 运行时桥（仅 WebUI 副本使用）

为无 TUI 的 Worker 提供两个能力：
1. 事件上报：把日志与进度写成 JSON Lines 到标准输出，供 Web 进程解析
2. 协作式控制：读取控制文件，在网络请求、进度上报、长等待等安全边界响应暂停/停止

设计约束：
- 不改变原有业务逻辑，只提供可选的钩子
- 未初始化时所有函数退化为无操作，保证副本仍可在纯 CLI 场景下导入
"""

import json
import os
import sys
import threading
import time

# ============================================================
# 控制信号
# ============================================================


class StopRequested(BaseException):
    """协作式停止信号，由控制检查点抛出"""


class PauseAwareSleep:
    """占位类型，便于外部 isinstance 判断（实际由 sleep() 函数实现）"""


CONTROL_RUN = "run"
CONTROL_PAUSE = "pause"
CONTROL_STOP = "stop"

_POLL_INTERVAL = 0.3


class ControlState:
    """
    任务控制状态

    控制文件为 JSON: {"command": "run|pause|stop", "version": int}
    Web 进程每次下达命令都会递增 version，Worker 按 mtime/size 变化重新读取。
    """

    def __init__(self, control_path: str, poll_interval: float = _POLL_INTERVAL,
                 sink: "EventSink" = None):
        self.path = control_path
        self.poll_interval = max(0.05, float(poll_interval))
        self._sink = sink
        self._command = CONTROL_RUN
        self._version = 0
        self._stamp = None
        self._lock = threading.Lock()
        self._pause_notified = False
        self._stop_notified = False
        self._refresh(force=True)

    # --------------------------------------------------------
    # 读取
    # --------------------------------------------------------

    def _signature(self):
        try:
            stat = os.stat(self.path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _refresh(self, force: bool = False) -> bool:
        """重新读取控制文件，返回命令是否发生变化"""
        signature = self._signature()
        if not force and signature is not None and signature == self._stamp:
            return False
        with self._lock:
            if not force and signature is not None and signature == self._stamp:
                return False
            self._stamp = signature
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return False
            command = str(data.get("command", CONTROL_RUN)).lower()
            version = int(data.get("version", 0) or 0)
            changed = command != self._command or version != self._version
            self._command = command
            self._version = version
            return changed

    @property
    def command(self) -> str:
        self._refresh()
        return self._command

    # --------------------------------------------------------
    # 检查点
    # --------------------------------------------------------

    def check(self):
        """
        控制检查点

        - stop：抛出 StopRequested
        - pause：阻塞直到恢复运行或收到停止命令（期间上报 paused/resumed 事件）
        """
        self._refresh()
        if self._command == CONTROL_STOP:
            self._raise_stop()
        if self._command != CONTROL_PAUSE:
            if self._pause_notified:
                self._pause_notified = False
                self._emit("resumed", "任务已继续运行")
            return

        if not self._pause_notified:
            self._pause_notified = True
            self._emit("paused", "任务已暂停，等待继续指令")

        while True:
            time.sleep(self.poll_interval)
            self._refresh(force=False)
            if self._command == CONTROL_STOP:
                self._pause_notified = False
                self._raise_stop()
            if self._command != CONTROL_PAUSE:
                self._pause_notified = False
                self._emit("resumed", "任务已继续运行")
                return

    def sleep(self, seconds: float):
        """可暂停、可停止的分段等待"""
        remaining = float(seconds)
        if remaining <= 0:
            self.check()
            return
        while True:
            # check() 可能阻塞等待恢复，暂停时间不能消耗实际等待量。
            self.check()
            if remaining <= 0:
                return
            started = time.monotonic()
            time.sleep(min(self.poll_interval, remaining))
            remaining -= max(0, time.monotonic() - started)

    def _raise_stop(self):
        if not self._stop_notified:
            self._stop_notified = True
            self._emit("stop_requested", "任务收到停止指令，正在安全退出")
        raise StopRequested("任务被停止")

    def _emit(self, event: str, message: str):
        if self._sink is not None:
            self._sink.emit(event, message, level="info", stage="control")


# ============================================================
# 事件上报
# ============================================================


class EventSink:
    """事件出口：把结构化事件写成一行 JSON 到标准输出"""

    def __init__(self, task_id: str = "", stream=None):
        self.task_id = task_id
        self._stream = stream if stream is not None else sys.stdout
        self._lock = threading.Lock()

    def emit(self, event: str, message: str = "", level: str = "info",
             stage: str = "", payload: dict = None):
        record = {
            "event": event,
            "task_id": self.task_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "level": level,
            "stage": stage,
            "message": message,
            "payload": payload or {},
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
            except (ValueError, OSError):
                # 通道已关闭（例如 Web 进程退出），忽略即可
                pass

    # 与 loguru logger 兼容的最小接口，便于直接替换 log 对象
    def debug(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="debug", stage="log")

    def info(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="info", stage="log")

    def success(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="success", stage="log")

    def warning(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="warning", stage="log")

    def error(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="error", stage="log")

    def exception(self, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level="error", stage="log")

    def log(self, level, message, *args, **kwargs):
        self.emit("log", self._format(message, args), level=str(level).lower(), stage="log")

    @staticmethod
    def _format(message, args) -> str:
        text = str(message)
        for arg in args or ():
            text = text.replace("{}", str(arg), 1)
        return text


# ============================================================
# 全局钩子
# ============================================================

_sink: EventSink = None
_control: ControlState = None


def set_sink(sink: EventSink):
    global _sink
    _sink = sink


def get_sink() -> EventSink:
    return _sink


def set_control(control: ControlState):
    global _control
    _control = control


def get_control() -> ControlState:
    return _control


def emit(event: str, message: str = "", level: str = "info",
         stage: str = "", payload: dict = None):
    if _sink is not None:
        _sink.emit(event, message, level=level, stage=stage, payload=payload)


def checkpoint():
    """控制检查点：无控制时为空操作"""
    if _control is not None:
        _control.check()


def sleep(seconds: float):
    """可暂停/可停止的等待：无控制时等价于 time.sleep"""
    if _control is not None:
        _control.sleep(seconds)
    else:
        time.sleep(seconds)
