"""v2.4.0 T12.3：事件导出端点（json/txt + 时间范围）。"""
import json
import time


def _seed(db, task_id="export-task", n=5, base=None):
    db.create_task({"id": task_id, "account_id": "acc",
                    "feature": "course_all", "status": "running"})
    base = base if base is not None else time.time() - 1000
    ids = []
    for i in range(n):
        ids.append(db.add_event(task_id, "acc", "log", f"事件 {i}",
                                ts=base + i * 10))
    return ids, base


def test_events_export_json_format(app_client):
    from app import main as main_module

    _seed(main_module.db, n=5)
    resp = app_client.get("/api/events/export?task_id=export-task&format=json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["total"] == 5
    assert [item["message"] for item in data["items"]] == [
        f"事件 {i}" for i in range(5)]
    # JSON 导出携带 presentation/narrative（与 _event_view 口径一致）
    assert "presentation" in data["items"][0]
    assert "narrative" in data["items"][0]


def test_events_export_txt_format(app_client):
    from app import main as main_module

    _seed(main_module.db, n=3)
    resp = app_client.get("/api/events/export?task_id=export-task&format=txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert body.count("\n") == 3
    # 行格式与 /api/tasks/{id}/logs 一致：时间 | 级别 | 阶段 | 消息
    assert "| info |" in body
    assert "事件 0" in body and "事件 2" in body


def test_events_export_time_window(app_client):
    from app import main as main_module

    base = time.time() - 1000
    _seed(main_module.db, n=5, base=base)
    # 窗口只覆盖事件 1..3（ts = base+10..base+30）
    resp = app_client.get(
        f"/api/events/export?task_id=export-task&format=json"
        f"&since={base + 5}&until={base + 35}")
    data = resp.json()
    assert [item["message"] for item in data["items"]] == ["事件 1", "事件 2", "事件 3"]


def test_events_export_cross_task_and_invalid_format(app_client):
    from app import main as main_module

    _seed(main_module.db, task_id="export-a", n=2)
    _seed(main_module.db, task_id="export-b", n=2)
    # task_id 为空 → 跨任务导出（含两个任务的事件）
    data = app_client.get("/api/events/export?format=json").json()
    messages = [item["message"] for item in data["items"]]
    assert "事件 0" in messages and data["total"] >= 4

    assert app_client.get(
        "/api/events/export?format=csv").status_code == 422
    assert app_client.get(
        "/api/events/export?task_id=no-such&format=json").json()["total"] == 0
