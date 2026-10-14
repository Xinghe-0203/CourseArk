"""TaskManager 事件解析、状态流转、控制命令与恢复测试"""

import json
import os
import time

import pytest

from app import accounts, control, events, paths, settings
from app.database import Database
from app.task_manager import RunningTask, TaskManager


class FakeProcess:
    """模拟 subprocess.Popen 的最小接口"""

    def __init__(self, pid: int = 4321, poll_value=None):
        self.pid = pid
        self._poll = poll_value
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        return self._poll

    def terminate(self):
        self.terminated = True
        self._poll = -1

    def kill(self):
        self.killed = True
        self._poll = -9


@pytest.fixture()
def manager(sandbox):
    db = Database()
    hub = events.EventHub()
    mgr = TaskManager(db, hub)
    yield mgr
    db.close()


def _make_task(db, feature="video", status="pending"):
    account = accounts.create_account(f"135000{int(time.time() * 1000) % 100000:05d}", "pwd")
    task = {
        "id": f"t{int(time.time() * 1000000) % 10 ** 9}",
        "run_id": "run-1",
        "account_id": account["id"],
        "account_label": account["label"],
        "course_id": "c1",
        "class_id": "k1",
        "cpi": "cpi1",
        "course_name": "测试课程",
        "feature": feature,
        "status": status,
        "params": {"video": {"mode": "instant", "max_workers": 2, "random_progress": False}},
        "created_at": time.time(),
    }
    db.create_run("run-1", 1)
    db.create_task(task)
    return task


# ============================================================
# 事件解析
# ============================================================

def test_json_event_is_parsed_and_stored(manager):
    task = _make_task(manager.db, status="running")
    line = json.dumps({
        "event": "task_progress",
        "task_id": task["id"],
        "level": "info",
        "stage": "video",
        "message": "进度更新",
        "payload": {"current": 3, "total": 10, "success": 2},
    }, ensure_ascii=False)
    manager._handle_line(task["id"], task["account_id"], line)

    row = manager.db.get_task(task["id"])
    stats = json.loads(row["stats_json"])
    assert stats["current"] == 3 and stats["success"] == 2
    assert row["stage"] == "video"

    stored = manager.db.list_events(task["id"])
    assert stored[-1]["event"] == "task_progress"
    assert stored[-1]["message"] == "进度更新"
    assert json.loads(stored[-1]["payload_json"])["total"] == 10


def test_non_json_output_becomes_log_event(manager):
    task = _make_task(manager.db, status="running")
    manager._handle_line(task["id"], task["account_id"], "Warning: 这不是 JSON")
    manager._handle_line(task["id"], task["account_id"], "")
    stored = manager.db.list_events(task["id"])
    assert len(stored) == 1
    assert stored[0]["event"] == "log"
    assert "不是 JSON" in stored[0]["message"]


def test_mismatched_task_id_is_ignored(manager):
    task = _make_task(manager.db, status="running")
    line = json.dumps({"event": "task_succeeded", "task_id": "another-task", "message": "x"})
    manager._handle_line(task["id"], task["account_id"], line)
    row = manager.db.get_task(task["id"])
    assert row["status"] == "running"  # 未被其它任务的事件改变
    stored = manager.db.list_events(task["id"])
    assert any("忽略来自其它任务" in item["message"] for item in stored)


def test_malformed_json_payload_does_not_break_reader(manager):
    task = _make_task(manager.db, status="running")
    # 事件字段类型异常时不应抛错
    manager._handle_line(task["id"], task["account_id"], '{"event": 5, "payload": [1,2]}')
    manager._handle_line(task["id"], task["account_id"], '[1, 2, 3]')
    manager._handle_line(task["id"], task["account_id"], '{"event": "log"}')
    assert manager.db.get_task(task["id"]) is not None


def test_exam_stats_accumulate(manager):
    task = _make_task(manager.db, status="running")
    for submit in (1, 0):
        manager._handle_line(task["id"], task["account_id"], json.dumps({
            "event": "exam_stats", "task_id": task["id"], "payload": {
                "cache_hits": 2, "tiku_hits": 1, "llm_calls": 3, "random_answers": 0,
                "questions": 5, "submit_ok": submit, "submit_fail": 1 - submit,
            },
        }))
    stats = json.loads(manager.db.get_task(task["id"])["stats_json"])
    assert stats["submit_ok"] == 1
    assert stats["submit_fail"] == 1
    assert stats["questions"] == 10
    assert stats["cache_hits"] == 2


# ============================================================
# 状态流转
# ============================================================

def test_event_sequence_drives_status(manager):
    task = _make_task(manager.db, status="starting")
    sequence = [
        ("login_started", "logging_in"),
        ("login_succeeded", "loading_courses"),
        ("courses_loaded", "loading_courses"),
        ("course_started", "running"),
    ]
    for event, expected in sequence:
        manager._handle_line(task["id"], task["account_id"], json.dumps({
            "event": event, "task_id": task["id"], "message": event,
        }))
        assert manager.db.get_task(task["id"])["status"] == expected


def test_terminal_event_marks_finished_and_updates_run(manager):
    task = _make_task(manager.db, status="running")
    manager._handle_line(task["id"], task["account_id"], json.dumps({
        "event": "task_succeeded", "task_id": task["id"], "message": "完成",
        "payload": {"stats": {"success": 7, "failed": 1}},
    }))
    row = manager.db.get_task(task["id"])
    assert row["status"] == "succeeded"
    assert row["finished_at"] is not None
    assert json.loads(row["stats_json"])["success"] == 7
    assert manager.db.get_run("run-1")["status"] == "succeeded"


