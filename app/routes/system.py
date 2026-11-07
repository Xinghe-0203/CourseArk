"""系统级路由：健康检查、内部关机、SSE 事件流。"""

import asyncio
import hmac
import os
import queue
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .. import paths
from .. import main

router = APIRouter()


@router.get("/api/health")
def health():
    return {
        "ok": True,
        "data_dir": paths.DATA_DIR,
        "source_cli_dir": paths.SOURCE_CLI_DIR,
        "source_cli_writable": False,
        "schema_version": 1,
        "worker_runner": os.path.exists(paths.WORKER_RUNNER),
        "scheduler": main.manager.snapshot(),
        "sse_subscribers": main.hub.subscriber_count(),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }


@router.post("/api/internal/shutdown", status_code=202, include_in_schema=False)
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


@router.get("/api/events/stream")
async def stream(request: Request, last_event_id: int = Query(default=0, ge=0)):
    header = request.headers.get("last-event-id")
    if header is not None:
        try:
            last_event_id = int(header)
            if last_event_id < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的事件游标")
    subscriber = main.hub.subscribe()

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
                    missing = main.db.events_after(cursor, limit=500)
                    missing = [row for row in missing if row["id"] <= event_id]
                    if not missing:
                        break
                    for row in missing:
                        cursor = row["id"]
                        yield main._sse(main._event_view(row))
                if event_id <= cursor:
                    return
            cursor = max(cursor, event_id)
            yield main._sse(record)

        try:
            # 先订阅再读取数据库，期间发生的事件由游标去重。
            while True:
                rows = main.db.events_after(cursor, limit=500)
                if not rows:
                    break
                for row in rows:
                    cursor = row["id"]
                    yield main._sse(main._event_view(row))
                await asyncio.sleep(0)
            # 同步服务等内存事件保留兼容；数据库事件已经发送过则跳过。
            backlog = main.hub.replay_since(cursor, limit=2000)
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
            main.hub.unsubscribe(subscriber)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
