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

路由按域拆在 app/routes/（system/overview/accounts/workspace/tasks/settings/bank）；
本模块保留：惰性资源单例、请求模型、视图序列化辅助、鉴权守卫与静态托管。
tests/conftest.py 会整体替换本模块上的 db/hub/manager/sessions——路由模块因此
必须经 `from .. import main` 在调用时动态取这些单例，不允许顶层一次性绑定。
"""

import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .log_redaction import redact, redact_data

from . import (accounts, events, narrative, paths,
               question_bank_manager, session_service, settings, sync_service)
from .database import Database
from .task_manager import TaskManager
from .task_model import FEATURE_LABELS, is_terminal

paths.ensure_dirs()

_logger = logging.getLogger("courseark.autosync")


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
        # v2.2.1：启动后后台同步已登录账号，解决课程列表一直 0/0 任务点。
        # 线程为 daemon 且不参与启动等待；测试可用 AUTOCXWEBUI_DISABLE_AUTO_SYNC=1 关闭。
        _start_auto_sync()
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

AUTO_SYNC_DISABLE_ENV = "AUTOCXWEBUI_DISABLE_AUTO_SYNC"
_TRUTHY = {"1", "true", "yes", "on"}


def _auto_sync_disabled() -> bool:
    """测试/排障可整体关闭启动自动同步（环境变量优先于设置项）"""
    return os.environ.get(AUTO_SYNC_DISABLE_ENV, "").strip().lower() in _TRUTHY


def _auto_sync_enabled() -> bool:
    if _auto_sync_disabled():
        return False
    try:
        scheduler = (settings.load() or {}).get("scheduler") or {}
    except Exception:
        return True
    value = scheduler.get("sync_on_start", True)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return bool(value)


def _auto_sync_accounts():
    """后台串行同步登录状态为 ok 的账号；失败只写任务事件，不影响启动"""
    try:
        account_list = accounts.list_accounts(public=False)
    except Exception:
        _logger.warning("启动自动同步：读取账号列表失败", exc_info=True)
        return
    for account in account_list:
        account_id = str(account.get("id") or "")
        if not account_id or account.get("login_state") != "ok":
            continue
        try:
            if sync_service.is_syncing(account_id):
                continue
        except Exception:
            continue
        try:
            sync_service.sync_account(db, hub, account_id, blocking=True)
        except Exception as exc:
            _logger.warning("启动自动同步账号 %s 失败：%s", account_id, exc)
            db.add_event("", account_id, "sync_failed",
                         f"启动自动同步失败：{exc}", level="error", stage="sync")


def _start_auto_sync():
    """按设置启动自动同步守护线程；未启用时返回 None（便于测试断言）"""
    if not _auto_sync_enabled():
        return None
    thread = threading.Thread(target=_auto_sync_accounts,
                              name="courseark-auto-sync", daemon=True)
    thread.start()
    return thread


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


def _register_routes(app: FastAPI):
    """把按域拆分的路由挂到应用上（路由实现在 app/routes/）。"""
    from .routes import accounts, bank, overview, settings, system, tasks, workspace

    for module in (system, overview, accounts, workspace, tasks, settings, bank):
        # 直接并入 APIRoute 而不是 include_router：本机 FastAPI 会把 include_router
        # 的结果包成惰性 _IncludedRouter（没有 .path），而 tests/test_reliability.py
        # 需要从 app.routes 按 path 找到 SSE endpoint；直接并入行为与逐条
        # @app.get 装饰注册完全一致。
        app.router.routes.extend(module.router.routes)


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


# 恢复未完成单元时最多扫描的 work_result 事件条数
WORK_EVENT_LIMIT = 2000


def _unfinished_units_from_plan(task_id: str, plan, results: list):
    """基于已取出的 work_plan / work_result 事件行计算未完成单元数（批量预取用）"""
    if plan is None:
        return None
    payload = redact_data(_json(plan.get("payload_json")))
    units = payload.get("units") if isinstance(payload, dict) else None
    if not isinstance(units, list):
        return None
    planned = [unit for unit in units if isinstance(unit, dict) and unit.get("id") is not None]
    done = set()
    for row in results or []:
        result = redact_data(_json(row.get("payload_json")))
        if not isinstance(result, dict) or result.get("status") != "succeeded":
            continue
        if result.get("id") is not None:
            done.add(str(result.get("id")))
    return sum(1 for unit in planned if str(unit.get("id")) not in done)


def _unfinished_units(task_id: str):
    """
    未完成任务点数（中断续跑入口用）

    执行历史从未落库到 stats.work，只能从事件流恢复：取最近一条 work_plan 的 units，
    减去其后的 work_result 中 status=succeeded 的项。没有 work_plan 时返回 None，
    前端按“未知”处理而不是误报 0。
    """
    plans = db.list_events(task_id, limit=1, event="work_plan", latest=True)
    if not plans:
        return None
    plan = plans[-1]
    try:
        after = int(plan.get("id") or 0)
    except (TypeError, ValueError):
        after = 0
    results = db.list_events(task_id, after_id=after, limit=WORK_EVENT_LIMIT, event="work_result")
    return _unfinished_units_from_plan(task_id, plan, results)


def _unfinished_units_batch(rows: list) -> dict:
    """一次查询预取一批任务的未完成单元数：{task_id: int|None}（T5 N+1 消灭）"""
    targets = [row["id"] for row in rows if row.get("status") != "succeeded"]
    if not targets:
        return {}
    plans = db.work_plans_batch(targets)
    after = {}
    for task_id, plan in plans.items():
        try:
            after[task_id] = int(plan.get("id") or 0)
        except (TypeError, ValueError):
            after[task_id] = 0
    results = db.events_after_batch(targets, after, "work_result", WORK_EVENT_LIMIT)
    return {task_id: _unfinished_units_from_plan(task_id, plans.get(task_id), results.get(task_id))
            for task_id in targets}


def _task_view(row: dict, precomputed: dict = None) -> dict:
    from .work_progress import summarize
    stats = redact_data(_json(row.get("stats_json")))
    if row.get("status") == "succeeded":
        unfinished = 0
    elif precomputed is not None:
        unfinished = precomputed.get(row["id"])
    else:
        unfinished = _unfinished_units(row["id"])
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
        # v2.2.1：从 work_plan/work_result 事件恢复的未完成任务点数；无计划事件为 None
        "unfinished_units": unfinished,
        "error": redact(row.get("error", "")),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


# 逐题作答明细最多回放的 answer_result 事件条数：长作业也只需最近 500 条
ANSWER_EVENT_LIMIT = 500


def _task_exam_view(row: dict, stats: dict) -> dict:
    """已完成考试任务里的考试信息（「已完成」页展示用），没有考试返回 None"""
    params = _json(row.get("params_json"))
    exam_params = params.get("exam") if isinstance(params, dict) else None
    url = ""
    if isinstance(exam_params, dict):
        url = str(exam_params.get("url") or "")
    unit = None
    work = stats.get("work") if isinstance(stats, dict) else None
    units = work.get("units") if isinstance(work, dict) else None
    if isinstance(units, dict):
        for item in units.values():
            if isinstance(item, dict) and item.get("kind") == "exam":
                unit = item
                break
    if not url and not unit:
        return None
    unit = unit or {}
    exam_id = str(unit.get("id") or "").split(":")[-1]
    return {
        "title": str(unit.get("name") or "") or "考试",
        "exam_id": exam_id,
        "url": url,
        # already_done / detail 由 exam_room_url 的「平台已交卷」分支写入
        "already_done": bool(unit.get("already_done")),
        "detail": str(unit.get("detail") or ""),
    }


def _completed_view(row: dict, answers: list = None) -> dict:
    """已完成任务视图：在任务视图上补充耗时、逐题汇总、结果说明与考试信息"""
    view = _task_view(row)
    stats = view.get("stats") or {}
    if answers is None:
        answers = _task_answers(row["id"])
    else:
        answers = _task_answers_from_rows(answers)
    view["answers_summary"] = _answers_summary(answers, stats)
    view["answers_count"] = len(answers)

    started, finished = row.get("started_at"), row.get("finished_at")
    try:
        view["duration_seconds"] = (round(float(finished) - float(started), 1)
                                    if started and finished else None)
    except (TypeError, ValueError):
        view["duration_seconds"] = None

    exam = _task_exam_view(row, stats)
    view["exam"] = exam
    reason = redact(row.get("error", "") or "")
    if not reason and exam and exam.get("already_done"):
        reason = exam.get("detail") or ""
    if not reason:
        # 历史任务（在「平台已交卷」分支写入 already_done 之前完成的）没有 error，
        # 但同样存在「显示已完成却看不到明细」的问题，这里复用逐题明细的解释。
        reason = _answers_note(row, answers, stats)
    view["outcome"] = {"status": row.get("status", ""), "reason": reason}
    return view


def _answers_note(row: dict, answers: list, stats: dict) -> str:
    """逐题明细为空时给出可读解释；有明细时返回空串。

    用户反馈「告诉我已完成但是我实际上看不到」：明细为空必须说明原因，
    不能只显示一个空的作答列表。
    """
    if answers:
        return ""
    if int((stats or {}).get("questions", 0) or 0) > 0:
        return "本次运行的逐题明细未记录（任务在支持逐题明细的版本之前完成）。"
    if row.get("feature") == "exam":
        return "考试已交卷，但平台在考后不提供逐题回顾，本场考试没有可展示的逐题明细。"
    if row.get("status") == "succeeded":
        return "该任务完成时没有产生逐题作答（例如只处理了视频任务点）。"
    return ""


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
    return _dedupe_answers([_answer_view(row) for row in rows])


def _dedupe_answers(items: list) -> list:
    """按 (media, index) 去重保首现序（输入须已是 _answer_view 映射后的 dict 列表）"""
    latest, order = {}, []
    for item in items:
        dedupe_key = (item["media"], item["index"])
        if dedupe_key not in latest:
            order.append(dedupe_key)
        latest[dedupe_key] = item
    return [latest[key] for key in order]


def _task_answers_from_rows(rows: list) -> list:
    """批量预取的原始事件行 → 去重后的 answer 视图（与 _task_answers 等价，T5 用）"""
    return _dedupe_answers([_answer_view(row) for row in rows or []])


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
