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
from .notifications import NotificationCenter

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
    try:
        if process.poll() is not None:
            return
    except Exception:
        pass
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=max(0.1, grace))
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    try:
        process.kill()
        process.wait(timeout=max(1.0, grace))
    except Exception:
        pass


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
        os.makedirs(os.path.dirname(job_path), exist_ok=True)
        tmp = job_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
        os.replace(tmp, job_path)

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["AUTOCXWEBUI_DATA_DIR"] = paths.DATA_DIR

        process = subprocess.Popen(
            [sys.executable, os.path.join(paths.ROOT_DIR, "worker", "sync_runner.py"), job_path],
            cwd=paths.ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
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
            for raw in iter(process.stdout.readline, b""):
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    _publish(hub, account_id, "log", text[:1000], level="info")
                    continue
                if not isinstance(record, dict):
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
                _publish(hub, account_id, event, message,
                         level=record.get("level", "info"), payload=payload)
        except Exception:
            failure = "读取课程同步结果失败，请重试"
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass
            code = process.poll()
            if code is None:
                try:
                    code = process.wait(timeout=10)
                except Exception:
                    code = -1
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
        _publish(hub, account_id, "sync_completed",
                 f"课程同步完成，共 {len(courses)} 门课程", level="success",
                 payload={"courses": len(courses)})
        return
    message = failure or f"同步进程异常退出 (exit={exit_code})"
    accounts.mark_sync(account_id, False, error=message)
    if failure and "登录" in str(message):
        accounts.mark_login(account_id, False, error=message)
    _publish(hub, account_id, "sync_failed", message, level="error")
    account = accounts.get_account(account_id) or {}
    NotificationCenter(db).record(event="sync_failed", level="error", message=message,
                                  account_id=account_id, account_label=account.get("label", ""), stage="sync")
    db.add_event("", account_id, "sync_failed", message, level="error", stage="sync")


def _publish(hub: events.EventHub, account_id: str, event: str, message: str,
             level: str = "info", payload: dict = None):
    hub.publish(events.make_record(0, "", account_id, event, message,
                                   level=level, stage="sync", payload=payload,
                                   narrative=narrative.describe(event, message, level=level, stage="sync", payload=payload)))
