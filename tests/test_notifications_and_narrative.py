"""
通知中心与叙事流测试

覆盖用户反馈的两个核心问题：
1. 错误提醒过一会儿就消失 —— 现在必须持久化、不自动消失
2. 前端展示命令行 —— 现在必须转成"做什么/进度/成功失败"
另外覆盖"仅本机运行"的配置约束。
"""

import json
import time

import pytest

from app import narrative, settings
from app.database import Database
from app.notifications import NotificationCenter


@pytest.fixture()
def center(sandbox):
    db = Database()
    yield NotificationCenter(db)
    db.close()


# ============================================================
# 通知中心：持久化、不自动消失
# ============================================================

def test_error_becomes_persistent_notification(center):
    center.record(event="task_failed", level="error", message="登录失败: 密码错误",
                  task_id="t1", account_id="a1", account_label="账号 01",
                  course_name="高等数学")
    data = center.list()
    assert data["unread"] == 1
    item = data["items"][0]
    assert item["level"] == "error"
    assert item["title"] == "学习通登录失败"
    assert "账号 01" == json.loads(item["context_json"])["account_label"]


def test_notifications_survive_new_center_instance(sandbox):
    """重启后通知仍在（落库而非内存）"""
    db1 = Database()
    NotificationCenter(db1).record(event="task_failed", level="error", message="任务异常: 网络超时",
                                   task_id="t1", account_label="账号 02")
    db1.close()

    db2 = Database()
    data = NotificationCenter(db2).list()
    db2.close()
    assert data["unread"] == 1
    assert data["items"][0]["title"] == "任务执行失败"


def test_repeated_problem_accumulates_count(center):
    """反爬反复触发不应刷屏，累计次数即可"""
    for _ in range(3):
        center.record(event="log", level="warning",
                      message="任务点'1.3 习题课'触发反爬虫: 状态码202",
                      task_id="t1", account_id="a1", course_name="高等数学")
    data = center.list()
    assert len(data["items"]) == 1
    assert data["items"][0]["count"] == 3
    assert data["items"][0]["title"] == "触发反爬虫限制"


def test_informational_events_do_not_notify(center):
    center.record(event="log", level="info", message="课程章节获取成功", task_id="t1")
    center.record(event="task_progress", level="info", message="统计更新", task_id="t1")
    assert center.list()["unread"] == 0


def test_noisy_debug_lines_are_ignored(center):
    """命令行式的调试日志不应进入问题中心"""
    for text in ("GET https://mooc1.chaoxing.com/xxx",
                 "POST https://mooc1.chaoxing.com/yyy",
                 "重定向解析: https://example.com"):
        center.record(event="log", level="warning", message=text, task_id="t1")
    assert center.list()["unread"] == 0


def test_llm_and_answer_failures_are_classified(center):
    center.record(event="log", level="error", message="LLM 请求超时 (>180s)", task_id="t1")
    center.record(event="log", level="error", message="答题提交失败", task_id="t1")
    titles = {item["title"] for item in center.list()["items"]}
    assert "LLM 请求超时" in titles
    assert "答题提交失败" in titles


def test_mark_read_and_clear(center):
    center.record(event="task_failed", level="error", message="任务异常: 失败", task_id="t1")
    center.record(event="sync_failed", level="error", message="课程同步失败", account_id="a1")

    assert center.list()["unread"] == 2
    assert center.mark_read(category="task") == 1
    assert center.list()["unread"] == 1
    # 默认列表只含未读
    assert len(center.list()["items"]) == 1

    assert center.clear(only_read=True) == 1
    assert center.list(include_read=True)["total"] == 1

    assert center.mark_read() == 1
    assert center.list()["unread"] == 0


def test_notification_counts_by_level(center):
    center.record(event="task_failed", level="error", message="任务异常: x", task_id="t1")
    center.record(event="log", level="warning", message="触发反爬虫 202", task_id="t2")
    counts = center.list()["by_level"]
    assert counts.get("error") == 1
    assert counts.get("warning") == 1


# ============================================================
# 叙事流：把日志翻译成人话
# ============================================================

def test_login_and_course_stages_readable():
    item = narrative.describe("login_started", "正在登录账号 账号 01", stage="login")
    assert item["kind"] == "stage"
    assert "登录" in item["title"]

    item = narrative.describe("courses_loaded", "课程读取成功，共 12 门",
                             payload={"courses": 12}, stage="course")
    assert item["title"] == "读取到 12 门课程"


def test_media_progress_shows_percentage():
    item = narrative.describe("media_progress", "视频'第一讲'进度上报", stage="video",
                              payload={"media": "第一讲", "current": 3, "total": 12})
    assert item["progress"] == 25
    assert "第一讲" in item["title"]
    assert item["kind"] == "media"


def test_exam_progress_without_counts_has_no_placeholder():
    """缺少数目时不能渲染成 '进度 None/None 题'"""
    item = narrative.describe("exam_stats", "答题进度", stage="exam",
                              payload={"media": "第三章测验"})
    assert "None" not in item["detail"]
    assert item["detail"] == "开始作答"


def test_exam_progress_reports_sources():
    item = narrative.describe("exam_stats", "答题进度", stage="exam",
                              payload={"media": "第三章测验", "current": 5, "total": 20,
                                       "cache_hits": 2, "llm_calls": 3})
    assert item["progress"] == 25
    assert "答题缓存 2" in item["detail"]
    assert "AI 作答 3" in item["detail"]
    assert "在线题库" not in item["detail"]
    assert "题库" not in item["detail"].replace("答题缓存", "")


