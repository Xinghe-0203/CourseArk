"""
Web 进程侧的 Worker 子进程公共工具

task_manager、sync_service、session_service、catalog_service 四处此前各自维护一份
「Popen + JSON Lines 逐行解析 + env 注入 + 优雅终止」样板（v2.4.0 T1 只统一了
worker 侧，web 侧漂移未合并）；这里合并为单一出口。行为差异保留在各调用方：
- 非 JSON 行的兜底（sync 记为 log 事件，其余跳过）
- 等待退出超时后是否强杀（session_service 会 kill，其余直接放弃）
"""

import json
import os
import subprocess
import sys

from . import paths


def worker_env(extra: dict = None) -> dict:
    """子进程环境：强制 UTF-8 与无缓冲 stdout，把用户数据重定向进 WebUI 数据目录
    （避免 Worker 在 cli_copy 里生成 config.yml / 日志等文件）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["AUTOCXWEBUI_DATA_DIR"] = paths.DATA_DIR
    if extra:
        env.update(extra)
    return env


def spawn(runner: str, arg: str, env: dict) -> subprocess.Popen:
    """启动 worker/<name>.py 子进程：stdout 合并 stderr、二进制无缓冲按行回传。"""
    return subprocess.Popen(
        [sys.executable, runner, arg],
        cwd=paths.ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=0,
        universal_newlines=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )


def iter_lines(process: subprocess.Popen):
    """逐行读取并解码子进程 stdout（替代各处 iter(process.stdout.readline, b"") 样板）。"""
    for raw in iter(process.stdout.readline, b""):
        yield raw.decode("utf-8", errors="replace").strip()


def parse_record(text: str):
    """把一行文本解析为 JSON dict；非 JSON / 非 dict 返回 None，兜底方式由调用方定。"""
    try:
        record = json.loads(text)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def write_json_atomic(path: str, payload) -> None:
    """任务/作业 JSON 文件统一原子写（临时文件 + os.replace）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def wait_exit(process: subprocess.Popen, timeout: int = 10,
              kill_on_timeout: bool = False) -> int:
    """读取收尾：关 stdout、等退出并返回码；超时按需强杀（session_service 语义）。"""
    try:
        process.stdout.close()
    except Exception:
        pass
    try:
        return process.wait(timeout=timeout)
    except Exception:
        if kill_on_timeout:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
        return -1


def stop_process(process, grace: float) -> None:
    """v2.4.0 T1：统一走 worker/common 优雅终止阶梯（taskkill 无 /F → 等待 → 强杀）。"""
    from worker import common

    try:
        common.terminate_gracefully(process, max(0.5, grace))
    except Exception:
        pass
