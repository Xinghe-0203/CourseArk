"""任务路由：批次创建、任务列表/详情/控制、事件检索与导出、历史与已完成。"""

import json
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from .. import narrative
from ..log_redaction import redact
from ..task_model import RunCreateRequest, build_tasks, is_terminal
from .. import main

router = APIRouter()


@router.post("/api/runs", status_code=201)
def create_run(payload: RunCreateRequest):
    try:
        run_id, tasks, params = build_tasks(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    main.manager.create_run(tasks, run_id, note=payload.note)
    return {
        "run_id": run_id,
        "task_ids": [task["id"] for task in tasks],
        "count": len(tasks),
        "params": params.snapshot(),
    }


@router.get("/api/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=200),
              offset: int = Query(default=0, ge=0)):
    db = main.db
    rows = db.list_runs(limit, offset)
    for row in rows:
        row["tasks"] = db.count_tasks({"run_id": row["id"]})
    return {"items": rows}


@router.get("/api/tasks")
def list_tasks(status: str = "", account_id: str = "", run_id: str = "",
               feature: str = "", course_id: str = "", q: str = "",
               since: float = 0, until: float = 0,
               include_live: int = 0,
               limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0)):
    """
    任务列表。

    include_live=1 时同时返回非终态任务的 live 快照（当前动作 / 已用时 / ETA）。
    前端此前只能先拿列表、再对每个运行中任务各打一次 /tasks/{id} 补 live，
    8 个小窗/列表同时刷新就是 8 次带逐题明细的详情请求；这里合并成一次。
    """
    db = main.db
    filters = {"status": status, "account_id": account_id, "run_id": run_id,
               "feature": feature, "course_id": course_id, "q": q,
               "since": since or None, "until": until or None}
    rows = db.list_tasks(filters, limit, offset)
    # T5：一次批量预取非 succeeded 任务的未完成单元数，替代逐行 _unfinished_units
    precomputed = main._unfinished_units_batch(rows)
    items = [main._task_view(row, precomputed) for row in rows]
    if include_live:
        for row, item in zip(rows, items):
            if item.get("status") in main.LIVE_STATUSES:
                item["live"] = main._live_view(row)
    return {"total": db.count_tasks(filters), "items": items}


@router.get("/api/tasks/{task_id}")
def task_detail(task_id: str):
    db = main.db
    row = db.get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    detail = main._task_view(row)
    detail["events"] = [main._event_view(item) for item in db.list_events(task_id, limit=50, latest=True)]
    detail["activity_events"] = [main._event_view(item) for item in db.list_events(task_id, limit=50, latest=True, business=True)]
    # 逐题作答明细：老任务没有 answer_result 事件时返回空数组与零值汇总
    answers = main._task_answers(task_id)
    detail["answers"] = answers
    detail["answers_summary"] = main._answers_summary(answers, detail.get("stats") or {})
    # 明细为空时说明原因，避免「显示已完成但看不到任何作答」
    detail["answers_note"] = main._answers_note(row, answers, detail.get("stats") or {})
    detail["live"] = main._live_view(row)
    return detail


@router.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str):
    return main._control(main.manager.pause, task_id)


@router.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str):
    """
    继续任务

    - interrupted / stopped / failed：用原参数快照新建 pending 任务（Worker 会按平台
      状态重新发现未完成任务点），返回新任务视图，并给出 resumed_from / new_task_id
    - paused / pausing：恢复原 Worker（v2.1 行为，保持不变）
    - 其它状态：409
    """
    db = main.db
    row = db.get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    status = row.get("status", "")
    if status in ("interrupted", "stopped", "failed"):
        try:
            new_row = main.manager.retry_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在")
        detail = main._task_view(new_row)
        detail["resumed_from"] = task_id
        detail["new_task_id"] = new_row["id"]
        return detail
    if status in ("paused", "pausing"):
        return main._control(main.manager.resume, task_id)
    raise HTTPException(status_code=409, detail="仅中断、已停止或失败的任务可以继续执行")


@router.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str):
    return main._control(main.manager.stop, task_id)


