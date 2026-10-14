"""
题库 .db 导入、源配置导入与全选相关的测试

覆盖：
- CLI 格式题库 db 的读取（含 WAL 附带文件、缺列、非题库文件）
- 源库预览与导入的幂等性
- 上传 .db 的 API（multipart）与错误响应
- LLM/题库配置从源 config.yml 导入并持久化到本地 settings.json
"""

import json
import os
import sqlite3
import sys

import pytest

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEBUI_ROOT)


def _make_cli_bank(path, rows):
    """生成一个 CLI 格式的题库文件"""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE question_cache (
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
    for index, (question, answer, qtype, options) in enumerate(rows):
        conn.execute(
            """INSERT INTO question_cache
               (hash, question_text, question_type, options, answer, course_id, chapter_id,
                created_at, hit_count) VALUES (?, ?, ?, ?, ?, '', '', ?, ?)""",
            (f"hash-{index}", question, qtype, options, answer, 1.0 + index, index + 1),
        )
    conn.commit()
    conn.close()


# ============================================================
# 读取 CLI 格式题库
# ============================================================

def test_read_db_records_preserves_cli_hash(sandbox):
    """导入必须保留 CLI 的 options 原样，否则哈希对不上、去重失效"""
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "cli.db")
    options = json.dumps(["A. 甲", "B. 乙"], ensure_ascii=False, sort_keys=True)
    _make_cli_bank(db_path, [("题目一", "A", "单选题", options)])

    records = bank.read_db_records(db_path)
    assert len(records) == 1
    assert records[0]["options"] == options
    # 与 CLI 自身的哈希算法一致
    assert records[0]["hash"] == bank.make_hash("题目一", options)


def test_read_db_records_handles_wal_sidecar_files(sandbox):
    """
    源库可能带着未回放的 -wal / -shm：只读打开会读到不完整数据，
    必须复制三个文件后读取才能拿到全部题目。

    注意：最后一个连接关闭时 SQLite 会 checkpoint 并删除 -wal，
    所以这里保持连接打开来复现真实场景。
    """
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "wal.db")
    holder = sqlite3.connect(db_path)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("""
        CREATE TABLE question_cache (
            hash TEXT PRIMARY KEY, question_text TEXT NOT NULL, question_type TEXT NOT NULL,
            options TEXT DEFAULT '', answer TEXT NOT NULL, course_id TEXT DEFAULT '',
            chapter_id TEXT DEFAULT '', created_at REAL NOT NULL, hit_count INTEGER DEFAULT 1)
    """)
    holder.commit()
    # 数据写入 WAL，尚未 checkpoint 回主库文件
    holder.execute(
        "INSERT INTO question_cache VALUES ('h1', 'WAL 题目', '单选题', '', 'A', '', '', 1.0, 1)")
    holder.commit()

    try:
        assert os.path.exists(db_path + "-wal")
        records = bank.read_db_records(db_path)
        assert len(records) == 1
        assert records[0]["question_text"] == "WAL 题目"
    finally:
        holder.close()


def test_read_db_records_skips_incomplete_rows(sandbox):
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "partial.db")
    _make_cli_bank(db_path, [
        ("完整题目", "A", "单选题", ""),
        ("缺答案题目", "", "单选题", ""),
        ("", "B", "单选题", ""),
    ])
    records = bank.read_db_records(db_path)
    assert [item["question_text"] for item in records] == ["完整题目"]


def test_read_db_records_rejects_non_bank_file(sandbox):
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "other.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE unrelated (x TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="question_cache"):
        bank.read_db_records(db_path)


def test_read_db_records_rejects_missing_file(sandbox):
    from app import question_bank_manager as bank

    with pytest.raises(FileNotFoundError):
        bank.read_db_records(os.path.join(sandbox, "absent.db"))


def test_read_db_records_does_not_modify_source(sandbox):
    """导入是只读操作：源文件内容与修改时间都不应变"""
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "readonly.db")
    _make_cli_bank(db_path, [("只读校验", "A", "单选题", "")])
    before_bytes = open(db_path, "rb").read()
    before_mtime = os.path.getmtime(db_path)

    bank.read_db_records(db_path)

    assert open(db_path, "rb").read() == before_bytes
    assert os.path.getmtime(db_path) == before_mtime


# ============================================================
# 合并与幂等
# ============================================================

