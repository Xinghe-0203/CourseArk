"""Electron runtime data paths must stay outside read-only packaged resources."""

import io
import json
import os
import subprocess
import sys

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_data_root_uses_environment(tmp_path):
    data_dir = tmp_path / "user-data"
    source_dir = tmp_path / "source-cli"
    env = dict(
        os.environ,
        AUTOCXWEBUI_DATA_DIR=str(data_dir),
        AUTOCXWEBUI_SOURCE_CLI_DIR=str(source_dir),
    )
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json; from app import paths; "
            "print(json.dumps([paths.DATA_DIR, paths.DATABASE_FILE, paths.SOURCE_CLI_DIR]))"
        )], cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )

    assert json.loads(result.stdout) == [
        str(data_dir), str(data_dir / "webui.db"), str(source_dir),
    ]


def test_data_root_defaults_to_repository_data():
    env = dict(os.environ)
    env.pop("AUTOCXWEBUI_DATA_DIR", None)
    env.pop("AUTOCXWEBUI_SOURCE_CLI_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json; from app import paths; "
            "print(json.dumps([paths.ROOT_DIR, paths.DATA_DIR]))"
        )], cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )

    assert json.loads(result.stdout) == [ROOT, os.path.join(ROOT, "data")]


def test_relative_download_paths_are_under_data_root(monkeypatch, tmp_path):
    from app import paths

    data_dir = tmp_path / "user-data"
    monkeypatch.setattr(paths, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(paths, "DOWNLOAD_DIR", str(data_dir / "downloads"))

    assert paths.resolve_download_path("data/downloads") == str(data_dir / "downloads")
    assert paths.resolve_download_path("data/downloads/course") == str(
        data_dir / "downloads" / "course"
    )
    assert paths.resolve_download_path("exports/course") == str(data_dir / "exports" / "course")
    assert paths.resolve_download_path(str(tmp_path / "external")) == str(tmp_path / "external")
    with pytest.raises(ValueError, match="数据目录"):
        paths.resolve_download_path("../outside")
    with pytest.raises(ValueError, match="数据目录"):
        paths.resolve_download_path("data/../../outside")


def test_task_manager_payload_uses_configured_data_paths(app_client, sandbox):
    from app import accounts, main as main_module, paths

    account = app_client.post("/api/accounts", json={
        "username": "13800000001", "password": "secret",
    }).json()
    private_account = accounts.get_account(account["id"], public=False)
    payload = main_module.manager._build_task_file(
        {
            "id": "task-path-test",
            "account_id": account["id"],
            "feature": "course_all",
            "params_json": "{}",
        },
        private_account,
    )

    assert payload["task_dir"] == paths.TASK_DIR
    assert payload["log_dir"] == paths.LOG_DIR
    assert payload["question_bank_path"] == paths.QUESTION_BANK_FILE


def test_task_manager_launches_worker_with_active_python(app_client, sandbox, monkeypatch):
    from app import accounts, main as main_module, paths, task_manager

    account = accounts.create_account("13800000003", "secret")
    row = main_module.manager.db.create_task({
        "id": "desktop-python-check",
        "account_id": account["id"],
        "feature": "course_all",
        "status": "running",
        "params": {},
    })
    captured = {}

    def capture(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise RuntimeError("test does not start a real Worker")

    monkeypatch.setattr(task_manager.subprocess, "Popen", capture)
    main_module.manager._launch_pending(row)

    assert captured["args"][:2] == [sys.executable, paths.WORKER_RUNNER]


class _CompletedProcess:
    def __init__(self, output=b""):
        self.stdout = io.BytesIO(output)
        self.pid = 12345

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass


def test_sync_and_session_jobs_pass_task_directory(app_client, sandbox, monkeypatch):
    from app import main as main_module, paths
    from app import session_service, sync_service

    account = app_client.post("/api/accounts", json={
        "username": "13800000002", "password": "secret",
    }).json()
    captured = []

    def capture_sync(args, **kwargs):
        with open(args[-1], encoding="utf-8") as handle:
            captured.append(("sync", args, json.load(handle)))
        return _CompletedProcess()

    monkeypatch.setattr(sync_service.subprocess, "Popen", capture_sync)
    db = main_module.manager.db
    hub = main_module.hub
    sync_service.sync_account(db, hub, account["id"], blocking=True)

    session_output = json.dumps({
        "event": "session_result",
        "payload": {
            "cookies": [{"name": "sid", "value": "cookie", "domain": ".chaoxing.com"}],
            "display_name": "Test",
            "uid": "1",
        },
    }).encode("utf-8") + b"\n"

    def capture_session(args, **kwargs):
        with open(args[-1], encoding="utf-8") as handle:
            captured.append(("session", args, json.load(handle)))
        return _CompletedProcess(session_output)

    monkeypatch.setattr(session_service.subprocess, "Popen", capture_session)
    service = session_service.SessionService()
    service.fetch(account["id"], blocking=True)

    assert [name for name, _, _ in captured] == ["sync", "session"]
    assert all(args[0] == sys.executable for _, args, _ in captured)
    assert all(job["task_dir"] == paths.TASK_DIR for _, _, job in captured)
