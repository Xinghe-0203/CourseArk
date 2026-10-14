"""HTTP API：状态码、错误响应、SSE 与敏感字段不泄露"""

import json
import threading
import time

import pytest

from app import accounts, paths, settings


def _create_account(client, username="13800001111", password="pwd123", label=""):
    response = client.post("/api/accounts", json={
        "username": username, "password": password, "label": label,
    })
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================
# 健康检查
# ============================================================

def test_health_reports_paths_and_scheduler(app_client):
    data = app_client.get("/api/health").json()
    assert data["ok"] is True
    assert data["source_cli_writable"] is False
    assert data["worker_runner"] is True
    assert "max_active_workers" in data["scheduler"] or "limit" in data["scheduler"]


# ============================================================
# 账号接口
# ============================================================

def test_account_lifecycle_never_leaks_password(app_client):
    created = _create_account(app_client, label="主账号")
    assert created["has_password"] is True
    assert "password" not in created
    assert created["username_masked"] == "138****1111"

    listed = app_client.get("/api/accounts").json()["items"]
    assert len(listed) == 1
    assert "password" not in listed[0]

    patched = app_client.patch(f"/api/accounts/{created['id']}", json={"label": "改名"}).json()
    assert patched["label"] == "改名"
    assert "password" not in patched

    # 用空密码提交不应清空已保存的密码
    app_client.patch(f"/api/accounts/{created['id']}", json={"password": "", "label": "改名2"})
    assert accounts.get_account(created["id"], public=False)["password"] == "pwd123"

    assert app_client.delete(f"/api/accounts/{created['id']}").status_code == 200
    assert app_client.get("/api/accounts").json()["items"] == []


def test_account_validation_errors(app_client):
    assert app_client.post("/api/accounts", json={"username": "1", "password": "x"}).status_code == 422
    assert app_client.post("/api/accounts", json={"username": "13900002222", "password": ""}).status_code == 422
    _create_account(app_client, "13900002222", "pwd123")
    duplicate = app_client.post("/api/accounts", json={"username": "13900002222", "password": "other"})
    assert duplicate.status_code == 400
    assert "已存在" in duplicate.json()["detail"]


def test_account_not_found_paths(app_client):
    assert app_client.patch("/api/accounts/ghost", json={"label": "x"}).status_code == 404
    assert app_client.delete("/api/accounts/ghost").status_code == 404
    assert app_client.get("/api/accounts/ghost/courses").status_code == 404


def test_account_courses_are_isolated_and_marked_stale(app_client):
    first = _create_account(app_client, "13800003333")
    second = _create_account(app_client, "13800004444")

    from app.main import db
    db.replace_courses(first["id"], [{
        "course_id": "c1", "class_id": "k1", "name": "高数", "author": "张老师",
        "if_open": True, "mission_fn": 3, "mission_all": 10,
    }])
    db.replace_courses(second["id"], [{
        "course_id": "c1", "class_id": "k2", "name": "高数", "author": "李老师",
        "if_open": False, "mission_fn": 0, "mission_all": 5,
    }])

    left = app_client.get(f"/api/accounts/{first['id']}/courses").json()
    right = app_client.get(f"/api/accounts/{second['id']}/courses").json()
    # 同名课程在不同账号下必须彼此独立
    assert left["items"][0]["class_id"] == "k1"
    assert left["items"][0]["mission_all"] == 10
    assert right["items"][0]["class_id"] == "k2"
    assert right["items"][0]["if_open"] is False

    accounts.mark_sync(first["id"], False, error="登录失败")
    stale = app_client.get(f"/api/accounts/{first['id']}/courses").json()
    assert stale["stale"] is True
    assert stale["items"][0]["name"] == "高数"  # 旧快照保留


# ============================================================
# 批次与任务
# ============================================================

