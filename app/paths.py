"""
WebUI 路径管理

所有运行期数据都落在 WebUI 自己的 data 目录下，
AutoChaoxingCLI 源目录只读，不作为运行时可写目录。
"""

import os

# WebUI 根目录（app/ 的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 源 CLI 目录（只读，仅用于首次导入题库和配置）
SOURCE_CLI_DIR = os.path.abspath(os.environ.get(
    "AUTOCXWEBUI_SOURCE_CLI_DIR",
    os.path.join(os.path.dirname(ROOT_DIR), "AutoChaoxingCLI"),
))

DATA_DIR = os.path.abspath(os.environ.get(
    "AUTOCXWEBUI_DATA_DIR", os.path.join(ROOT_DIR, "data"),
))
CONTROL_DIR = os.path.join(DATA_DIR, "control")
TASK_DIR = os.path.join(DATA_DIR, "tasks")
LOG_DIR = os.path.join(DATA_DIR, "logs")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")

ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
# 历史配置文件：仅作为一次性迁移来源
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
# 设置以 SQLite 为主存储，这里保留一份 JSON 备份便于人工查看
SETTINGS_BACKUP_FILE = os.path.join(DATA_DIR, "settings.backup.json")
DATABASE_FILE = os.path.join(DATA_DIR, "webui.db")
QUESTION_BANK_FILE = os.path.join(DATA_DIR, "question_bank.db")

CLI_COPY_DIR = os.path.join(ROOT_DIR, "cli_copy")
WORKER_RUNNER = os.path.join(ROOT_DIR, "worker", "runner.py")
STATIC_DIR = os.path.join(ROOT_DIR, "webui_static")

SOURCE_QUESTION_BANK = os.path.join(SOURCE_CLI_DIR, "data", "question_bank.db")
SOURCE_CONFIG = os.path.join(SOURCE_CLI_DIR, "config.yml")


def ensure_dirs():
    """创建所有运行期目录"""
    for path in (DATA_DIR, CONTROL_DIR, TASK_DIR, LOG_DIR, EXPORT_DIR, DOWNLOAD_DIR):
        os.makedirs(path, exist_ok=True)


def control_path(task_id: str) -> str:
    return os.path.join(CONTROL_DIR, f"{task_id}.json")


def task_file_path(task_id: str) -> str:
    return os.path.join(TASK_DIR, f"{task_id}.json")


def resolve_download_path(value: str | None = None) -> str:
    """Resolve download destinations without writing into packaged app resources."""
    if value is None or not str(value).strip():
        return DOWNLOAD_DIR
    value = os.path.expanduser(str(value).strip())
    if os.path.isabs(value):
        return os.path.normpath(value)
    parts = os.path.normpath(value).replace("\\", "/").split("/")
    if parts[0].casefold() == "data":
        parts = parts[1:]
    if not parts:
        return DATA_DIR
    root = os.path.abspath(DATA_DIR)
    target = os.path.abspath(os.path.join(root, *parts))
    try:
        common = os.path.commonpath((root, target))
    except ValueError as exc:
        raise ValueError("相对下载路径必须位于数据目录内") from exc
    if os.path.normcase(common) != os.path.normcase(root):
        raise ValueError("相对下载路径必须位于数据目录内")
    return target