def test_import_from_db_file_merges_and_is_idempotent(sandbox):
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "source.db")
    _make_cli_bank(db_path, [
        ("导入题目一", "A", "单选题", ""),
        ("导入题目二", "true", "判断题", ""),
    ])

    first = bank.import_from_db_file(db_path)
    assert first["imported"] == 2
    assert bank.stats()["total"] == 2

    # 重复导入同一文件不产生新记录
    second = bank.import_from_db_file(db_path)
    assert second["imported"] == 0
    assert second["skipped"] == 2
    assert bank.stats()["total"] == 2


def test_import_overwrite_updates_existing_answer(sandbox):
    from app import question_bank_manager as bank

    db_path = os.path.join(sandbox, "v1.db")
    _make_cli_bank(db_path, [("会变的题目", "A", "单选题", "")])
    bank.import_from_db_file(db_path)

    db_path2 = os.path.join(sandbox, "v2.db")
    _make_cli_bank(db_path2, [("会变的题目", "D", "单选题", "")])

    keep = bank.import_from_db_file(db_path2, overwrite=False)
    assert keep["imported"] == 0 and keep["updated"] == 0
    assert bank.search("会变的题目")["items"][0]["answer"] == "A"

    changed = bank.import_from_db_file(db_path2, overwrite=True)
    assert changed["updated"] == 1
    assert bank.search("会变的题目")["items"][0]["answer"] == "D"


def test_source_info_reports_counts(sandbox, monkeypatch):
    from app import paths, question_bank_manager as bank

    source = os.path.join(sandbox, "cli_source.db")
    _make_cli_bank(source, [("源题一", "A", "单选题", ""), ("源题二", "B", "单选题", "")])
    monkeypatch.setattr(paths, "SOURCE_QUESTION_BANK", source)

    info = bank.source_info()
    assert info["exists"] is True
    assert info["source_total"] == 2
    assert info["current_total"] == 0

    bank.import_from_source()
    assert bank.source_info()["current_total"] == 2


def test_import_from_source_missing_file_raises(sandbox, monkeypatch):
    from app import paths, question_bank_manager as bank

    monkeypatch.setattr(paths, "SOURCE_QUESTION_BANK", os.path.join(sandbox, "nope.db"))
    with pytest.raises(FileNotFoundError):
        bank.import_from_source()


def test_import_from_source_once_skips_when_bank_has_content(sandbox, monkeypatch):
    from app import paths, question_bank_manager as bank

    source = os.path.join(sandbox, "cli_source.db")
    _make_cli_bank(source, [("源题", "A", "单选题", "")])
    monkeypatch.setattr(paths, "SOURCE_QUESTION_BANK", source)

    bank.merge_records(bank.read_db_records(source))
    result = bank.import_from_source_once()
    assert result["imported"] is False
    assert "已有内容" in result["reason"]


# ============================================================
# API
# ============================================================

def test_api_source_import_flow(app_client, sandbox, monkeypatch):
    from app import paths

    source = os.path.join(sandbox, "api_source.db")
    _make_cli_bank(source, [
        ("API 源题一", "A", "单选题", ""),
        ("API 源题二", "AB", "多选题", ""),
    ])
    monkeypatch.setattr(paths, "SOURCE_QUESTION_BANK", source)

    info = app_client.get("/api/question-bank/source").json()
    assert info["exists"] is True and info["source_total"] == 2

    preview = app_client.post("/api/question-bank/import-source",
                              json={"preview_only": True}).json()
    assert preview["parsed"] == 2 and preview["new"] == 2

    committed = app_client.post("/api/question-bank/import-source", json={}).json()
    assert committed["imported"] == 2
    assert app_client.get("/api/question-bank/stats").json()["total"] == 2

    again = app_client.post("/api/question-bank/import-source", json={}).json()
    assert again["imported"] == 0 and again["skipped"] == 2


def test_api_source_import_missing_file_returns_404(app_client, sandbox, monkeypatch):
    from app import paths

    monkeypatch.setattr(paths, "SOURCE_QUESTION_BANK", os.path.join(sandbox, "absent.db"))
    response = app_client.post("/api/question-bank/import-source", json={})
    assert response.status_code == 404


def test_api_upload_db_import(app_client, sandbox, tmp_path):
    upload = tmp_path / "upload.db"
    _make_cli_bank(str(upload), [("上传题目一", "C", "单选题", ""),
                                 ("上传题目二", "false", "判断题", "")])

    with open(upload, "rb") as handle:
        preview = app_client.post(
            "/api/question-bank/import-db",
            files={"file": ("upload.db", handle, "application/octet-stream")},
            data={"preview_only": "true"},
        )
    assert preview.status_code == 200, preview.text
    assert preview.json()["parsed"] == 2

    with open(upload, "rb") as handle:
        committed = app_client.post(
            "/api/question-bank/import-db",
            files={"file": ("upload.db", handle, "application/octet-stream")},
        )
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported"] == 2
    assert app_client.get("/api/question-bank/stats").json()["total"] == 2


