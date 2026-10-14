"""测试夹具：把数据目录指向临时目录，避免污染真实 data/"""

import os
import shutil
import sys
import tempfile

import pytest

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WEBUI_ROOT not in sys.path:
    sys.path.insert(0, WEBUI_ROOT)
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
if CLI_COPY not in sys.path:
    sys.path.insert(0, CLI_COPY)


@pytest.fixture()
def sandbox(monkeypatch):
    """隔离的 WebUI 数据目录"""
    tmp = tempfile.mkdtemp(prefix="autocxwebui-test-")
    from app import paths

    for name, value in {
        "DATA_DIR": os.path.join(tmp, "data"),
        "CONTROL_DIR": os.path.join(tmp, "data", "control"),
        "TASK_DIR": os.path.join(tmp, "data", "tasks"),
        "LOG_DIR": os.path.join(tmp, "data", "logs"),
        "EXPORT_DIR": os.path.join(tmp, "data", "exports"),
        "DOWNLOAD_DIR": os.path.join(tmp, "data", "downloads"),
        "ACCOUNTS_FILE": os.path.join(tmp, "data", "accounts.json"),
        "SETTINGS_FILE": os.path.join(tmp, "data", "settings.json"),
        "SETTINGS_BACKUP_FILE": os.path.join(tmp, "data", "settings.backup.json"),
        "DATABASE_FILE": os.path.join(tmp, "data", "webui.db"),
        "QUESTION_BANK_FILE": os.path.join(tmp, "data", "question_bank.db"),
        "SOURCE_QUESTION_BANK": os.path.join(tmp, "nonexistent-source.db"),
        "SOURCE_CONFIG": os.path.join(tmp, "nonexistent-config.yml"),
    }.items():
        monkeypatch.setattr(paths, name, value)
    paths.ensure_dirs()

    # 重置设置缓存与存储单例：它们绑定的是上一个测试的数据库文件，
    # 不重置会让后续测试继续读写已删除的临时库（表现为 SQLite 报错）
    from app import settings as settings_module

    def _reset_settings():
        if getattr(settings_module, "_storage", None) is not None:
            try:
                settings_module._storage.close()
            except Exception:
                pass
        settings_module._cache = None
        settings_module._storage = None

    _reset_settings()
    monkeypatch.setattr(settings_module, "paths", paths)

    from app import question_bank_manager as bank_module
    monkeypatch.setattr(bank_module, "paths", paths)

    # 会话服务持有数据库连接，同样需要按测试隔离
    from app import session_service as session_module
    monkeypatch.setattr(session_module, "paths", paths)

    # main 的惰性资源必须整体重建：上轮实例可能绑定在已删除的临时数据库上。
    # 直接重新构造 _Lazy 而不是调 reset()，因为测试可能已把属性替换成真实实例。
    from app import main as main_module

    def _rebuild_resources():
        closeables = [main_module.db, main_module.hub,
                      main_module.manager, main_module.sessions]
        for item in closeables:
            instance = getattr(item, "_instance", None)
            if instance is not None and hasattr(instance, "close"):
                try:
                    instance.close()
                except Exception:
                    pass
        main_module.db = main_module._Lazy(main_module.Database, "db")
        main_module.hub = main_module._Lazy(main_module.events.EventHub, "hub")
        main_module.manager = main_module._Lazy(
            lambda: main_module.TaskManager(main_module.db, main_module.hub), "manager")
        main_module.sessions = main_module._Lazy(
            main_module.session_service.SessionService, "sessions")

    _rebuild_resources()

    yield tmp
    _rebuild_resources()
    _reset_settings()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def app_client(sandbox):
    """独立的应用实例（每个测试一个数据库与数据目录）"""
    from fastapi.testclient import TestClient

    from app import events, main as main_module
    from app.database import Database
    from app.task_manager import TaskManager

    db = Database()
    hub = events.EventHub()
    manager = TaskManager(db, hub)
    main_module.db = db
    main_module.hub = hub
    main_module.manager = manager
    client = TestClient(main_module.create_app())
    with client:
        yield client
    db.close()
