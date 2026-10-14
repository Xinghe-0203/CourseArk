"""
SQLite 键值存储

WebUI 的配置类数据（全局设置、界面偏好等）统一保存在 webui.db 的 app_settings 表里，
不再依赖独立的 JSON 文件。相比 JSON 文件的好处：
- 与任务数据同一事务边界，不会出现“配置写一半”的中间状态
- 并发读写由 SQLite 的锁与 WAL 保证
- 迁移与备份只需要处理一个数据库文件

仍然保留 JSON 导入/导出能力，方便人工查看与迁移。
"""

import json
import os
import sqlite3
import threading
import time

from . import paths

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
)
"""

_busy_timeout_ms = 30000


def connect(db_path: str = None) -> sqlite3.Connection:
    """
    打开 WebUI 数据库连接（统一 busy_timeout / WAL 设置）

    check_same_thread=False：FastAPI 会在工作线程里处理请求，
    而连接可能在主线程创建，必须允许跨线程使用（访问由调用方的锁串行化）。
    """
    path = db_path or paths.DATABASE_FILE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=_busy_timeout_ms / 1000.0,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # busy_timeout 必须先于 WAL 切换设置，否则并发初始化会直接抛 SQLITE_BUSY
    conn.execute(f"PRAGMA busy_timeout={_busy_timeout_ms}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(TABLE_SQL)
    conn.commit()
    return conn


class SettingsStore:
    """键值存储：所有值以 JSON 文本保存"""

    def __init__(self, db_path: str = None):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = connect(db_path)

    def close(self):
        with self._lock:
            self._conn.close()

    def get(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set(self, key: str, value):
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES(?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                                  updated_at = excluded.updated_at""",
                (key, payload, time.time()),
            )
            self._conn.commit()

    def has(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row is not None

    def keys(self) -> list:
        with self._lock:
            return [row["key"] for row in
                    self._conn.execute("SELECT key FROM app_settings ORDER BY key")]
