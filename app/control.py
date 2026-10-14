"""
任务控制文件

Web 进程与 Worker 之间的本地 IPC：
- 每个任务一个 JSON 文件：{"command": "run|pause|stop", "version": n, "updated_at": ts}
- version 单调递增，Worker 按文件 mtime/size 变化感知新命令
- 控制事件与实际生效事件都写入历史，避免“界面显示已暂停但仍在工作”
"""

import json
import os
import time

from . import paths

RUN = "run"
PAUSE = "pause"
STOP = "stop"

VALID_COMMANDS = (RUN, PAUSE, STOP)


def write_command(task_id: str, command: str, reason: str = "") -> dict:
    if command not in VALID_COMMANDS:
        raise ValueError(f"非法控制命令: {command}")
    payload = {
        "command": command,
        "version": _next_version(task_id),
        "updated_at": time.time(),
        "reason": reason,
    }
    path = paths.control_path(task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    return payload


def read_command(task_id: str) -> dict:
    path = paths.control_path(task_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ensure_run(task_id: str) -> dict:
    """任务启动时写入初始 run 命令"""
    return write_command(task_id, RUN, reason="worker_start")


def clear(task_id: str):
    path = paths.control_path(task_id)
    try:
        os.remove(path)
    except OSError:
        pass


def _next_version(task_id: str) -> int:
    current = read_command(task_id)
    try:
        return int(current.get("version", 0)) + 1
    except (TypeError, ValueError):
        return 1
