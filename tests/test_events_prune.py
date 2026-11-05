"""v2.4.0 T10.9：事件保留期清理 + SSE 游标重连 + worker_crash 可见化。"""
import json
import time

import pytest

from app.database import Database


@pytest.fixture()
def db(sandbox):
    from app.database import Database as DB

    instance = DB()
    yield instance
    instance.close()


def _seed_task(db, task_id="prune-task"):
    db.create_task({"id": task_id, "account_id": "acc", "feature": "course_all",
                    "status": "succeeded"})


# ---------------- prune_events ----------------

def test_prune_events_removes_only_old_rows(db):
    _seed_task(db)
    old_ts = time.time() - 30 * 86400
    db.add_event("prune-task", "acc", "log", "一个月前的事件", ts=old_ts)
    db.add_event("prune-task", "acc", "log", "刚刚的事件")
    removed = db.prune_events(7)
    assert removed == 1
    remaining = [row["message"] for row in db.list_events("prune-task")]
    assert remaining == ["刚刚的事件"]


def test_prune_events_flushes_buffer_first(db):
    """缓冲中的旧时间戳行也必须参与清理（add_event 支持显式 ts）。"""
    _seed_task(db)
    db.add_event("prune-task", "acc", "log", "缓冲中的旧事件",
                 ts=time.time() - 100 * 86400)
    assert db._event_buffer, "事件应仍在缓冲中"
    removed = db.prune_events(7)
    assert removed == 1
    assert db.list_events("prune-task") == []


def test_prune_events_ignores_invalid_days(db):
    _seed_task(db)
    db.add_event("prune-task", "acc", "log", "正常事件")
    assert db.prune_events(0) == 0
    assert db.prune_events(-3) == 0
    assert db.prune_events(None) == 0
    assert db.prune_events("abc") == 0
    assert len(db.list_events("prune-task")) == 1


def test_prune_events_zero_window_keeps_everything(db):
    _seed_task(db)
    db.add_event("prune-task", "acc", "log", "旧事件", ts=time.time() - 10)
    assert db.prune_events(1) == 0
    assert len(db.list_events("prune-task")) == 1


# ---------------- list_events 扩展（T10.8） ----------------

def test_list_events_filters_by_stage_q_and_window(db):
    _seed_task(db)
    now = time.time()
    db.add_event("prune-task", "acc", "log", "视频播放卡顿", stage="video", ts=now - 100)
    db.add_event("prune-task", "acc", "log", "登录失败", stage="boot", ts=now - 50)
    db.add_event("prune-task", "acc", "log", "下载完成", stage="download", ts=now)

    assert [r["stage"] for r in db.list_events("prune-task", stage="video")] == ["video"]
    assert [r["message"] for r in db.list_events("prune-task", q="下载")] == ["下载完成"]
    rows = db.list_events("prune-task", since=now - 60)
    assert [r["message"] for r in rows] == ["登录失败", "下载完成"]
    rows = db.list_events("prune-task", until=now - 60)
    assert [r["message"] for r in rows] == ["视频播放卡顿"]


def test_list_events_combined_filters(db):
    _seed_task(db)
    now = time.time()
    db.add_event("prune-task", "acc", "log", "视频超时重试", stage="video", ts=now - 30)
    db.add_event("prune-task", "acc", "log", "视频正常", stage="video", ts=now - 10)
    rows = db.list_events("prune-task", stage="video", q="超时", since=now - 60)
    assert [r["message"] for r in rows] == ["视频超时重试"]


# ---------------- events 端点游标分页 ----------------

def test_task_events_endpoint_cursor_and_filters(app_client):
    from app import main as main_module

    db = main_module.db
    db.create_task({"id": "cursor-task", "account_id": "acc",
                    "feature": "course_all", "status": "running"})
    for i in range(5):
        db.add_event("cursor-task", "acc", "log", f"事件 {i}", stage="video")

    data = app_client.get("/api/tasks/cursor-task/events?limit=2").json()
    assert len(data["items"]) == 2
    assert data["next_after_id"] == data["items"][-1]["id"]

    page2 = app_client.get(
        f"/api/tasks/cursor-task/events?limit=2&after_id={data['next_after_id']}"
    ).json()
    assert page2["items"][0]["message"] == "事件 2"

    filtered = app_client.get(
        "/api/tasks/cursor-task/events?q=事件 3"
    ).json()
    assert [item["message"] for item in filtered["items"]] == ["事件 3"]

    by_stage = app_client.get(
        "/api/tasks/cursor-task/events?stage=video&limit=10"
    ).json()
    assert len(by_stage["items"]) == 5
    # 结果不满一页时游标归零，前端停止翻页
    assert by_stage["next_after_id"] == 0

    missing = app_client.get("/api/tasks/no-such/events")
    assert missing.status_code == 404


# ---------------- overview level=problem ----------------

def test_overview_problem_level_returns_only_warnings(app_client):
    from app import main as main_module

    db = main_module.db
    db.create_task({"id": "problem-task", "account_id": "acc",
                    "feature": "course_all", "status": "running"})
    db.add_event("problem-task", "acc", "log", "普通日志", level="info")
    db.add_event("problem-task", "acc", "log", "触发反爬虫限制", level="warning")

    default = app_client.get("/api/overview").json()
    assert any(item["message"] == "普通日志" for item in default["recent_events"])
    problems = app_client.get("/api/overview?level=problem").json()
    messages = [item["message"] for item in problems["recent_events"]]
    assert messages == ["触发反爬虫限制"]


