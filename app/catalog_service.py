"""
课程目录服务：独立作业 / 独立考试的待做列表

设计要点：
- 列表由子进程 `worker/catalog_runner.py` 登录后只读拉取，Web 进程不持有超星 Session
- 结果缓存在 SQLite `course_catalog` 表，TTL 600 秒；`refresh=true` 强制重取
- 子进程 stdout 每行一个 JSON：`log` / `catalog_result` / `catalog_failed`
- 取数失败但仍有旧缓存时返回旧列表并带上 error，前端提示可重试
"""

import json
import os
import subprocess
import sys
import time

from . import accounts, paths

CATALOG_TTL = 600
CATALOG_TIMEOUT = 180
KINDS = ("work", "exam")


def fetch_catalog(db, account_id: str, course_id: str, kind: str = "work",
                  refresh: bool = False) -> dict:
    """
    读取某账号某课程的作业 / 考试列表

    Raises:
        KeyError: 账号不存在
        ValueError: kind 非法
        RuntimeError: 无缓存且取数失败（路由转为 502）
    """
    kind = (kind or "work").strip() or "work"
    if kind not in KINDS:
        raise ValueError("目录类型必须是 work 或 exam")
    account = accounts.get_account(account_id, public=False)
    if not account:
        raise KeyError("账号不存在")

    cached = db.get_catalog(account_id, course_id, kind)
    now = time.time()
    if cached and not refresh and now - float(cached.get("fetched_at") or 0) < CATALOG_TTL:
        return _response(cached, from_cache=True)

    course = db.get_course(account_id, course_id) or {}
    job = {
        "account_id": account["id"],
        "account_label": account.get("label", ""),
        "username": account["username"],
        "password": account["password"],
        "course_id": course_id,
        "class_id": course.get("class_id", ""),
        "cpi": course.get("cpi", ""),
        "kind": kind,
        "task_dir": paths.TASK_DIR,
    }
    try:
        items = _run_catalog_job(job)
    except RuntimeError as exc:
        if cached:
            # 仍展示旧列表，但明确告诉前端这次刷新失败
            return _response(cached, from_cache=True, error=str(exc))
        raise

    stored = db.save_catalog(account_id, course_id, kind, items, fetched_at=time.time())
    return _response(stored, from_cache=False)


def _response(catalog: dict, from_cache: bool, error: str = "") -> dict:
    return {
        "account_id": catalog.get("account_id", ""),
        "course_id": catalog.get("course_id", ""),
        "kind": catalog.get("kind", ""),
        "items": catalog.get("items") or [],
        "fetched_at": catalog.get("fetched_at"),
        "from_cache": bool(from_cache),
        "error": error or "",
    }


def _job_path(job: dict) -> str:
    os.makedirs(paths.TASK_DIR, exist_ok=True)
    name = "catalog-{}-{}-{}.json".format(
        str(job.get("account_id", ""))[:32], str(job.get("course_id", ""))[:32],
        str(job.get("kind", "work")))
    return os.path.join(paths.TASK_DIR, name.replace("/", "_").replace("\\", "_"))


def _run_catalog_job(job: dict) -> list:
    """启动 catalog_runner 子进程并解析 stdout；失败抛 RuntimeError（中文原因）"""
    job_path = _job_path(job)
    tmp = job_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, job_path)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["AUTOCXWEBUI_DATA_DIR"] = paths.DATA_DIR

    runner = os.path.join(paths.ROOT_DIR, "worker", "catalog_runner.py")
    try:
        process = subprocess.Popen(
            [sys.executable, runner, job_path],
            cwd=paths.ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
            bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise RuntimeError("无法启动作业列表读取进程，请重试") from exc

    try:
        stdout, _ = process.communicate(timeout=CATALOG_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.communicate(timeout=5)
        except Exception:
            pass
        raise RuntimeError("读取作业列表超时，请稍后重试")
    except Exception as exc:
        try:
            process.kill()
        except Exception:
            pass
        raise RuntimeError("读取作业列表失败，请重试") from exc

    items, failure = None, ""
    for line in (stdout or b"").decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        event = record.get("event") or "log"
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if event == "catalog_result":
            value = payload.get("items")
            if isinstance(value, list):
                items = value
        elif event == "catalog_failed":
            failure = str(record.get("message") or "").strip() or "读取列表失败"

    if failure:
        raise RuntimeError(failure)
    if items is None:
        raise RuntimeError("读取作业列表失败，请稍后重试")
    return items