def _make_wal_bank(db_path, checkpoint_table=True):
    """
    构造一个“主文件 + 未回放 WAL”的题库

    checkpoint_table=True 时先 checkpsoint 建表与旧数据，只把新数据留在 WAL；
    否则整张表都还在 WAL 中（CLI 刚创建库就异常退出时的情况）。
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE question_cache (
            hash TEXT PRIMARY KEY, question_text TEXT NOT NULL, question_type TEXT NOT NULL,
            options TEXT DEFAULT '', answer TEXT NOT NULL, course_id TEXT DEFAULT '',
            chapter_id TEXT DEFAULT '', created_at REAL NOT NULL, hit_count INTEGER DEFAULT 1)
    """)
    conn.execute(
        "INSERT INTO question_cache VALUES ('h0', '已落盘题目', '单选题', '', 'A', '', '', 1.0, 1)")
    conn.commit()
    if checkpoint_table:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # 这一条只存在于 WAL 中
    conn.execute(
        "INSERT INTO question_cache VALUES ('h1', '仅WAL题目', '单选题', '', 'B', '', '', 2.0, 1)")
    conn.commit()
    assert os.path.exists(db_path + "-wal")
    return conn


def _upload_all(app_client, db_path, preview_only=True):
    """把 .db 与两个侧车文件一起上传"""
    opened = [open(db_path, "rb"), open(db_path + "-wal", "rb"), open(db_path + "-shm", "rb")]
    base = os.path.basename(db_path)
    try:
        files = [
            ("file", (base, opened[0], "application/octet-stream")),
            ("file", (base + "-wal", opened[1], "application/octet-stream")),
            ("file", (base + "-shm", opened[2], "application/octet-stream")),
        ]
        return app_client.post(
            "/api/question-bank/import-db", files=files,
            data={"preview_only": "true" if preview_only else "false"},
        )
    finally:
        for handle in opened:
            handle.close()


def test_api_upload_with_wal_sidecars_keeps_pending_rows(app_client, tmp_path):
    """
    只上传 .db 会丢掉尚未 checkpoint 的 WAL 数据；
    同时上传 .db + .db-wal + .db-shm 必须能拿到全部题目。
    """
    db_path = str(tmp_path / "pending.db")
    holder = _make_wal_bank(db_path, checkpoint_table=True)
    try:
        # 只传主文件：只能看到已落盘的 1 题，并给出 WAL 提示
        with open(db_path, "rb") as handle:
            single = app_client.post(
                "/api/question-bank/import-db",
                files={"file": ("pending.db", handle, "application/octet-stream")},
                data={"preview_only": "true"},
            )
        assert single.status_code == 200, single.text
        assert single.json()["parsed"] == 1
        assert "wal" in single.json()["wal_warning"].lower()

        # 三个文件一起传：两题都能读到，且不再提示
        combined = _upload_all(app_client, db_path)
        assert combined.status_code == 200, combined.text
        body = combined.json()
        assert body["parsed"] == 2, body
        assert "wal_warning" not in body
    finally:
        holder.close()


def test_api_upload_main_only_when_table_still_in_wal_gives_clear_error(app_client, tmp_path):
    """
    整张表都还在 WAL 中时，单独上传主文件会得到明确的“不是有效题库文件”提示，
    而不是静默导入 0 条。
    """
    db_path = str(tmp_path / "tableau.db")
    holder = _make_wal_bank(db_path, checkpoint_table=False)
    try:
        with open(db_path, "rb") as handle:
            single = app_client.post(
                "/api/question-bank/import-db",
                files={"file": ("tableau.db", handle, "application/octet-stream")},
            )
        assert single.status_code == 400
        assert "question_cache" in single.json()["detail"]

        # 带上侧车文件即可正常读取
        combined = _upload_all(app_client, db_path)
        assert combined.status_code == 200, combined.text
        assert combined.json()["parsed"] == 2
    finally:
        holder.close()


def test_api_upload_sidecar_without_main_file_is_rejected(app_client, tmp_path):
    wal = tmp_path / "only.db-wal"
    wal.write_bytes(b"dummy")

    with open(wal, "rb") as handle:
        response = app_client.post(
            "/api/question-bank/import-db",
            files={"file": ("only.db-wal", handle, "application/octet-stream")},
        )
    assert response.status_code == 400
    assert "主文件" in response.json()["detail"]


