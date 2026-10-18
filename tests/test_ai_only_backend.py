"""v2.1「只保留 AI 做题」后端契约

覆盖：
- 设置接口不再暴露 tiku 组 / fallback_to_tiku，旧 mode=tiku 归一化为 ai
- 任务详情新增 answers（按 (media, index) 去重取最新）与 answers_summary
- DELETE /api/question-bank 清空本地答题缓存
- answer_result 的 presentation / narrative 映射
"""

import json


def _create_account(app_client, username="13800002222"):
    response = app_client.post("/api/accounts", json={
        "username": username, "password": "pwd123",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(app_client, username="13800003333", feature="chapter_exam",
                 params=None, course_name="第4章组件"):
    account = _create_account(app_client, username)
    response = app_client.post("/api/runs", json={
        "feature": feature,
        "targets": [{"account_id": account["id"], "course_id": "c1",
                     "class_id": "k1", "course_name": course_name}],
        "params": params or {},
    })
    assert response.status_code == 201, response.text
    return response.json()["task_ids"][0]


def _answer_payload(**overrides):
    payload = {
        "index": 1, "total": 3, "media": "第3章vue指令",
        "question_type": "单选题", "question": "下列关于组件通信的说法……",
        "options": ["A. props", "B. emit"], "answer": "A",
        "source": "ai", "status": "answered", "note": "",
    }
    payload.update(overrides)
    return payload


# ============================================================
# 设置：删除在线题库配置面
# ============================================================

def test_settings_api_has_no_tiku(app_client):
    data = app_client.get("/api/settings").json()
    assert "tiku" not in data
    assert "fallback_to_tiku" not in data["defaults"]["answer"]
    assert "has_tiku_token" not in data["source_config"]
    assert not any("tiku" in flag for flag in data["secrets"])

    # 旧前端/旧备份提交 tiku 组也不是错误，但不会写回
    patched = app_client.patch("/api/settings", json={
        "tiku": {"enabled": True, "timeout": 9, "enncy-token": "token-x"},
        "defaults": {"answer": {"fallback_to_tiku": True, "mode": "tiku"}},
    }).json()
    assert "tiku" not in patched
    assert "fallback_to_tiku" not in patched["defaults"]["answer"]
    assert patched["defaults"]["answer"]["mode"] == "ai"


def test_legacy_stored_settings_with_tiku_is_cleaned_on_read(sandbox):
    """旧数据库里残留的 tiku 组在读取时被丢弃，不抛错"""
    from app import settings

    settings.ensure_initialized()
    settings._store().set(settings.SETTINGS_KEY, {
        "tiku": {"enabled": True, "timeout": 9},
        "defaults": {"answer": {"mode": "tiku", "fallback_to_tiku": True}},
    })
    settings._cache = None
    data = settings.load()
    assert "tiku" not in data
    assert data["defaults"]["answer"]["mode"] == "ai"
    assert "fallback_to_tiku" not in data["defaults"]["answer"]


def test_legacy_tiku_mode_in_task_params_falls_back_to_ai(app_client):
    task_id = _create_task(app_client, params={"answer": {"mode": "tiku"}})
    detail = app_client.get(f"/api/tasks/{task_id}").json()
    assert detail["params"]["answer"]["mode"] == "ai"
    assert "fallback_to_tiku" not in detail["params"]["answer"]


# ============================================================
# 任务详情：逐题作答明细
# ============================================================

def test_task_detail_answers_dedupe_and_summary(app_client):
    from app.main import db

    task_id = _create_task(app_client, feature="independent_homework",
                           course_name="第3章vue指令")
    account_id = ""

    # 第 1 题重试两次：消费端只保留最后一条
    db.add_event(task_id, account_id, "answer_result", "第1题 单选题 -> A（AI）",
                 stage="work", payload=_answer_payload(index=1, answer="A"))
    db.add_event(task_id, account_id, "answer_result", "第1题 单选题 -> B（AI）",
                 stage="work", payload=_answer_payload(index=1, answer="B"))
    db.add_event(task_id, account_id, "answer_result", "第2题 未作答",
                 stage="work", level="warning",
                 payload=_answer_payload(index=2, answer="", source="failed",
                                         status="skipped", note="题面未识别"))
    db.add_event(task_id, account_id, "answer_result", "第3题 题面未识别",
                 stage="work", level="warning",
                 payload=_answer_payload(index=3, answer="", source="failed",
                                         status="unreadable", note="字体缺失"))
    db.update_task(task_id, stats_json=json.dumps(
        {"submit_ok": 1, "submit_fail": 0}, ensure_ascii=False))

    detail = app_client.get(f"/api/tasks/{task_id}").json()
    answers = detail["answers"]
    assert len(answers) == 3  # (media, index) 去重

    first = [item for item in answers if item["index"] == 1][0]
    assert first["answer"] == "B"
    assert first["key"] == "第3章vue指令#1"
    assert first["time"]  # 已格式化为本地时间字符串

    assert detail["answers_summary"] == {
        "answered": 1, "skipped": 2, "total": 3,
        "ai": 1, "cache": 0, "random": 0, "failed": 2,
        "submit_ok": 1, "submit_fail": 0,
    }


def test_task_detail_answers_empty_for_legacy_task(app_client):
    task_id = _create_task(app_client)
    detail = app_client.get(f"/api/tasks/{task_id}").json()
    assert detail["answers"] == []
    assert detail["answers_summary"] == {
        "answered": 0, "skipped": 0, "total": 0,
        "ai": 0, "cache": 0, "random": 0, "failed": 0,
        "submit_ok": 0, "submit_fail": 0,
    }


def test_task_detail_answers_are_redacted(app_client):
    from app.main import db

    task_id = _create_task(app_client)
    db.add_event(task_id, "", "answer_result", "第1题", stage="work",
                 payload=_answer_payload(answer="A", note="api_key=sk-secret-123456"))
    detail = app_client.get(f"/api/tasks/{task_id}").json()
    # 敏感值由 redact_data 统一脱敏，不应原样出现在响应里
    assert "sk-secret-123456" not in json.dumps(detail, ensure_ascii=False)


# ============================================================
# 答题缓存：清空接口
# ============================================================

def test_clear_question_bank_cache(app_client):
    payload = json.dumps([{"question_text": "清空测试题", "answer": "A"}],
                         ensure_ascii=False)
    imported = app_client.post("/api/question-bank/import", json={"content": payload}).json()
    assert imported["imported"] == 1
    assert app_client.get("/api/question-bank/stats").json()["total"] == 1

    response = app_client.delete("/api/question-bank")
    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    assert app_client.get("/api/question-bank/stats").json()["total"] == 0

    # 清空后再次清空仍返回 0，而不是 404
    assert app_client.delete("/api/question-bank").json() == {"deleted": 0}


# ============================================================
# 叙事层：answer_result 映射
# ============================================================

def test_answer_result_presentation_mapping():
    from app.presentation import describe

    answered = describe("answer_result", "第1题 单选题 -> A（AI）", "info", "work",
                        _answer_payload(index=1, answer="A", question_type="单选题"))
    assert answered["category"] == "exam"
    assert answered["title"] == "AI 已作答"
    assert "单选题" in answered["detail"] and "A" in answered["detail"]
    assert answered["visible"] is True

    skipped = describe("answer_result", "第2题 跳过", "warning", "work",
                       _answer_payload(index=2, answer="", source="failed",
                                       status="skipped", note="题面未识别"))
    assert skipped["title"] == "已跳过"
    assert "题面未识别" in skipped["detail"]
    assert skipped["visible"] is True

    unreadable = describe("answer_result", "第3题 题面未识别", "warning", "exam",
                          _answer_payload(index=3, answer="", source="failed",
                                          status="unreadable"))
    assert unreadable["title"] == "题面未识别"
    assert unreadable["category"] == "exam"


def test_answer_result_narrative_and_exam_stats_wording():
    from app import narrative

    item = narrative.describe("answer_result", "第1题 单选题 -> A（AI）", level="info",
                              stage="work", payload=_answer_payload(index=1, answer="A"))
    assert item["kind"] == "answer"
    assert "第3章vue指令" in item["title"]
    assert "答案 A" in item["detail"]

    stats = narrative.describe("exam_stats", "第4章组件", level="info", stage="exam",
                               payload={"media": "第4章组件", "current": 2, "total": 4,
                                        "cache_hits": 1, "tiku_hits": 3, "llm_calls": 1})
    assert stats["kind"] == "answer"
    assert "在线题库" not in stats["detail"]
    assert "答题缓存 1" in stats["detail"]