def test_submit_result_readable():
    item = narrative.describe("exam_stats", "提交结果", stage="exam",
                              payload={"media": "第三章测验", "submit_ok": 18, "submit_fail": 2})
    assert "18" in item["detail"]
    assert item["level"] in ("success", "warning")


def test_task_result_readable():
    item = narrative.describe("task_succeeded", "任务完成", payload={"stats": {"success": 9}})
    assert item["title"] == "任务完成"
    assert item["progress"] == 100

    item = narrative.describe("task_failed", "任务异常: 网络错误", level="error")
    assert item["title"] == "任务失败"


def test_raw_commands_are_hidden_from_narrative():
    """命令行式的原始日志不应原样出现在叙事里"""
    item = narrative.describe(
        "log", "GET https://mooc1.chaoxing.com/xxx?a=1&b=2", level="info")
    assert "https://" not in item["title"]
    assert "GET" not in item["title"]

    item = narrative.describe(
        "log", "视频'1.1 绪论' 当前刷取时长3分钟", level="info")
    assert item["kind"] == "media"
    assert "视频" in item["actor"]


def test_warning_maps_to_notice():
    item = narrative.describe("log", "触发反爬虫: 状态码202，触发反爬虫验证", level="warning")
    assert item["kind"] == "notice"
    assert item["title"] == "触发反爬虫限制"


def test_feature_label_translation():
    assert narrative.feature_label("course_all") == "完成课程任务点"
    assert narrative.feature_label("learn_count") == "刷取学习次数"


# ============================================================
# 仅本机运行
# ============================================================

def test_host_is_forced_to_loopback(sandbox):
    data = settings.save({"server": {"host": "0.0.0.0"}})
    assert data["server"]["host"] == "127.0.0.1"

    data = settings.save({"server": {"host": "192.168.1.50"}})
    assert data["server"]["host"] == "127.0.0.1"

    data = settings.save({"server": {"host": "localhost"}})
    assert data["server"]["host"] == "localhost"


def test_default_host_is_loopback(sandbox):
    assert settings.resolve("server.host") == "127.0.0.1"
    assert settings.masked()["server"]["host"] in settings.LOOPBACK_HOSTS


def test_storage_info_reports_sqlite(sandbox):
    info = settings.storage_info()
    assert info["backend"] == "sqlite"
    assert info["table"] == "app_settings"
    assert info["host_mode"] == "local-only"


# ============================================================
# API 集成
# ============================================================

def test_api_notification_lifecycle(app_client):
    from app.main import db
    db.upsert_notification(category="task", title="任务执行失败", detail="网络异常",
                           level="error", dedupe_key="k1",
                           context={"account_label": "账号 01", "course_name": "高等数学"})

    data = app_client.get("/api/notifications").json()
    assert data["unread"] == 1
    item = data["items"][0]
    # context 必须是解析后的对象，前端才能展示归属
    assert isinstance(item["context"], dict)
    assert item["context"]["account_label"] == "账号 01"
    assert item["count"] == 1
    item_id = item["id"]

    assert app_client.post("/api/notifications/read", json={"id": item_id}).json()["updated"] == 1
    assert app_client.get("/api/notifications").json()["unread"] == 0

    assert app_client.get("/api/notifications?include_read=true").json()["total"] == 1
    assert app_client.request("DELETE", "/api/notifications?only_read=true").json()["removed"] == 1


def test_api_events_carry_narrative(app_client):
    _, created = _make_run(app_client)
    task_id = created["task_ids"][0]
    from app.main import db
    db.add_event(task_id, "acc", "media_progress", "视频'第一讲'进度上报",
                 level="info", stage="video", payload={"media": "第一讲", "current": 1, "total": 4})

    events = app_client.get(f"/api/tasks/{task_id}/events").json()["items"]
    progress = [item for item in events if item["event"] == "media_progress"][0]
    assert progress["narrative"]["progress"] == 25
    assert "第一讲" in progress["narrative"]["title"]
    # 原始 message 仍然保留，供排查使用
    assert "第一讲" in progress["message"]


def test_api_task_failure_creates_notification(app_client):
    _, created = _make_run(app_client)
    task_id = created["task_ids"][0]
    from app.main import db, manager
    db.set_task_status(task_id, "running")
    manager._handle_line(task_id, "acc", json.dumps({
        "event": "task_failed", "task_id": task_id, "level": "error",
        "message": "任务异常: 登录凭据无效",
    }))

    data = app_client.get("/api/notifications").json()
    assert data["unread"] >= 1
    # 标题按失败内容细化：登录类失败会明确写成“学习通登录失败”
    assert any(item["title"] == "学习通登录失败" for item in data["items"]), data["items"]


def test_health_reports_local_only(app_client):
    data = app_client.get("/api/health").json()
    assert data["source_cli_writable"] is False


def _make_run(app_client, username="13800009090"):
    account = app_client.post("/api/accounts", json={
        "username": username, "password": "pwd123",
    }).json()
    created = app_client.post("/api/runs", json={
        "feature": "video",
        "targets": [{"account_id": account["id"], "course_id": "c1",
                     "class_id": "k1", "course_name": "测试课程"}],
    }).json()
    return account, created