def test_api_upload_rejects_non_bank_file(app_client, tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database at all")

    with open(bad, "rb") as handle:
        response = app_client.post(
            "/api/question-bank/import-db",
            files={"file": ("bad.db", handle, "application/octet-stream")},
        )
    assert response.status_code == 400
    assert app_client.get("/api/question-bank/stats").json()["total"] == 0


def test_api_import_db_by_server_path(app_client, tmp_path):
    target = tmp_path / "bypath.db"
    _make_cli_bank(str(target), [("路径导入题目", "A", "单选题", "")])

    response = app_client.post("/api/question-bank/import-db", json={"path": str(target)})
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1

    missing = app_client.post("/api/question-bank/import-db", json={"path": str(tmp_path / "no.db")})
    assert missing.status_code == 404

    empty = app_client.post("/api/question-bank/import-db", json={})
    assert empty.status_code == 400


# ============================================================
# 源配置导入
# ============================================================

def _write_source_config(sandbox, content: str):
    path = os.path.join(sandbox, "source_config.yml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def test_import_source_config_fills_keys_and_persists(sandbox, monkeypatch):
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-from-source-config"
  model: "deepseek-chat"
tiku:
  enabled: true
  timeout: 15
advanced:
  request_delay: 2.5
  max_retries: 4
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)

    result = settings.import_from_source_config(only_empty=True)
    assert result["imported"] is True
    assert settings.resolve("llm.api_key") == "sk-from-source-config"
    assert settings.resolve("tiku.timeout") == 15
    assert settings.resolve("advanced.request_delay") == 2.5
    assert settings.resolve("advanced.max_retries") == 4

    # 必须落到本地数据库（SQLite 主存储）
    stored = settings._store().get("global")
    assert stored["llm"]["api_key"] == "sk-from-source-config"

    # 备份 JSON 也同步更新，便于人工查看
    with open(paths.SETTINGS_BACKUP_FILE, "r", encoding="utf-8") as handle:
        backup = json.load(handle)
    assert backup["llm"]["api_key"] == "sk-from-source-config"

    # 清掉内存缓存（模拟重启）后仍可读到
    settings._cache = None
    assert settings.resolve("llm.api_key") == "sk-from-source-config"


def test_import_source_config_does_not_overwrite_local_settings(sandbox, monkeypatch):
    """only_empty 模式下不得覆盖用户在 WebUI 已保存的值"""
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  api_key: "sk-from-source"
  model: "source-model"
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)

    settings.save({"llm": {"api_key": "sk-local-mine", "model": "local-model"}})

    result = settings.import_from_source_config(only_empty=True)
    assert result["imported"] is False
    assert settings.resolve("llm.api_key") == "sk-local-mine"
    assert settings.resolve("llm.model") == "local-model"


def test_import_source_config_can_force_overwrite(sandbox, monkeypatch):
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  api_key: "sk-from-source"
  model: "source-model"
monitor: {}
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)
    settings.save({"llm": {"api_key": "sk-local-mine", "model": "local-model"}})

    result = settings.import_from_source_config(only_empty=False)
    assert result["imported"] is True
    assert settings.resolve("llm.api_key") == "sk-from-source"
    assert settings.resolve("llm.model") == "source-model"


def test_import_source_config_without_file(sandbox, monkeypatch):
    from app import paths, settings

    monkeypatch.setattr(paths, "SOURCE_CONFIG", os.path.join(sandbox, "absent.yml"))
    result = settings.import_from_source_config()
    assert result["imported"] is False
    assert "未找到" in result["reason"]


def test_source_config_info_reports_availability(sandbox, monkeypatch):
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  api_key: "sk-x"
  model: "deepseek-chat"
tiku:
  enabled: true
  enncy-token: "token-x"
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)
    info = settings.source_config_info()
    assert info["exists"] is True
    assert info["has_llm_key"] is True
    assert info["has_tiku_token"] is True
    assert info["llm_model"] == "deepseek-chat"


def test_corrupted_legacy_json_migrates_safely(sandbox, monkeypatch):
    """
    回归：历史 settings.json 若被写成非对象（旧缺陷会写入数组），
    迁移时必须忽略它并使用默认值，而不是把服务带崩。
    """
    from app import paths, settings

    settings._cache = None
    settings._storage = None
    with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as handle:
        json.dump(["llm.api_key", "llm.model"], handle)

    data = settings.load()
    assert isinstance(data, dict)
    assert data["scheduler"]["max_active_workers"] == 8

    # 保存后写入 SQLite，数据类型始终是对象
    settings.save({"scheduler": {"max_active_workers": 5}})
    assert settings.resolve("scheduler.max_active_workers") == 5
    assert isinstance(settings._store().get("global"), dict)
    # 损坏的历史文件被改名保留，不会再次参与迁移
    assert not os.path.exists(paths.SETTINGS_FILE)