def _create_run(app_client, feature="video", count=2, params=None, username="13800005555"):
    account = _create_account(app_client, username)
    targets = [{
        "account_id": account["id"], "course_id": f"c{i}", "class_id": f"k{i}",
        "course_name": f"课程{i}",
    } for i in range(count)]
    response = app_client.post("/api/runs", json={
        "feature": feature, "targets": targets, "params": params or {},
    })
    assert response.status_code == 201, response.text
    return account, response.json()


def test_create_run_expands_subtasks_and_freezes_params(app_client):
    account, created = _create_run(app_client, "video", count=3,
                                   params={"video": {"mode": "instant", "max_workers": 4}})
    assert created["count"] == 3
    assert len(created["task_ids"]) == 3

    tasks = app_client.get("/api/tasks").json()
    assert tasks["total"] == 3
    for task in tasks["items"]:
        assert task["status"] == "pending"
        assert task["feature"] == "video"
        assert task["params"]["video"]["mode"] == "instant"
        assert task["params"]["video"]["max_workers"] == 4
        assert "answer" not in task["params"]

    # 全局默认值变化不影响已冻结的快照
    settings.save({"defaults": {"video": {"mode": "real_time"}}})
    again = app_client.get(f"/api/tasks/{created['task_ids'][0]}").json()
    assert again["params"]["video"]["mode"] == "instant"


def test_create_run_validates_feature_and_targets(app_client):
    account = _create_account(app_client, "13800006666")
    bad_feature = app_client.post("/api/runs", json={
        "feature": "explode",
        "targets": [{"account_id": account["id"], "course_id": "c"}],
    })
    assert bad_feature.status_code == 422

    ghost = app_client.post("/api/runs", json={
        "feature": "video",
        "targets": [{"account_id": "ghost", "course_id": "c"}],
    })
    assert ghost.status_code == 400

    empty = app_client.post("/api/runs", json={"feature": "video", "targets": []})
    assert empty.status_code == 422


def test_create_run_rejects_bad_params(app_client):
    account = _create_account(app_client, "13800007777")
    response = app_client.post("/api/runs", json={
        "feature": "video",
        "targets": [{"account_id": account["id"], "course_id": "c"}],
        "params": {"video": {"max_workers": 500}},
    })
    assert response.status_code == 400
    assert "200" in response.json()["detail"] or "less" in response.json()["detail"].lower()


def test_task_filters_and_run_listing(app_client):
    _, created = _create_run(app_client, "download", count=2, username="13800008888")
    run_id = created["run_id"]

    filtered = app_client.get(f"/api/tasks?feature=download").json()
    assert filtered["total"] == 2
    assert app_client.get("/api/tasks?feature=video").json()["total"] == 0

    runs = app_client.get("/api/runs").json()["items"]
    assert runs[0]["id"] == run_id
    assert runs[0]["tasks"] == 2


def test_task_control_endpoints(app_client):
    _, created = _create_run(app_client, "video", count=1, username="13800009999")
    task_id = created["task_ids"][0]

    from app.main import db
    db.set_task_status(task_id, "running")

    assert app_client.post(f"/api/tasks/{task_id}/pause").status_code == 200
    assert db.get_task(task_id)["status"] == "pausing"
    assert app_client.post(f"/api/tasks/{task_id}/resume").status_code == 200
    assert db.get_task(task_id)["status"] == "running"
    assert app_client.post(f"/api/tasks/{task_id}/stop").status_code == 200
    stopping = db.get_task(task_id)["status"]
    assert stopping == "stopping"

    # 非终态任务不允许重试
    assert app_client.post(f"/api/tasks/{task_id}/retry").status_code == 409

    db.set_task_status(task_id, "failed", error="boom", finished=True)
    retry = app_client.post(f"/api/tasks/{task_id}/retry")
    assert retry.status_code == 201
    assert retry.json()["status"] == "pending"
    assert retry.json()["id"] != task_id


def test_task_control_unknown_task(app_client):
    assert app_client.post("/api/tasks/ghost/pause").status_code == 404
    assert app_client.get("/api/tasks/ghost").status_code == 404
    assert app_client.get("/api/tasks/ghost/events").status_code == 404


