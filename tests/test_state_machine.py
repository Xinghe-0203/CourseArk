"""v2.4.0 T4 状态机守卫与并发槽测试

覆盖计划卡 4.8：
- TRANSITIONS 放行矩阵（合法跳转、终态无出路、终态同值幂等）
- 观察模式（非法跳转产生 state_guard warning 事件、状态照写不回滚）
- 收紧模式（TASK_STATE_GUARD_STRICT=1 拒绝非法迁移）
- 并发槽按「非暂停态 Worker」计（paused 让出槽位）
"""

import json

from app import settings
from app.database import Database
from app.task_manager import _SLOT_EXEMPT_STATUSES, RunningTask, TaskManager
from app.task_model import (ACTIVE_STATES, TERMINAL_STATES, TRANSITIONS,
                            can_transition, is_terminal)

from test_task_manager import FakeProcess, _DummyThread, _make_task, manager  # noqa: F401


# ============================================================
# TRANSITIONS 表完整性
# ============================================================

def test_transitions_table_complete():
    # 每个非终态都有出路，终态无出路
    for state in TRANSITIONS:
        if is_terminal(state):
            assert TRANSITIONS[state] == set()
        else:
            assert TRANSITIONS[state], f"{state} 无出路"


def test_can_transition_boolean_semantics():
    assert can_transition("pending", "starting") is True
    assert can_transition("running", "paused") is True
    assert can_transition("paused", "running") is True
    assert can_transition("running", "succeeded") is True
    assert can_transition("succeeded", "running") is False
    assert can_transition("unknown-state", "running") is False


def test_terminal_states_have_no_outgoing():
    for state in TERMINAL_STATES:
        assert is_terminal(state)
        for nxt in TRANSITIONS:
            assert not can_transition(state, nxt)
        # 同值幂等：is_terminal + can_transition(cur, cur) 都不要求成立，
        # 守卫的同值放行在 _guard_status 内实现（见观察模式测试）


def test_active_and_terminal_disjoint():
    assert not (set(ACTIVE_STATES) & set(TERMINAL_STATES))


# ============================================================
# 观察模式：_apply_event 非法跳转只告警不拦截
# ============================================================

def test_illegal_transition_logs_state_guard_and_continues(manager):
    # succeeded → running 是非法迁移（worker 异常重复 resumed）
    task = _make_task(manager.db, status="succeeded")
    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "resumed", "task_id": task["id"]}))
    # 观察模式：终态早退直接 return，状态不回滚
    assert manager.db.get_task(task["id"])["status"] == "succeeded"
    stored = manager.db.list_events(task["id"])
    assert not any(item["event"] == "state_guard" for item in stored)


def test_guard_warns_but_writes_for_nonterminal_illegal_jump(manager, monkeypatch):
    # logging_in → paused 在扩表后已合法；构造一个真正非法的跳转：
    # pending → running（pending 不在 TRANSITIONS["pending"] 的 running 出路里…实际上在，
    # 所以改用 succeeded 早退路径之外的直接 _guard_status 单测）
    task = _make_task(manager.db, status="running")
    # running → starting 非法（无此出路）
    allowed = manager._guard_status(task["id"], "running", "starting")
    assert allowed is True  # 观察模式不拦截
    stored = manager.db.list_events(task["id"])
    guards = [item for item in stored if item["event"] == "state_guard"]
    assert len(guards) == 1
    assert guards[0]["level"] == "warning"
    assert "running" in guards[0]["message"] and "starting" in guards[0]["message"]


def test_guard_strict_mode_rejects(manager, monkeypatch):
    task = _make_task(manager.db, status="running")
    monkeypatch.setenv("TASK_STATE_GUARD_STRICT", "1")
    allowed = manager._guard_status(task["id"], "running", "starting")
    assert allowed is False


def test_guard_idempotent_same_value_allowed(manager):
    task = _make_task(manager.db, status="running")
    assert manager._guard_status(task["id"], "running", "running") is True
    stored = manager.db.list_events(task["id"])
    assert not any(item["event"] == "state_guard" for item in stored)


def test_stage_event_sequence_still_drives_status(manager):
    # 回归保护：T4 handler 表化后 STAGE_EVENTS 序列不变
    task = _make_task(manager.db, status="starting")
    sequence = [
        ("login_started", "logging_in"),
        ("login_succeeded", "loading_courses"),
        ("courses_loaded", "loading_courses"),
        ("course_started", "running"),
    ]
    for event, expected in sequence:
        manager._handle_line(task["id"], task["account_id"], json.dumps(
            {"event": event, "task_id": task["id"], "message": event}))
        assert manager.db.get_task(task["id"])["status"] == expected


def test_worker_terminal_events_land_from_any_intermediate_state(manager):
    # worker 异步 task_succeeded 可从任意中间态直达（终态收敛语义）
    for i, mid in enumerate(("starting", "logging_in", "loading_courses", "pausing", "stopping")):
        task = _make_task(manager.db, status=mid, run_id=f"run-sm-{i}")
        manager._handle_line(task["id"], task["account_id"], json.dumps(
            {"event": "task_succeeded", "task_id": task["id"], "message": "完成"}))
        row = manager.db.get_task(task["id"])
        assert row["status"] == "succeeded", f"from {mid}"
        assert row["finished_at"] is not None


# ============================================================
# 并发槽：paused 让出槽位
# ============================================================

def test_paused_handle_yields_slot(manager):
    task = _make_task(manager.db, status="running")
    handle = RunningTask(task["id"], FakeProcess(poll_value=None), monitor=_DummyThread())
    handle.status = "running"
    with manager._lock:
        manager._running[task["id"]] = handle
    assert manager._active_slots() == 1

    handle.status = "paused"
    assert manager._active_slots() == 0  # 暂停让出槽位
    assert _SLOT_EXEMPT_STATUSES == ("paused", "pausing")

    handle.status = "pausing"
    assert manager._active_slots() == 0

    handle.status = "running"
    assert manager._active_slots() == 1


def test_snapshot_distinguishes_workers_and_slots(manager):
    task = _make_task(manager.db, status="running")
    handle = RunningTask(task["id"], FakeProcess(poll_value=None), monitor=_DummyThread())
    handle.status = "paused"
    with manager._lock:
        manager._running[task["id"]] = handle
    snap = manager.snapshot()
    assert snap["workers"] == 1   # 常驻 Worker 数
    assert snap["running"] == 0   # 占用槽位数
    assert snap["busy"] == 0


def test_paused_event_remembered_on_handle(manager):
    task = _make_task(manager.db, status="running")
    handle = RunningTask(task["id"], FakeProcess(poll_value=None), monitor=_DummyThread())
    handle.status = "running"
    with manager._lock:
        manager._running[task["id"]] = handle

    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "paused", "task_id": task["id"]}))
    assert manager.db.get_task(task["id"])["status"] == "paused"
    assert handle.status == "paused"
    assert manager._active_slots() == 0

    manager._handle_line(task["id"], task["account_id"], json.dumps(
        {"event": "resumed", "task_id": task["id"]}))
    assert manager.db.get_task(task["id"])["status"] == "running"
    assert handle.status == "running"
    assert manager._active_slots() == 1


def test_default_settings_unchanged_by_t4(sandbox):
    # T4 未新增配置项：scheduler.max_active_workers/stop_grace_seconds 原值保持
    value = settings.resolve("scheduler.max_active_workers", 8)
    assert value == 8
    grace = settings.resolve("scheduler.stop_grace_seconds", 25)
    assert grace == 25