def test_first_init_writes_dict_then_import_fills_source_values(sandbox, monkeypatch):
    """
    回归：首次初始化写入的必须是完整设置字典（不能是“已应用字段列表”），
    随后显式导入源配置时，报告的结果要与实际发生的变更一致。
    """
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  api_key: "sk-init"
  model: "deepseek-chat"
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)
    settings._cache = None
    settings._storage = None

    # 首次加载只写默认值（存进 SQLite）
    data = settings.load()
    assert isinstance(data, dict)
    assert isinstance(settings._store().get("global"), dict)

    # 显式导入把源配置补齐并落库
    result = settings.import_from_source_config(only_empty=True)
    assert result["imported"] is True
    assert "llm.api_key" in result["applied"]
    assert settings._store().get("global")["llm"]["api_key"] == "sk-init"


def test_api_settings_exposes_storage_and_source_info(app_client):
    data = app_client.get("/api/settings").json()
    assert data["storage"]["backend"] == "sqlite"
    assert data["storage"]["database"].endswith("webui.db")
    assert data["storage"]["host_mode"] == "local-only"
    assert "exists" in data["source_config"]


def test_api_settings_export_and_import_roundtrip(app_client):
    """设置可导出为 JSON 并再导入（备份/迁移用）"""
    app_client.patch("/api/settings", json={"defaults": {"learn_count": {"times": 42}}})

    exported = app_client.get("/api/settings/export")
    assert exported.status_code == 200
    payload = json.loads(exported.text)
    assert payload["defaults"]["learn_count"]["times"] == 42

    imported = app_client.post("/api/settings/import", json={
        "content": json.dumps({"defaults": {"learn_count": {"times": 7}}}),
    })
    assert imported.status_code == 200, imported.text
    assert app_client.get("/api/settings").json()["defaults"]["learn_count"]["times"] == 7

    bad = app_client.post("/api/settings/import", json={"content": "not json"})
    assert bad.status_code == 400


def test_api_settings_key_can_actually_be_saved(app_client):
    """
    回归：以前用 "llm.api_key" in updates 判断提交，永远为 False，
    导致设置页提交的新密钥被旧值覆盖，用户根本存不进 API Key。
    """
    response = app_client.patch("/api/settings", json={"llm": {"api_key": "sk-brand-new"}})
    assert response.status_code == 200

    from app import settings as settings_module
    assert settings_module.resolve("llm.api_key") == "sk-brand-new"
    view = app_client.get("/api/settings").json()
    assert view["secrets"]["llm_api_key_configured"] is True
    assert view["llm"]["api_key"] == ""  # 依然不回显

    # 只读回显提交空值不清空
    app_client.patch("/api/settings", json={"llm": {"api_key": "", "model": "m"}})
    assert settings_module.resolve("llm.api_key") == "sk-brand-new"


def test_api_import_source_config(app_client, sandbox, monkeypatch):
    from app import paths, settings

    path = _write_source_config(sandbox, """
llm:
  api_key: "sk-api-import"
  model: "deepseek-chat"
""")
    monkeypatch.setattr(paths, "SOURCE_CONFIG", path)
    settings._cache = None

    response = app_client.post("/api/settings/import-source", json={"only_empty": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] is True
    assert "llm.api_key" in body["applied"]

    view = app_client.get("/api/settings").json()
    assert view["secrets"]["llm_api_key_configured"] is True
    # 密钥依然不回显
    assert view["llm"]["api_key"] == ""


# ============================================================
# 全选相关的模型层保证（前端行为在浏览器验收中检查）
# ============================================================

def test_multi_target_run_generates_one_subtask_per_course(app_client):
    """全选多个账号多个课程时，每个组合生成一个独立子任务"""
    targets = []
    for index in range(3):
        account = app_client.post("/api/accounts", json={
            "username": f"1390000000{index}", "password": "pwd123",
        }).json()
        for course in range(2):
            targets.append({
                "account_id": account["id"], "course_id": f"c{course}",
                "class_id": f"k{index}{course}", "course_name": f"课程{course}",
            })

    response = app_client.post("/api/runs", json={"feature": "video", "targets": targets})
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["count"] == 6

    tasks = app_client.get("/api/tasks?limit=50").json()["items"]
    combos = {(task["account_id"], task["course_id"]) for task in tasks}
    assert len(combos) == 6