def test_pause_rejected_when_running_not_applicable(app_client):
    _, created = _create_run(app_client, "video", count=1, username="13800001010")
    task_id = created["task_ids"][0]
    # pending 状态不允许暂停（还没有 Worker 在跑）
    assert app_client.post(f"/api/tasks/{task_id}/pause").status_code == 409


def test_task_events_endpoint_filters(app_client):
    _, created = _create_run(app_client, "video", count=1, username="13800002020")
    task_id = created["task_ids"][0]
    from app.main import db
    db.add_event(task_id, "acc", "log", "普通日志", level="info")
    db.add_event(task_id, "acc", "task_failed", "出错了", level="error")

    all_events = app_client.get(f"/api/tasks/{task_id}/events").json()["items"]
    assert len(all_events) >= 3  # 含创建事件
    only_errors = app_client.get(f"/api/tasks/{task_id}/events?level=error").json()["items"]
    assert len(only_errors) == 1
    assert only_errors[0]["message"] == "出错了"
    problems = app_client.get(f"/api/tasks/{task_id}/events?level=problem").json()["items"]
    assert len(problems) == 1

    after = app_client.get(f"/api/tasks/{task_id}/events?after_id=1").json()["items"]
    assert all(item["id"] > 1 for item in after)


def test_history_endpoint(app_client):
    _, created = _create_run(app_client, "video", count=2, username="13800003030")
    from app.main import db
    db.set_task_status(created["task_ids"][0], "succeeded", finished=True)
    db.set_task_status(created["task_ids"][1], "failed", error="网络异常", finished=True)

    data = app_client.get("/api/history").json()
    assert data["total"] == 2
    failed = app_client.get("/api/history?status=failed").json()
    assert failed["total"] == 1
    assert failed["items"][0]["error"] == "网络异常"


# ============================================================
# 总览
# ============================================================

def test_overview_shape(app_client):
    _create_account(app_client, "13800004040")
    data = app_client.get("/api/overview").json()
    assert set(["accounts", "tasks", "today", "workers", "question_bank",
                "queue", "recent_events", "problems"]).issubset(data.keys())
    assert data["accounts"]["total"] == 1
    assert data["workers"]["limit"] >= 1


# ============================================================
# SSE
# ============================================================

@pytest.fixture()
def live_server(app_client, sandbox):
    """
    SSE 需要边收边推的真实连接，TestClient 的流式读取会阻塞。

    注意：uvicorn.Server 会为自己的 asyncio 循环注册信号处理器，
    在非主线程中运行必须关闭该行为。
    """
    import socket
    import threading

    import uvicorn

    from app.main import create_app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("测试服务器启动失败")

    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_sse_stream_pushes_events_after_connect(live_server):
    """连上后新产生的事件应实时推送（Worker 事件走同一条链路）"""
    import httpx

    from app.main import db, hub

    received = []

    def reader():
        with httpx.stream("GET", f"{live_server}/api/events/stream?last_event_id=0",
                          timeout=15) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
                    if any(item.get("message") == "实时事件" for item in received):
                        break

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(1.5)  # 等待订阅建立

    event_id = db.add_event("t1", "a1", "log", "实时事件", level="info")
    hub.publish({
        "id": event_id, "task_id": "t1", "account_id": "a1", "event": "log",
        "message": "实时事件", "level": "info", "stage": "log", "payload": {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "ts": time.time(),
    })
    thread.join(timeout=15)
    assert any(item.get("message") == "实时事件" for item in received), received


def test_sse_replays_backlog_on_reconnect(live_server):
    """断线重连：客户端带上最后事件 ID，服务端补齐缺失的增量"""
    import httpx

    from app.main import hub

    for index in range(3):
        hub.publish({
            "id": index + 1, "task_id": "t", "account_id": "", "event": "log",
            "message": f"补发{index}", "level": "info", "stage": "", "payload": {},
            "timestamp": "", "ts": time.time(),
        })

    seen = []
    with httpx.stream("GET", f"{live_server}/api/events/stream?last_event_id=1", timeout=15) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:])["message"])
            if len(seen) >= 2:
                break
    assert "补发1" in seen and "补发2" in seen
    assert "补发0" not in seen


