# -*- coding: utf-8 -*-
"""T6 存储层加固回归：payload 截断 / 事件批量缓冲 / CAS 更新 / dashboard 白名单 / 设置类型防御"""

import json
import time

import pytest

from app import database as dbmod
from app import settings


# ------------------------------------------------------------
# fixture：临时数据库
# ------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    instance = dbmod.Database(str(tmp_path / "test.db"))
    _RUNS.clear()
    dbmod.paths.ensure_dirs()
    yield instance
    instance.close()


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """重定向 paths 到临时目录（设置测试用）"""
    monkeypatch.setattr(settings.paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings.paths, "DATABASE_FILE", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings.paths, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings.paths, "SETTINGS_BACKUP_FILE", str(tmp_path / "settings.backup.json"))
    settings._cache = None
    settings._storage = None
    yield tmp_path
    settings._cache = None
    settings._storage = None


_RUNS = set()


def _make_task(db_instance, task_id="t-1", status="succeeded", stats=None):
    if "run-1" not in _RUNS:
        db_instance.create_run("run-1", 1, note="")
        _RUNS.add("run-1")
    task = {
        "id": task_id, "run_id": "run-1", "account_id": "acc-1",
        "account_label": "账号一", "feature": "course_all", "status": status,
        "params": {}, "progress": {}, "stats": stats or {},
        "created_at": time.time(),
    }
    db_instance.create_task(task)
    return task_id


# ------------------------------------------------------------
# payload 截断
# ------------------------------------------------------------

class TestPayloadTruncation:
    def test_small_payload_stays_intact(self, db):
        db.add_event("t-1", "acc", "work_result", "ok", payload={"a": 1})
        rows = db.list_events("t-1")
        assert json.loads(rows[0]["payload_json"]) == {"a": 1}

    def test_oversized_payload_becomes_skeleton(self, db):
        big = {"items": [{"question": "x" * 500} for _ in range(50)]}
        db.add_event("t-1", "acc", "work_result", "ok", payload=big)
        rows = db.list_events("t-1")
        decoded = json.loads(rows[0]["payload_json"])
        assert decoded["truncated"] is True
        assert decoded["keys"] == ["items"]
        assert decoded["preview"].startswith("{")
        assert len(rows[0]["payload_json"]) < dbmod.MAX_PAYLOAD_JSON + 1000


# ------------------------------------------------------------
# 事件批量缓冲
# ------------------------------------------------------------

class TestEventBuffer:
    def test_flush_at_limit(self, db):
        for index in range(dbmod.EVENT_BUFFER_LIMIT):
            db.add_event("t-1", "acc", "log", f"m{index}")
        rows = db.list_events("t-1")
        assert len(rows) == dbmod.EVENT_BUFFER_LIMIT

    def test_read_flushes_pending(self, db):
        db.add_event("t-1", "acc", "log", "缓冲中的消息")
        # 未到条数阈值，但读方法必须看到它（读己之写）
        rows = db.list_events("t-1")
        assert [row["message"] for row in rows] == ["缓冲中的消息"]

    def test_close_flushes(self, tmp_path):
        instance = dbmod.Database(str(tmp_path / "flush.db"))
        instance.add_event("t-1", "acc", "log", "关闭前最后一条")
        instance.close()
        reopened = dbmod.Database(str(tmp_path / "flush.db"))
        rows = reopened.list_events("t-1")
        reopened.close()
        assert len(rows) == 1

    def test_returns_preallocated_positive_id(self, db):
        first = db.add_event("t-1", "acc", "log", "第一条")
        second = db.add_event("t-1", "acc", "log", "第二条")
        # id 预分配：即使事件还在缓冲，返回值也必须是可用的真实行 id（SSE 游标契约）
        assert first > 0 and second > first
        rows = db.list_events("t-1")
        assert [row["id"] for row in rows] == [first, second]


# ------------------------------------------------------------
# CAS 化：set_task_status / upsert_preset
# ------------------------------------------------------------

class TestCasUpdates:
    def test_set_task_status_writes_started_at_once(self, db):
        task_id = _make_task(db, status="pending")
        db.set_task_status(task_id, "running")
        first = db.get_task(task_id)
        assert first["started_at"] > 0
        # 第二次置 running 不应改写 started_at
        started = first["started_at"]
        db.set_task_status(task_id, "logging_in")
        again = db.get_task(task_id)
        assert again["started_at"] == started

    def test_set_task_status_error_and_finished(self, db):
        task_id = _make_task(db, status="running")
        db.set_task_status(task_id, "failed", error="登录失败", finished=True)
        row = db.get_task(task_id)
        assert row["status"] == "failed"
        assert row["error"] == "登录失败"
        assert row["finished_at"] > 0

    def test_upsert_preset_insert_then_update(self, db):
        first = db.upsert_preset("p-1", "参数A", {"a": 1})
        assert first["name"] == "参数A"
        second = db.upsert_preset("p-1", "参数B", {"b": 2})
        assert second["name"] == "参数B"
        assert json.loads(second["params_json"]) == {"b": 2}
        assert len(db.list_presets()) == 1
        assert db.list_presets()[0]["created_at"] == first["created_at"]


