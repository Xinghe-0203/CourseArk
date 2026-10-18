"""账号存储、设置、参数快照与状态机测试"""

import json
import os

import pytest

from app import accounts, control, paths, settings, task_model


# ============================================================
# 账号
# ============================================================

def test_account_crud_masks_password(sandbox):
    created = accounts.create_account("13800000000", "secret-pass", label="账号 01")
    assert created["has_password"] is True
    assert "password" not in created
    assert created["username_masked"] == "138****0000"

    listed = accounts.list_accounts()
    assert len(listed) == 1
    assert "password" not in listed[0]

    raw = accounts.get_account(created["id"], public=False)
    assert raw["password"] == "secret-pass"

    updated = accounts.update_account(created["id"], {"password": "new-pass"})
    assert "password" not in updated
    assert accounts.get_account(created["id"], public=False)["password"] == "new-pass"

    # 不提供密码时保持原值
    accounts.update_account(created["id"], {"label": "改名"})
    assert accounts.get_account(created["id"], public=False)["password"] == "new-pass"

    assert accounts.delete_account(created["id"]) is True
    assert accounts.list_accounts() == []


def test_account_rejects_duplicate_and_empty(sandbox):
    accounts.create_account("13900000000", "pwd")
    with pytest.raises(ValueError):
        accounts.create_account("13900000000", "other")
    with pytest.raises(ValueError):
        accounts.create_account("", "pwd")
    with pytest.raises(ValueError):
        accounts.create_account("13911111111", "")


def test_account_file_is_atomically_written_valid_json(sandbox):
    accounts.create_account("13700000000", "pwd", label="A")
    accounts.create_account("13700000001", "pwd", label="B")
    with open(paths.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["accounts"]) == 2
    assert not os.path.exists(paths.ACCOUNTS_FILE + ".tmp")


def test_mask_helpers():
    assert accounts.mask_username("13812345678") == "138****5678"
    assert accounts.mask_username("123") == "123"
    assert accounts.mask_password("x") == "********"
    assert accounts.mask_password("") == ""


# ============================================================
# 设置
# ============================================================

def test_settings_defaults_and_merge(sandbox):
    data = settings.load()
    assert data["scheduler"]["max_active_workers"] == 8
    assert data["defaults"]["video"]["mode"] == "hybrid"

    settings.save({"scheduler": {"max_active_workers": 15}})
    assert settings.resolve("scheduler.max_active_workers") == 15
    # 未提交的字段保持默认
    assert settings.resolve("defaults.answer.mode") == "ai"


def test_settings_clamps_out_of_range(sandbox):
    data = settings.save({
        "scheduler": {"max_active_workers": 999, "stop_grace_seconds": 1},
        "defaults": {"video": {"max_workers": 5000}, "learn_count": {"times": 0}},
        "advanced": {"max_retries": 99},
    })
    assert data["scheduler"]["max_active_workers"] == 20
    assert data["scheduler"]["stop_grace_seconds"] == 3
    assert data["defaults"]["video"]["max_workers"] == 200
    assert data["defaults"]["learn_count"]["times"] == 1
    assert data["advanced"]["max_retries"] == 10


def test_settings_rejects_invalid_enums(sandbox):
    data = settings.save({
        "defaults": {
            "video": {"mode": "warp"},
            "answer": {"mode": "psychic", "no_answer_action": "explode"},
        },
    })
    assert data["defaults"]["video"]["mode"] == "hybrid"
    assert data["defaults"]["answer"]["mode"] == "ai"
    assert data["defaults"]["answer"]["no_answer_action"] == "skip"


def test_settings_secrets_are_masked_and_kept(sandbox):
    settings.save({"llm": {"api_key": "sk-secret"}})
    masked = settings.masked()
    assert masked["llm"]["api_key"] == ""
    assert masked["secrets"]["llm_api_key_configured"] is True

    # 提交空值表示保持不变
    settings.apply_updates({"llm": {"api_key": "", "model": "deepseek-chat"}})
    assert settings.resolve("llm.api_key") == "sk-secret"


def test_tiku_settings_are_removed_on_read_and_write(sandbox):
    """v2.1 删除在线题库：旧配置里的 tiku 组与 fallback_to_tiku 不得回写"""
    data = settings.save({
        "tiku": {"enabled": True, "timeout": 15, "enncy-token": "token-x"},
        "defaults": {"answer": {"fallback_to_tiku": True, "mode": "tiku"}},
    })
    assert "tiku" not in data
    assert "fallback_to_tiku" not in data["defaults"]["answer"]
    assert data["defaults"]["answer"]["mode"] == "ai"

    masked = settings.masked()
    assert not any("tiku" in flag for flag in masked["secrets"])


# ============================================================
# 参数快照
# ============================================================

