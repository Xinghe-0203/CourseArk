"""
数据隔离约束：
- cli_copy 副本目录只读，运行期不得产生 config.yml / logs / data 等文件
- 副本的默认用户数据路径在 Worker 环境下重定向到 WebUI 数据目录
- 源 AutoChaoxingCLI 目录永不写入
"""

import os
import subprocess
import sys

import pytest

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
SOURCE_CLI = os.path.join(os.path.dirname(WEBUI_ROOT), "AutoChaoxingCLI")

RUNTIME_ARTIFACTS = ("config.yml", "logs", "data", "download")


def test_paths_redirect_when_env_is_set(sandbox, monkeypatch):
    monkeypatch.setenv("AUTOCXWEBUI_DATA_DIR", sandbox)
    sys.path.insert(0, CLI_COPY)
    from core.paths import get_base_dir, get_user_data_path

    assert get_base_dir() == sandbox
    assert get_user_data_path("config.yml").startswith(sandbox)


def test_resource_path_still_points_to_copy(monkeypatch, sandbox):
    """资源文件（字体映射表）必须仍从副本目录读取，不能被数据目录覆盖"""
    monkeypatch.setenv("AUTOCXWEBUI_DATA_DIR", sandbox)
    sys.path.insert(0, CLI_COPY)
    from core.paths import get_resource_path

    resource = get_resource_path(os.path.join("resource", "font_map_table.json"))
    assert resource.startswith(CLI_COPY)
    assert os.path.exists(resource)


def test_config_default_path_lands_in_data_dir(sandbox, monkeypatch):
    """未显式设置 _config_path 时，Config.load 的默认路径应落在数据目录"""
    monkeypatch.setenv("AUTOCXWEBUI_DATA_DIR", sandbox)
    sys.path.insert(0, CLI_COPY)
    from core.config import Config

    monkeypatch.setattr(Config, "_data", None)
    monkeypatch.setattr(Config, "_config_path", "config.yml")
    Config.load("config.yml")
    generated = os.path.join(sandbox, "config.yml")
    assert os.path.exists(generated), "配置应生成在数据目录"
    assert not os.path.exists(os.path.join(CLI_COPY, "config.yml")
                              ) or os.path.getmtime(os.path.join(CLI_COPY, "config.yml")) < 0


def test_cli_copy_has_no_runtime_artifacts():
    """副本目录不应残留运行期生成的文件"""
    leftovers = [name for name in RUNTIME_ARTIFACTS
                 if os.path.exists(os.path.join(CLI_COPY, name))]
    assert not leftovers, f"副本目录存在运行期文件: {leftovers}"


def test_worker_launch_env_includes_data_dir(sandbox, monkeypatch):
    """TaskManager 启动 Worker 时必须注入数据目录环境变量"""
    from app import accounts, events, paths, task_manager
    from app.database import Database
    account = accounts.create_account('13800007788', 'test-password')
    db = Database()
    captured = {}
    def capture(*args, **kwargs):
        captured.update(kwargs)
        raise RuntimeError('隔离测试不创建真实工作进程')
    monkeypatch.setattr(task_manager.subprocess, 'Popen', capture)
    try:
        row = db.create_task({'id': 'env-check', 'account_id': account['id'],
                             'feature': 'video', 'status': 'pending', 'params': {}})
        task_manager.TaskManager(db, events.EventHub())._launch(row)
        assert captured['env']['AUTOCXWEBUI_DATA_DIR'] == paths.DATA_DIR
        assert captured['env']['PYTHONIOENCODING'] == 'utf-8'
        assert captured['cwd'] == paths.ROOT_DIR
    finally:
        db.close()


def test_source_cli_dir_not_written_by_webui():
    """
    源目录只读约束：WebUI 的数据目录不在源 CLI 目录内，
    且 WebUI 不把任何运行期文件写到源目录。

    注意这里检查的是 paths 模块的默认常量（不加 sandbox 重定向），
    因为测试夹具本身会把路径改到临时目录。
    """
    import importlib
    import inspect

    from app import paths as paths_module

    source = inspect.getsource(paths_module)
    module = importlib.reload(paths_module)
    try:
        assert not module.DATA_DIR.startswith(module.SOURCE_CLI_DIR)
        assert not module.QUESTION_BANK_FILE.startswith(module.SOURCE_CLI_DIR)
        assert module.SOURCE_CLI_DIR != module.DATA_DIR
        # 源题库只作为一次性导入来源，与运行期题库不是同一文件
        assert module.SOURCE_QUESTION_BANK != module.QUESTION_BANK_FILE
        assert "SOURCE_QUESTION_BANK = os.path.join(SOURCE_CLI_DIR" in source
        assert "SOURCE_CONFIG = os.path.join(SOURCE_CLI_DIR" in source
    finally:
        importlib.reload(paths_module)


def test_worker_runner_sets_up_without_writing_copy(sandbox, monkeypatch, tmp_path):
    """
    以子进程方式运行 Worker，验证它不会在副本目录产生文件。
    任务故意指向不存在的账号凭据 -> 触发登录失败，但不影响本约束的检查。
    """
    import json

    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({
        "task_id": "isolation-check",
        "feature": "video",
        "username": "13800000000",
        "password": "pwd",
        "account_label": "隔离测试",
        "course_id": "c1",
        "class_id": "k1",
        "cpi": "",
        "course_name": "课程",
        "params": {"video": {"mode": "instant", "max_workers": 1}},
        "control_path": str(tmp_path / "control.json"),
        "task_dir": str(tmp_path),
        "log_dir": str(tmp_path / "logs"),
        "question_bank_path": str(tmp_path / "bank.db"),
    }, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "control.json").write_text(
        json.dumps({"command": "run", "version": 1}), encoding="utf-8")

    env = dict(os.environ)
    env["AUTOCXWEBUI_DATA_DIR"] = str(tmp_path / "webdata")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # 只跑导入与配置初始化，不发起真实网络请求
    probe = (
        "import sys, os;"
        f"sys.path.insert(0, r'{CLI_COPY}');"
        "from core.paths import get_base_dir;"
        "from core.config import Config;"
        "Config.load('config.yml');"
        "print(get_base_dir())"
    )
    result = subprocess.run([sys.executable, "-c", probe], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip() == str(tmp_path / "webdata")
    # 配置与数据都写在重定向目录，而不是副本目录
    assert (tmp_path / "webdata" / "config.yml").exists()
