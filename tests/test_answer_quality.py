"""答题缓存/题干乱码检测：字体加密残留必须被拦截，正常生僻词不能误杀。"""

import os
import sys

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (WEBUI_ROOT, CLI_COPY):
    if path not in sys.path:
        sys.path.insert(0, path)

from app import paths, question_bank_manager as bank  # noqa: E402
from core.answer_quality import encoding_issues, question_encoding_issues  # noqa: E402
from core.answer_validation import normalize_answer  # noqa: E402


GARBLED_ANSWER = "忑速忝忔忞忟热处忕为，和"
GARBLED_QUESTION = "忑速忝忔忞忟热处忕为（ ）"
CLEAN_ANSWER = "淬火加高温回火，复杂，综合力学性能"


def _save(question, answer, options=None, qtype="填空题"):
    conn = bank._connect()
    try:
        opts = bank.normalize_options([] if options is None else options)
        bank._immediate_transaction(conn)
        conn.execute(
            """INSERT OR REPLACE INTO question_cache
               (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
               VALUES (?, ?, ?, ?, ?, '', '', ?, 1)""",
            (bank.make_hash(question, opts), question, qtype, opts, answer, 1.0),
        )
        conn.commit()
    finally:
        conn.close()


def test_encoding_issues_flags_font_residue():
    assert encoding_issues("⾦属") == [
        "答案含字体解密残留码位：⾦(U+2FA6)"
    ]
    assert encoding_issues("答\ufffd案")
    assert encoding_issues("Ã©")
    assert encoding_issues(GARBLED_ANSWER)
    assert question_encoding_issues(GARBLED_QUESTION)


def test_encoding_issues_keeps_normal_rare_words():
    # 「饕餮」「魑魅魍魉」属于 GB2312 内的正常生僻词，不能误杀
    for text in ("淬火加高温回火", "马氏体", "魑魅魍魉", "饕餮", "赑屃",
                 "函数在闭区间连续、开区间可导", "this.$store"):
        assert encoding_issues(text) == []


def test_encoding_issues_keeps_traditional_chinese():
    """纯繁体/港台文本不在 GB2312 内，但两套字符集都能覆盖，不能误判成乱码。"""
    for text in ("社會主義核心價值觀", "液壓傳動系統", "繁體中文測試",
                 "電壓損失有百害而無一利", "依據《中華人民共和國憲法》規定"):
        assert encoding_issues(text) == []


def test_encoding_issues_flags_rare_residue_in_sentence():
    """字体残留的典型形状：一句里混进一批两套字符集都装不下的生僻字。"""
    for text in ("崪崫镚崬操作后，list_two崧崭崨",
                 "【单选憍愵】“时愡新愢”愇基本特愗惤( )",
                 "在PLC的面板嵮, POWER嵯嵪嵰嵭表嵪"):
        assert encoding_issues(text)


def test_normalize_answer_rejects_garbled_subjective_answer():
    assert normalize_answer("填空题", GARBLED_ANSWER) == ""
    assert normalize_answer("简答题", GARBLED_ANSWER) == ""
    import unicodedata
    assert normalize_answer("填空题", CLEAN_ANSWER) == unicodedata.normalize(
        "NFKC", CLEAN_ANSWER
    )
    # 客观题只看字母/布尔，不受生僻字检测影响
    assert normalize_answer("判断题", "true") == "true"
    assert normalize_answer("单选题", "B", ["A. x", "B. y"]) == "B"


def test_cache_stats_and_search_mark_suspicious(sandbox):
    _save("正常填空题", CLEAN_ANSWER)
    _save(GARBLED_QUESTION, GARBLED_ANSWER)

    stats = bank.stats()
    assert stats["total"] == 2
    assert stats["suspicious"] == 1  # 一行题干+答案都有残留，只计一次

    items = bank.search(limit=10)["items"]
    by_question = {item["question_text"]: item for item in items}
    assert by_question["正常填空题"]["quality"] == []
    assert by_question[GARBLED_QUESTION]["quality"]


def test_clean_anomalies_only_deletes_suspicious_rows(sandbox):
    _save("正常填空题", CLEAN_ANSWER)
    _save(GARBLED_QUESTION, GARBLED_ANSWER)

    deleted = bank.clean_anomalies()
    assert deleted == 1
    assert bank.stats()["total"] == 1
    assert bank.stats()["suspicious"] == 0
    assert bank.search("正常填空题")["total"] == 1
    assert bank.search(GARBLED_QUESTION)["total"] == 0


def test_worker_cache_lookup_skips_suspicious_rows(sandbox):
    from utils.question_bank import QuestionBank

    worker_bank = QuestionBank(db_path=paths.QUESTION_BANK_FILE)
    try:
        # 模拟旧版本写入的乱码缓存
        worker_bank._conn.execute(
            """INSERT OR REPLACE INTO question_cache
               (hash, question_text, question_type, options, answer, course_id, chapter_id, created_at, hit_count)
               VALUES (?, ?, '填空题', '[]', ?, '', '', ?, 1)""",
            (worker_bank._make_hash(GARBLED_QUESTION, "[]"), GARBLED_QUESTION,
             GARBLED_ANSWER, 1.0),
        )
        worker_bank._conn.commit()
        assert worker_bank.lookup(GARBLED_QUESTION, []) is None

        # 乱码答案也不能新写入
        worker_bank.save("正常题", "填空题", GARBLED_ANSWER, [])
        assert worker_bank.lookup("正常题", []) is None

        worker_bank.save("正常题", "填空题", CLEAN_ANSWER, [])
        assert worker_bank.lookup("正常题", []) == CLEAN_ANSWER
    finally:
        worker_bank.close()


def test_work_form_marks_garbled_question_unreadable():
    from core import work_form

    html = f"""
    <form action="/mooc-ans/work/addStudentWorkNewWeb?x=1">
      <div class="questionLi singleQuesId" data="900001" typename="填空题">
        <input type="hidden" name="answertype900001" value="2">
        <input type="hidden" name="tiankongsize900001" value="1">
        <h3 class="mark_name"><span class="colorShallow">(填空题)</span>{GARBLED_QUESTION}</h3>
        <textarea name="answerEditor9000011"></textarea>
      </div>
    </form>
    """
    questions = work_form.parse_questions(html)
    assert len(questions) == 1
    assert questions[0]["unreadable"] is True
    assert "字体加密" in questions[0]["unreadable_reason"]


def test_bank_anomaly_api(app_client, sandbox):
    _save("正常填空题", CLEAN_ANSWER)
    _save(GARBLED_QUESTION, GARBLED_ANSWER)

    data = app_client.get("/api/question-bank/stats?days=30").json()
    assert data["suspicious"] == 1

    search = app_client.get("/api/question-bank/search?limit=10").json()
    flagged = [item for item in search["items"] if item["quality"]]
    assert len(flagged) == 1

    result = app_client.delete("/api/question-bank/anomalies").json()
    assert result["deleted"] == 1
    assert app_client.get("/api/question-bank/stats?days=30").json()["suspicious"] == 0
