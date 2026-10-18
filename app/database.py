"""
WebUI SQLite 持久化

表结构：
- courses     账号课程缓存（按账号隔离）
- course_catalog 课程作业 / 考试目录缓存（TTL 由调用方控制）
- runs        批次
- tasks       子任务（含参数快照、状态、进度、统计）
- task_events 结构化事件（消息与 payload 分开存储）
- presets     参数预设
- settings_meta 数据库版本与迁移信息

所有写操作串行化（单连接 + 线程锁），配合 WAL 支持 Web 进程多线程访问。
"""

import json
import os
import sqlite3
import threading
import time

from . import paths

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    cpi TEXT DEFAULT '',
    name TEXT DEFAULT '',
    author TEXT DEFAULT '',
    if_open INTEGER DEFAULT 1,
    mission_fn INTEGER DEFAULT 0,
    mission_all INTEGER DEFAULT 0,
    raw_json TEXT DEFAULT '{}',
    synced_at REAL NOT NULL,
    UNIQUE(account_id, course_id, class_id)
);
CREATE INDEX IF NOT EXISTS idx_courses_account ON courses(account_id);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    source TEXT DEFAULT 'web',
    status TEXT DEFAULT 'pending',
    total INTEGER DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    account_id TEXT NOT NULL,
    account_label TEXT DEFAULT '',
    course_id TEXT DEFAULT '',
    class_id TEXT DEFAULT '',
    cpi TEXT DEFAULT '',
    course_name TEXT DEFAULT '',
    feature TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    params_json TEXT DEFAULT '{}',
    pid INTEGER,
    stage TEXT DEFAULT '',
    progress_json TEXT DEFAULT '{}',
    stats_json TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    account_id TEXT DEFAULT '',
    ts REAL NOT NULL,
    level TEXT DEFAULT 'info',
    event TEXT DEFAULT 'log',
    stage TEXT DEFAULT '',
    message TEXT DEFAULT '',
    payload_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON task_events(ts DESC);

CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    params_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 通知中心：需要人处理的问题，不自动消失
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'general',
    level TEXT NOT NULL DEFAULT 'warning',
    title TEXT NOT NULL,
    detail TEXT DEFAULT '',
    dedupe_key TEXT NOT NULL,
    context_json TEXT DEFAULT '{}',
    count INTEGER DEFAULT 1,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    read_at REAL
);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(read_at, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(dedupe_key);

-- 课程目录缓存：独立作业 / 独立考试的待做列表（由 worker/catalog_runner.py 拉取）
CREATE TABLE IF NOT EXISTS course_catalog (
    account_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    items_json TEXT DEFAULT '[]',
    fetched_at REAL NOT NULL,
    PRIMARY KEY (account_id, course_id, kind)
);
"""

# 非终态：WebUI 重启后需要标记为 interrupted
ACTIVE_STATUSES = (
    "pending", "starting", "logging_in", "loading_courses", "running",
    "pausing", "paused", "stopping",
)
TERMINAL_STATUSES = ("succeeded", "failed", "stopped", "interrupted")


class Database:
    def __init__(self, path: str = None):
        self.path = path or paths.DATABASE_FILE
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO settings_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    # --------------------------------------------------------
    # 低层封装
    # --------------------------------------------------------

    def _execute(self, sql: str, params=()):
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def _query(self, sql: str, params=()) -> list:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def _query_one(self, sql: str, params=()):
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # --------------------------------------------------------
    # 课程缓存
    # --------------------------------------------------------

    def replace_courses(self, account_id: str, courses: list):
        """整体替换某账号的课程缓存，保证同名课程按账号隔离"""
        now = time.time()
        with self._lock:
            self._conn.execute("DELETE FROM courses WHERE account_id = ?", (account_id,))
            for course in courses:
                self._conn.execute(
                    """INSERT INTO courses
                       (account_id, course_id, class_id, cpi, name, author, if_open,
                        mission_fn, mission_all, raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        account_id,
                        str(course.get("course_id", "")),
                        str(course.get("class_id", "")),
                        str(course.get("cpi", "")),
                        course.get("name", ""),
                        course.get("author", ""),
                        1 if course.get("if_open", True) else 0,
                        int(course.get("mission_fn", 0) or 0),
                        int(course.get("mission_all", 0) or 0),
                        json.dumps(course, ensure_ascii=False),
                        now,
                    ),
                )
            self._conn.commit()

    def list_courses(self, account_id: str) -> list:
        return self._query(
            "SELECT * FROM courses WHERE account_id = ? ORDER BY name", (account_id,)
        )

    def get_course(self, account_id: str, course_id: str, class_id: str = "") -> dict:
        if class_id:
            row = self._query_one(
                "SELECT * FROM courses WHERE account_id = ? AND course_id = ? AND class_id = ?",
                (account_id, course_id, class_id),
            )
        else:
            row = self._query_one(
                "SELECT * FROM courses WHERE account_id = ? AND course_id = ? LIMIT 1",
                (account_id, course_id),
            )
        return row

    # --------------------------------------------------------
    # 课程目录缓存（作业 / 考试列表）
    # --------------------------------------------------------

    def get_catalog(self, account_id: str, course_id: str, kind: str) -> dict:
        row = self._query_one(
            "SELECT * FROM course_catalog WHERE account_id = ? AND course_id = ? AND kind = ?",
            (account_id, course_id, kind),
        )
        if not row:
            return None
        try:
            items = json.loads(row.get("items_json") or "[]")
        except ValueError:
            items = []
        if not isinstance(items, list):
            items = []
        return {"account_id": row["account_id"], "course_id": row["course_id"],
                "kind": row["kind"], "items": items, "fetched_at": row["fetched_at"]}

    def save_catalog(self, account_id: str, course_id: str, kind: str, items: list,
                     fetched_at: float = None) -> dict:
        self._execute(
            """INSERT OR REPLACE INTO course_catalog(account_id, course_id, kind, items_json, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, course_id, kind,
             json.dumps(items or [], ensure_ascii=False),
             float(fetched_at if fetched_at is not None else time.time())),
        )
        return self.get_catalog(account_id, course_id, kind)

    def delete_catalog(self, account_id: str, course_id: str = "", kind: str = "") -> int:
        clauses = ["account_id = ?"]
        params = [account_id]
        if course_id:
            clauses.append("course_id = ?")
            params.append(course_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        cursor = self._execute(
            f"DELETE FROM course_catalog WHERE {' AND '.join(clauses)}", tuple(params))
        return int(cursor.rowcount or 0)

    # --------------------------------------------------------
    # 批次
    # --------------------------------------------------------

    def create_run(self, run_id: str, total: int, source: str = "web", note: str = "") -> dict:
        self._execute(
            "INSERT INTO runs(id, created_at, source, status, total, note) VALUES(?, ?, ?, 'running', ?, ?)",
            (run_id, time.time(), source, total, note),
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str):
        return self._query_one("SELECT * FROM runs WHERE id = ?", (run_id,))

    def list_runs(self, limit: int = 50, offset: int = 0) -> list:
        return self._query(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        )

    def refresh_run_status(self, run_id: str):
        """根据子任务状态汇总批次状态"""
        rows = self._query("SELECT status, COUNT(*) AS c FROM tasks WHERE run_id = ? GROUP BY status", (run_id,))
        counts = {row["status"]: row["c"] for row in rows}
        if not counts:
            return
        active = sum(counts.get(status, 0) for status in ACTIVE_STATUSES)
        if active:
            status = "running"
        elif counts.get("failed", 0) and (counts.get("failed", 0) == sum(counts.values())):
            status = "failed"
        elif counts.get("failed", 0) or counts.get("interrupted", 0):
            status = "partial"
        elif counts.get("stopped", 0) and not counts.get("succeeded", 0):
            status = "stopped"
        else:
            status = "succeeded"
        self._execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    # --------------------------------------------------------
    # 任务
    # --------------------------------------------------------

    def create_task(self, task: dict):
        self._execute(
            """INSERT INTO tasks
               (id, run_id, account_id, account_label, course_id, class_id, cpi, course_name,
                feature, status, params_json, progress_json, stats_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task["id"],
                task.get("run_id"),
                task["account_id"],
                task.get("account_label", ""),
                task.get("course_id", ""),
                task.get("class_id", ""),
                task.get("cpi", ""),
                task.get("course_name", ""),
                task["feature"],
                task.get("status", "pending"),
                json.dumps(task.get("params", {}), ensure_ascii=False),
                json.dumps(task.get("progress", {}), ensure_ascii=False),
                json.dumps(task.get("stats", {}), ensure_ascii=False),
                task.get("created_at", time.time()),
            ),
        )
        return self.get_task(task["id"])

    def get_task(self, task_id: str):
        return self._query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def update_task(self, task_id: str, **fields):
        if not fields:
            return
        allowed = {
            "status", "stage", "pid", "progress_json", "stats_json", "error",
            "started_at", "finished_at", "account_label", "course_name",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*updates.values(), task_id))

    def set_task_status(self, task_id: str, status: str, error: str = None,
                        finished: bool = False):
        fields = {"status": status}
        if error is not None:
            fields["error"] = error
        if finished:
            fields["finished_at"] = time.time()
        if status in ("running", "logging_in", "loading_courses", "starting"):
            row = self.get_task(task_id)
            if row and not row.get("started_at"):
                fields["started_at"] = time.time()
        self.update_task(task_id, **fields)

    @staticmethod
    def _task_filter_clause(filters: dict) -> tuple:
        """构造任务过滤条件，list 与 count 共用，避免总数与列表口径不一致"""
        filters = filters or {}
        clauses, params = [], []
        if filters.get("status"):
            statuses = filters["status"]
            if isinstance(statuses, str):
                statuses = [s for s in statuses.split(",") if s]
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                clauses.append(f"status IN ({placeholders})")
                params.extend(statuses)
        if filters.get('feature'):
            feature_values = [v for v in str(filters['feature']).split(',') if v]
            clauses.append('feature IN (' + ','.join('?' for _ in feature_values) + ')')
            params.extend(feature_values)
        for field in ("account_id", "run_id", "course_id"):
            if filters.get(field):
                clauses.append(f"{field} = ?")
                params.append(filters[field])
        if filters.get("since"):
            clauses.append("created_at >= ?")
            params.append(float(filters["since"]))
        if filters.get("until"):
            clauses.append("created_at <= ?")
            params.append(float(filters["until"]))
        if filters.get("q"):
            clauses.append("(course_name LIKE ? OR account_label LIKE ?)")
            like = f"%{filters['q']}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def list_tasks(self, filters: dict = None, limit: int = 100, offset: int = 0) -> list:
        where, params = self._task_filter_clause(filters)
        params.extend([limit, offset])
        return self._query(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", tuple(params)
        )

    def count_tasks(self, filters: dict = None) -> int:
        where, params = self._task_filter_clause(filters)
        row = self._query_one(f"SELECT COUNT(*) AS c FROM tasks {where}", tuple(params))
        return int(row["c"]) if row else 0

    def active_task_ids(self) -> list:
        rows = self._query("SELECT id FROM tasks WHERE status IN (%s)" % ",".join(
            "?" for _ in ACTIVE_STATUSES), ACTIVE_STATUSES)
        return [row["id"] for row in rows]

    def pending_tasks(self, limit: int = 50) -> list:
        return self._query(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )

    def count_active(self) -> int:
        row = self._query_one(
            "SELECT COUNT(*) AS c FROM tasks WHERE status IN (%s)"
            % ",".join("?" for _ in ACTIVE_STATUSES if _ != "pending"),
            tuple(status for status in ACTIVE_STATUSES if status != "pending"),
        )
        return int(row["c"]) if row else 0

    # --------------------------------------------------------
    # 事件
    # --------------------------------------------------------

    def add_event(self, task_id: str, account_id: str, event: str, message: str,
                  level: str = "info", stage: str = "", payload: dict = None,
                  ts: float = None) -> int:
        cursor = self._execute(
            """INSERT INTO task_events(task_id, account_id, ts, level, event, stage, message, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                account_id or "",
                ts if ts is not None else time.time(),
                level or "info",
                event or "log",
                stage or "",
                message or "",
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        return cursor.lastrowid

    def list_events(self, task_id: str, after_id: int = 0, limit: int = 200,
                    level: str = None, event: str = None, latest: bool = False,
                    business: bool = False) -> list:
        clauses = ["task_id = ?", "id > ?"]
        params = [task_id, int(after_id or 0)]
        if level and level != "all":
            if level == "problem":
                clauses.append("level IN ('warning', 'error')")
            else:
                clauses.append("level = ?")
                params.append(level)
        if event and event != "all":
            clauses.append("event = ?")
            params.append(event)
        if business:
            # 独立读取业务动态，频繁播放上报与 DEBUG 日志不会挤掉处理结果。
            clauses.append("(event NOT IN ('log', 'task_progress', 'work_progress', 'media_progress', 'worker_exit') "
                           "OR (event = 'log' AND level IN ('warning', 'error')))" )
        params.append(int(limit))
        order = "DESC" if latest else "ASC"
        rows = self._query(
            f"SELECT * FROM task_events WHERE {' AND '.join(clauses)} ORDER BY id {order} LIMIT ?",
            tuple(params),
        )
        return list(reversed(rows)) if latest else rows

    def recent_events(self, limit: int = 100) -> list:
        return self._query(
            "SELECT * FROM task_events ORDER BY id DESC LIMIT ?", (int(limit),)
        )

    def events_after(self, last_id: int, limit: int = 500) -> list:
        return self._query(
            "SELECT * FROM task_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(last_id or 0), int(limit)),
        )

    # --------------------------------------------------------
    # 通知中心
    # --------------------------------------------------------

    def repair_notification_labels(self, classify):
        """修正历史通用告警分类，保留原始内容、次数、时间和处理状态。"""
        updates = []
        for row in self._query("SELECT id, detail, level, context_json FROM notifications WHERE category = 'general'"):
            try:
                context = json.loads(row['context_json'] or '{}')
            except (TypeError, ValueError):
                context = {}
            category_title = classify('log', row['level'], row['detail'], context.get('stage', 'log'))
            if category_title and category_title[0] != 'general':
                updates.append((*category_title[:2], row['id']))
        if updates:
            with self._lock:
                self._conn.executemany("UPDATE notifications SET category = ?, title = ? WHERE id = ? AND category = 'general'", updates)
                self._conn.commit()
        return len(updates)

    def upsert_notification(self, *, category: str, title: str, detail: str, level: str,
                            dedupe_key: str, context: dict = None) -> dict:
        """
        按去重键累积通知：同一问题重复出现只累加次数与最近时间，
        这样“反爬虫反复触发”不会把列表刷爆。
        """
        now = time.time()
        existing = self._query_one(
            "SELECT id, count FROM notifications WHERE dedupe_key = ?", (dedupe_key,)
        )
        if existing:
            self._execute(
                """UPDATE notifications
                   SET count = count + 1, last_seen = ?, detail = ?, level = ?,
                       context_json = ?, read_at = NULL
                   WHERE id = ?""",
                (now, detail, level, json.dumps(context or {}, ensure_ascii=False),
                 existing["id"]),
            )
            return self._query_one("SELECT * FROM notifications WHERE id = ?", (existing["id"],))

        self._execute(
            """INSERT INTO notifications
               (category, level, title, detail, dedupe_key, context_json, count,
                first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (category, level, title, detail, dedupe_key,
             json.dumps(context or {}, ensure_ascii=False), now, now),
        )
        return self._query_one(
            "SELECT * FROM notifications WHERE dedupe_key = ? ORDER BY id DESC LIMIT 1",
            (dedupe_key,),
        )

    def list_notifications(self, include_read: bool = False, limit: int = 200, offset: int = 0, category: str = '') -> list:
        clauses, params = [], []
        if not include_read:
            clauses.append('read_at IS NULL')
        if category:
            clauses.append('category = ?')
            params.append(category)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        return self._query(
            f"SELECT * FROM notifications {where} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        )

    def count_notifications(self, unread_only: bool = False, category: str = '') -> int:
        clauses, params = [], []
        if unread_only:
            clauses.append('read_at IS NULL')
        if category:
            clauses.append('category = ?')
            params.append(category)
        sql = 'SELECT COUNT(*) AS c FROM notifications' + (' WHERE '+ ' AND '.join(clauses) if clauses else '')
        row = self._query_one(sql, tuple(params))
        return int(row["c"]) if row else 0

    def notification_counts_by_level(self) -> dict:
        rows = self._query(
            "SELECT level, COUNT(*) AS c FROM notifications WHERE read_at IS NULL GROUP BY level"
        )
        return {row["level"]: row["c"] for row in rows}

    def mark_notifications_read(self, notification_id: int = None, category: str = "") -> int:
        now = time.time()
        if notification_id:
            cursor = self._execute(
                "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (now, int(notification_id)),
            )
        elif category:
            cursor = self._execute(
                "UPDATE notifications SET read_at = ? WHERE category = ? AND read_at IS NULL",
                (now, category),
            )
        else:
            cursor = self._execute(
                "UPDATE notifications SET read_at = ? WHERE read_at IS NULL", (now,)
            )
        return cursor.rowcount or 0

    def clear_notifications(self, only_read: bool = True) -> int:
        sql = ("DELETE FROM notifications WHERE read_at IS NOT NULL"
               if only_read else "DELETE FROM notifications")
        cursor = self._execute(sql)
        return cursor.rowcount or 0

    # --------------------------------------------------------
    # 预设
    # --------------------------------------------------------

    def list_presets(self) -> list:
        return self._query("SELECT * FROM presets ORDER BY updated_at DESC")

    def upsert_preset(self, preset_id: str, name: str, params: dict) -> dict:
        now = time.time()
        existing = self._query_one("SELECT id FROM presets WHERE id = ?", (preset_id,))
        if existing:
            self._execute(
                "UPDATE presets SET name = ?, params_json = ?, updated_at = ? WHERE id = ?",
                (name, json.dumps(params, ensure_ascii=False), now, preset_id),
            )
        else:
            self._execute(
                "INSERT INTO presets(id, name, params_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
                (preset_id, name, json.dumps(params, ensure_ascii=False), now, now),
            )
        return self._query_one("SELECT * FROM presets WHERE id = ?", (preset_id,))

    def delete_preset(self, preset_id: str) -> bool:
        cursor = self._execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        return cursor.rowcount > 0

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    def dashboard_stats(self, since: float) -> dict:
        """今日统计：任务点成功/失败、答题数、来源命中、提交结果"""
        rows = self._query(
            "SELECT stats_json FROM tasks WHERE created_at >= ? AND status IN ('succeeded','failed','stopped','running','paused')",
            (since,),
        )
        totals = {
            "success": 0, "failed": 0, "skipped": 0, "already_done": 0,
            "questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
            "random_answers": 0, "submit_ok": 0, "submit_fail": 0,
            "download_ok": 0, "download_fail": 0,
        }
        for row in rows:
            try:
                stats = json.loads(row["stats_json"] or "{}")
            except ValueError:
                continue
            for key in totals:
                totals[key] += int(stats.get(key, 0) or 0)
        return totals
