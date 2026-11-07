"""
账号课程同步服务

- 同步在独立子进程中执行，Web 进程不持有超星 Session
- 结果写入 courses 表（按账号隔离）并更新账号的登录/同步状态
- 同步失败时保留上一次课程快照，只记录错误与“课程可能过期”标记
"""

import json
import os
import subprocess
import sys
import threading
import time

from . import accounts, events, paths, settings, narrative
from .subprocess_runner import iter_lines, parse_record, spawn, stop_process, wait_exit, worker_env, write_json_atomic

_lock = threading.RLock()
_running = {}  # account_id -> {"started_at": float, "process": Popen}


def is_syncing(account_id: str) -> bool:
    with _lock:
        return account_id in _running


def syncing_accounts() -> list:
    with _lock:
        return list(_running)


def shutdown(grace: float = 3.0) -> None:
    """Stop sync subprocesses before the API process exits."""
    with _lock:
        running = list(_running.items())
    deadline = time.monotonic() + max(0.0, grace)
    for account_id, reservation in running:
        process = reservation.get("process")
        if process is not None:
            _stop_process(process, max(0.1, deadline - time.monotonic()))
        with _lock:
            if _running.get(account_id) is reservation:
                _running.pop(account_id, None)


def _stop_process(process, grace: float) -> None:
    stop_process(process, grace)


def sync_account(db, hub: events.EventHub, account_id: str, blocking: bool = False) -> dict:
    """
    触发账号同步

    Returns:
        dict: {"started": bool, "reason": str}
    """
    account = accounts.get_account(account_id, public=False)
    if not account:
        raise KeyError("账号不存在")
    with _lock:
        if is_syncing(account_id):
            return {"started": False, "reason": "该账号正在同步中"}
        reservation = {"started_at": time.time(), "process": None}
        _running[account_id] = reservation

    job = {
        "account_id": account["id"],
        "account_label": account.get("label", ""),
        "username": account["username"],
        "password": account["password"],
        "question_bank_path": paths.QUESTION_BANK_FILE,
        "task_dir": paths.TASK_DIR,
        "advanced": settings.resolve("advanced", {}),
    }
    try:
        job_path = os.path.join(paths.TASK_DIR, f"sync-{account['id']}.json")
        write_json_atomic(job_path, job)

        process = spawn(
            os.path.join(paths.ROOT_DIR, "worker", "sync_runner.py"), job_path,
            worker_env(),
        )
    except Exception as exc:
        with _lock:
            _running.pop(account_id, None)
        raise RuntimeError("无法启动课程同步进程，请重试") from exc
    with _lock:
        reservation["process"] = process

    def _consume():
        result = None
        failure = None
        try:
            for text in iter_lines(process):
                if not text:
                    continue
                record = parse_record(text)
                if record is None:
                    _publish(db, hub, account_id, "log", text[:1000], level="info")
                    continue
                event = record.get("event", "log")
                message = record.get("message", "")
                payload = record.get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                if event == "sync_result":
                    result = payload
                elif event == "sync_failed":
                    failure = message
                _publish(db, hub, account_id, event, message,
                         level=record.get("level", "info"), payload=payload)
        except Exception:
            failure = "读取课程同步结果失败，请重试"
        finally:
            code = wait_exit(process)
            try:
                _finalize(db, hub, account_id, result, failure, code)
            finally:
                with _lock:
                    if _running.get(account_id) is reservation:
                        _running.pop(account_id, None)

    if blocking:
        _consume()
        return {"started": True, "reason": ""}
    threading.Thread(target=_consume, name=f"sync-{account_id[:8]}", daemon=True).start()
    return {"started": True, "reason": ""}


def _finalize(db, hub, account_id: str, result, failure, exit_code: int):
    if exit_code == 0 and not failure and isinstance(result, dict) and isinstance(result.get("courses"), list):
        courses = result["courses"]
        db.replace_courses(account_id, courses)
        accounts.mark_sync(account_id, True)
        accounts.mark_login(account_id, True, display_name=result.get("display_name", ""))
        _publish(db, hub, account_id, "sync_completed",
                 f"课程同步完成，共 {len(courses)} 门课程", level="success",
                 payload={"courses": len(courses)})
        return
    message = failure or f"同步进程异常退出 (exit={exit_code})"
    accounts.mark_sync(account_id, False, error=message)
    if failure and "登录" in str(message):
        accounts.mark_login(account_id, False, error=message)
    _publish(db, hub, account_id, "sync_failed", message, level="error")


def _publish(db, hub: events.EventHub, account_id: str, event: str, message: str,
             level: str = "info", payload: dict = None):
    """同步事件落库 + 推送（v2.4.0 T10）。

    此前事件 id 恒为 0 仅存内存：SSE 不写 id: 行、重启即丢、事件页看不到。
    现在写入 task_events 哨兵行（task_id="0"，该表无外键约束），
    拿到真实 id 后再 publish，SSE 据此携带游标、断线可增量续传。
    """
    event_id = db.add_event("0", account_id, event, message, level=level,
                            stage="sync", payload=payload)
    hub.publish(events.make_record(event_id, "0", account_id, event, message,
                                   level=level, stage="sync", payload=payload,
                                   narrative=narrative.describe(event, message, level=level, stage="sync", payload=payload)))
