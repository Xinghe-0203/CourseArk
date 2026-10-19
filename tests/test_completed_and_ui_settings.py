"""v2.2.3：已完成任务专页数据源、逐题明细为空时的解释、界面偏好设置。

用户反馈「独立考试看不到具体信息，他告诉我已完成但是我实际上看不到」：
- 考试交卷后平台不提供逐题回顾，明细必然为空，接口必须给出可读原因；
- 已完成任务需要能集中查看（/api/completed）；
- 黄色续跑提示要支持「不再提醒」，状态持久化在 settings.ui。
"""

import pytest

from app import settings as settings_module


def _db():
    from app.main import db
    return db


def _create_account(app_client, username="13800009991", label="已完成测试"):
    response = app_client.post("/api/accounts", json={
        "username": username, "password": "pwd123", "label": label,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(task_id, account_id, feature="exam", status="succeeded",
                 started_at=1760000000.0, finished_at=1760000060.0,
                 stats=None, params=None, error=None, course_name="测试课程"):
    _db().create_task({
        "id": task_id, "account_id": account_id, "feature": feature,
        "status": status, "created_at": 1760000000.0, "course_name": course_name,
        "params": params or {}, "stats": stats or {},
    })
    _db().update_task(task_id, started_at=started_at, finished_at=finished_at,
                      error=error)
    return task_id


def _event(task_id, event, payload=None, message="", level="info", stage="exam"):
    return _db().add_event(task_id, "", event, message, level=level, stage=stage,
                           payload=payload or {}, ts=1760000001.0)


# ============================================================
# 设置：ui 分组
# ============================================================

def test_ui_settings_defaults():
    data = settings_module.normalize({})
    assert data["ui"]["dismissed_resume_tasks"] == []
    assert data["ui"]["completed_page_size"] == 30


def test_ui_settings_normalizes_dismissed_list():
    data = settings_module.normalize({
        "ui": {"dismissed_resume_tasks": ["a", "a", "", None, " b ", "a"],
               "completed_page_size": 9999},
    })
    assert data["ui"]["dismissed_resume_tasks"] == ["a", "b"]
    assert data["ui"]["completed_page_size"] == 100


def test_ui_settings_rejects_garbage_and_clamps():
    data = settings_module.normalize({"ui": {"dismissed_resume_tasks": "nope",
                                             "completed_page_size": 1}})
    assert data["ui"]["dismissed_resume_tasks"] == []
    assert data["ui"]["completed_page_size"] == 10


def test_ui_settings_caps_list_length():
    data = settings_module.normalize({
        "ui": {"dismissed_resume_tasks": [f"t{i}" for i in range(500)]}})
    assert len(data["ui"]["dismissed_resume_tasks"]) == settings_module.DISMISSED_TASKS_LIMIT


def test_dismissed_tasks_persist_through_api(app_client):
    """前端「不再提醒」通过既有 PATCH /api/settings 保存，无需新端点"""
    patched = app_client.patch("/api/settings", json={
        "ui": {"dismissed_resume_tasks": ["task-1", "task-2"]}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["ui"]["dismissed_resume_tasks"] == ["task-1", "task-2"]
    fetched = app_client.get("/api/settings").json()
    assert fetched["ui"]["dismissed_resume_tasks"] == ["task-1", "task-2"]


# ============================================================
# /api/completed
# ============================================================

def test_completed_lists_terminal_tasks_with_detail(app_client):
    account = _create_account(app_client)
    _create_task("done-1", account["id"], feature="exam", status="succeeded",
                 stats={"work": {"units": {
                     "exam:11021171": {"id": "exam:11021171", "name": "vue3第一章测试题",
                                       "kind": "exam", "status": "succeeded"}},
                     "sealed": True},
                     "success": 1, "total": 1, "questions": 0, "submit_ok": 0},
                 params={"exam": {"url": "https://mooc1.chaoxing.com/x?enc=1"}})
    _create_task("running-1", account["id"], feature="exam", status="running")

    payload = app_client.get("/api/completed").json()
    ids = [item["id"] for item in payload["items"]]
    assert ids == ["done-1"]
    assert payload["total"] == 1

    item = payload["items"][0]
    assert item["duration_seconds"] == 60.0
    assert item["answers_count"] == 0
    assert "answered" in item["answers_summary"]
    assert item["outcome"]["status"] == "succeeded"
    assert item["exam"]["exam_id"] == "11021171"
    assert item["exam"]["title"] == "vue3第一章测试题"
    assert item["exam"]["url"].endswith("enc=1")


def test_completed_filters_by_feature_and_account(app_client):
    account = _create_account(app_client)
    _create_task("done-exam", account["id"], feature="exam")
    _create_task("done-homework", account["id"], feature="independent_homework")

    only_exam = app_client.get("/api/completed?feature=exam").json()
    assert [item["id"] for item in only_exam["items"]] == ["done-exam"]

    both = app_client.get("/api/completed?feature=exam,independent_homework").json()
    assert {item["id"] for item in both["items"]} == {"done-exam", "done-homework"}

    missing = app_client.get("/api/completed?account_id=ghost").json()
    assert missing["items"] == [] and missing["total"] == 0


def test_completed_pagination_bounds(app_client):
    assert app_client.get("/api/completed?limit=0").status_code == 422
    assert app_client.get("/api/completed?limit=101").status_code == 422
    assert app_client.get("/api/completed?offset=-1").status_code == 422


def test_completed_includes_answer_items_and_summary(app_client):
    account = _create_account(app_client)
    _create_task("done-hw", account["id"], feature="independent_homework",
                 stats={"submit_ok": 1, "submit_fail": 0})
    _event("done-hw", "answer_result", {
        "media": "第一章作业", "index": 1, "total": 10, "question_type": "单选题",
        "question": "Vue.js 的作者来自中国哪个城市?", "options": ["A. 北京", "B. 上海"],
        "answer": "C", "source": "ai", "status": "answered"}, stage="work")

    item = app_client.get("/api/completed").json()["items"][0]
    assert item["answers_count"] == 1
    assert item["answers_summary"]["answered"] == 1
    assert item["answers_summary"]["ai"] == 1
    assert item["exam"] is None


def test_completed_reports_failed_reason(app_client):
    account = _create_account(app_client)
    _create_task("bad-1", account["id"], feature="exam", status="failed",
                 error="平台安全验证不通过")
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["outcome"]["status"] == "failed"
    assert "安全验证" in item["outcome"]["reason"]


def test_completed_explains_already_done_exam(app_client):
    """考试「已交卷」任务：明细为空，但 outcome.reason 必须说明原因"""
    account = _create_account(app_client)
    detail = ("平台显示该场考试已交卷（可能由上一次运行或你在浏览器里手动交卷完成）；"
              "考试结束后平台不再提供逐题回顾，因此这场考试没有可展示的逐题明细。")
    _create_task("done-early", account["id"], feature="exam", status="succeeded",
                 stats={"work": {"units": {
                     "exam:11021171": {"id": "exam:11021171", "name": "vue3第一章测试题",
                                       "kind": "exam", "status": "succeeded",
                                       "already_done": True, "detail": detail}},
                     "sealed": True}})
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["already_done"] is True
    assert "逐题回顾" in item["outcome"]["reason"]
    assert item["answers_count"] == 0


def test_completed_explains_legacy_exam_without_flag(app_client):
    """旧版本完成的考试任务没有 already_done 标记，仍要给出可读解释"""
    account = _create_account(app_client)
    _create_task("legacy-exam", account["id"], feature="exam", status="succeeded",
                 stats={"work": {"units": {
                     "exam:11021171": {"id": "exam:11021171", "name": "vue3第一章测试题",
                                       "kind": "exam", "status": "succeeded"}},
                     "sealed": True}})
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["already_done"] is False
    assert "逐题回顾" in item["outcome"]["reason"]


def test_completed_explains_succeeded_video_task(app_client):
    account = _create_account(app_client)
    _create_task("video-done", account["id"], feature="course_all", status="succeeded")
    item = app_client.get("/api/completed").json()["items"][0]
    assert "视频任务点" in item["outcome"]["reason"]


def test_completed_keeps_failure_error_as_reason(app_client):
    account = _create_account(app_client)
    _create_task("failed-video", account["id"], feature="course_all", status="failed",
                 error="网络请求连续失败")
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["outcome"]["reason"] == "网络请求连续失败"


def test_completed_avoids_full_event_scan_per_task(app_client, monkeypatch):
    """每条任务只查一次 answer_result，不能在循环里拉全量事件"""
    from app import main as main_module

    account = _create_account(app_client)
    for index in range(5):
        _create_task(f"bulk-{index}", account["id"], feature="exam")
    calls = []
    original = main_module._task_answers

    def counting(task_id):
        calls.append(task_id)
        return original(task_id)

    monkeypatch.setattr(main_module, "_task_answers", counting)
    app_client.get("/api/completed?limit=5")
    assert sorted(calls) == [f"bulk-{index}" for index in range(5)]


# ============================================================
# task_detail：answers_note
# ============================================================

def test_task_detail_answers_note_for_exam(app_client):
    account = _create_account(app_client)
    _create_task("exam-empty", account["id"], feature="exam", status="succeeded")
    detail = app_client.get("/api/tasks/exam-empty").json()
    assert detail["answers"] == []
    assert "逐题回顾" in detail["answers_note"]


def test_task_detail_answers_note_for_legacy_questions(app_client):
    """stats.questions>0 却没有事件：说明是旧版本完成的任务"""
    account = _create_account(app_client)
    _create_task("legacy-1", account["id"], feature="independent_homework",
                 status="succeeded", stats={"questions": 10})
    detail = app_client.get("/api/tasks/legacy-1").json()
    assert "版本之前" in detail["answers_note"]


def test_task_detail_answers_note_for_video_only_task(app_client):
    account = _create_account(app_client)
    _create_task("video-1", account["id"], feature="course_all", status="succeeded")
    detail = app_client.get("/api/tasks/video-1").json()
    assert "视频任务点" in detail["answers_note"]


def test_task_detail_answers_note_empty_when_answers_exist(app_client):
    account = _create_account(app_client)
    _create_task("has-answers", account["id"], feature="independent_homework")
    _event("has-answers", "answer_result", {
        "media": "作业", "index": 1, "total": 1, "question": "题干",
        "answer": "A", "source": "ai", "status": "answered"}, stage="work")
    detail = app_client.get("/api/tasks/has-answers").json()
    assert detail["answers"]
    assert detail["answers_note"] == ""


# ============================================================
# 事件叙事：平台已交卷要说明原因
# ============================================================

def test_presentation_explains_already_done_exam():
    from app import presentation

    item = presentation.describe("work_result", "该场考试此前已交卷", stage="exam", payload={
        "id": "exam:11021171", "name": "vue3第一章测试题", "kind": "exam",
        "status": "succeeded", "already_done": True,
        "detail": "考试结束后平台不再提供逐题回顾，因此这场考试没有可展示的逐题明细。"})
    assert item["title"] == "此前已完成"
    assert "vue3第一章测试题" in item["detail"]
    assert "逐题回顾" in item["detail"]


def test_presentation_keeps_normal_work_result_wording():
    from app import presentation

    item = presentation.describe("work_result", "作业已完成", stage="work", payload={
        "id": "work:1", "name": "第一章作业", "kind": "homework", "status": "succeeded"})
    assert item["title"] == "已确认完成"
    assert item["detail"] == "第一章作业"
