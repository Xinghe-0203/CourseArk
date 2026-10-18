"""v2.2.1：启动自动同步 + 中断任务续跑 + 未完成任务点计数"""

import pytest

from app import accounts, main, settings, sync_service


# ============================================================
# 辅助
# ============================================================

def _create_account(client, username="13800002222"):
    response = client.post("/api/accounts", json={"username": username, "password": "pwd123"})
    assert response.status_code == 201, response.text
    return response.json()


def _create_run(client, feature="chapter_exam", count=1, params=None,
                username="13800003333"):
    account = _create_account(client, username)
    targets = [{
        "account_id": account["id"], "course_id": f"c{i}", "class_id": f"k{i}",
        "course_name": f"课程{i}",
    } for i in range(count)]
    response = client.post("/api/runs", json={
        "feature": feature, "targets": targets, "params": params or {},
    })
    assert response.status_code == 201, response.text
    return account, response.json()


# ============================================================
# 设置：scheduler.sync_on_start
# ============================================================

def test_settings_sync_on_start_default_and_patch(app_client):
    data = app_client.get("/api/settings").json()
    assert data["scheduler"]["sync_on_start"] is True

    patched = app_client.patch("/api/settings", json={"scheduler": {"sync_on_start": False}}).json()
    assert patched["scheduler"]["sync_on_start"] is False
    assert app_client.get("/api/settings").json()["scheduler"]["sync_on_start"] is False

    app_client.patch("/api/settings", json={"scheduler": {"sync_on_start": True}})
    assert app_client.get("/api/settings").json()["scheduler"]["sync_on_start"] is True


def test_settings_sync_on_start_normalizes_strings(app_client):
    app_client.patch("/api/settings", json={"scheduler": {"sync_on_start": "false"}})
    assert app_client.get("/api/settings").json()["scheduler"]["sync_on_start"] is False
    app_client.patch("/api/settings", json={"scheduler": {"sync_on_start": "yes"}})
    assert app_client.get("/api/settings").json()["scheduler"]["sync_on_start"] is True


# ============================================================
# 启动自动同步
# ============================================================

def test_auto_sync_disabled_by_env(sandbox):
    # conftest 的沙箱已设置 AUTOCXWEBUI_DISABLE_AUTO_SYNC=1
    assert main._auto_sync_disabled() is True
    assert main._auto_sync_enabled() is False
    assert main._start_auto_sync() is None


def test_auto_sync_disabled_by_setting(sandbox, monkeypatch):
    monkeypatch.delenv(main.AUTO_SYNC_DISABLE_ENV, raising=False)
    settings.save({"scheduler": {"sync_on_start": False}})
    assert main._auto_sync_enabled() is False
    assert main._start_auto_sync() is None


def test_auto_sync_thread_starts_when_enabled(sandbox, monkeypatch):
    monkeypatch.delenv(main.AUTO_SYNC_DISABLE_ENV, raising=False)
    thread = main._start_auto_sync()
    assert thread is not None
    thread.join(5)
    assert thread.daemon is True


def test_auto_sync_accounts_only_logged_in_and_idle(sandbox, monkeypatch):
    ok = accounts.create_account("13800000101", "pwd123", label="已登录")
    accounts.mark_login(ok["id"], True)
    accounts.create_account("13800000102", "pwd123", label="未登录")
    busy = accounts.create_account("13800000103", "pwd123", label="同步中")
    accounts.mark_login(busy["id"], True)

    calls = []

    def fake_sync(db, hub, account_id, blocking=False):
        calls.append((account_id, blocking))
        return {"started": True, "reason": ""}

    monkeypatch.setattr(sync_service, "sync_account", fake_sync)
    monkeypatch.setattr(sync_service, "is_syncing", lambda account_id: account_id == busy["id"])

    main._auto_sync_accounts()

    # 只同步登录状态 ok 且不在同步中的账号，并串行阻塞等待
    assert calls == [(ok["id"], True)]


def test_auto_sync_failure_only_records_notification(sandbox, monkeypatch):
    account = accounts.create_account("13800000104", "pwd123", label="失败账号")
    accounts.mark_login(account["id"], True)

    def boom(db, hub, account_id, blocking=False):
        raise RuntimeError("无法启动课程同步进程")

    monkeypatch.setattr(sync_service, "sync_account", boom)
    monkeypatch.setattr(sync_service, "is_syncing", lambda account_id: False)

    main._auto_sync_accounts()  # 不抛异常

    items = main.manager.notifications.list(include_read=False)["items"]
    assert any("启动自动同步失败" in item["detail"] for item in items)