def test_params_snapshot_is_frozen_per_feature(sandbox):
    settings.save({"defaults": {"video": {"mode": "instant", "max_workers": 3}}})
    params = task_model.TaskParams.from_settings({"video": {"max_workers": 12}})
    snapshot = params.for_feature("video")
    assert snapshot["video"]["max_workers"] == 12
    assert snapshot["video"]["mode"] == "instant"
    assert "answer" not in snapshot  # 与功能无关的参数不进快照

    # 后续修改全局设置不影响已生成的快照
    settings.save({"defaults": {"video": {"mode": "real_time", "max_workers": 1}}})
    assert snapshot["video"]["mode"] == "instant"
    assert snapshot["video"]["max_workers"] == 12


def test_params_reject_out_of_range():
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate({"video": {"max_workers": 500}})
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate({"video": {"mode": "nope"}})
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate({"answer": {"submit_delay": -3}})
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate({"learn_count": {"times": 0}})


def test_feature_names_and_labels_match_design():
    assert set(task_model.FEATURES) == {
        "course_all", "chapter_exam", "independent_homework", "exam", "video",
        "learn_count", "download",
    }
    assert task_model.FEATURE_LABELS["exam"] == "独立考试"
    for key in task_model.FEATURES:
        assert task_model.FEATURE_LABELS[key]


def test_exam_url_params_in_snapshot_and_optional():
    url = ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?"
           "courseId=244694077&classId=151670988&tId=11021171&id=171477623"
           "&enc=b4acbaa84dfa579ce1c7884985a2eeee&cpi=518380181&newMooc=true")
    params = task_model.TaskParams.from_settings({"exam": {"url": url}})
    snapshot = params.for_feature("exam")
    assert snapshot["exam"]["url"] == url
    assert "selection" in snapshot

    # 不填 URL 时保持空字符串（回到「按考试列表处理」模式）
    empty = task_model.TaskParams.from_settings({}).for_feature("exam")
    assert empty["exam"]["url"] == ""


def test_exam_url_params_reject_non_answer_page():
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate({"exam": {"url": "https://example.com/x"}})
    with pytest.raises(Exception):
        task_model.TaskParams.model_validate(
            {"exam": {"url": "https://mooc1.chaoxing.com/exam/test?courseId=1"}})


def test_run_request_requires_known_feature_and_targets(sandbox):
    with pytest.raises(Exception):
        task_model.RunCreateRequest(feature="nope", targets=[{"account_id": "a", "course_id": "c"}])
    with pytest.raises(Exception):
        task_model.RunCreateRequest(feature="video", targets=[])


def test_build_tasks_expands_targets_and_validates_account(sandbox):
    account = accounts.create_account("13600000000", "pwd")
    request = task_model.RunCreateRequest(
        feature="video",
        targets=[
            {"account_id": account["id"], "course_id": "c1", "class_id": "k1", "course_name": "课程1"},
            {"account_id": account["id"], "course_id": "c2", "class_id": "k2", "course_name": "课程2"},
        ],
    )
    run_id, tasks, params = task_model.build_tasks(request)
    assert len(tasks) == 2
    assert tasks[0]["run_id"] == run_id
    assert tasks[0]["account_label"] == account["label"]
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["params"]["video"]["mode"] == "hybrid"

    with pytest.raises(ValueError):
        task_model.build_tasks(task_model.RunCreateRequest(
            feature="video", targets=[{"account_id": "ghost", "course_id": "c"}],
        ))


def test_build_tasks_rejects_disabled_account(sandbox):
    account = accounts.create_account("13600000001", "pwd", enabled=False)
    with pytest.raises(ValueError):
        task_model.build_tasks(task_model.RunCreateRequest(
            feature="video",
            targets=[{"account_id": account["id"], "course_id": "c"}],
        ))


# ============================================================
# 状态机
# ============================================================

def test_state_machine_transitions():
    assert task_model.can_transition("pending", "starting")
    assert task_model.can_transition("running", "paused")
    assert task_model.can_transition("paused", "running")
    assert task_model.can_transition("running", "succeeded")
    assert task_model.can_transition("running", "interrupted")
    assert task_model.can_transition("stopping", "stopped")

    # 终态不可再转换
    for terminal in ("succeeded", "failed", "stopped", "interrupted"):
        assert task_model.is_terminal(terminal)
        assert not task_model.can_transition(terminal, "running")
        assert task_model.TRANSITIONS[terminal] == set()


def test_active_and_terminal_sets_are_disjoint():
    assert not (task_model.ACTIVE_STATES & task_model.TERMINAL_STATES)


# ============================================================
# 控制文件
# ============================================================

def test_control_file_versions_increase(sandbox):
    first = control.write_command("task-1", control.PAUSE, reason="user")
    assert first["command"] == "pause" and first["version"] == 1
    second = control.write_command("task-1", control.RUN, reason="user")
    assert second["version"] == 2
    assert control.read_command("task-1")["command"] == "run"
    assert not os.path.exists(paths.control_path("task-1") + ".tmp")

    control.clear("task-1")
    assert control.read_command("task-1") == {}


def test_control_rejects_unknown_command(sandbox):
    with pytest.raises(ValueError):
        control.write_command("task-1", "explode")