def test_task_failed_records_error(manager):
    task = _make_task(manager.db, status="running")
    manager._handle_line(task["id"], task["account_id"], json.dumps({
        "event": "task_failed", "task_id": task["id"], "level": "error",
        "payload": {"message": "登录凭据无效"},
    }))
    row = manager.db.get_task(task["id"])
    assert row["status"] == "failed"
    assert "登录凭据无效" in row["error"]


def test_events_after_terminal_are_ignored(manager):
    task = _make_task(manager.db, status="running")
    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "task_stopped", "task_id": task["id"]}))
    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "task_succeeded", "task_id": task["id"]}))
    assert manager.db.get_task(task["id"])["status"] == "stopped"


def test_paused_and_resumed_events_flip_status(manager):
    task = _make_task(manager.db, status="running")
    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "paused", "task_id": task["id"]}))
    assert manager.db.get_task(task["id"])["status"] == "paused"
    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "resumed", "task_id": task["id"]}))
    assert manager.db.get_task(task["id"])["status"] == "running"


# ============================================================
# 控制命令
# ============================================================

def test_pause_resume_stop_write_control_files(manager):
    task = _make_task(manager.db, status="running")

    manager.pause(task["id"])
    assert control.read_command(task["id"])["command"] == "pause"
    assert manager.db.get_task(task["id"])["status"] == "pausing"

    manager.resume(task["id"])
    assert control.read_command(task["id"])["command"] == "run"
    assert manager.db.get_task(task["id"])["status"] == "running"

    manager.stop(task["id"])
    assert control.read_command(task["id"])["command"] == "stop"
    assert manager.db.get_task(task["id"])["status"] == "stopping"
    events_stored = manager.db.list_events(task["id"])
    assert any(item["event"] == "stop_requested" for item in events_stored)


def test_control_rejected_in_terminal_state(manager):
    task = _make_task(manager.db, status="succeeded")
    for action in (manager.pause, manager.resume, manager.stop):
        with pytest.raises(ValueError):
            action(task["id"])


def test_pause_rejected_when_already_paused(manager):
    task = _make_task(manager.db, status="paused")
    with pytest.raises(ValueError):
        manager.pause(task["id"])


def test_stop_of_pending_task_marks_stopped_immediately(manager):
    task = _make_task(manager.db, status="pending")
    manager.stop(task["id"])
    row = manager.db.get_task(task["id"])
    assert row["status"] == "stopped"
    assert row["finished_at"] is not None


def test_control_unknown_task_raises(manager):
    with pytest.raises(KeyError):
        manager.pause("ghost")


# ============================================================
# 重试
# ============================================================

def test_retry_creates_new_task_with_same_params(manager):
    task = _make_task(manager.db, status="failed")
    manager.db.set_task_status(task["id"], "failed", error="boom", finished=True)
    retried = manager.retry_task(task["id"])
    assert retried["id"] != task["id"]
    assert retried["status"] == "pending"
    assert json.loads(retried["params_json"]) == task["params"]
    assert retried["feature"] == task["feature"]


# ============================================================
# 重启恢复
# ============================================================

def test_recovery_marks_active_tasks_interrupted(sandbox):
    db = Database()
    hub = events.EventHub()
    task = _make_task(db, status="running")
    db.update_task(task["id"], pid=999999999)  # 不存在的 pid

    mgr = TaskManager(db, hub)
    mgr._recover_interrupted()

    row = db.get_task(task["id"])
    assert row["status"] == "interrupted"
    assert row["finished_at"] is not None
    assert "重启" in row["error"]
    assert not os.path.exists(paths.control_path(task["id"]))
    db.close()


def test_recovery_leaves_terminal_tasks_untouched(sandbox):
    db = Database()
    hub = events.EventHub()
    task = _make_task(db, status="succeeded")
    manager = TaskManager(db, hub)
    manager._recover_interrupted()
    assert db.get_task(task["id"])["status"] == "succeeded"
    db.close()


# ============================================================
# 强制停止
# ============================================================

def test_force_stop_after_grace_period(manager):
    task = _make_task(manager.db, status="stopping")
    process = FakeProcess(poll_value=None)
    handle = RunningTask(task["id"], process, monitor=_DummyThread())
    handle.stop_requested_at = time.time() - 999  # 已超过宽限时间
    settings.save({"scheduler": {"stop_grace_seconds": 5}})

    with manager._lock:
        manager._running[task["id"]] = handle
    manager._prune_finished()

    assert process.terminated is True
    row = manager.db.get_task(task["id"])
    assert row["status"] == "stopped"
    assert "强制终止" in row["error"]


def test_finished_process_is_pruned(manager):
    task = _make_task(manager.db, status="running")
    process = FakeProcess(poll_value=0)
    handle = RunningTask(task["id"], process, monitor=_DummyThread())
    with manager._lock:
        manager._running[task["id"]] = handle
    manager._prune_finished()
    with manager._lock:
        assert task["id"] not in manager._running


class _DummyThread:
    def is_alive(self):
        return False

    def join(self, timeout=None):
        return None