def test_lifespan_starts_auto_sync(sandbox, monkeypatch):
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(main, "_start_auto_sync", lambda: calls.append(True))

    with TestClient(main.create_app()):
        pass
    assert calls == [True]


# ============================================================
# 中断任务续跑
# ============================================================

@pytest.mark.parametrize("status", ["interrupted", "stopped", "failed"])
def test_resume_terminal_failure_creates_pending_task(app_client, status):
    from app.main import db

    _, created = _create_run(app_client, "independent_homework",
                             params={"selection": {"mode": "selected", "ids": ["unit-1"]}})
    task_id = created["task_ids"][0]

    db.set_task_status(task_id, status, error="进程中断", finished=True)
    response = app_client.post(f"/api/tasks/{task_id}/resume")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "pending"
    assert body["new_task_id"] == body["id"]
    assert body["new_task_id"] != task_id
    assert body["resumed_from"] == task_id
    # 直接复用原参数快照（含 selection），不重新解析
    assert body["params"]["selection"] == {"mode": "selected", "ids": ["unit-1"]}
    assert body["unfinished_units"] is None


def test_resume_rejects_running_and_pending(app_client):
    from app.main import db

    _, created = _create_run(app_client, "chapter_exam")
    task_id = created["task_ids"][0]

    assert app_client.post(f"/api/tasks/{task_id}/resume").status_code == 409

    db.set_task_status(task_id, "running")
    response = app_client.post(f"/api/tasks/{task_id}/resume")
    assert response.status_code == 409
    assert "继续" in response.json()["detail"]


def test_resume_unknown_task(app_client):
    assert app_client.post("/api/tasks/ghost/resume").status_code == 404


def test_resume_keeps_paused_worker_control(app_client):
    from app.main import db

    _, created = _create_run(app_client, "video")
    task_id = created["task_ids"][0]
    db.set_task_status(task_id, "running")
    assert app_client.post(f"/api/tasks/{task_id}/pause").status_code == 200
    assert db.get_task(task_id)["status"] == "pausing"

    response = app_client.post(f"/api/tasks/{task_id}/resume")
    assert response.status_code == 200
    assert db.get_task(task_id)["status"] == "running"


# ============================================================
# unfinished_units：从 work_plan / work_result 事件恢复
# ============================================================

def test_unfinished_units_from_work_events(app_client):
    from app.main import db

    _, created = _create_run(app_client, "chapter_exam")
    task_id = created["task_ids"][0]
    account_id = db.get_task(task_id)["account_id"]

    db.add_event(task_id, account_id, "work_plan", "任务范围已读取", stage="course",
                 payload={"units": [
                     {"id": "u1", "name": "视频A", "kind": "video"},
                     {"id": "u2", "name": "作业B", "kind": "homework"},
                     {"id": "u3", "name": "测验C", "kind": "exam"},
                 ], "sealed": True})
    db.add_event(task_id, account_id, "work_result", "此前已完成", stage="video",
                 payload={"id": "u1", "name": "视频A", "status": "succeeded"})
    db.set_task_status(task_id, "interrupted", finished=True)

    detail = app_client.get(f"/api/tasks/{task_id}").json()
    assert detail["unfinished_units"] == 2

    db.add_event(task_id, account_id, "work_result", "作业提交已接受", stage="homework",
                 payload={"id": "u2", "name": "作业B", "status": "succeeded"})
    assert app_client.get(f"/api/tasks/{task_id}").json()["unfinished_units"] == 1


def test_unfinished_units_null_without_work_plan(app_client):
    _, created = _create_run(app_client, "chapter_exam")
    task_id = created["task_ids"][0]
    assert app_client.get(f"/api/tasks/{task_id}").json()["unfinished_units"] is None


def test_unfinished_units_zero_after_plan_sealed(app_client):
    from app.main import db

    _, created = _create_run(app_client, "chapter_exam")
    task_id = created["task_ids"][0]
    account_id = db.get_task(task_id)["account_id"]

    db.add_event(task_id, account_id, "work_plan", "任务范围已读取", stage="course",
                 payload={"units": [], "sealed": True})
    db.set_task_status(task_id, "interrupted", finished=True)
    assert app_client.get(f"/api/tasks/{task_id}").json()["unfinished_units"] == 0