# ============================================================
# 设置接口
# ============================================================

def test_settings_api_masks_secrets_and_keeps_them(app_client):
    response = app_client.patch("/api/settings", json={"llm": {"api_key": "sk-live-secret"}})
    assert response.status_code == 200

    data = app_client.get("/api/settings").json()
    assert data["llm"]["api_key"] == ""
    assert data["secrets"]["llm_api_key_configured"] is True

    # 前端只读回显提交空值时不得清空密钥
    app_client.patch("/api/settings", json={"llm": {"api_key": "", "model": "deepseek-chat"}})
    assert settings.resolve("llm.api_key") == "sk-live-secret"


def test_settings_api_clamps_values(app_client):
    data = app_client.patch("/api/settings", json={
        "scheduler": {"max_active_workers": 99},
        "defaults": {"learn_count": {"times": 0}},
    }).json()
    assert data["scheduler"]["max_active_workers"] == 20
    assert data["defaults"]["learn_count"]["times"] == 1


def test_presets_crud(app_client):
    created = app_client.post("/api/presets", json={
        "name": "晚高峰", "params": {"video": {"mode": "instant"}},
    })
    assert created.status_code == 201
    preset = created.json()
    assert preset["params"]["video"]["mode"] == "instant"

    listed = app_client.get("/api/presets").json()["items"]
    assert len(listed) == 1

    assert app_client.delete(f"/api/presets/{preset['id']}").status_code == 200
    assert app_client.delete(f"/api/presets/{preset['id']}").status_code == 404


# ============================================================
# 题库接口
# ============================================================

def test_question_bank_api(app_client):
    payload = json.dumps([
        {"question_text": "API题目", "answer": "B", "question_type": "单选题"},
    ], ensure_ascii=False)

    preview = app_client.post("/api/question-bank/import", json={
        "content": payload, "format": "json", "preview_only": True,
    }).json()
    assert preview["parsed"] == 1 and preview["new"] == 1

    committed = app_client.post("/api/question-bank/import", json={
        "content": payload, "format": "json",
    }).json()
    assert committed["imported"] == 1

    stats = app_client.get("/api/question-bank/stats").json()
    assert stats["total"] == 1

    search = app_client.get("/api/question-bank/search?q=API").json()
    assert search["total"] == 1
    assert search["items"][0]["answer"] == "B"

    exported = app_client.get("/api/question-bank/export?format=json")
    assert "API题目" in exported.text
    csv_export = app_client.get("/api/question-bank/export?format=csv")
    assert "attachment" in csv_export.headers["content-disposition"]

    assert app_client.post("/api/question-bank/import", json={
        "content": payload, "format": "yaml",
    }).status_code == 400


def test_question_bank_import_requires_content(app_client):
    assert app_client.post("/api/question-bank/import", json={}).status_code == 422


# ============================================================
# 静态页面
# ============================================================

def test_index_page_is_served(app_client):
    response = app_client.get("/")
    assert response.status_code == 200
    assert "CourseArk" in response.text
    # 现在是本机专用：明确写出只监听回环地址，且不再有“同网段可控制”的旧风险提示
    # Vue 生产页通过同源请求访问本机服务；检查实际入口可加载。
    import re
    assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text)
    assert assets
    assert all(app_client.get(asset).status_code == 200 for asset in assets)
    assert "无鉴权" not in response.text


def test_missing_vue_build_reports_how_to_rebuild(app_client, monkeypatch, tmp_path):
    from app.main import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(paths, 'STATIC_DIR', str(tmp_path))
    (tmp_path / 'index.html').write_text('retired frontend', encoding='utf-8')
    response = TestClient(create_app()).get('/')
    assert response.status_code == 503
    assert 'npm run build' in response.json()['detail']


def test_cors_is_not_open_to_any_origin(app_client):
    response = app_client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers.keys()}
