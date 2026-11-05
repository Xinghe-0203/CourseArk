"""v2.4.0 T11.5：多行 traceback 聚合为单事件（50 行上界 + 2s 滑窗）。"""
import json
import time

import pytest


@pytest.fixture()
def manager(sandbox):
    from app import events
    from app.database import Database
    from app.task_manager import TaskManager

    db = Database()
    hub = events.EventHub()
    instance = TaskManager(db, hub)
    try:
        yield instance, db
    finally:
        db.close()


def _seed(manager, task_id="tb-task"):
    manager.db.create_task({"id": task_id, "account_id": "acc",
                            "feature": "course_all", "status": "running"})


def _traceback_lines(n_body=10):
    lines = ["Traceback (most recent call last):",
             '  File "worker/runner.py", line 1, in <module>',
             "    main()"]
    for i in range(n_body):
        lines.append(f"  frame_{i}: some detail {i}")
    lines.append("RuntimeError: 任务执行失败")
    return lines


def test_multiline_traceback_becomes_single_event(manager):
    instance, db = manager
    _seed(instance)
    for line in _traceback_lines():
        instance._handle_line("tb-task", "acc", line)
    # 缓冲未满 50 行、未超 2s 窗口：尚未落库
    assert instance._traceback_buffer is not None
    # JSON 行出现即断 → 触发 flush
    instance._handle_line("tb-task", "acc", json.dumps({"event": "log", "message": "x"}))
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 1
    row = rows[0]
    assert row["level"] == "error"
    assert "Traceback (most recent call last):" in row["message"]
    assert "RuntimeError: 任务执行失败" in row["message"]
    payload = json.loads(row["payload_json"])
    assert payload["traceback"] is True
    assert payload["lines"] == len(_traceback_lines())


def test_traceback_50_line_upper_bound(manager):
    instance, db = manager
    _seed(instance)
    lines = _traceback_lines(60)  # 共 64 行
    for line in lines[:50]:
        instance._handle_line("tb-task", "acc", line)
    # 第 50 行时已触发 flush（上界），并重开空缓冲继续聚合剩余行
    assert instance._traceback_buffer is not None
    assert instance._traceback_buffer[0] == []
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["lines"] == 50
    # 后续行作为新的 traceback 缓冲继续聚合
    for line in lines[50:]:
        instance._handle_line("tb-task", "acc", line)
    instance._flush_traceback("tb-task", "acc")
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 2
    assert json.loads(rows[1]["payload_json"])["lines"] == 14


def test_traceback_two_second_window_flush(manager):
    instance, db = manager
    _seed(instance)
    instance._handle_line("tb-task", "acc", "Traceback (most recent call last):")
    instance._handle_line("tb-task", "acc", "  frame A")
    # 把窗口起点拨回 3s 前：下一条到达即超窗 flush
    instance._traceback_buffer[1] = time.time() - 3.0
    instance._handle_line("tb-task", "acc", "  frame B")
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 1
    assert instance._traceback_buffer is None
    assert "frame B" in rows[0]["message"]


def test_new_traceback_header_resets_buffer(manager):
    instance, db = manager
    _seed(instance)
    instance._handle_line("tb-task", "acc", "Traceback (most recent call last):")
    instance._handle_line("tb-task", "acc", "  old frame")
    # 第二个 traceback 开头：旧缓冲先落，新缓冲独立
    instance._handle_line("tb-task", "acc", "Traceback (most recent call last):")
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 1
    assert "old frame" in rows[0]["message"]
    assert instance._traceback_buffer[0] == ["Traceback (most recent call last):"]


def test_monitor_final_flush_on_exit(manager):
    """monitor 收尾（管道 EOF）时残余缓冲必须落库。"""
    instance, db = manager
    _seed(instance)

    class FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            return self._lines.pop(0).encode("utf-8") + b"\n" if self._lines else b""

        def close(self):
            pass

    class FakeProcess:
        stdout = FakeStream(["Traceback (most recent call last):",
                             '  File "x.py", line 1',
                             "ValueError: boom"])
        started = False

        def poll(self):
            return 0 if self.started else None

        def wait(self, timeout=None):
            self.started = True
            return 0

    # poll 返回 None → wait 收敛为 0 → succeeded
    instance._monitor("tb-task", FakeProcess())
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert len(rows) == 1
    assert "ValueError: boom" in rows[0]["message"]
    assert rows[0]["level"] == "error"


def test_normal_raw_logs_not_affected(manager):
    instance, db = manager
    _seed(instance)
    instance._handle_line("tb-task", "acc", "普通日志一行")
    instance._handle_line("tb-task", "acc", "另一行日志")
    assert instance._traceback_buffer is None
    rows = [r for r in db.list_events("tb-task") if r["stage"] == "raw"]
    assert [r["message"] for r in rows] == ["普通日志一行", "另一行日志"]
    assert all(r["level"] == "info" for r in rows)
