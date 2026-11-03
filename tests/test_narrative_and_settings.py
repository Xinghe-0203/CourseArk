"""叙事流与设置约束测试

覆盖用户反馈的核心问题：
1. 前端展示命令行 —— 现在必须转成"做什么/进度/成功失败"
2. 错误提示必须可读、可归类
另外覆盖"仅本机运行"的配置约束。
"""

import json

from app import narrative, settings


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


def test_api_task_failure_is_persisted_as_event(app_client):
    _, created = _make_run(app_client)
    task_id = created["task_ids"][0]
    from app.main import db, manager
    db.set_task_status(task_id, "running")
    manager._handle_line(task_id, "acc", json.dumps({
        "event": "task_failed", "task_id": task_id, "level": "error",
        "message": "任务异常: 登录凭据无效",
    }))

    task = app_client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "failed"
    events = app_client.get(f"/api/tasks/{task_id}/events").json()["items"]
    failures = [item for item in events if item["event"] == "task_failed"]
    assert failures, events
    # 事件自带可读叙事，前端详情页据此展示失败原因
    assert failures[-1]["presentation"]["category"] == "login"


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
