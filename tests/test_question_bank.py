"""共享题库：并发读写、搜索、哈希去重、JSON/CSV 导入导出"""

import json
import sqlite3
import threading

import pytest

from app import paths, question_bank_manager as bank


def _save(question, answer, options=None, course="c1", qtype="单选题", hits=1):
    conn = bank._connect()
    try:
        opts = bank.normalize_options([] if options is None else options)
        bank._immediate_transaction(conn)
        conn.execute(
            """INSERT OR REPLACE INTO question_cache
               (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
               VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)""",
            (bank.make_hash(question, opts), question, qtype, opts, answer, course, 1.0, hits),
        )
        conn.commit()
    finally:
        conn.close()


def test_stats_counts_and_groups(sandbox):
    _save("题目一", "A", ["A. x", "B. y"])
    _save("题目二", "AB", ["A. x", "B. y"], qtype="多选题")
    _save("题目三", "true", qtype="判断题", hits=4)

    data = bank.stats()
    assert data["total"] == 3
    assert data["hits"] == 6
    types = {item["type"]: item["count"] for item in data["by_type"]}
    assert types["单选题"] == 1 and types["多选题"] == 1 and types["判断题"] == 1
    assert data["by_course"][0]["course_id"] == "c1"


def test_search_filters_by_keyword_and_type(sandbox):
    _save("超星平台的使用方法", "A", qtype="单选题")
    _save("超星平台的判断题", "true", qtype="判断题")
    assert bank.search("超星")["total"] == 2
    assert bank.search("超星", "判断题")["total"] == 1
    assert bank.search("不存在的题目")["total"] == 0
    assert bank.search("超星", limit=1)["total"] == 2


def test_export_json_and_csv_roundtrip(sandbox):
    _save("导出题目", "B", ["A. x", "B. y"])
    payload = json.loads(bank.export_json())
    assert payload[0]["question_text"] == "导出题目"

    csv_text = bank.export_csv()
    assert "question_text" in csv_text.splitlines()[0]
    assert "导出题目" in csv_text


def test_import_json_adds_new_and_dedupes(sandbox):
    content = json.dumps([
        {"question_text": "新题一", "answer": "A", "question_type": "单选题",
         "options": ["A. x", "B. y"]},
        {"question_text": "新题一", "answer": "A", "question_type": "单选题",
         "options": ["A. x", "B. y"]},
    ], ensure_ascii=False)
    preview = bank.preview_import(content)
    assert preview["parsed"] == 2
    # 同一文件内重复题目在写入时按哈希去重
    result = bank.commit_import(content)
    assert result["imported"] == 1
    assert bank.stats()["total"] == 1


def test_import_json_detects_existing_duplicates(sandbox):
    _save("已有题目", "A")
    content = json.dumps([{"question_text": "已有题目", "answer": "A"}])
    preview = bank.preview_import(content)
    assert preview["duplicate"] == 1 and preview["new"] == 0
    assert bank.commit_import(content)["imported"] == 0


def test_import_overwrite_updates_answer(sandbox):
    _save("待覆盖题目", "A")
    content = json.dumps([{"question_text": "待覆盖题目", "answer": "D"}])
    result = bank.commit_import(content, overwrite=True)
    assert result["updated"] == 1
    assert bank.search("待覆盖")["items"][0]["answer"] == "D"


def test_import_csv(sandbox):
    rows = [
        "question_text,question_type,answer,options",
        '"CSV题目","单选题","C","[""A. x"", ""B. y"", ""C. z""]"',
    ]
    result = bank.commit_import("\n".join(rows), fmt="csv")
    assert result["imported"] == 1
    assert bank.search("CSV题目")["items"][0]["answer"] == "C"


def test_import_rejects_bad_payloads(sandbox):
    parsed, errors = bank.parse_import("not json at all", fmt="json")
    assert parsed == [] and errors

    parsed, errors = bank.parse_import(json.dumps([{"answer": "A"}]), fmt="json")
    assert parsed == [] and any("question_text" in item for item in errors)

    parsed, errors = bank.parse_import(json.dumps([{"question_text": "题"}]), fmt="json")
    assert parsed == [] and any("answer" in item for item in errors)

    parsed, errors = bank.parse_import("a,b\n1,2", fmt="csv")
    assert parsed == [] and errors


def test_import_failure_keeps_existing_bank_intact(sandbox):
    _save("保底题目", "A")
    before = bank.stats()["total"]
    result = bank.commit_import(json.dumps({"weird": "shape"}))
    assert result["imported"] == 0
    assert bank.stats()["total"] == before
    assert bank.search("保底题目")["total"] == 1


def test_concurrent_writes_do_not_corrupt(sandbox):
    """多个 Worker 进程共享同一题库：并发写入后数据完整可读"""
    errors = []

    def worker(index):
        try:
            for i in range(15):
                _save(f"并发题目-{index}-{i}", "A", hits=i + 1)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert bank.stats()["total"] == 60
    assert bank.search("并发题目")["total"] == 60


def test_delete_by_hash(sandbox):
    _save("待删除", "A")
    question_hash = bank.search("待删除")["items"][0]["hash"]
    assert bank.delete_by_hash(question_hash) is True
    assert bank.delete_by_hash(question_hash) is False
    assert bank.stats()["total"] == 0


def test_hit_rate_is_lookup_based_not_question_based(sandbox):
    """命中率必须是 命中/查询，不能是 命中次数/题目数（后者会超过 100%）"""
    from core.config import Config
    Config._data = Config._default_config()
    bank._connect().close()

    import os as _os
    from utils.question_bank import QuestionBank

    worker_bank = QuestionBank(db_path=paths.QUESTION_BANK_FILE)
    try:
        worker_bank.save("命中率测试题", "单选题", "A", ["A. x"])
        # 1 次命中 + 2 次未命中
        assert worker_bank.lookup("命中率测试题", ["A. x"]) == "A"
        assert worker_bank.lookup("不存在的题一") is None
        assert worker_bank.lookup("不存在的题二") is None
    finally:
        worker_bank.close()

    data = bank.stats()
    assert data["lookups"] == 3
    assert 0 < data["hit_rate"] <= 1.0, data["hit_rate"]
    assert abs(data["hit_rate"] - 1 / 3) < 0.01


def test_hit_rate_is_zero_without_lookups(sandbox):
    _save("从未被查询的题", "A")
    assert bank.stats()["hit_rate"] == 0.0


def test_normalize_options_is_stable_between_save_and_lookup(sandbox):
    """避免历史 bug：同一题目的 options 序列化必须一致，否则哈希错配"""
    options = ["A. 甲", "B. 乙"]
    assert bank.normalize_options(options) == bank.normalize_options(list(options))
    as_string = bank.normalize_options(options)
    assert bank.normalize_options(as_string) == as_string
    assert bank.normalize_options("") == ""
