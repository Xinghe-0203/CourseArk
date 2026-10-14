"""
AutoChaoxingCLI - 本地题库缓存模块 (SQLite)

提供题目缓存功能：
1. 缓存已回答过的题目及其答案
2. 重复题目直接从缓存获取
3. 记录命中次数

线程安全：使用threading.Lock确保并发访问安全。
"""

import hashlib
import json
import os
import sqlite3
import threading
import time

from loguru import logger

from core.paths import get_user_data_path

# 多个 Worker 进程共享同一题库文件，写锁冲突时等待重试
BUSY_TIMEOUT_SECONDS = 30.0
WRITE_RETRY_TIMES = 5
WRITE_RETRY_DELAY = 0.4


class QuestionBank:
    """
    题库缓存管理器

    基于SQLite存储，使用WAL日志模式提高并发性能。

    Attributes:
        _lock (threading.Lock): 线程锁
        _conn (sqlite3.Connection): 数据库连接
    """

    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = get_user_data_path("data/question_bank.db")
        elif not os.path.isabs(db_path):
            db_path = get_user_data_path(db_path)
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=BUSY_TIMEOUT_SECONDS)
        # busy_timeout 必须先设置，否则并发的 WAL 切换/建表会在锁冲突时直接抛 SQLITE_BUSY
        self._conn.execute("PRAGMA busy_timeout=%d" % int(BUSY_TIMEOUT_SECONDS * 1000))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构（多个进程可能同时建表，需容错）"""
        for attempt in range(WRITE_RETRY_TIMES):
            try:
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS question_cache (
                        hash TEXT PRIMARY KEY,
                        question_text TEXT NOT NULL,
                        question_type TEXT NOT NULL,
                        options TEXT DEFAULT '',
                        answer TEXT NOT NULL,
                        course_id TEXT DEFAULT '',
                        chapter_id TEXT DEFAULT '',
                        created_at REAL NOT NULL,
                        hit_count INTEGER DEFAULT 1
                    )
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS question_stats (
                        key TEXT PRIMARY KEY,
                        value INTEGER NOT NULL DEFAULT 0
                    )
                """)
                self._conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                    raise
                if attempt == WRITE_RETRY_TIMES - 1:
                    raise
                time.sleep(WRITE_RETRY_DELAY * (attempt + 1))

    def _commit_with_retry(self) -> bool:
        """提交写入，遇跨进程写锁时退避重试"""
        for attempt in range(WRITE_RETRY_TIMES):
            try:
                self._conn.commit()
                return True
            except sqlite3.OperationalError as e:
                message = str(e).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                time.sleep(WRITE_RETRY_DELAY * (attempt + 1))
        logger.warning("题库写入重试耗尽，本次答案未落库（不影响课程任务）")
        try:
            self._conn.rollback()
        except sqlite3.Error:
            pass
        return False

    @staticmethod
    def _normalize_options(options) -> str:
        """统一序列化options字段，确保hash一致性"""
        if isinstance(options, (list, dict)):
            return json.dumps(options, ensure_ascii=False, sort_keys=True)
        return str(options) if options else ""

    @staticmethod
    def _make_hash(question_text: str, options: str = "") -> str:
        """生成题目的唯一哈希值"""
        raw = question_text + options
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def lookup(self, question_text: str, options=None) -> str | None:
        """查询题目答案，命中则增加计数"""
        opts_str = self._normalize_options(options)
        q_hash = self._make_hash(question_text, opts_str)
        with self._lock:
            row = self._conn.execute(
                "SELECT answer FROM question_cache WHERE hash = ?", (q_hash,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE question_cache SET hit_count = hit_count + 1 WHERE hash = ?",
                    (q_hash,),
                )
                self._bump_stat("lookups")
                self._bump_stat("hits")
                self._commit_with_retry()
                return row[0]
            self._bump_stat("lookups")
            self._commit_with_retry()
        return None

    def _bump_stat(self, key: str, amount: int = 1):
        """累计题库访问计数（与答案同事务提交，供命中率统计）"""
        self._conn.execute(
            """INSERT INTO question_stats(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value = value + ?""",
            (key, amount, amount),
        )

    def batch_lookup(self, questions: list[dict]) -> dict[str, str]:
        """批量查询题目答案"""
        result = {}
        for q in questions:
            # 直接传原始options给lookup，由lookup内部调用_normalize_options
            ans = self.lookup(q.get("question_text", ""), q.get("options", ""))
            if ans:
                result[q.get("question_text", "")] = ans
        return result

    def save(self, question_text: str, question_type: str, answer: str,
             options=None, course_id: str = "", chapter_id: str = ""):
        """保存题目和答案（INSERT OR REPLACE语义）"""
        opts_str = self._normalize_options(options)
        q_hash = self._make_hash(question_text, opts_str)
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO question_cache
                   (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM question_cache WHERE hash = ?), 1))""",
                (q_hash, question_text, question_type, opts_str, answer,
                 course_id, chapter_id, time.time(), q_hash),
            )
            self._commit_with_retry()

    def batch_save(self, questions: list[dict]):
        """批量保存题目和答案"""
        if not questions:
            return
        with self._lock:
            for q in questions:
                opts_str = self._normalize_options(q.get("options", ""))
                q_hash = self._make_hash(
                    q.get("question_text", ""),
                    opts_str,
                )
                self._conn.execute(
                    """INSERT OR REPLACE INTO question_cache
                       (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM question_cache WHERE hash = ?), 1))""",
                    (q_hash, q.get("question_text", ""), q.get("question_type", ""),
                     opts_str,
                     q.get("answer", ""), q.get("course_id", ""),
                     q.get("chapter_id", ""), time.time(), q_hash),
                )
            self._commit_with_retry()

    def close(self):
        """关闭数据库连接"""
        try:
            self._conn.commit()
        except sqlite3.Error:
            pass
        self._conn.close()

    def stats(self) -> dict:
        """题库统计（总数、命中次数、命中率、按题型）"""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM question_cache").fetchone()[0]
            hits = self._conn.execute("SELECT COALESCE(SUM(hit_count), 0) FROM question_cache").fetchone()[0]
            counters = dict(self._conn.execute("SELECT key, value FROM question_stats").fetchall())
            by_type = self._conn.execute(
                "SELECT question_type, COUNT(*) FROM question_cache GROUP BY question_type"
            ).fetchall()
        lookups = int(counters.get("lookups", 0) or 0)
        cache_hits = int(counters.get("hits", 0) or 0)
        return {
            "total": int(total or 0),
            "hits": int(hits or 0),
            "lookups": lookups,
            # 命中率 = 命中次数 / 查询次数，无查询时为 0
            "hit_rate": round(cache_hits / lookups, 4) if lookups else 0.0,
            "by_type": {row[0] or "未知": row[1] for row in by_type},
        }
