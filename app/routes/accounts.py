"""账号路由：账号 CRUD、课程同步、学习通会话（一键登录）、课程与目录查询。"""

from fastapi import APIRouter, Body, HTTPException

from .. import accounts, catalog_service, sync_service
from .. import main

router = APIRouter()


@router.get("/api/accounts")
def list_accounts():
    db = main.db
    items = accounts.list_accounts()
    for item in items:
        item["syncing"] = sync_service.is_syncing(item["id"])
        item["course_count"] = len(db.list_courses(item["id"]))
        item["session"] = {**main.sessions.status(item["id"]),
                           "fetching": main.sessions.is_fetching(item["id"]),
                           "last_result": main.sessions.last_result(item["id"])}
    return {"items": items}


@router.post("/api/accounts", status_code=201)
def create_account(payload: main.AccountCreate):
    try:
        return accounts.create_account(payload.username.strip(), payload.password,
                                       payload.label, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/accounts/{account_id}")
def update_account(account_id: str, payload: main.AccountUpdate):
    updates = payload.model_dump(exclude_none=True)
    if "username" in updates:
        updates["username"] = updates["username"].strip()
    try:
        return accounts.update_account(account_id, updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="账号不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str):
    if sync_service.is_syncing(account_id):
        raise HTTPException(status_code=409, detail="该账号正在同步，无法删除")
    if not accounts.delete_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"ok": True}


@router.post("/api/accounts/{account_id}/sync")
def sync_account(account_id: str):
    try:
        result = sync_service.sync_account(main.db, main.hub, account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


# ---------------- 学习通会话（一键登录网页） ----------------

# Cookie 导出/回写白名单：会话内容敏感，只在这些字段间搬运，其余一律丢弃
_COOKIE_FIELDS = ("name", "value", "domain", "path", "expires",
                  "secure", "httpOnly", "sameSite")


@router.get("/api/accounts/{account_id}/session/cookies")
def session_cookies_export(account_id: str):
    """导出已保存会话的 Cookie（供桌面端「应用内验证窗」注入登录态）。

    服务只监听本机回环，Cookie 不出本机；无会话时 409 提示先获取会话。
    """
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    entry = main.sessions.get(account_id) or {}
    cookies = entry.get("cookies") or []
    if not cookies:
        raise HTTPException(status_code=409, detail="该账号还没有可用会话，请先获取会话")
    return {"items": cookies}


@router.post("/api/accounts/{account_id}/session/cookies")
def session_cookies_import(account_id: str, payload: dict = Body(default={})):
    """把验证窗里完成人机验证后的 Cookie 写回会话缓存。

    桌面端验证窗捕获答题页地址时同步回传窗口会话的 Cookie；写回后
    Python Worker 用同一份登录态继续逐题作答，避免验证状态丢失。
    """
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="缺少 Cookie 列表")
    if not all(isinstance(c, dict) and c.get("name") and c.get("value") is not None
               for c in items):
        raise HTTPException(status_code=400, detail="Cookie 列表格式不正确")
    clean = [{key: c[key] for key in _COOKIE_FIELDS if c.get(key) is not None}
             for c in items]
    entry = main.sessions.get(account_id) or {}
    main.sessions.save(account_id, clean,
                       display_name=entry.get("display_name", ""),
                       uid=entry.get("uid", ""))
    accounts.mark_login(account_id, True,
                        display_name=entry.get("display_name", ""))
    return {"ok": True, "count": len(clean)}


@router.get("/api/accounts/{account_id}/session")
def session_status(account_id: str):
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    status = main.sessions.status(account_id)
    status["fetching"] = main.sessions.is_fetching(account_id)
    status["last_result"] = main.sessions.last_result(account_id)
    return status


@router.post("/api/accounts/{account_id}/session")
def session_fetch(account_id: str):
    """用账号密码换取登录 Cookie 并保存（供一键打开学习通使用）"""
    try:
        result = main.sessions.fetch(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not result["started"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


@router.delete("/api/accounts/{account_id}/session")
def session_drop(account_id: str):
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    main.sessions.drop(account_id)
    return {"ok": True}


@router.post("/api/accounts/{account_id}/open-chaoxing")
def open_chaoxing(account_id: str, payload: dict = Body(default={})):
    """
    一键用已保存会话打开学习通网页（浏览器直接进入登录态）

    未保存会话时自动先用账号密码取一次会话（阻塞到取完），
    避免用户还要手动点两次。
    """
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    auto_fetch = payload.get("auto_fetch", True)

    status = main.sessions.status(account_id)
    if not status.get("has_session") or (auto_fetch and not status.get("fresh")):
        if not auto_fetch:
            raise HTTPException(status_code=409, detail="该账号还没有可用会话，请先获取会话")
        try:
            result = main.sessions.fetch(account_id, blocking=True)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if not result.get("started") or not main.sessions.last_result(account_id).get("ok"):
            raise HTTPException(status_code=409, detail=result.get("reason") or
                                main.sessions.last_result(account_id).get("message") or "会话获取失败")
        status = main.sessions.status(account_id)
        if not status.get("has_session"):
            raise HTTPException(
                status_code=409,
                detail=main.sessions.last_result(account_id).get("message")
                or "会话获取失败，请检查账号密码")

    try:
        return main.sessions.open_browser(account_id, payload.get("url", ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/api/accounts/{account_id}/courses")
def account_courses(account_id: str):
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    db = main.db
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

@router.get("/api/accounts/{account_id}/courses/{course_id}/catalog")
def course_catalog(account_id: str, course_id: str, kind: str = "work",
                   refresh: bool = False):
    """列出课程下待做的作业 / 考试；默认缓存 600 秒，refresh=true 强制重取"""
    try:
        return catalog_service.fetch_catalog(main.db, account_id, course_id,
                                             kind=kind, refresh=refresh)
    except KeyError:
        raise HTTPException(status_code=404, detail="账号不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------- 账号级任务批量控制 ----------------

@router.post('/api/accounts/{account_id}/tasks/{operation}')
def account_task_control(account_id: str, operation: str):
    if not accounts.get_account(account_id):
        raise HTTPException(status_code=404, detail='账号不存在')
    db = main.db
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
    command = getattr(main.manager, operation)
    for task_id in targets:
        try:
            command(task_id)
            accepted += 1
        except (ValueError, KeyError):
            changed.append(task_id)
    return {'account_id': account_id, 'operation': operation, 'accepted': accepted,
            'changed': len(changed), 'total': len(targets)}
