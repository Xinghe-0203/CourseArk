"""
共享题库管理

所有账号与 Worker 使用同一个 data/question_bank.db：
- 统计：总数、命中、按题型、按课程、最近写入
- 搜索：按题干模糊查询
- 导出：JSON / CSV
- 导入：先校验格式与数量并预览，按题目哈希去重，事务写入

WebUI 自己打开连接（WAL + busy_timeout），与 Worker 并发读写互不损坏。
"""

import csv
import hashlib
import io
import json
import os
import sqlite3
import time

from . import paths

BUSY_TIMEOUT_SECONDS = 30.0

TABLE_SQL = """
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
);
CREATE TABLE IF NOT EXISTS question_stats (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
)
"""


def _connect() -> sqlite3.Connection:
    """
    打开共享题库连接

    注意顺序：先设置 busy_timeout，再切换 WAL 和建表。
    busy_timeout 是 busy handler 生效的前提，放在后面会让并发的
    WAL 切换/建表在锁冲突时直接抛 SQLITE_BUSY。
    """
    os.makedirs(os.path.dirname(paths.QUESTION_BANK_FILE) or ".", exist_ok=True)
    conn = sqlite3.connect(paths.QUESTION_BANK_FILE, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=%d" % int(BUSY_TIMEOUT_SECONDS * 1000))

    for attempt in range(5):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            # executescript 支持多语句（建表 SQL 含两张表）
            conn.executescript(TABLE_SQL)
            conn.commit()
            return conn
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                conn.close()
                raise
            if attempt == 4:
                conn.close()
                raise
            time.sleep(0.3 * (attempt + 1))
    return conn


def _count_rows() -> int:
    """当前 WebUI 题库的题目数量"""
    conn = _connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM question_cache").fetchone()[0] or 0)
    finally:
        conn.close()


def read_db_records(db_path: str) -> list:
    """
    从任意 CLI 格式的题库文件读取题目

    WAL 处理：源库可能带着未回放的 -wal/-shm，只读模式无法回放，
    因此先把三个文件复制到临时目录再打开，让 SQLite 正常恢复。
    源文件本身从不被写入。
    """
    import shutil
    import tempfile

    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    tmp_dir = tempfile.mkdtemp(prefix="cxbank-")
    try:
        target = os.path.join(tmp_dir, "bank.db")
        shutil.copy2(db_path, target)
        for suffix in ("-wal", "-shm"):
            source_extra = db_path + suffix
            if os.path.exists(source_extra):
                shutil.copy2(source_extra, target + suffix)

        conn = sqlite3.connect(target)
        conn.row_factory = sqlite3.Row
        try:
            try:
                tables = {row[0] for row in
                          conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.DatabaseError as exc:
                # 非 SQLite 文件（例如误传了文本或压缩包）
                raise ValueError(f"文件不是有效的 SQLite 数据库: {exc}")
            if "question_cache" not in tables:
                raise ValueError("该数据库不包含 question_cache 表，不是有效的题库文件")
            try:
                rows = conn.execute(
                    """SELECT question_text, question_type, options, answer,
                              course_id, chapter_id, created_at, hit_count
                       FROM question_cache"""
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                raise ValueError(f"读取题库表失败（表结构不符）: {exc}")
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    records = []
    for row in rows:
        question_text = str(row["question_text"] or "").strip()
        answer = str(row["answer"] or "").strip()
        if not question_text or not answer:
            continue
        # 原样保留 CLI 存储的 options 序列化结果，保证哈希与 CLI 一致、去重可靠
        options = str(row["options"] or "")
        records.append({
            "hash": make_hash(question_text, options),
            "question_text": question_text,
            "question_type": str(row["question_type"] or "未知").strip(),
            "options": options,
            "answer": answer,
            "course_id": str(row["course_id"] or ""),
            "chapter_id": str(row["chapter_id"] or ""),
            "created_at": float(row["created_at"] or time.time()),
            "hit_count": int(row["hit_count"] or 1),
        })
    return records


def source_info() -> dict:
    """源 CLI 题库信息（界面用于显示可导入数量）"""
    exists = os.path.exists(paths.SOURCE_QUESTION_BANK)
    info = {
        "exists": exists,
        "path": paths.SOURCE_QUESTION_BANK,
        "source_total": 0,
        "current_total": _count_rows(),
    }
    if exists:
        try:
            info["source_total"] = len(read_db_records(paths.SOURCE_QUESTION_BANK))
        except (sqlite3.Error, ValueError, OSError) as exc:
            info["error"] = str(exc)
    return info


def import_from_source(overwrite: bool = False) -> dict:
    """把源 CLI 题库合并进来（源文件只读，重复题目按哈希跳过或覆盖）"""
    if not os.path.exists(paths.SOURCE_QUESTION_BANK):
        raise FileNotFoundError(paths.SOURCE_QUESTION_BANK)
    records = read_db_records(paths.SOURCE_QUESTION_BANK)
    result = merge_records(records, overwrite=overwrite)
    result["source"] = "cli"
    result["source_total"] = len(records)
    return result


def import_from_db_file(db_path: str, overwrite: bool = False) -> dict:
    """从上传或指定的题库文件合并（先校验格式，再事务写入）"""
    records = read_db_records(db_path)
    if not records:
        return {"imported": 0, "updated": 0, "skipped": 0,
                "errors": ["文件中没有可导入的题目（缺少题干或答案）"], "error_count": 1}
    result = merge_records(records, overwrite=overwrite)
    result["source"] = "file"
    result["source_total"] = len(records)
    return result


def import_from_source_once():
    """首次启动时把源 CLI 的题库并入（同一题目按哈希去重，重复执行安全）"""
    if _count_rows() > 0:
        return {"imported": False, "reason": "题库已有内容"}
    if not os.path.exists(paths.SOURCE_QUESTION_BANK):
        return {"imported": False, "reason": "源题库不存在"}
    try:
        result = import_from_source(overwrite=False)
    except (sqlite3.Error, ValueError, OSError) as exc:
        return {"imported": False, "reason": f"源题库读取失败: {exc}"}
    return {"imported": True, "count": result.get("imported", 0), **result}


def stats(days: int = 7) -> dict:
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM question_cache").fetchone()[0]
        hits = conn.execute("SELECT COALESCE(SUM(hit_count), 0) FROM question_cache").fetchone()[0]
        counters = dict(conn.execute("SELECT key, value FROM question_stats").fetchall())
        by_type = conn.execute(
            "SELECT question_type, COUNT(*) AS c FROM question_cache GROUP BY question_type ORDER BY c DESC"
        ).fetchall()
        by_course = conn.execute(
            """SELECT course_id, COUNT(*) AS c FROM question_cache
               WHERE course_id IS NOT NULL AND course_id != '' GROUP BY course_id ORDER BY c DESC LIMIT 20"""
        ).fetchall()
        recent = conn.execute(
            "SELECT COUNT(*) FROM question_cache WHERE created_at >= ?",
            (time.time() - days * 86400,),
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT question_text, answer, created_at FROM question_cache ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    total = int(total or 0)
    lookups = int(counters.get("lookups", 0) or 0)
    cache_hits = int(counters.get("hits", 0) or 0)
    return {
        "total": total,
        "hits": int(hits or 0),
        "lookups": lookups,
        # 命中率 = 命中次数 / 查询次数（由各 Worker 进程累计）
        "hit_rate": round(cache_hits / lookups, 4) if lookups else 0.0,
        "by_type": [{"type": row["question_type"] or "未知", "count": row["c"]} for row in by_type],
        "by_course": [{"course_id": row["course_id"], "count": row["c"]} for row in by_course],
        "recent_days": days,
        "recent_count": int(recent or 0),
        "latest": [{"question": row["question_text"][:120], "answer": row["answer"],
                    "created_at": row["created_at"]} for row in latest],
    }


def search(keyword: str = "", question_type: str = "", limit: int = 50, offset: int = 0) -> dict:
    conn = _connect()
    try:
        clauses, params = [], []
        if keyword:
            clauses.append("question_text LIKE ?")
            params.append(f"%{keyword}%")
        if question_type:
            clauses.append("question_type = ?")
            params.append(question_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(f"SELECT COUNT(*) FROM question_cache {where}", tuple(params)).fetchone()[0]
        rows = conn.execute(
            f"""SELECT hash, question_text, question_type, options, answer, course_id, created_at, hit_count
                FROM question_cache {where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            tuple(params) + (int(limit), int(offset)),
        ).fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        try:
            options = json.loads(row["options"]) if row["options"] else []
        except ValueError:
            options = row["options"] or ""
        items.append({
            "hash": row["hash"],
            "question_text": row["question_text"],
            "question_type": row["question_type"],
            "options": options,
            "answer": row["answer"],
            "course_id": row["course_id"],
            "created_at": row["created_at"],
            "hit_count": row["hit_count"],
        })
    return {"total": int(total or 0), "items": items}


# ============================================================
# 导入导出
# ============================================================

REQUIRED_FIELDS = ("question_text", "answer")


def export_json() -> str:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT question_text, question_type, options, answer, course_id, chapter_id,
                      created_at, hit_count FROM question_cache ORDER BY created_at DESC"""
        ).fetchall()
    finally:
        conn.close()
    payload = []
    for row in rows:
        try:
            options = json.loads(row["options"]) if row["options"] else []
        except ValueError:
            options = row["options"] or ""
        payload.append({
            "question_text": row["question_text"],
            "question_type": row["question_type"],
            "options": options,
            "answer": row["answer"],
            "course_id": row["course_id"],
            "chapter_id": row["chapter_id"],
            "created_at": row["created_at"],
            "hit_count": row["hit_count"],
        })
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_csv() -> str:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT question_text, question_type, options, answer, course_id, created_at, hit_count
               FROM question_cache ORDER BY created_at DESC"""
        ).fetchall()
    finally:
        conn.close()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["question_text", "question_type", "options", "answer", "course_id",
                     "created_at", "hit_count"])
    for row in rows:
        writer.writerow([row["question_text"], row["question_type"], row["options"],
                         row["answer"], row["course_id"], row["created_at"], row["hit_count"]])
    return buffer.getvalue()


def normalize_options(options) -> str:
    if isinstance(options, (list, dict)):
        return json.dumps(options, ensure_ascii=False, sort_keys=True)
    return str(options) if options else ""


def make_hash(question_text: str, options: str = "") -> str:
    return hashlib.md5((question_text + options).encode("utf-8")).hexdigest()


def parse_import(content: str, fmt: str = "json") -> tuple:
    """
    解析导入内容

    Returns:
        (records, errors): 可写入记录列表与错误信息列表
    """
    records, errors = [], []
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or "question_text" not in reader.fieldnames:
            return [], ["CSV 缺少 question_text 列"]
        rows = list(reader)
    else:
        try:
            data = json.loads(content)
        except ValueError as exc:
            return [], [f"JSON 解析失败: {exc}"]
        if isinstance(data, dict):
            data = data.get("items") or data.get("questions") or []
        if not isinstance(data, list):
            return [], ["JSON 结构应为数组，或包含 items/questions 数组"]
        rows = data

    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            errors.append(f"第{index}条不是对象")
            continue
        question_text = str(raw.get("question_text") or raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question_text:
            errors.append(f"第{index}条缺少 question_text")
            continue
        if not answer:
            errors.append(f"第{index}条缺少 answer")
            continue
        options_raw = raw.get("options")
        if isinstance(options_raw, str):
            try:
                options_raw = json.loads(options_raw)
            except ValueError:
                options_raw = options_raw
        if options_raw is None or options_raw == "":
            # 与 CLI 保持一致：无选项题目统一序列化为 "[]"，
            # 否则导入的哈希与 Worker 查询的哈希对不上，去重和命中都会失效
            options_raw = []
        options = normalize_options(options_raw)
        records.append({
            "hash": make_hash(question_text, options),
            "question_text": question_text,
            "question_type": str(raw.get("question_type") or "未知").strip(),
            "options": options,
            "answer": answer,
            "course_id": str(raw.get("course_id") or ""),
            "chapter_id": str(raw.get("chapter_id") or ""),
            "created_at": float(raw.get("created_at") or time.time()),
            "hit_count": int(raw.get("hit_count") or 1),
        })
    return records, errors


def preview_records(records: list, errors: list = None) -> dict:
    """按已解析记录预览：总数、新增数量与重复数量"""
    conn = _connect()
    try:
        existing = set()
        if records:
            hashes = [record["hash"] for record in records]
            placeholders = ",".join("?" for _ in hashes)
            for row in conn.execute(
                f"SELECT hash FROM question_cache WHERE hash IN ({placeholders})", tuple(hashes)
            ):
                existing.add(row["hash"])
    finally:
        conn.close()
    new_count = sum(1 for record in records if record["hash"] not in existing)
    return {
        "parsed": len(records),
        "new": new_count,
        "duplicate": len(records) - new_count,
        "errors": (errors or [])[:50],
        "error_count": len(errors or []),
    }


def preview_import(content: str, fmt: str = "json") -> dict:
    """导入前预览：解析数量、重复数量与错误"""
    records, errors = parse_import(content, fmt)
    return preview_records(records, errors)


def _immediate_transaction(conn: sqlite3.Connection):
    """显式 IMMEDIATE 事务：先取得写锁，避免读锁升级导致的立刻 SQLITE_BUSY"""
    for attempt in range(5):
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            time.sleep(0.2 * (attempt + 1))
    conn.execute("BEGIN IMMEDIATE")


def merge_records(records: list, overwrite: bool = False) -> dict:
    """
    事务合并题目（JSON/CSV 导入与题库文件导入共用）

    overwrite=True 时覆盖同哈希答案，否则只补新增题目。
    使用 IMMEDIATE 事务，冲突时回滚重试，不损坏现有题库。
    """
    if not records:
        return {"imported": 0, "updated": 0, "skipped": 0, "errors": [], "error_count": 0}

    conn = _connect()
    inserted = updated = 0
    try:
        for attempt in range(3):
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            _immediate_transaction(conn)
            try:
                inserted = updated = 0
                for record in records:
                    exists = conn.execute(
                        "SELECT 1 FROM question_cache WHERE hash = ?", (record["hash"],)
                    ).fetchone()
                    if exists and not overwrite:
                        continue
                    if exists:
                        conn.execute(
                            """UPDATE question_cache SET answer = ?, question_type = ?, question_text = ?,
                               options = ?, course_id = ?, chapter_id = ?
                               WHERE hash = ?""",
                            (record["answer"], record["question_type"], record["question_text"],
                             record["options"], record["course_id"], record["chapter_id"],
                             record["hash"]),
                        )
                        updated += 1
                    else:
                        conn.execute(
                            """INSERT INTO question_cache
                               (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (record["hash"], record["question_text"], record["question_type"],
                             record["options"], record["answer"], record["course_id"],
                             record["chapter_id"], record["created_at"], record["hit_count"]),
                        )
                        inserted += 1
                conn.commit()
                break
            except sqlite3.Error:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                if attempt == 2:
                    return {"imported": 0, "updated": 0, "skipped": 0,
                            "errors": ["题库写入冲突，已回滚，请重试"], "error_count": 1}
                time.sleep(0.4 * (attempt + 1))
    finally:
        conn.close()
    return {"imported": inserted, "updated": updated, "skipped": len(records) - inserted - updated,
            "errors": [], "error_count": 0}


def commit_import(content: str, fmt: str = "json", overwrite: bool = False) -> dict:
    """事务写入 JSON/CSV 导入内容"""
    records, errors = parse_import(content, fmt)
    if not records:
        return {"imported": 0, "updated": 0, "skipped": 0,
                "errors": errors[:50], "error_count": len(errors)}
    result = merge_records(records, overwrite=overwrite)
    if errors:
        result["errors"] = errors[:50]
        result["error_count"] = len(errors)
    return result


def delete_by_hash(question_hash: str) -> bool:
    conn = _connect()
    try:
        _immediate_transaction(conn)
        cursor = conn.execute("DELETE FROM question_cache WHERE hash = ?", (question_hash,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
