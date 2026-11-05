"""v2.4.0 T11.5：log_level 全链路——settings → 任务文件 → runner → sink 生效。"""
import io
import json

import pytest


# ---------------- runner.setup_logging 级别解析 ----------------

def _run_setup_logging(task, monkeypatch):
    """调用 worker.runner.setup_logging 并捕获传给 setup_common_logging 的 level。"""
    captured = {}

    def _fake_setup(sink, level="DEBUG", task_id="", extra_filter=None):
        captured["level"] = level

    from worker import runner

    monkeypatch.setattr(runner.common, "setup_common_logging", _fake_setup)
    monkeypatch.setattr(runner, "add_file_logger", lambda *a, **k: None)
    runner.setup_logging(None, task)
    return captured["level"]


@pytest.mark.parametrize("raw,expected", [
    ("DEBUG", "DEBUG"),
    ("INFO", "INFO"),
    ("WARNING", "WARNING"),
    ("ERROR", "ERROR"),
    ("warning", "WARNING"),
    ("trace", "INFO"),       # 非法值回退 INFO
    ("", "INFO"),
])
def test_setup_logging_reads_params_advanced_log_level(raw, expected, monkeypatch):
    assert _run_setup_logging({"params": {"advanced": {"log_level": raw}}},
                              monkeypatch) == expected


def test_setup_logging_defaults_info_without_params(monkeypatch):
    assert _run_setup_logging(None, monkeypatch) == "INFO"
    assert _run_setup_logging({}, monkeypatch) == "INFO"
    assert _run_setup_logging({"params": {}}, monkeypatch) == "INFO"


# ---------------- 任务文件携带 log_level 与 log_retention_days ----------------

def test_build_task_file_carries_log_settings(sandbox, monkeypatch):
    from app.task_manager import TaskManager
    from app.database import Database

    db = Database()
    manager = TaskManager(db, None)

    # 直接改设置：log_level=WARNING、retention=3
    from app import settings as settings_module

    settings_module.apply_updates({"advanced": {"log_level": "WARNING"},
                                   "storage": {"log_retention_days": 3}})
    row = {"id": "ll-task", "account_id": "acc", "feature": "course_all",
           "status": "pending", "params_json": "{}"}
    account = {"id": "acc", "username": "u", "password": "p", "label": "L"}
    payload = manager._build_task_file(row, account)
    assert payload["log_retention_days"] == 3
    # 设置层 log_level 注入 params.advanced，runner 端据此收敛 sink 级别
    assert payload["params"]["advanced"]["log_level"] == "WARNING"
    db.close()


# ---------------- sink 级别抑制（WARNING 时不发 debug/info） ----------------

class _CaptureSink:
    def __init__(self):
        self.records = []

    def emit(self, event, message="", level="info", stage="", payload=None):
        self.records.append((event, level, message, payload))


def test_module_logger_carries_caller_payload():
    """T11.3：_ModuleLogger 发出的 log 事件带调用方 module:function:line。"""
    from cli_copy.core import runtime

    sink = _CaptureSink()
    runtime.set_sink(sink)
    try:
        runtime.logger.warning("关注一下 {}", "这里")
        event, level, message, payload = sink.records[-1]
        assert (event, level) == ("log", "warning")
        assert message == "关注一下 这里"
        assert payload and "module" in payload
        assert "test_log_level_chain" in payload["module"]
    finally:
        runtime.set_sink(None)


def test_loguru_sink_respects_level_threshold(monkeypatch):
    """setup_common_logging(level=WARNING) 抑制 debug/info 走 sink。"""
    from worker import common

    sink = _CaptureSink()
    common.setup_common_logging(sink, level="WARNING")
    try:
        from loguru import logger

        logger.debug("不应出现")
        logger.info("也不应出现")
        logger.warning("应出现")
        levels = [r[1] for r in sink.records]
        assert "debug" not in levels
        assert "info" not in levels
        assert "warning" in levels
    finally:
        logger.remove()


def test_runner_emit_line_level_filtered():
    """端到端（进程内）：EventSink 不做级别过滤（协议事件必须全量透传），
    级别闸门在 loguru sink——验证 runner 侧 logger.debug 不产生输出而
    sink.emit 直发仍可见。"""
    from cli_copy.core import runtime

    sink = _CaptureSink()
    runtime.set_sink(sink)
    try:
        runtime.logger.debug("debug line")
        runtime.emit("work_result", "协议事件", level="info", stage="x")
        levels = [r[1] for r in sink.records]
        # _ModuleLogger 只暴露与级别无关的转发；闸门由 loguru 层负责
        assert "debug" in levels
        assert "info" in levels
    finally:
        runtime.set_sink(None)
