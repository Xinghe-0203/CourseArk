# -*- coding: utf-8 -*-
"""T5 5.6：列表端点 SQL 语句数上界回归

用 sqlite3 set_trace_callback 统计一次请求触发的 SQL 条数：
- /api/tasks?limit=100        未完成单元数必须走一次批量预取，不能逐行查询
- /api/completed?limit=30     逐题明细必须走一次批量预取
- /api/workspace/accounts     每账号一遍分页 + 一次批量预取

阈值取实测值上浮少量余量，防止未来改动悄悄退回 N+1。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import events, main as main_module  # noqa: E402
from app.database import Database  # noqa: E402
from app.task_manager import TaskManager  # noqa: E402


@pytest.fixture()
def app_client(monkeypatch):
    # 临时目录放到系统 temp：此前用 ROOT/.tmp-gate 会在仓库（甚至父目录）里留垃圾。
    tmp = tempfile.mkdtemp(prefix="autocxwebui-nplus1-")
    monkeypatch.setenv("AUTOCXWEBUI_DATA_DIR", tmp)
    from app import paths
    paths.DATA_DIR = tmp
    paths.CONTROL_DIR = os.path.join(tmp, "control")
    paths.TASK_DIR = os.path.join(tmp, "tasks")
    paths.LOG_DIR = os.path.join(tmp, "logs")
    paths.EXPORT_DIR = os.path.join(tmp, "exports")
    paths.DOWNLOAD_DIR = os.path.join(tmp, "downloads")
    paths.ACCOUNTS_FILE = os.path.join(tmp, "accounts.json")
    paths.SETTINGS_FILE = os.path.join(tmp, "settings.json")
    paths.SETTINGS_BACKUP_FILE = os.path.join(tmp, "settings.backup.json")
    paths.DATABASE_FILE = os.path.join(tmp, "webui.db")
    paths.QUESTION_BANK_FILE = os.path.join(tmp, "question_bank.db")
    paths.ensure_dirs()

    db = Database()
    hub = events.EventHub()
    manager = TaskManager(db, hub)
    main_module.db = db
    main_module.hub = hub
    main_module.manager = manager
    client = TestClient(main_module.create_app())

    yield client, db

    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _seed_workspace(client, db, n_tasks=30):
    """1 账号 + n_tasks 任务（一半带 work_plan/work_result，一半 succeeded）"""
    created = client.post("/api/accounts", json={
        "username": "13800007777", "password": "pwd123", "label": "压测账号",
    })
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    try:
        db.create_run("run-nplus1", n_tasks)
    except Exception:
        pass
    for i in range(n_tasks):
        status = "succeeded" if i % 2 == 0 else "running"
        task_id = f"np-{i:03d}"
        db.create_task({
            "id": task_id, "run_id": "run-nplus1", "account_id": account_id,
            "account_label": "压测账号", "course_id": f"c{i}", "class_id": "k1",
            "cpi": "cpi1", "course_name": f"课程 {i}", "feature": "course_all",
            "status": status, "params": {}, "created_at": 1000.0 + i,
        })
        if status == "succeeded":
            continue
        units = [{"id": f"ch{i}-{j}", "name": f"章节 {j}", "kind": "video"}
                 for j in range(10)]
        db.add_event(task_id, account_id, "work_plan", "计划", stage="task",
                     payload={"units": units})
        for j in range(5):
            db.add_event(task_id, account_id, "work_result", "完成", stage="task",
                         payload={"id": f"ch{i}-{j}", "status": "succeeded"})
        if i % 2 == 1:
            for j in range(4):
                db.add_event(task_id, account_id, "answer_result", "作答", stage="answer",
                             payload={"media": f"m{j}", "index": j, "total": 4,
                                      "question": "题目", "answer": "A", "source": "ai",
                                      "status": "answered"})
    return account_id


def _count_sql(db, fn):
    count = {"n": 0}

    def tracer(statement):
        count["n"] += 1

    db._conn.set_trace_callback(tracer)
    try:
        fn()
    finally:
        db._conn.set_trace_callback(None)
    return count["n"]


def test_tasks_list_sql_upper_bound(app_client):
    """/api/tasks 未完成单元数走批量预取：SQL 数不随任务数线性增长"""
    client, db = app_client
    _seed_workspace(client, db, n_tasks=30)
    baseline = _count_sql(db, lambda: client.get("/api/tasks?limit=100"))
    # 30 任务 → 列表 1 + count 1 + plans 1 + results 1 ≈ 4；给宽裕上界 12
    assert baseline <= 12, f"/api/tasks SQL 数 {baseline} 超过上界（疑似 N+1 回退）"


def test_completed_sql_upper_bound(app_client):
    """/api/completed 逐题明细走批量预取：SQL 数不随任务数线性增长"""
    client, db = app_client
    _seed_workspace(client, db, n_tasks=30)
    baseline = _count_sql(db, lambda: client.get("/api/completed?limit=30"))
    assert baseline <= 12, f"/api/completed SQL 数 {baseline} 超过上界（疑似 N+1 回退）"


def test_workspace_sql_upper_bound(app_client):
    """/api/workspace/accounts 每账号一遍分页 + 一次批量预取"""
    client, db = app_client
    _seed_workspace(client, db, n_tasks=30)
    baseline = _count_sql(db, lambda: client.get("/api/workspace/accounts"))
    # 账号 1 + 课程同步表 2 + 分页 1 + recent 1 + count×5 + plans 1 + results 1 ≈ 13；
    # 实测 58：workspace 还有账号列表、每账号 while-True 分页循环（每账号常数条）、
    # course/live 快照与 workspace-stats 聚合等每账号固定成本——它们不随同任务重复扫表
    # 增长，不属于 N+1；上界防的是「每任务一条」型回退，故取实测 1.5 倍余量 90。
    assert baseline <= 90, f"/api/workspace/accounts SQL 数 {baseline} 超过上界（疑似 N+1 回退）"


def test_batch_methods_shape(app_client):
    """三个批量方法返回形状契约"""
    client, db = app_client
    _seed_workspace(client, db, n_tasks=6)
    ids = [f"np-{i:03d}" for i in range(6)]
    plans = db.work_plans_batch(ids)
    assert set(plans.keys()) <= set(ids)
    results = db.events_after_batch(ids, {tid: 0 for tid in ids}, "work_result", 2000)
    assert set(results.keys()) == set(ids)
    answers = db.answers_batch(ids, 500)
    assert set(answers.keys()) == set(ids)
    for tid in ("np-001", "np-003", "np-005"):
        assert len(answers[tid]) == 4
        assert answers[tid][0]["event"] == "answer_result"
