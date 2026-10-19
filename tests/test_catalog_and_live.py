"""
v2.2 后端：独立作业选择、独立考试目录 API、任务运行中快照 live

约定（实现与发布说明见 docs/release-2.2.md 第三节「挑选作业/考试」、第四节「运行中的进度小窗」）：
- SelectionParams 默认 all，selected 时必须勾选条目
- GET /api/accounts/{account_id}/courses/{course_id}/catalog?kind=work|exam
  子进程 + SQLite 缓存（TTL 600s），测试注入假 runner，不真登录
- GET /api/tasks/{id} 的 live 字段由事件流推导，老任务为 null
"""

import json

import pytest

from app import catalog_service, narrative, presentation, task_model


# ============================================================
# 工具
# ============================================================

def _db():
    from app.main import db
    return db


def _create_account(app_client, username="13800008881", password="pwd123", label="目录测试"):
    response = app_client.post("/api/accounts", json={
        "username": username, "password": password, "label": label,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _add_course(account_id, course_id="course-1", class_id="class-1"):
    _db().replace_courses(account_id, [{
        "course_id": course_id, "class_id": class_id, "cpi": "cpi-1",
        "name": "测试课程", "author": "老师",
    }])
    return course_id


def _create_task(task_id, account_id, feature="video", status="running",
                 started_at=None, finished_at=None, stage="", stats=None,
                 params=None):
    _db().create_task({
        "id": task_id, "account_id": account_id, "feature": feature,
        "status": status, "stage": stage, "created_at": 1760000000.0,
        "params": params or {}, "stats": stats or {},
    })
    _db().update_task(task_id, started_at=started_at, finished_at=finished_at)
    return task_id


def _event(task_id, event, payload=None, ts=1760000000.0, stage="",
           message="", level="info"):
    return _db().add_event(task_id, "", event, message, level=level, stage=stage,
                           payload=payload or {}, ts=ts)


# ============================================================
# 任务模型：exam 功能 + SelectionParams
# ============================================================

def test_exam_feature_and_selection_defaults():
    assert "exam" in task_model.FEATURES
    assert task_model.FEATURE_LABELS["exam"] == "独立考试"

    selection = task_model.SelectionParams()
    assert selection.mode == "all"
    assert selection.ids == []

    with pytest.raises(ValueError, match="选择模式下至少选择一项"):
        task_model.SelectionParams(mode="selected", ids=[])

    with pytest.raises(ValueError, match="选择方式"):
        task_model.SelectionParams(mode="whatever")

    normalized = task_model.SelectionParams(mode="selected", ids=[" a ", "a", "", "b"])
    assert normalized.ids == ["a", "b"]


def test_selection_is_kept_for_exam_and_independent_homework(sandbox):
    params = task_model.TaskParams.from_settings(
        {"selection": {"mode": "selected", "ids": ["work-2"]}},
        feature="independent_homework")
    snapshot = params.for_feature("independent_homework")
    assert snapshot["selection"] == {"mode": "selected", "ids": ["work-2"]}
    # 列表整体替换：不会把默认值或上一次的 id 拼进来
    params = task_model.TaskParams.from_settings(
        {"selection": {"mode": "selected", "ids": ["exam-1"]}}, feature="exam")
    assert params.for_feature("exam")["selection"]["ids"] == ["exam-1"]

    exam_snapshot = task_model.TaskParams.from_settings(feature="exam").for_feature("exam")
    assert set(exam_snapshot) == {"answer", "advanced", "selection", "exam"}
    assert exam_snapshot["exam"] == {"url": ""}
    assert exam_snapshot["selection"] == {"mode": "all", "ids": []}

    # 其它功能不携带选择参数
    assert "selection" not in task_model.TaskParams.from_settings(
        feature="chapter_exam").for_feature("chapter_exam")


def test_create_exam_run_freezes_selection(app_client):
    account = _create_account(app_client)
    _add_course(account["id"], course_id="exam-course")
    response = app_client.post("/api/runs", json={
        "feature": "exam",
        "targets": [{"account_id": account["id"], "course_id": "exam-course",
                     "class_id": "class-1", "course_name": "测试课程"}],
        "params": {"selection": {"mode": "selected", "ids": ["exam-9"]}},
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["count"] == 1
    assert data["params"]["selection"] == {"mode": "selected", "ids": ["exam-9"]}

    detail = app_client.get(f"/api/tasks/{data['task_ids'][0]}").json()
    assert detail["feature"] == "exam"
    assert detail["feature_label"] == "独立考试"
    assert detail["params"]["selection"] == {"mode": "selected", "ids": ["exam-9"]}
    # 旧任务快照没有 selection 时按 all 处理（读取不报错）
    assert detail["live"] is None


def test_settings_features_include_exam(app_client):
    data = app_client.get("/api/settings").json()
    labels = {item["key"]: item["label"] for item in data["features"]}
    assert labels["exam"] == "独立考试"
    assert "tiku" not in json.dumps(data)


# ============================================================
# 课程目录 API（假 runner，不真登录）
# ============================================================

def test_catalog_api_uses_cache_and_refresh(app_client, monkeypatch):
    account = _create_account(app_client, username="13800008882")
    course_id = _add_course(account["id"])
    calls = []

    def fake_runner(job):
        calls.append(job)
        return [{"id": "work-1", "title": "第4章组件", "status": "待做",
                 "time_left": "剩余 2 天", "valid": True, "url": ""}]

    monkeypatch.setattr(catalog_service, "_run_catalog_job", fake_runner)

    first = app_client.get(
        f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=work")
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["kind"] == "work"
    assert data["from_cache"] is False
    assert data["error"] == ""
    assert data["items"][0]["id"] == "work-1"
    assert data["fetched_at"] > 0
    assert len(calls) == 1
    assert calls[0]["kind"] == "work"
    assert calls[0]["username"] == "13800008882"

    second = app_client.get(
        f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=work")
    assert second.json()["from_cache"] is True
    assert second.json()["items"] == data["items"]
    assert len(calls) == 1  # 缓存期内不重复拉取

    refreshed = app_client.get(
        f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=work&refresh=true")
    assert refreshed.json()["from_cache"] is False
    assert len(calls) == 2


def test_catalog_api_validation_and_failures(app_client, monkeypatch):
    account = _create_account(app_client, username="13800008883")
    course_id = _add_course(account["id"])

    bad_kind = app_client.get(
        f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=paper")
    assert bad_kind.status_code == 400
    assert "work 或 exam" in bad_kind.json()["detail"]

    missing = app_client.get(
        f"/api/accounts/ghost/courses/{course_id}/catalog?kind=work")
    assert missing.status_code == 404

    def failing_runner(job):
        raise RuntimeError("登录失败，请检查账号密码")

    monkeypatch.setattr(catalog_service, "_run_catalog_job", failing_runner)
    failure = app_client.get(
        f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=exam")
    assert failure.status_code == 502
    assert "登录失败" in failure.json()["detail"]


def test_catalog_api_falls_back_to_stale_cache(app_client, monkeypatch):
    account = _create_account(app_client, username="13800008884")
    course_id = _add_course(account["id"])
    state = {"fail": False}

    def runner(job):
        if state["fail"]:
            raise RuntimeError("网络超时")
        return [{"id": "w1", "title": "旧列表", "valid": True}]

    monkeypatch.setattr(catalog_service, "_run_catalog_job", runner)
    url = f"/api/accounts/{account['id']}/courses/{course_id}/catalog?kind=work"
    assert app_client.get(url).json()["items"][0]["title"] == "旧列表"

    state["fail"] = True
    stale = app_client.get(url + "&refresh=true")
    assert stale.status_code == 200
    body = stale.json()
    assert body["from_cache"] is True
    assert body["items"][0]["title"] == "旧列表"
    assert "网络超时" in body["error"]


def test_catalog_runner_stdout_parser(app_client, monkeypatch, sandbox):
    """直接验证子进程 stdout 的 catalog_result / catalog_failed 解析"""
    class FakeProcess:
        def __init__(self, stdout):
            self.stdout = stdout

        def communicate(self, timeout=None):
            return self.stdout, None

        def kill(self):
            pass

    monkeypatch.setattr(catalog_service.subprocess, "Popen",
                        lambda *args, **kwargs: FakeProcess(
                            b'{"event":"log","message":"\xe7\x99\xbb\xe5\xbd\x95"}\n'
                            b'{"event":"catalog_result","payload":{"items":[{"id":"x"}]}}\n'))
    job = {"account_id": "a1", "course_id": "c1", "kind": "work"}
    assert catalog_service._run_catalog_job(job) == [{"id": "x"}]

    monkeypatch.setattr(catalog_service.subprocess, "Popen",
                        lambda *args, **kwargs: FakeProcess(
                            b'{"event":"catalog_failed","message":"\xe8\xaf\xbe\xe7\xa8\x8b\xe4\xb8\x8d\xe5\xad\x98\xe5\x9c\xa8"}\n'))
    with pytest.raises(RuntimeError, match="课程不存在"):
        catalog_service._run_catalog_job(job)

    monkeypatch.setattr(catalog_service.subprocess, "Popen",
                        lambda *args, **kwargs: FakeProcess(b"not json\n"))
    with pytest.raises(RuntimeError, match="读取作业列表失败"):
        catalog_service._run_catalog_job(job)


# ============================================================
# 任务详情 live 快照
# ============================================================

def test_live_snapshot_unit_rate(app_client, monkeypatch):
    import app.main as main_module
    account = _create_account(app_client, username="13800008885")
    now = 1760000100.0
    started = now - 100
    _create_task("live-unit", account["id"], feature="video", status="running",
                 started_at=started)
    _event("live-unit", "media_progress", {
        "media": "1.1 Vue 基础", "current": 120, "total": 600,
    }, ts=now - 90, stage="video")

    monkeypatch.setattr(main_module.time, "time", lambda: now)
    detail = app_client.get("/api/tasks/live-unit").json()
    live = detail["live"]
    assert live is not None
    assert "1.1 Vue 基础" in live["activity"]
    assert live["activity_at"] == now - 90
    assert live["elapsed_seconds"] == 100
    assert live["unit"] == {"label": "1.1 Vue 基础", "current": 120, "total": 600}
    assert live["eta_seconds"] == 360
    assert live["eta_source"] == "unit"


def test_live_snapshot_task_rate_and_activity(app_client, monkeypatch):
    import app.main as main_module
    account = _create_account(app_client, username="13800008886")
    now = 1760000200.0
    started = now - 400
    _create_task("live-task", account["id"], feature="download", status="running",
                 started_at=started, stats={"success": 1, "total": 4})
    _event("live-task", "chapter_started", {"chapter": "第 1 章", "current": 1, "total": 4},
           ts=now - 50, stage="chapter", message="第 1 章")

    monkeypatch.setattr(main_module.time, "time", lambda: now)
    detail = app_client.get("/api/tasks/live-task").json()
    live = detail["live"]
    assert live["elapsed_seconds"] == 400
    assert "第 1 章" in live["activity"]
    assert live["unit"] is None
    assert live["eta_seconds"] == 1200
    assert live["eta_source"] == "task"
    assert live["activity_at"] == now - 50


def test_live_snapshot_absent_for_legacy_and_terminal(app_client):
    account = _create_account(app_client, username="13800008887")
    _create_task("live-old", account["id"], feature="course_all", status="succeeded")
    detail = app_client.get("/api/tasks/live-old").json()
    assert detail["live"] is None

    _create_task("live-done", account["id"], feature="video", status="succeeded",
                 started_at=1760000000.0, finished_at=1760000050.0)
    live = app_client.get("/api/tasks/live-done").json()["live"]
    assert live["elapsed_seconds"] == 50
    assert live["eta_seconds"] is None
    assert live["eta_source"] is None


# ============================================================
# 考试阶段文案
# ============================================================

def test_exam_stage_presentation_and_narrative_wording():
    payload = {"media": "期末考试", "current": 2, "total": 10, "llm_calls": 2}
    item = narrative.describe("exam_stats", "考试进度", stage="exam", payload=payload)
    assert item["title"] == "AI 正在作答考试：期末考试"
    assert "题库" not in json.dumps(item, ensure_ascii=False)

    view = presentation.describe("exam_stats", "考试进度", stage="exam", payload=payload)
    assert view["category"] == "exam"
    assert "AI 正在作答考试" in view["title"]
    assert view["visible"] is True

    result = presentation.describe("answer_result", "第 1 题", stage="exam", payload={
        "status": "answered", "question_type": "单选题", "answer": "A",
    })
    assert result["category"] == "exam"
    assert result["title"] == "AI 已作答"
