"""v2.2.3 独立复核（task-12 / backend-api）：只读审计，不修改产品代码。

覆盖 Lead 声称已修好的三件事：
1. 考试「已完成」必须能解释清楚（/api/completed 的 outcome.reason、task_detail 的 answers_note）；
2. 「已完成」专页数据源 GET /api/completed 的契约（过滤、分页、汇总、考试字段、原因优先级）；
3. settings.ui（「不再提醒」与每页条数）的归一与持久化。

另含反例尝试与真实数据目录的只读复核。真实数据用 sqlite `mode=ro` 打开，
不会写库、不会触发同步，也不会调用 start/submit。
"""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import settings as settings_module  # noqa: E402


# ============================================================
# 通用辅助
# ============================================================

def _db():
    from app.main import db
    return db


def _create_account(app_client, username="13800007771", label="v2.2.3 审计"):
    response = app_client.post("/api/accounts", json={
        "username": username, "password": "pwd123", "label": label,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(task_id, account_id, feature="exam", status="succeeded",
                 started_at=1760000000.0, finished_at=1760000060.0,
                 stats=None, params=None, error=None, course_name="审计课程"):
    _db().create_task({
        "id": task_id, "account_id": account_id, "feature": feature,
        "status": status, "created_at": 1760000000.0, "course_name": course_name,
        "params": params or {}, "stats": stats or {},
    })
    fields = {"error": error}
    if started_at is not None:
        fields["started_at"] = started_at
    if finished_at is not None:
        fields["finished_at"] = finished_at
    _db().update_task(task_id, **fields)
    return task_id


def _event(task_id, event, payload=None, message="", level="info", stage="exam"):
    return _db().add_event(task_id, "", event, message, level=level, stage=stage,
                           payload=payload or {}, ts=1760000001.0)


def _exam_unit(unit_id="exam:11021171", name="vue3第一章测试题", **extra):
    unit = {"id": unit_id, "name": name, "kind": "exam", "status": "succeeded"}
    unit.update(extra)
    return {"work": {"units": {unit_id: unit}, "sealed": True}, "success": 1, "total": 1}


# ============================================================
# /api/completed：只返回终态、结构完整
# ============================================================

def test_completed_contract_terminal_only_and_shape(app_client):
    account = _create_account(app_client)
    for task_id, status, feature in [
        ("c-succeeded", "succeeded", "exam"),
        ("c-failed", "failed", "independent_homework"),
        ("c-stopped", "stopped", "course_all"),
        ("c-interrupted", "interrupted", "independent_homework"),
    ]:
        _create_task(task_id, account["id"], feature=feature, status=status)
    _create_task("c-running", account["id"], feature="exam", status="running")
    _create_task("c-pending", account["id"], feature="exam", status="pending")

    payload = app_client.get("/api/completed").json()
    ids = [item["id"] for item in payload["items"]]
    assert set(ids) == {"c-succeeded", "c-failed", "c-stopped", "c-interrupted"}
    assert payload["total"] == 4

    item = payload["items"][0]
    # 契约字段逐个存在（不依赖任何人的口头结论）
    for key in ("id", "feature", "status", "stats", "progress", "created_at",
                "answers_summary", "answers_count", "duration_seconds",
                "outcome", "exam"):
        assert key in item, key
    assert set(item["answers_summary"]) == {
        "answered", "skipped", "total", "ai", "cache", "random", "failed",
        "submit_ok", "submit_fail"}
    assert isinstance(item["answers_count"], int)
    assert set(item["outcome"]) == {"status", "reason"}
    assert item["outcome"]["status"] == item["status"]


def test_completed_feature_filter_and_account_filter(app_client):
    account = _create_account(app_client)
    _create_task("f-exam", account["id"], feature="exam")
    _create_task("f-hw", account["id"], feature="independent_homework")
    _create_task("f-video", account["id"], feature="course_all")

    only_exam = app_client.get("/api/completed?feature=exam").json()
    assert [item["id"] for item in only_exam["items"]] == ["f-exam"]
    assert only_exam["total"] == 1

    merged = app_client.get("/api/completed?feature=exam,independent_homework").json()
    assert {item["id"] for item in merged["items"]} == {"f-exam", "f-hw"}

    ghost = app_client.get("/api/completed?account_id=ghost").json()
    assert ghost == {"total": 0, "items": []}

    unknown = app_client.get("/api/completed?feature=not-a-feature").json()
    assert unknown == {"total": 0, "items": []}


def test_completed_pagination_boundaries(app_client):
    account = _create_account(app_client)
    for index in range(3):
        _create_task(f"p-{index}", account["id"])
    assert app_client.get("/api/completed?limit=0").status_code == 422
    assert app_client.get("/api/completed?limit=101").status_code == 422
    assert app_client.get("/api/completed?limit=-1").status_code == 422
    assert app_client.get("/api/completed?offset=-1").status_code == 422

    first = app_client.get("/api/completed?limit=2&offset=0").json()
    assert len(first["items"]) == 2 and first["total"] == 3
    second = app_client.get("/api/completed?limit=2&offset=2").json()
    assert len(second["items"]) == 1 and second["total"] == 3
    assert {item["id"] for item in first["items"]} & {
        item["id"] for item in second["items"]} == set()


# ============================================================
# /api/completed：outcome.reason 优先级 error > already_done > 逐题解释
# ============================================================

def test_completed_reason_priority_error_wins(app_client):
    """error 优先：即使统计里带 already_done，失败原因也必须原样给出"""
    account = _create_account(app_client)
    _create_task("r-error", account["id"], feature="exam", status="failed",
                 error="平台安全验证不通过",
                 stats=_exam_unit(already_done=True, detail="平台显示该场考试已交卷，考后无逐题回顾。"))
    reason = app_client.get("/api/completed").json()["items"][0]["outcome"]["reason"]
    assert reason == "平台安全验证不通过"


def test_completed_reason_priority_already_done_detail(app_client):
    """无 error 时取 already_done 分支写入的 detail"""
    account = _create_account(app_client)
    detail = ("平台显示该场考试已交卷（可能由上一次运行或你在浏览器里手动交卷完成）；"
              "考试结束后平台不再提供逐题回顾，因此这场考试没有可展示的逐题明细。")
    _create_task("r-already", account["id"], feature="exam", status="succeeded",
                 stats=_exam_unit(already_done=True, detail=detail))
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["already_done"] is True
    assert item["outcome"]["reason"] == detail
    assert "逐题回顾" in item["outcome"]["reason"]


def test_completed_reason_falls_back_for_legacy_exam(app_client):
    """旧版本完成的考试没有 already_done/detail，也必须能解释「为什么没有明细」"""
    account = _create_account(app_client)
    _create_task("r-legacy", account["id"], feature="exam", status="succeeded",
                 stats=_exam_unit())
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["already_done"] is False
    assert item["answers_count"] == 0
    assert item["outcome"]["reason"]
    assert "逐题回顾" in item["outcome"]["reason"]


def test_completed_reason_for_video_and_failed_other_features(app_client):
    account = _create_account(app_client)
    _create_task("r-video", account["id"], feature="course_all", status="succeeded")
    _create_task("r-hw-fail", account["id"], feature="independent_homework",
                 status="failed", error="网络请求连续失败")
    items = {item["id"]: item for item in app_client.get("/api/completed").json()["items"]}
    assert "视频任务点" in items["r-video"]["outcome"]["reason"]
    assert items["r-hw-fail"]["outcome"]["reason"] == "网络请求连续失败"


# ============================================================
# /api/completed：逐题汇总与去重
# ============================================================

def test_completed_answers_summary_dedupes_and_counts(app_client):
    """同一 (media,index) 只算最新一条；total 取同一份作业的最大题数"""
    account = _create_account(app_client)
    _create_task("s-hw", account["id"], feature="independent_homework", status="succeeded",
                 stats={"submit_ok": 7, "submit_fail": 2})
    _event("s-hw", "answer_result", {
        "media": "第一章", "index": 1, "total": 10, "question_type": "单选题",
        "question": "题干一", "answer": "A", "source": "ai", "status": "answered"},
        stage="work")
    _event("s-hw", "answer_result", {
        "media": "第一章", "index": 2, "total": 10, "question_type": "单选题",
        "question": "题干二", "answer": "", "source": "failed", "status": "skipped"},
        stage="work")
    _event("s-hw", "answer_result", {
        "media": "第二章", "index": 1, "total": 5, "question_type": "判断题",
        "question": "题干三", "answer": "对", "source": "cache", "status": "answered"},
        stage="work")
    # 同一题后到的结果覆盖先前一条
    _event("s-hw", "answer_result", {
        "media": "第一章", "index": 1, "total": 10, "question_type": "单选题",
        "question": "题干一", "answer": "", "source": "random", "status": "skipped"},
        stage="work")

    item = app_client.get("/api/completed").json()["items"][0]
    assert item["answers_count"] == 3
    assert item["answers_summary"] == {
        "answered": 1, "skipped": 2, "total": 15,
        "ai": 0, "cache": 1, "random": 1, "failed": 1,
        "submit_ok": 7, "submit_fail": 2,
    }


def test_completed_answer_items_match_task_detail(app_client):
    """两条接口读的是同一份事件，去重后条数必须一致"""
    account = _create_account(app_client)
    _create_task("s-same", account["id"], feature="independent_homework", status="succeeded")
    for index in (1, 2, 2, 3):
        _event("s-same", "answer_result", {
            "media": "作业A", "index": index, "total": 3, "question": f"题{index}",
            "answer": "A", "source": "ai", "status": "answered"}, stage="work")
    detail = app_client.get("/api/tasks/s-same").json()
    assert len(detail["answers"]) == 3
    assert detail["answers_summary"]["answered"] == 3
    assert app_client.get("/api/completed").json()["items"][0]["answers_count"] == 3


# ============================================================
# /api/completed：duration 与 exam 字段
# ============================================================

def test_completed_duration_seconds(app_client):
    account = _create_account(app_client)
    _create_task("d-ok", account["id"], started_at=1000.0, finished_at=1060.5)
    _create_task("d-missing", account["id"], started_at=None, finished_at=None)
    items = {item["id"]: item for item in app_client.get("/api/completed").json()["items"]}
    assert items["d-ok"]["duration_seconds"] == 60.5
    assert items["d-missing"]["duration_seconds"] is None


def test_completed_exam_field_from_params_and_units(app_client):
    account = _create_account(app_client)
    _create_task("x-exam", account["id"], feature="exam", status="succeeded",
                 params={"exam": {"url": "https://mooc1.chaoxing.com/x?enc=abc"}},
                 stats=_exam_unit())
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"] == {
        "title": "vue3第一章测试题", "exam_id": "11021171",
        "url": "https://mooc1.chaoxing.com/x?enc=abc",
        "already_done": False, "detail": "",
    }
    # 非考试任务没有 exam 字段值
    _create_task("x-hw", account["id"], feature="independent_homework", status="succeeded")
    again = {row["id"]: row for row in app_client.get("/api/completed").json()["items"]}
    assert again["x-hw"]["exam"] is None


# ============================================================
# settings.ui
# ============================================================

def test_ui_settings_defaults_and_normalization():
    data = settings_module.normalize({})
    assert data["ui"] == {"dismissed_resume_tasks": [], "completed_page_size": 30}

    data = settings_module.normalize({"ui": {
        "dismissed_resume_tasks": ["a", "a", "", None, " b ", "a", 3],
        "completed_page_size": 9999,
    }})
    assert data["ui"]["dismissed_resume_tasks"] == ["a", "b", "3"]
    assert data["ui"]["completed_page_size"] == 100

    data = settings_module.normalize({"ui": {
        "dismissed_resume_tasks": "not-a-list", "completed_page_size": 1}})
    assert data["ui"]["dismissed_resume_tasks"] == []
    assert data["ui"]["completed_page_size"] == 10

    data = settings_module.normalize({"ui": {
        "dismissed_resume_tasks": [f"t{i}" for i in range(500)]}})
    assert len(data["ui"]["dismissed_resume_tasks"]) == 100
    assert data["ui"]["dismissed_resume_tasks"][:2] == ["t0", "t1"]


def test_ui_settings_patch_persists_and_clamps_through_api(app_client):
    patched = app_client.patch("/api/settings", json={
        "ui": {"dismissed_resume_tasks": ["task-1", "task-1", "task-2"],
               "completed_page_size": 5}})
    assert patched.status_code == 200, patched.text
    body = patched.json()["ui"]
    assert body["dismissed_resume_tasks"] == ["task-1", "task-2"]
    assert body["completed_page_size"] == 10  # 5 被 clamp 到下限

    fetched = app_client.get("/api/settings").json()["ui"]
    assert fetched == body

    patched = app_client.patch("/api/settings", json={
        "ui": {"dismissed_resume_tasks": [f"id-{i}" for i in range(150)],
               "completed_page_size": 500}})
    body = patched.json()["ui"]
    assert len(body["dismissed_resume_tasks"]) == 100
    assert body["completed_page_size"] == 100
    assert app_client.get("/api/settings").json()["ui"] == body


def test_completed_has_no_extra_mutation_endpoints(app_client):
    """确认没有为「已完成」新增未授权写端点：只读 GET，其它方法 405"""
    for method in ("post", "put", "patch", "delete"):
        response = getattr(app_client, method)("/api/completed")
        assert response.status_code == 405, (method, response.status_code, response.text)
    assert app_client.get("/api/completed/anything").status_code == 404


# ============================================================
# task_detail：answers_note
# ============================================================

def test_answers_note_cases(app_client):
    account = _create_account(app_client)
    _create_task("n-exam", account["id"], feature="exam", status="succeeded")
    _create_task("n-legacy", account["id"], feature="independent_homework",
                 status="succeeded", stats={"questions": 10})
    _create_task("n-video", account["id"], feature="course_all", status="succeeded")
    _create_task("n-ok", account["id"], feature="independent_homework", status="succeeded")
    _event("n-ok", "answer_result", {
        "media": "作业", "index": 1, "total": 1, "question": "题干",
        "answer": "A", "source": "ai", "status": "answered"}, stage="work")

    assert "逐题回顾" in app_client.get("/api/tasks/n-exam").json()["answers_note"]
    assert "版本之前" in app_client.get("/api/tasks/n-legacy").json()["answers_note"]
    assert "视频任务点" in app_client.get("/api/tasks/n-video").json()["answers_note"]
    assert app_client.get("/api/tasks/n-ok").json()["answers_note"] == ""


def test_presentation_explains_already_done():
    from app import presentation
    item = presentation.describe("work_result", "该场考试此前已交卷", stage="exam", payload={
        "id": "exam:11021171", "name": "vue3第一章测试题", "kind": "exam",
        "status": "succeeded", "already_done": True,
        "detail": "考试结束后平台不再提供逐题回顾，因此这场考试没有可展示的逐题明细。",
    })
    assert item["title"] == "此前已完成"
    assert "vue3第一章测试题" in item["detail"]
    assert "逐题回顾" in item["detail"]
    assert item["visible"] is True


# ============================================================
# 反例尝试：能不能骗过它
# ============================================================

def test_counterexample_forged_already_done_without_detail(app_client):
    """伪造 already_done=True 但不给 detail：不能出现空 reason"""
    account = _create_account(app_client)
    _create_task("fake-already", account["id"], feature="exam", status="succeeded",
                 stats=_exam_unit(already_done=True, detail=""))
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["detail"] == ""
    assert item["exam"]["already_done"] is True
    assert item["outcome"]["reason"]  # 不能为空
    assert "逐题回顾" in item["outcome"]["reason"]


def test_counterexample_answers_empty_but_questions_positive(app_client):
    """统计说有 10 题但一条 answer_result 都没有：必须解释是版本原因，不能假装 0 题"""
    account = _create_account(app_client)
    _create_task("fake-count", account["id"], feature="independent_homework",
                 status="succeeded", stats={"questions": 10})
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["answers_count"] == 0
    assert "版本之前" in item["outcome"]["reason"]
    detail = app_client.get("/api/tasks/fake-count").json()
    assert "版本之前" in detail["answers_note"]


def test_counterexample_status_query_cannot_hide_failures(app_client):
    """/?status=failed 不是契约参数，不能用来只挑失败任务或隐藏失败任务"""
    account = _create_account(app_client)
    _create_task("hide-ok", account["id"], status="succeeded")
    _create_task("hide-fail", account["id"], status="failed", error="失败了")
    payload = app_client.get("/api/completed?status=failed").json()
    assert {item["id"] for item in payload["items"]} == {"hide-ok", "hide-fail"}


def test_counterexample_exam_shape_from_stats_only(app_client):
    """只伪造 stats.work.units 的 exam 单元（无 params.exam.url）：接口仍给出 exam，
    这是契约（从 stats/params 取），但 url 为空——前端需要容错，不能视为有地址"""
    account = _create_account(app_client)
    unit = {"id": "exam:999", "name": "伪造考试", "kind": "exam", "status": "succeeded"}
    _create_task("fake-unit", account["id"], feature="independent_homework",
                 status="succeeded",
                 stats={"work": {"units": {"exam:999": unit}, "sealed": True}})
    item = app_client.get("/api/completed").json()["items"][0]
    assert item["exam"]["url"] == ""
    assert item["exam"]["title"] == "伪造考试"
    assert item["exam"]["exam_id"] == "999"


def test_boundary_interrupted_and_failed_without_cause_keep_reason_empty(app_client):
    """设计边界：interrupted/failed 无 error、无 exam、无逐题明细解释时不编造 reason（空串）。

    Lead 已说明 seed 数据里这两条空 reason 属预期；这里独立锁住该边界，
    防止以后为了「好看」而伪造解释。
    """
    account = _create_account(app_client)
    _create_task("b-interrupted", account["id"], feature="independent_homework",
                 status="interrupted")
    _create_task("b-failed", account["id"], feature="course_all", status="failed",
                 error="")
    _create_task("b-failed-err", account["id"], feature="independent_homework",
                 status="failed", error="网络中断，任务失败")

    items = {item["id"]: item
             for item in app_client.get("/api/completed").json()["items"]}
    assert items["b-interrupted"]["outcome"]["reason"] == ""
    assert items["b-failed"]["outcome"]["reason"] == ""
    assert items["b-failed-err"]["outcome"]["reason"] == "网络中断，任务失败"
    # 没有任何来源时也不应伪造逐题解释
    assert "逐题回顾" not in items["b-interrupted"]["outcome"]["reason"]
    assert "版本之前" not in items["b-failed"]["outcome"]["reason"]


# ============================================================
# 真实数据目录只读复核：历史三条 succeeded 考试任务
# ============================================================

_REAL_DATA_DIR = os.environ.get(
    "AUTOCXWEBUI_REAL_DATA_DIR", r"C:\Users\Zora\AppData\Roaming\AutoCxWebUI")
_REAL_DB = os.path.join(_REAL_DATA_DIR, "webui.db")
# Lead 给出的三条任务 id 前缀（数据库里是 32 位 uuid hex）
_AUDIT_PREFIXES = ("606b4d0a2918", "547ca1d40a88", "0785abb1eb3d")


class _ReadOnlyDB:
    """只读事件查询：实现 Database.list_events 的同一语义，用于真实库审计"""

    def __init__(self, path):
        uri = "file:" + path.replace("\\", "/") + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        self._conn.close()

    def list_events(self, task_id, after_id=0, limit=200, level=None, event=None,
                    latest=False, business=False):
        clauses = ["task_id = ?", "id > ?"]
        params = [task_id, int(after_id or 0)]
        if level and level != "all":
            if level == "problem":
                clauses.append("level IN ('warning', 'error')")
            else:
                clauses.append("level = ?")
                params.append(level)
        if event and event != "all":
            clauses.append("event = ?")
            params.append(event)
        if business:
            clauses.append(
                "(event NOT IN ('log', 'task_progress', 'work_progress', "
                "'media_progress', 'worker_exit') OR (event = 'log' "
                "AND level IN ('warning', 'error')))")
        params.append(int(limit))
        order = "DESC" if latest else "ASC"
        rows = [dict(row) for row in self._conn.execute(
            f"SELECT * FROM task_events WHERE {' AND '.join(clauses)} "
            f"ORDER BY id {order} LIMIT ?", tuple(params)).fetchall()]
        return list(reversed(rows)) if latest else rows


def _find_real_rows(prefixes=_AUDIT_PREFIXES):
    """按 id 前缀找到 Lead 报的三条历史考试任务；只读连接"""
    conn = sqlite3.connect(
        "file:" + _REAL_DB.replace("\\", "/") + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = []
    try:
        for prefix in prefixes:
            found = [dict(row) for row in conn.execute(
                "SELECT * FROM tasks WHERE id LIKE ? ORDER BY created_at",
                (prefix + "%",)).fetchall()]
            assert len(found) <= 1, f"前缀 {prefix} 匹配到 {len(found)} 条任务"
            rows.extend(found)
    finally:
        conn.close()
    return rows


@pytest.mark.skipif(not os.path.exists(_REAL_DB),
                    reason=f"真实数据目录不存在: {_REAL_DB}")
def test_real_history_exam_tasks_explain_outcome(monkeypatch):
    """历史三条 succeeded 考试任务：outcome.reason 非空且提到「逐题回顾」"""
    import app.main as main_module

    rows = _find_real_rows()
    assert len(rows) == 3, (
        "没有找到 Lead 报的三条历史任务，实际找到: "
        + json.dumps([row["id"] for row in rows], ensure_ascii=False))

    fake = _ReadOnlyDB(_REAL_DB)
    monkeypatch.setattr(main_module, "db", fake)
    try:
        for row in rows:
            assert row["feature"] == "exam", row["id"]
            assert row["status"] == "succeeded", row["id"]
            view = main_module._completed_view(row)
            reason = view["outcome"]["reason"]
            print("\n[真实数据] task={} status={} answers_count={} exam={} reason={}".format(
                row["id"], row["status"], view["answers_count"],
                json.dumps(view["exam"], ensure_ascii=False), reason))
            assert reason, "task {} 的 outcome.reason 为空".format(row["id"])
            assert "逐题回顾" in reason, (
                "task {} 的 reason 没有提到逐题回顾: {}".format(row["id"], reason))
            assert view["answers_count"] == 0
    finally:
        fake.close()


def _print_real_evidence():
    """命令行只读审计：python tests/test_v223_audit.py（打印，不写库）"""
    if not os.path.exists(_REAL_DB):
        print("真实数据库不存在: " + _REAL_DB)
        return 1
    import app.main as main_module
    rows = _find_real_rows()
    print("找到历史考试任务 {} 条:".format(len(rows)))
    fake = _ReadOnlyDB(_REAL_DB)
    original_db = main_module.db
    main_module.db = fake
    try:
        for row in rows:
            view = main_module._completed_view(row)
            print("- task={} feature={} status={}".format(
                row["id"], row["feature"], row["status"]))
            print("  answers_count={} exam={}".format(
                view["answers_count"], json.dumps(view["exam"], ensure_ascii=False)))
            print("  outcome={}".format(json.dumps(view["outcome"], ensure_ascii=False)))
            print("  duration_seconds={}".format(view["duration_seconds"]))
    finally:
        main_module.db = original_db
        fake.close()
    return 0


if __name__ == "__main__":
    sys.exit(_print_real_evidence())