# ---------------- worker_crash / worker_exit ----------------

def test_worker_crash_recorded_on_monitor_failure(sandbox, monkeypatch):
    """_monitor 读循环抛异常 → 落 worker_crash 事件（level=error）。"""
    from app import events, main as main_module
    from app.database import Database
    from app.task_manager import TaskManager

    db = Database()
    hub = events.EventHub()
    manager = TaskManager(db, hub)
    main_module.db = db
    main_module.hub = hub
    try:
        db.create_task({"id": "crash-task", "account_id": "acc",
                        "feature": "course_all", "status": "running"})

        class FakeStream:
            def readline(self):
                raise OSError("pipe closed")

            def close(self):
                pass

        class FakeProcess:
            stdout = FakeStream()

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        manager._monitor("crash-task", FakeProcess())
        rows = db.list_events("crash-task")
        crash = [r for r in rows if r["event"] == "worker_crash"]
        assert len(crash) == 1
        assert crash[0]["level"] == "error"
        assert "监控线程" in crash[0]["message"]
    finally:
        db.close()


def test_monitor_records_worker_exit_with_payload(sandbox):
    from app import events
    from app.database import Database
    from app.task_manager import TaskManager

    db = Database()
    hub = events.EventHub()
    manager = TaskManager(db, hub)
    try:
        db.create_task({"id": "exit-task", "account_id": "acc",
                        "feature": "course_all", "status": "running"})

        class FakeStream:
            def readline(self):
                return b""

            def close(self):
                pass

        class FakeProcess:
            stdout = FakeStream()

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        manager._monitor("exit-task", FakeProcess())
        rows = db.list_events("exit-task")
        exits = [r for r in rows if r["event"] == "worker_exit"]
        assert len(exits) == 1
        assert json.loads(exits[0]["payload_json"])["exit_code"] == 0
        assert exits[0]["level"] == "info"
        # 任务状态同步收敛为 succeeded
        assert db.get_task("exit-task")["status"] == "succeeded"
    finally:
        db.close()


# ---------------- sync 事件落库（T10.4） ----------------

def test_sync_publish_persists_with_real_id(sandbox):
    from app import events
    from app.database import Database
    from app import sync_service

    db = Database()
    hub = events.EventHub()
    try:
        sync_service._publish(db, hub, "acc-1", "log", "同步进行中", level="info")
        row = db.list_events("0")
        assert len(row) == 1
        assert row[0]["task_id"] == "0"
        assert row[0]["stage"] == "sync"
        assert row[0]["id"] > 0
        # hub 收到的记录带真实 id（SSE 据此写 id: 行）
        record = hub.replay_since(0, limit=10)[0]
        assert record["id"] == row[0]["id"]
    finally:
        db.close()


def test_sync_finalize_failure_no_duplicate_row(sandbox):
    """sync_failed 落库走 _publish，不再重复写第二行。"""
    from app import events
    from app.database import Database
    from app import sync_service

    db = Database()
    hub = events.EventHub()
    try:
        sync_service._finalize(db, hub, "acc-1", None, "登录失败", 1)
        rows = db.list_events("0", event="sync_failed")
        assert len(rows) == 1
        assert rows[0]["level"] == "error"
    finally:
        db.close()


# ---------------- SSE 增量重连（T10.3） ----------------

def test_sse_stream_resume_from_last_event_id(app_client):
    """游标重连语义：真流式会因心跳循环永不 EOF 而挂死 TestClient，
    这里拆成三段等价断言——①游标前的历史不回放；②落库事件带真实 id
    （SSE据 _sse() 写 id: 行，EventSource 重连自动携带 Last-Event-ID）；
    ③非法游标被 400 拒绝。"""
    from app import main as main_module

    db = main_module.db
    db.create_task({"id": "sse-task", "account_id": "acc",
                    "feature": "course_all", "status": "running"})
    ids = [db.add_event("sse-task", "acc", "log", f"历史 {i}") for i in range(3)]
    assert ids == [1, 2, 3]

    # ① 游标=2：events_after 只应给出 id>2 的行（generator 的第一段回放源）
    backlog = db.events_after(2, limit=500)
    assert [row["id"] for row in backlog] == [3]

    # ② _sse() 为持久事件写 id: 行（前端据 event.lastEventId 维护 lastEventId）
    frame = main_module._sse(main_module._event_view(db.list_events("sse-task")[0]))
    assert frame.startswith("id: 1\n")
    # 内存即时事件（id=0）不得写 id: 行——防止覆盖浏览器恢复游标
    live = main_module._sse({"id": 0, "event": "log", "message": "即时"})
    assert not live.startswith("id:")

    # ③ 负数游标拒绝（防游标回退重放旧事件）
    assert app_client.get(
        "/api/events/stream", headers={"Last-Event-ID": "-1"}
    ).status_code == 400


# ---------------- 脱敏（T10.7） ----------------

def test_redact_bare_phone_and_account_id():
    from app.log_redaction import redact

    assert redact("正在登录账号 13812345678") == "正在登录账号 [已隐藏]"
    assert redact("账号：2021012345 已提交") == "账号 [已隐藏] 已提交"
    assert redact("学号: 20210123 已同步") == "学号 [已隐藏] 已同步"
    # 普通数字不受影响
    assert redact("共 3 门课程，耗时 120 秒") == "共 3 门课程，耗时 120 秒"
    # key=value 形式仍走原规则
    assert redact("username=13812345678") == "username=[已隐藏]"