@router.post("/api/tasks/{task_id}/retry", status_code=201)
def retry_task(task_id: str):
    db = main.db
    row = db.get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not is_terminal(row["status"]):
        raise HTTPException(status_code=409, detail="仅终态任务可以重试")
    try:
        return main._task_view(main.manager.retry_task(task_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/api/tasks/{task_id}/events")
def task_events(task_id: str, after_id: int = 0, limit: int = Query(default=200, ge=1, le=1000),
                level: str = "all", event: str = "all", latest: bool = False,
                stage: str = "all", since: float = 0, until: float = 0,
                q: str = ""):
    """事件检索（v2.4.0 T10.8）：游标分页 + 阶段/时间窗/关键词过滤。

    next_after_id 为「按当前过滤条件继续向后翻页」的游标——传回前端，
    下次请求 after_id=next_after_id 即可取到后续事件。
    """
    db = main.db
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = db.list_events(task_id, after_id, limit, level, event, latest=latest,
                          stage=stage or "all", since=since or 0, until=until or 0,
                          q=q or None)
    items = [main._event_view(item) for item in rows]
    next_after_id = items[-1]["id"] if len(items) >= limit else 0
    return {"items": items, "next_after_id": next_after_id}


@router.get("/api/tasks/{task_id}/logs")
def task_logs(task_id: str):
    db = main.db
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


@router.get("/api/events/export")
def events_export(format: str = "json", task_id: str = "",
                  since: float = 0, until: float = 0):
    """事件导出（v2.4.0 T12）：JSON 完整事件数组 / txt 文本渲染，支持时间窗。

    跨任务：task_id 为空导出全部任务（同步哨兵行 task_id="0" 一并包含）。
    """
    db = main.db
    fmt = (format or "json").lower()
    if fmt not in ("json", "txt"):
        raise HTTPException(status_code=422, detail="format 仅支持 json 或 txt")

    def _rows():
        after = 0
        while True:
            if task_id:
                rows = db.list_events(task_id, after_id=after, limit=1000,
                                      since=since or 0, until=until or 0)
            else:
                rows = db.events_window(since=since or 0, until=until or 0,
                                        after_id=after, limit=1000)
            if not rows:
                return
            yield from rows
            after = rows[-1]["id"]

    if fmt == "txt":
        def txt_lines():
            for row in _rows():
                stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["ts"]))
                yield f"{stamp} | {row['level']} | {row['stage']} | {redact(row['message'])}\n"

        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"events-{task_id or 'all'}-{stamp}.txt"
        return StreamingResponse(txt_lines(), media_type="text/plain; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    items = []
    for row in _rows():
        view = main._event_view(row)
        from ..presentation import describe as _present
        view["presentation"] = _present(view["event"], view["message"],
                                        level=view["level"], stage=view["stage"],
                                        payload=view["payload"])
        view["narrative"] = narrative.describe(view["event"], view["message"],
                                               level=view["level"], stage=view["stage"],
                                               payload=view["payload"])
        items.append(view)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"events-{task_id or 'all'}-{stamp}.json"
    payload_bytes = json.dumps({"total": len(items), "items": items},
                               ensure_ascii=False).encode("utf-8")
    return Response(payload_bytes, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------- 历史 ----------------

@router.get("/api/history")
def history(status: str = "", account_id: str = "", feature: str = "",
            q: str = "", since: float = 0, until: float = 0,
            limit: int = Query(default=50, ge=1, le=200),
            offset: int = Query(default=0, ge=0)):
    db = main.db
    filters = {"status": status or "succeeded,failed,stopped,interrupted", "account_id": account_id, "feature": feature,
               "q": q, "since": since or None, "until": until or None}
    rows = db.list_tasks(filters, limit, offset)
    precomputed = main._unfinished_units_batch(rows)
    return {"total": db.count_tasks(filters),
            "items": [main._task_view(row, precomputed) for row in rows]}


@router.get("/api/completed")
def completed_tasks(feature: str = "", account_id: str = "", q: str = "",
                    status: str = "", since: float = 0, until: float = 0,
                    limit: int = Query(default=30, ge=1, le=100),
                    offset: int = Query(default=0, ge=0)):
    """
    已结束任务的完整视图（「已完成」专页数据源）

    与 /api/history 的区别：这里逐条补充逐题汇总、耗时、结果说明与考试信息，
    用于集中展示「各种已完成的具体信息」。明细事件按任务各查一次，
    不在循环里拉全量事件。

    status 支持按终态过滤（succeeded/failed/stopped/interrupted，可逗号分隔）；
    为空时返回全部终态。分页语义在过滤后依然成立——前端不再需要先取 200 条
    再本地筛选（旧实现会导致「筛选时不能翻页」且丢失逐题汇总）。
    """
    db = main.db
    terminal = "succeeded,failed,stopped,interrupted"
    filters = {"status": status or terminal,
               "account_id": account_id, "feature": feature, "q": q,
               "since": since or None, "until": until or None}
    rows = db.list_tasks(filters, limit, offset)
    # T5：逐题明细一次批量预取（每任务最近 ANSWER_EVENT_LIMIT 条），消灭逐行 _task_answers
    answer_map = db.answers_batch([row["id"] for row in rows], main.ANSWER_EVENT_LIMIT)
    return {"total": db.count_tasks(filters),
            "items": [main._completed_view(row, answer_map.get(row["id"])) for row in rows]}