# ------------------------------------------------------------
# dashboard_stats 状态白名单
# ------------------------------------------------------------

class TestDashboardStatsWhitelist:
    def test_running_task_stats_count(self, db):
        _make_task(db, task_id="t-run", status="running",
                   stats={"success": 5, "questions": 3})
        totals = db.dashboard_stats(since=0)
        assert totals["success"] == 5
        assert totals["questions"] == 3

    def test_interrupted_task_stats_count(self, db):
        _make_task(db, task_id="t-int", status="interrupted",
                   stats={"success": 2, "failed": 1})
        totals = db.dashboard_stats(since=0)
        assert totals["success"] == 2
        assert totals["failed"] == 1

    def test_pending_starting_stopping_count(self, db):
        _make_task(db, task_id="t-p", status="pending", stats={"success": 1})
        _make_task(db, task_id="t-s", status="stopping", stats={"success": 1})
        totals = db.dashboard_stats(since=0)
        assert totals["success"] == 2

    def test_corrupt_stats_json_skipped(self, db):
        db.create_run("run-2", 1, note="")
        db.create_task({
            "id": "t-bad", "run_id": "run-2", "account_id": "acc-1",
            "feature": "course_all", "status": "succeeded",
            "params": {}, "progress": {}, "stats": {},
            "created_at": time.time(),
        })
        # 直接把 stats_json 写坏，模拟旧版本脏数据
        db.update_task("t-bad", stats_json="{corrupt")
        totals = db.dashboard_stats(since=0)
        assert totals["success"] == 0


# ------------------------------------------------------------
# 设置：类型防御 / 导出脱敏 / null 清除
# ------------------------------------------------------------

class TestSettingsHardening:
    def test_deep_merge_rejects_scalar_over_dict(self):
        base = {"scheduler": {"max_active_workers": 8, "stop_grace_seconds": 25}}
        merged = settings._deep_merge(base, {"scheduler": "reset"})
        assert merged["scheduler"]["max_active_workers"] == 8

    def test_deep_merge_keeps_scalar_overwrite(self):
        merged = settings._deep_merge({"a": {"b": 1}}, {"a": {"b": 2}})
        assert merged["a"]["b"] == 2

    def test_export_json_redacts_secret(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-secret-123"}})
        exported = json.loads(settings.export_json())
        assert exported["llm"]["api_key"] == settings.REDACTED_PLACEHOLDER
        assert "sk-secret-123" not in settings.export_json()

    def test_import_skips_redacted_placeholder(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-live-key"}})
        settings.import_json(json.dumps({"llm": {"api_key": settings.REDACTED_PLACEHOLDER}}))
        assert settings.resolve("llm.api_key") == "sk-live-key"

    def test_import_roundtrip_preserves_settings(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-abc", "model": "gpt-x"}})
        exported = settings.export_json()
        settings.apply_updates({"llm": {"model": "changed"}})
        settings.import_json(exported)
        assert settings.resolve("llm.model") == "gpt-x"
        assert settings.resolve("llm.api_key") == "sk-abc"

    def test_apply_updates_null_clears_secret(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-to-clear"}})
        settings.apply_updates({"llm": {"api_key": None}})
        assert settings.resolve("llm.api_key", "missing") in ("", None, "missing")

    def test_apply_updates_empty_string_keeps_secret(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-keep"}})
        settings.apply_updates({"llm": {"api_key": ""}})
        assert settings.resolve("llm.api_key") == "sk-keep"

    def test_apply_updates_missing_key_keeps_secret(self, sandbox):
        settings.apply_updates({"llm": {"api_key": "sk-keep"}})
        settings.apply_updates({"llm": {"model": "m-1"}})
        assert settings.resolve("llm.api_key") == "sk-keep"

    def test_normalize_survives_garbage_sections(self, sandbox):
        settings._cache = {"scheduler": "garbage", "llm": ["bad"], "video": 3}
        data = settings.normalize(settings._cache)
        assert isinstance(data["scheduler"], dict)
        assert data["scheduler"]["max_active_workers"] == 8
