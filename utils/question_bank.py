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

from core.paths import get_user_data_path


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
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
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
        self._conn.commit()

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
                self._conn.commit()
                return row[0]
        return None

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
            self._conn.commit()

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
            self._conn.commit()

    def close(self):
        """关闭数据库连接"""
        self._conn.close()
