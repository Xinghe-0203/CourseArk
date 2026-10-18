"""
CourseArk 服务入口

FastAPI + Uvicorn。Web 进程职责：
- 校验请求和参数
- 维护账号、课程缓存、任务状态和历史
- 调度 Worker 子进程
- 接收结构化事件并写入数据库
- 通过 SSE 向浏览器推送事件
- 提供答题缓存的统计、搜索、导入和导出

Web 进程不直接持有超星账号 Session，不在 API 请求线程执行长时间刷课。
"""

import asyncio
import hmac
import json
import os
import queue
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .log_redaction import redact, redact_data

from . import (accounts, catalog_service, events, narrative, paths,
               question_bank_manager, session_service, settings, sync_service)
from .database import Database
from .task_manager import TaskManager
from .task_model import (FEATURE_LABELS, RunCreateRequest, build_tasks,
                         is_terminal)

paths.ensure_dirs()


class _Lazy:
    """
    惰性资源代理

    数据库连接等资源不能在模块导入时就创建：导入时机可能与实际数据目录
    配置不一致（测试隔离、嵌入式调用都会踩到）。这里把创建推迟到第一次
    真正使用，属性访问全部转发给真实实例。
    """

    def __init__(self, factory, name: str):
        self._factory = factory
        self._name = name
        self._instance = None

    def _get(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def __getattr__(self, item):
        # 仅当常规属性查找失败时才会走到这里
        return getattr(self._get(), item)

    def reset(self):
        """释放实例，下次访问时重建（测试或数据目录切换时使用）"""
        instance, self._instance = self._instance, None
        return instance


db = _Lazy(Database, "db")
hub = _Lazy(events.EventHub, "hub")
manager = _Lazy(lambda: TaskManager(db, hub), "manager")
sessions = _Lazy(session_service.SessionService, "sessions")


# ============================================================
# 请求模型
# ============================================================

class AccountCreate(BaseModel):
    username: str = Field(min_length=5, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=64)
    enabled: bool = True


class AccountUpdate(BaseModel):
    username: str | None = Field(default=None, max_length=32)
    password: str | None = Field(default=None, max_length=128)
    label: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


class PresetCreate(BaseModel):
    id: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


class QuestionBankImport(BaseModel):
    content: str = Field(min_length=1)
    format: str = "json"
    overwrite: bool = False
    preview_only: bool = False


class QuestionBankImportPath(BaseModel):
    """按服务器本地路径导入题库（例如源 CLI 的 data/question_bank.db）"""
    path: str = Field(default="", max_length=1024)
    overwrite: bool = False
    preview_only: bool = False


class TaskTargetModel(BaseModel):
    account_id: str
    course_id: str
    class_id: str = ""
    cpi: str = ""
    course_name: str = ""


# ============================================================
# 应用
# ============================================================

def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        # 首次启动：把源 CLI 的题库与配置一次性导入到 WebUI 数据目录
        # 两者都只读源文件，且只填充空缺、不覆盖用户已保存的设置
        question_bank_manager.import_from_source_once()
        try:
            settings.import_from_source_config(only_empty=True)
        except Exception:
            pass  # 配置导入失败不应阻止服务启动
        manager.start()
        try:
            yield
        finally:
            manager.shutdown()
            sync_service.shutdown()
            sessions.shutdown()
            db.close()

    app = FastAPI(title="CourseArk", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=lifespan)

    _guard_cross_site_mutations(app)
    _mount_static(app)
    _register_routes(app)
    return app


LOCAL_PAGE_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _guard_cross_site_mutations(app: FastAPI):
    """只接受本机页面的写请求，阻止跨站网页向本机服务盲发操作。"""

    @app.middleware("http")
    async def reject_cross_site_mutations(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_PAGE_HOSTS:
                    return JSONResponse(status_code=403, content={"detail": "仅接受来自本机页面的请求"})
        return await call_next(request)


# ============================================================
# 路由
# ============================================================

def _register_routes(app: FastAPI):

    # ---------------- 健康检查 ----------------

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "data_dir": paths.DATA_DIR,
            "source_cli_dir": paths.SOURCE_CLI_DIR,
            "source_cli_writable": False,
            "schema_version": 1,
            "worker_runner": os.path.exists(paths.WORKER_RUNNER),
            "scheduler": manager.snapshot(),
            "sse_subscribers": hub.subscriber_count(),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }

    @app.post("/api/internal/shutdown", status_code=202, include_in_schema=False)
    def request_shutdown(request: Request):
        expected = os.environ.get("AUTOCXWEBUI_SHUTDOWN_TOKEN", "")
        if not expected:
            raise HTTPException(status_code=404, detail="Not found")
        supplied = request.headers.get("X-AutoCx-Shutdown-Token", "")
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail="无权关闭本机服务")
        server = getattr(request.app.state, "uvicorn_server", None)
        if server is None:
            raise HTTPException(status_code=503, detail="服务尚未就绪")
        server.should_exit = True
        return {"ok": True}

    # ---------------- 总览 ----------------

    @app.get("/api/overview")
    def overview():
        day_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        stats = db.dashboard_stats(day_start)
        tasks_today = db.count_tasks({"since": day_start})
        active = db.list_tasks({"status": "running,starting,logging_in,loading_courses,pausing,stopping"}, limit=50)
        paused = db.list_tasks({"status": "paused"}, limit=50)
        pending = db.list_tasks({"status": "pending"}, limit=50)
        recent = db.recent_events(limit=60)
        problems = [item for item in db.recent_events(limit=200)
                    if item["level"] in ("warning", "error")][:30]
        bank = question_bank_manager.stats()
        account_summary = accounts.summary()
        queue_rows = []
        for row in (active + paused + pending)[:60]:
            queue_rows.append({
                "id": row["id"],
                "account_id": row["account_id"],
                "account_label": row["account_label"],
                "course_name": row["course_name"],
                "feature": row["feature"],
                "feature_label": FEATURE_LABELS.get(row["feature"], row["feature"]),
                "status": row["status"],
                "stage": row["stage"],
                "stats": _json(row["stats_json"]),
                "created_at": row["created_at"],
            })
        return {
            "accounts": account_summary,
            "tasks": {
                "active": db.count_tasks({"status": "running,starting,logging_in,loading_courses,pausing,stopping"}),
                "paused": db.count_tasks({"status": "paused"}),
                "pending": db.count_tasks({"status": "pending"}),
                "today_total": tasks_today,
            },
            "today": stats,
            "workers": manager.snapshot(),
            "question_bank": {
                "total": bank["total"],
                "hits": bank["hits"],
                "hit_rate": bank["hit_rate"],
                "lookups": bank["lookups"],
            },
            "queue": queue_rows,
            "recent_events": [_event_view(item) for item in recent],
            "problems": [_event_view(item) for item in problems],
        }

    # ---------------- 账号 ----------------

    @app.get("/api/accounts")
    def list_accounts():
        items = accounts.list_accounts()
        for item in items:
            item["syncing"] = sync_service.is_syncing(item["id"])
            item["course_count"] = len(db.list_courses(item["id"]))
            item["session"] = {**sessions.status(item["id"]),
                               "fetching": sessions.is_fetching(item["id"]),
                               "last_result": sessions.last_result(item["id"])}
        return {"items": items}

    @app.post("/api/accounts", status_code=201)
    def create_account(payload: AccountCreate):
        try:
            return accounts.create_account(payload.username.strip(), payload.password,
                                           payload.label, payload.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.patch("/api/accounts/{account_id}")
    def update_account(account_id: str, payload: AccountUpdate):
        updates = payload.model_dump(exclude_none=True)
        if "username" in updates:
            updates["username"] = updates["username"].strip()
        try:
            return accounts.update_account(account_id, updates)
        except KeyError:
            raise HTTPException(status_code=404, detail="账号不存在")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: str):
        if sync_service.is_syncing(account_id):
            raise HTTPException(status_code=409, detail="该账号正在同步，无法删除")
        if not accounts.delete_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/sync")
    def sync_account(account_id: str):
        try:
            result = sync_service.sync_account(db, hub, account_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="账号不存在")
        if not result["started"]:
            raise HTTPException(status_code=409, detail=result["reason"])
        return result

    # ---------------- 学习通会话（一键登录网页） ----------------

    @app.get("/api/accounts/{account_id}/session")
    def session_status(account_id: str):
        if not accounts.get_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        status = sessions.status(account_id)
        status["fetching"] = sessions.is_fetching(account_id)
        status["last_result"] = sessions.last_result(account_id)
        return status

    @app.post("/api/accounts/{account_id}/session")
    def session_fetch(account_id: str):
        """用账号密码换取登录 Cookie 并保存（供一键打开学习通使用）"""
        try:
            result = sessions.fetch(account_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="账号不存在")
        if not result["started"]:
            raise HTTPException(status_code=409, detail=result["reason"])
        return result

    @app.delete("/api/accounts/{account_id}/session")
    def session_drop(account_id: str):
        if not accounts.get_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        sessions.drop(account_id)
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/open-chaoxing")
    def open_chaoxing(account_id: str, payload: dict = Body(default={})):
        """
        一键用已保存会话打开学习通网页（浏览器直接进入登录态）

        未保存会话时自动先用账号密码取一次会话（阻塞到取完），
        避免用户还要手动点两次。
        """
        if not accounts.get_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        auto_fetch = payload.get("auto_fetch", True)

        status = sessions.status(account_id)
        if not status.get("has_session") or (auto_fetch and not status.get("fresh")):
            if not auto_fetch:
                raise HTTPException(status_code=409, detail="该账号还没有可用会话，请先获取会话")
            try:
                result = sessions.fetch(account_id, blocking=True)
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            if not result.get("started") or not sessions.last_result(account_id).get("ok"):
                raise HTTPException(status_code=409, detail=result.get("reason") or
                                    sessions.last_result(account_id).get("message") or "会话获取失败")
            status = sessions.status(account_id)
            if not status.get("has_session"):
                raise HTTPException(
                    status_code=409,
                    detail=sessions.last_result(account_id).get("message")
                    or "会话获取失败，请检查账号密码")

        try:
            return sessions.open_browser(account_id, payload.get("url", ""))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/api/accounts/{account_id}/courses")
    def account_courses(account_id: str):
        if not accounts.get_account(account_id):
            raise HTTPException(status_code=404, detail="账号不存在")
        rows = db.list_courses(account_id)
        account = accounts.get_account(account_id)
        items = [{
            "course_id": row["course_id"],
            "class_id": row["class_id"],
            "cpi": row["cpi"],
            "name": row["name"],
            "author": row["author"],
            "if_open": bool(row["if_open"]),
            "mission_fn": row["mission_fn"],
            "mission_all": row["mission_all"],
            "synced_at": row["synced_at"],
        } for row in rows]
        return {
            "items": items,
            "synced_at": account.get("last_sync_at"),
            "sync_status": account.get("last_sync_status", ""),
            "stale": account.get("last_sync_status") == "failed",
            "syncing": sync_service.is_syncing(account_id),
        }

    # ---------------- 课程目录（独立作业 / 独立考试） ----------------

    @app.get("/api/accounts/{account_id}/courses/{course_id}/catalog")
    def course_catalog(account_id: str, course_id: str, kind: str = "work",
                       refresh: bool = False):
        """列出课程下待做的作业 / 考试；默认缓存 600 秒，refresh=true 强制重取"""
        try:
            return catalog_service.fetch_catalog(db, account_id, course_id,
                                                 kind=kind, refresh=refresh)
        except KeyError:
            raise HTTPException(status_code=404, detail="账号不存在")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    # ---------------- 批次与任务 ----------------

    @app.get('/api/workspace/accounts')
    def account_workspace():
        """多账号工作台，一次读取各账号课程、当前任务和最近结果。"""
        items = []
        current_states = 'pending,starting,logging_in,loading_courses,running,pausing,paused,stopping'
        for account in accounts.list_accounts():
            account_id = account['id']
            course_rows = db.list_courses(account_id)
            filters = {'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': current_states}
            current, offset = [], 0
            while True:
                page = db.list_tasks(filters, limit=500, offset=offset)
                current.extend(page)
                if len(page) < 500:
                    break
                offset += len(page)
            recent = db.list_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'succeeded,failed,stopped,interrupted'}, limit=12)
            items.append({'account': {**account, 'syncing': sync_service.is_syncing(account_id),
                                     'session': sessions.status(account_id)},
                          'courses': [{'course_id': c['course_id'], 'class_id': c['class_id'], 'cpi': c['cpi'],
                                       'name': c['name'], 'author': c['author'], 'if_open': bool(c['if_open']),
                                       'mission_fn': c['mission_fn'], 'mission_all': c['mission_all'],
                                       'synced_at': c['synced_at']} for c in course_rows],
                          'tasks': [_task_view(t) for t in current if t['feature'] in ('course_all', 'independent_homework')],
                          'recent': [_task_view(t) for t in recent if t['feature'] in ('course_all', 'independent_homework')],
                          'counts': {'active': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'running,starting,logging_in,loading_courses,pausing,stopping'}),
                                     'pending': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'pending'}),
                                     'paused': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'paused'}),
                                     'succeeded': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'succeeded'}),
                                     'failed': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'failed,interrupted'})}})
        return {'items': items}

    @app.post('/api/accounts/{account_id}/tasks/{operation}')
    def account_task_control(account_id: str, operation: str):
        if not accounts.get_account(account_id):
            raise HTTPException(status_code=404, detail='账号不存在')
        allowed = {'pause': 'running,starting,logging_in,loading_courses',
                   'resume': 'paused', 'stop': 'pending,starting,logging_in,loading_courses,running,pausing,paused'}
        if operation not in allowed:
            raise HTTPException(status_code=400, detail='批量指令仅支持暂停、继续和停止')
        filters = {'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': allowed[operation]}
        targets, offset = [], 0
        while True:
            rows = db.list_tasks(filters, limit=500, offset=offset)
            targets.extend(row['id'] for row in rows)
            if len(rows) < 500:
                break
            offset += len(rows)
        accepted, changed = 0, []
        command = getattr(manager, operation)
        for task_id in targets:
            try:
                command(task_id)
                accepted += 1
            except (ValueError, KeyError):
                changed.append(task_id)
        return {'account_id': account_id, 'operation': operation, 'accepted': accepted,
                'changed': len(changed), 'total': len(targets)}

    @app.post("/api/runs", status_code=201)
    def create_run(payload: RunCreateRequest):
        try:
            run_id, tasks, params = build_tasks(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        manager.create_run(tasks, run_id, note=payload.note)
        return {
            "run_id": run_id,
            "task_ids": [task["id"] for task in tasks],
            "count": len(tasks),
            "params": params.snapshot(),
        }

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0)):
        rows = db.list_runs(limit, offset)
        for row in rows:
            row["tasks"] = db.count_tasks({"run_id": row["id"]})
        return {"items": rows}

    @app.get("/api/tasks")
    def list_tasks(status: str = "", account_id: str = "", run_id: str = "",
                   feature: str = "", course_id: str = "", q: str = "",
                   since: float = 0, until: float = 0,
                   limit: int = Query(default=100, ge=1, le=500),
                   offset: int = Query(default=0, ge=0)):
        filters = {"status": status, "account_id": account_id, "run_id": run_id,
                   "feature": feature, "course_id": course_id, "q": q,
                   "since": since or None, "until": until or None}
        rows = db.list_tasks(filters, limit, offset)
        return {
            "total": db.count_tasks(filters),
            "items": [_task_view(row) for row in rows],
        }

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str):
        row = db.get_task(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        detail = _task_view(row)
        detail["events"] = [_event_view(item) for item in db.list_events(task_id, limit=50, latest=True)]
        detail["activity_events"] = [_event_view(item) for item in db.list_events(task_id, limit=50, latest=True, business=True)]
        # 逐题作答明细：老任务没有 answer_result 事件时返回空数组与零值汇总
        answers = _task_answers(task_id)
        detail["answers"] = answers
        detail["answers_summary"] = _answers_summary(answers, detail.get("stats") or {})
        detail["live"] = _live_view(row)
        return detail

    @app.post("/api/tasks/{task_id}/pause")
    def pause_task(task_id: str):
        return _control(manager.pause, task_id)

    @app.post("/api/tasks/{task_id}/resume")
    def resume_task(task_id: str):
        return _control(manager.resume, task_id)

    @app.post("/api/tasks/{task_id}/stop")
    def stop_task(task_id: str):
        return _control(manager.stop, task_id)

    @app.post("/api/tasks/{task_id}/retry", status_code=201)
    def retry_task(task_id: str):
        row = db.get_task(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        if not is_terminal(row["status"]):
            raise HTTPException(status_code=409, detail="仅终态任务可以重试")
        try:
            return _task_view(manager.retry_task(task_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在")

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str, after_id: int = 0, limit: int = Query(default=200, ge=1, le=1000),
                    level: str = "all", event: str = "all", latest: bool = False):
        if not db.get_task(task_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        rows = db.list_events(task_id, after_id, limit, level, event, latest=latest)
        return {"items": [_event_view(item) for item in rows]}

    @app.get("/api/tasks/{task_id}/logs")
    def task_logs(task_id: str):
        if not db.get_task(task_id):
            raise HTTPException(status_code=404, detail="任务不存在")

        def lines():
            after = 0
            while True:
                rows = db.list_events(task_id, after_id=after, limit=1000)
                if not rows:
                    break
                for row in rows:
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["ts"]))
                    yield f"{stamp} | {row['level']} | {row['stage']} | {redact(row['message'])}\n"
                after = rows[-1]["id"]

        return StreamingResponse(lines(), media_type="text/plain; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="task-{task_id}.log"'})

    # ---------------- 历史 ----------------

    @app.get("/api/history")
    def history(status: str = "", account_id: str = "", feature: str = "",
                q: str = "", since: float = 0, until: float = 0,
                limit: int = Query(default=50, ge=1, le=200),
                offset: int = Query(default=0, ge=0)):
        filters = {"status": status or "succeeded,failed,stopped,interrupted", "account_id": account_id, "feature": feature,
                   "q": q, "since": since or None, "until": until or None}
        rows = db.list_tasks(filters, limit, offset)
        return {"total": db.count_tasks(filters), "items": [_task_view(row) for row in rows]}

    # ---------------- SSE ----------------

    @app.get("/api/events/stream")
    async def stream(request: Request, last_event_id: int = Query(default=0, ge=0)):
        header = request.headers.get("last-event-id")
        if header is not None:
            try:
                last_event_id = int(header)
                if last_event_id < 0:
                    raise ValueError
            except ValueError:
                raise HTTPException(status_code=400, detail="无效的事件游标")
        subscriber = hub.subscribe()

        async def generator():
            cursor = last_event_id
            heartbeat = time.monotonic()

            async def ordered(record):
                nonlocal cursor
                event_id = record.get("id", 0)
                if event_id and event_id <= cursor:
                    return
                if event_id > cursor + 1:
                    # 提交与推送可能乱序；数据库是持久事件顺序的唯一依据。
                    while cursor < event_id:
                        missing = db.events_after(cursor, limit=500)
                        missing = [row for row in missing if row["id"] <= event_id]
                        if not missing:
                            break
                        for row in missing:
                            cursor = row["id"]
                            yield _sse(_event_view(row))
                    if event_id <= cursor:
                        return
                cursor = max(cursor, event_id)
                yield _sse(record)

            try:
                # 先订阅再读取数据库，期间发生的事件由游标去重。
                while True:
                    rows = db.events_after(cursor, limit=500)
                    if not rows:
                        break
                    for row in rows:
                        cursor = row["id"]
                        yield _sse(_event_view(row))
                    await asyncio.sleep(0)
                # 同步服务等内存事件保留兼容；数据库事件已经发送过则跳过。
                backlog = hub.replay_since(cursor, limit=2000)
                for record in backlog:
                    async for chunk in ordered(record):
                        yield chunk
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        record = subscriber.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.5)
                        if time.monotonic() - heartbeat >= 15:
                            yield ": keep-alive\n\n"
                            heartbeat = time.monotonic()
                        continue
                    async for chunk in ordered(record):
                        yield chunk
            finally:
                hub.unsubscribe(subscriber)

        return StreamingResponse(generator(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ---------------- 设置与预设 ----------------

    @app.get("/api/settings")
    def get_settings():
        data = settings.masked()
        data["features"] = [{"key": key, "label": FEATURE_LABELS[key]}
                            for key in FEATURE_LABELS]
        data["storage"] = {**data.get('storage', {}), **settings.storage_info()}
        data["source_config"] = settings.source_config_info()
        return data

    @app.patch("/api/settings")
    def patch_settings(payload: dict = Body(default={})):
        return settings.apply_updates(payload)

    @app.post("/api/settings/import-source")
    def import_settings_from_source(payload: dict = Body(default={})):
        """从源 CLI 的 config.yml 导入 LLM/题库/通知配置并持久化到本地数据库"""
        only_empty = payload.get("only_empty", True)
        return settings.import_from_source_config(only_empty=bool(only_empty))

    @app.get("/api/settings/export")
    def export_settings():
        return Response(
            content=settings.export_json(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="webui-settings.json"'},
        )

    @app.post("/api/settings/import")
    def import_settings(payload: dict = Body(default={})):
        content = payload.get("content")
        if not content:
            raise HTTPException(status_code=400, detail="缺少 content 字段")
        try:
            return settings.import_json(content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ---------------- 通知中心（问题不会自动消失） ----------------

    @app.get("/api/notifications")
    def list_notifications(include_read: bool = False,
                           limit: int = Query(default=200, ge=1, le=1000),
                           offset: int = Query(default=0, ge=0), category: str = ''):
        """
        问题列表

        context_json 是数据库列名，前端需要的是解析后的对象，
        这里统一展开为 context / count / first_seen / last_seen，避免前端各自解析。
        """
        data = manager.notifications.list(include_read=include_read, limit=limit, offset=offset, category=category)
        data["items"] = [_notification_view(row) for row in data["items"]]
        return data

    @app.post("/api/notifications/read")
    def read_notifications(payload: dict = Body(default={})):
        """标记已读：传 id 标记单条，传 category 标记某类，都不传则全部标记"""
        return {"updated": manager.notifications.mark_read(
            notification_id=payload.get("id"), category=payload.get("category", ""))}

    @app.delete("/api/notifications")
    def clear_notifications(only_read: bool = True):
        return {"removed": manager.notifications.clear(only_read=only_read)}

    @app.get("/api/presets")
    def list_presets():
        return {"items": [_preset_view(row) for row in db.list_presets()]}

    @app.post("/api/presets", status_code=201)
    def create_preset(payload: PresetCreate):
        preset_id = payload.id or ("preset-" + str(int(time.time() * 1000)))
        row = db.upsert_preset(preset_id, payload.name, payload.params)
        return _preset_view(row)

    @app.delete("/api/presets/{preset_id}")
    def delete_preset(preset_id: str):
        if not db.delete_preset(preset_id):
            raise HTTPException(status_code=404, detail="预设不存在")
        return {"ok": True}

    # ---------------- 答题缓存 ----------------

    @app.get("/api/question-bank/stats")
    def bank_stats(days: int = Query(default=7, ge=1, le=365)):
        return question_bank_manager.stats(days)

    @app.delete("/api/question-bank")
    def bank_clear():
        """清空全部本地答题缓存（只删 WebUI 自己的缓存，不动源 CLI 的题库文件）"""
        return {"deleted": question_bank_manager.clear_cache()}

    @app.get("/api/question-bank/search")
    def bank_search(q: str = "", question_type: str = "",
                    limit: int = Query(default=50, ge=1, le=200),
                    offset: int = Query(default=0, ge=0)):
        return question_bank_manager.search(q, question_type, limit, offset)

    @app.get("/api/question-bank/source")
    def bank_source():
        """源 CLI 题库信息：界面据此显示一键导入的数量"""
        return question_bank_manager.source_info()

    @app.post("/api/question-bank/import-source")
    def bank_import_source(payload: QuestionBankImportPath):
        """一键导入源 AutoChaoxingCLI 的题库（源文件只读）"""
        try:
            if payload.preview_only:
                info = question_bank_manager.source_info()
                if not info.get("exists"):
                    raise HTTPException(status_code=404, detail="未找到源 CLI 的题库文件")
                if info.get("error"):
                    raise HTTPException(status_code=400, detail=info["error"])
                records = question_bank_manager.read_db_records(paths.SOURCE_QUESTION_BANK)
                current = question_bank_manager._count_rows()
                preview = question_bank_manager.preview_records(records)
                preview["current_total"] = current
                return preview
            return question_bank_manager.import_from_source(overwrite=payload.overwrite)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="未找到源 CLI 的题库文件")
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/question-bank/import-db")
    async def bank_import_db(request: Request):
        """
        导入题库 .db 文件：支持 multipart 上传，也支持 JSON 指定服务器本地路径
        """
        import tempfile

        overwrite = False
        preview_only = False
        content_type = request.headers.get("content-type", "")

        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            uploads = form.getlist("file")
            uploads = [item for item in uploads if getattr(item, "filename", "")]
            if not uploads:
                raise HTTPException(status_code=400, detail="缺少上传文件")
            overwrite = str(form.get("overwrite", "")).lower() in ("1", "true", "on", "yes")
            preview_only = str(form.get("preview_only", "")).lower() in ("1", "true", "on", "yes")

            # 允许同时选中 .db 与其 -wal / -shm 侧车文件：
            # 只上传 .db 会丢掉尚未回放（checkpoint）的数据，导致题目变少
            tmp_dir = tempfile.mkdtemp(prefix="cxbank-upload-")
            main_path = None
            try:
                for upload in uploads:
                    # 只取文件名部分，避免路径穿越写入临时目录之外
                    name = os.path.basename(str(upload.filename).replace("\\", "/"))
                    if not name or name.startswith("."):
                        raise HTTPException(status_code=400, detail=f"非法的文件名: {upload.filename}")
                    target = os.path.join(tmp_dir, name)
                    with open(target, "wb") as handle:
                        while True:
                            chunk = await upload.read(1024 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                    if not (name.endswith("-wal") or name.endswith("-shm")):
                        main_path = target
                if main_path is None:
                    raise HTTPException(status_code=400,
                                        detail="未找到题库主文件（.db），仅收到 -wal/-shm 侧车文件")
                result = _import_db_path(main_path, overwrite, preview_only)
                if len(uploads) == 1:
                    result["wal_warning"] = (
                        "仅上传了 .db 文件。若该题库存在 .db-wal 侧车文件（CLI 未正常退出时常见），"
                        "其中的题目不会被导入。建议同时选中 .db、.db-wal、.db-shm 三个文件，"
                        "或直接使用“导入源题库”。"
                    )
                return result
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

        payload = QuestionBankImportPath(**await request.json())
        if not payload.path:
            raise HTTPException(status_code=400, detail="请提供题库文件路径或上传文件")
        return _import_db_path(payload.path, payload.overwrite, payload.preview_only)

    @app.get("/api/question-bank/export")
    def bank_export(format: str = "json"):
        if format == "csv":
            content = question_bank_manager.export_csv()
            return Response(
                content="\ufeff" + content,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="question_bank.csv"'},
            )
        return Response(
            content=question_bank_manager.export_json(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="question_bank.json"'},
        )

    @app.post("/api/question-bank/import")
    def bank_import(payload: QuestionBankImport):
        if payload.format not in ("json", "csv"):
            raise HTTPException(status_code=400, detail="format 必须是 json 或 csv")
        if payload.preview_only:
            return question_bank_manager.preview_import(payload.content, payload.format)
        return question_bank_manager.commit_import(payload.content, payload.format,
                                                   payload.overwrite)

    @app.delete("/api/question-bank/{question_hash}")
    def bank_delete(question_hash: str):
        if not question_bank_manager.delete_by_hash(question_hash):
            raise HTTPException(status_code=404, detail="题目不存在")
        return {"ok": True}


# ============================================================
# 视图与工具
# ============================================================

def _import_db_path(db_path: str, overwrite: bool, preview_only: bool) -> dict:
    """按路径导入题库文件，统一错误转换为 HTTP 响应"""
    try:
        if preview_only:
            records = question_bank_manager.read_db_records(db_path)
            preview = question_bank_manager.preview_records(records)
            preview["current_total"] = question_bank_manager._count_rows()
            return preview
        return question_bank_manager.import_from_db_file(db_path, overwrite=overwrite)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {db_path}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败: {exc}")


def _control(action, task_id: str):
    try:
        return _task_view(action(task_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _json(text, default=None):
    try:
        value = json.loads(text or "{}")
        return value if value is not None else (default or {})
    except ValueError:
        return default if default is not None else {}


def _task_view(row: dict) -> dict:
    from .work_progress import summarize
    stats = redact_data(_json(row.get("stats_json")))
    return {
        "id": row["id"],
        "run_id": row.get("run_id"),
        "account_id": row["account_id"],
        "account_label": row.get("account_label", ""),
        "course_id": row.get("course_id", ""),
        "class_id": row.get("class_id", ""),
        "cpi": row.get("cpi", ""),
        "course_name": row.get("course_name", ""),
        "feature": row["feature"],
        "feature_label": FEATURE_LABELS.get(row["feature"], row["feature"]),
        "status": row["status"],
        "stage": row.get("stage", ""),
        "pid": row.get("pid"),
        "params": _json(row.get("params_json")),
        "stats": stats,
        "progress": summarize(stats.get("work", {})),
        "error": redact(row.get("error", "")),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


# 逐题作答明细最多回放的 answer_result 事件条数：长作业也只需最近 500 条
ANSWER_EVENT_LIMIT = 500


def _answer_view(row: dict) -> dict:
    """把一条 answer_result 事件转成逐题明细（payload 已通过 redact_data 脱敏）"""
    payload = redact_data(_json(row.get("payload_json")))
    if not isinstance(payload, dict):
        payload = {}
    media = str(payload.get("media") or "")
    index = payload.get("index")
    options = payload.get("options")
    if not isinstance(options, list):
        options = []
    ts = row.get("ts") or time.time()
    return {
        "key": f"{media}#{index}",
        "index": index,
        "total": payload.get("total"),
        "media": media,
        "question_type": str(payload.get("question_type") or ""),
        "question": str(payload.get("question") or ""),
        "options": [str(item) for item in options],
        "answer": str(payload.get("answer") or ""),
        "source": str(payload.get("source") or ""),
        "status": str(payload.get("status") or ""),
        "note": str(payload.get("note") or ""),
        "ts": ts,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
    }


def _task_answers(task_id: str) -> list:
    """按 (media, index) 去重取最新一条，保持题目首次出现的顺序返回平铺数组"""
    rows = db.list_events(task_id, limit=ANSWER_EVENT_LIMIT, event="answer_result", latest=True)
    latest, order = {}, []
    for row in rows:
        item = _answer_view(row)
        dedupe_key = (item["media"], item["index"])
        if dedupe_key not in latest:
            order.append(dedupe_key)
        latest[dedupe_key] = item
    return [latest[key] for key in order]


def _answers_summary(items: list, stats: dict) -> dict:
    """逐题汇总；submit_* 取自任务 stats（服务器对提交的确认）"""
    summary = {
        "answered": 0, "skipped": 0, "total": 0,
        "ai": 0, "cache": 0, "random": 0, "failed": 0,
        "submit_ok": int((stats or {}).get("submit_ok", 0) or 0),
        "submit_fail": int((stats or {}).get("submit_fail", 0) or 0),
    }
    media_totals = {}
    for item in items:
        if item["status"] == "answered":
            summary["answered"] += 1
        elif item["status"] in ("skipped", "unreadable"):
            summary["skipped"] += 1
        if item["source"] in ("ai", "cache", "random", "failed"):
            summary[item["source"]] += 1
        if item.get("total"):
            summary_media = item["media"]
            media_totals[summary_media] = max(media_totals.get(summary_media, 0),
                                              int(item["total"] or 0))
    # 每题只报一次总数：同一份作业以最大的 total 为准；没有 total 时退回已见题数
    summary["total"] = sum(media_totals.values()) or len(items)
    return summary


# 运行中快照最多回放的业务事件条数：小窗只关心“最近在做什么”
LIVE_EVENT_LIMIT = 60

# 没有业务事件时用阶段名兜底
_STAGE_ACTIVITY = {
    "login": "正在登录学习通",
    "course": "正在读取课程",
    "chapter": "正在处理章节",
    "video": "正在学习视频",
    "audio": "正在学习音频",
    "exam": "AI 正在作答考试",
    "homework": "AI 正在作答作业",
    "work": "AI 正在作答作业",
    "download": "正在下载资源",
    "sync": "正在同步课程",
    "finish": "正在收尾",
}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _live_unit(rows: list):
    """最近一条带数字进度的 work_progress / media_progress 事件"""
    for item in reversed(rows):
        if item.get("event") not in ("work_progress", "media_progress"):
            continue
        payload = redact_data(_json(item.get("payload_json")))
        if not isinstance(payload, dict):
            continue
        label = str(payload.get("name") or payload.get("media") or "").strip()
        current, total = payload.get("current"), payload.get("total")
        if _number(current) and _number(total) and float(total) > 0:
            return {"label": label, "current": current, "total": total}
    return None


def _task_level_progress(stats: dict):
    """任务级已完成项 / 总项（用于没有当前项速率时的兜底 ETA）"""
    from .work_progress import summarize
    stats = stats or {}
    work = summarize(stats.get("work") or {})
    candidates = []
    if _number(stats.get("success")) or _number(stats.get("completed")):
        completed = stats.get("success") if _number(stats.get("success")) else stats.get("completed")
        candidates.append((completed, stats.get("total")))
    candidates.append((work.get("completed"), work.get("total")))
    for completed, total in candidates:
        if _number(completed) and int(completed) > 0 and _number(total) and int(total) > int(completed):
            return int(completed), int(total)
    return None


def _live_eta(row: dict, unit, activity_at, elapsed: int):
    """返回 (eta_seconds, eta_source)：优先当前项速率，其次任务级速率"""
    if is_terminal(row.get("status", "")):
        return None, None
    now = time.time()
    if unit:
        current = float(unit["current"])
        total = float(unit["total"])
        age = now - float(activity_at or now)
        if current > 0 and total > current and age > 1:
            rate = current / age
            return int(round((total - current) / rate)), "unit"
    pair = _task_level_progress(_json(row.get("stats_json")))
    if pair and elapsed > 0:
        completed, total = pair
        return int(round((total - completed) / completed * elapsed)), "task"
    return None, None


def _live_view(row: dict):
    """
    运行中快照：最近动作、已用时、当前项进度与预计剩余

    老任务没有 started_at / 业务事件时返回 None，前端按“无快照”处理。
    """
    started = row.get("started_at")
    if not started:
        return None
    now = time.time()
    finished = row.get("finished_at")
    if is_terminal(row.get("status", "")) and finished:
        elapsed = int(max(0, float(finished) - float(started)))
    else:
        elapsed = int(max(0, now - float(started)))

    business_rows = db.list_events(row["id"], limit=LIVE_EVENT_LIMIT,
                                   latest=True, business=True)
    recent_rows = db.list_events(row["id"], limit=LIVE_EVENT_LIMIT * 2, latest=True)
    activity, activity_at = "", float(started)
    for item in reversed(business_rows):
        presentation = (_event_view(item) or {}).get("presentation") or {}
        title = str(presentation.get("title") or "").strip()
        if not title:
            continue
        detail = str(presentation.get("detail") or "").strip()
        activity = f"{title} · {detail}" if detail else title
        activity_at = float(item.get("ts") or started)
        break
    if not activity:
        # 没有业务动态时用最近的进度事件兜底，小窗能看到“当前项”
        for item in reversed(recent_rows):
            if item.get("event") in ("log", "worker_exit"):
                continue
            presentation = (_event_view(item) or {}).get("presentation") or {}
            title = str(presentation.get("title") or "").strip()
            if not title:
                continue
            detail = str(presentation.get("detail") or "").strip()
            activity = f"{title} · {detail}" if detail else title
            activity_at = float(item.get("ts") or started)
            break
    if not activity:
        stage = str(row.get("stage") or "").strip()
        activity = _STAGE_ACTIVITY.get(stage) or ("正在" + stage if stage else "准备中")

    unit = _live_unit(recent_rows)
    eta_seconds, eta_source = _live_eta(row, unit, activity_at, elapsed)
    return {
        "activity": activity,
        "activity_at": activity_at,
        "elapsed_seconds": elapsed,
        "unit": unit,
        "eta_seconds": eta_seconds,
        "eta_source": eta_source,
    }


def _event_view(row: dict) -> dict:
    from .presentation import describe
    payload = redact_data(_json(row.get("payload_json")))
    event = row.get("event", "log")
    message = redact(row.get("message", ""))
    level = row.get("level", "info")
    stage = row.get("stage", "")
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "account_id": row.get("account_id", ""),
        "ts": row["ts"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(row["ts"])),
        "level": level,
        "event": event,
        "stage": stage,
        "message": message,
        "payload": payload,
        "presentation": describe(event, message, level, stage, payload),
        # 前端默认只渲染这份“人话”描述，原始 message 仅用于排查
        "narrative": narrative.describe(event, message, level=level, stage=stage,
                                        payload=payload),
    }


def _notification_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "category": row.get("category", "general"),
        "level": row.get("level", "warning"),
        "title": row.get("title", ""),
        "detail": redact(row.get("detail", "")),
        "context": _json(row.get("context_json")),
        "count": row.get("count", 1),
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "read_at": row.get("read_at"),
    }


def _preset_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "params": _json(row.get("params_json")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _sse(record: dict) -> str:
    payload = json.dumps(redact_data(record), ensure_ascii=False)
    event_id = record.get("id") or 0
    # 即时同步消息没有持久 ID，不能覆盖 EventSource 已记住的恢复游标。
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {payload}\n\n"


# 内嵌 SVG 图标：不需要额外文件，也避免浏览器请求 favicon 产生 404
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#0d1b2a"/>'
    '<text x="16" y="22" font-family="Segoe UI, sans-serif" font-size="15" font-weight="700" '
    'fill="#128a72" text-anchor="middle">AC</text></svg>'
)


def _mount_static(app: FastAPI):
    @app.get("/favicon.ico", include_in_schema=False)
    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return Response(content=FAVICON, media_type="image/svg+xml")

    if os.path.isdir(paths.STATIC_DIR):
        app.mount("/static", StaticFiles(directory=paths.STATIC_DIR), name="static")
    vue_dir = os.path.join(paths.STATIC_DIR, 'vue')

    @app.get("/")
    def index():
        vue_index = os.path.join(vue_dir, 'index.html')
        if not os.path.isfile(vue_index):
            raise HTTPException(status_code=503, detail='网页尚未构建，请在 frontend 目录执行 npm ci 和 npm run build，或使用 start.bat 启动。')
        return FileResponse(vue_index, headers={'Cache-Control': 'no-cache'})


app = create_app()


def main():
    import uvicorn

    host = settings.resolve("server.host", "127.0.0.1")
    if host not in settings.LOOPBACK_HOSTS:
        host = "127.0.0.1"  # 兜底：只允许本机访问
    port = int(settings.resolve("server.port", 8848))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
