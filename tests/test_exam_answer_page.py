"""答题页解析与提交报文构造的单元测试（纯离线，不发请求）。"""

import json

import pytest

from core import exam_answer_page as page

URL = ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?"
       "courseId=244694077&classId=151670988&tId=11021171&id=171477623&p=1&tag=1"
       "&enc=b4acbaa84dfa579ce1c7884985a2eeee&cpi=518380181"
       "&openc=05cd1269b1538587b7c2bbe77668dee9&newMooc=true")


def _question_html(qid="885325008", type_code="0", stem="Vue.js 的作者来自中国哪个城市?( )",
                   options=(("A", "北京"), ("B", "上海"), ("C", "无锡"), ("D", "深圳"))):
    option_html = "".join(
        f'<div class="clearfix answerBg singleoption" onclick="addChoice(this);">'
        f'<span data="{key}" qid="{qid}" class="addChoice num_option">{key}</span>'
        f'<div class="fl answer_p">{text}</div></div>'
        for key, text in options)
    form_action = ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew?"
                   "keyboardDisplayRequiresUserAction=1&amp;classId=151670988"
                   "&amp;courseId=244694077&amp;testPaperId=11021171"
                   "&amp;testUserRelationId=171477623")
    return f"""<html><body>
<h2 class="h2_subject">vue3第一章测试题</h2>
<div class="test-info">题量：10 剩余时间 100:00</div>
<div class="singleQuesId" data="{qid}">
  <h3 class="mark_name colorDeep">1.<span class="colorShallow">(单选题, 10.0分)</span> {stem}</h3>
  <div class="splitS-right">{option_html}</div>
</div>
<form id="submitTest" action="{form_action}" method="post">
  <input type="hidden" name="remainTime" value="5251">
  <input type="hidden" name="encRemainTime" value="5251">
  <input type="hidden" name="encLastUpdateTime" value="1792335387949">
  <input type="hidden" name="type" value="0">
  <input type="hidden" name="start" value="0">
  <input type="hidden" name="enc" value="13a6b9cdffbecb97643971f0e2172706">
  <input type="hidden" name="questionId" value="{qid}">
  <input type="hidden" name="type{qid}" value="{type_code}">
  <input type="hidden" name="score{qid}" value="10.0">
  <input type="hidden" name="typeName{qid}" value="单选题">
  <input type="hidden" name="answer{qid}" value="">
  <input type="hidden" name="tempSave" value="false">
  <input type="hidden" name="subCount" value="">
  <input type="hidden" name="timeOver" value="false">
  <input type="hidden" name="paperId" value="471087489">
  <input type="hidden" name="userId" value="430052849">
</form>
</body></html>"""


class TestParseExamUrl:
    def test_accepts_real_answer_page_url(self):
        entry = page.parse_exam_url(URL)
        assert entry["course_id"] == "244694077"
        assert entry["class_id"] == "151670988"
        assert entry["exam_id"] == "11021171"
        assert entry["relation_id"] == "171477623"
        assert entry["cpi"] == "518380181"
        assert entry["enc"] == "b4acbaa84dfa579ce1c7884985a2eeee"

    def test_scheme_less_url_is_completed(self):
        assert page.parse_exam_url("//mooc1.chaoxing.com" + URL.split(".com", 1)[1])["exam_id"]

    def test_rejects_empty(self):
        with pytest.raises(page.ExamUrlError):
            page.parse_exam_url("   ")

    def test_rejects_other_site(self):
        with pytest.raises(page.ExamUrlError):
            page.parse_exam_url("https://example.com/exam-ans/exam/test/"
                                "reVersionTestStartNew?courseId=1&classId=2&tId=3&id=4")

    def test_rejects_exam_list_page(self):
        with pytest.raises(page.ExamUrlError):
            page.parse_exam_url("https://mooc1.chaoxing.com/exam/test"
                                "?courseId=1&classId=2&enc=x")

    def test_rejects_missing_ids(self):
        with pytest.raises(page.ExamUrlError):
            page.parse_exam_url("https://mooc1.chaoxing.com/exam-ans/exam/test/"
                                "reVersionTestStartNew?courseId=1&classId=2")


class TestParseAnswerPage:
    def test_parses_question_and_form(self):
        result = page.parse_answer_page(_question_html())
        assert result["qid"] == "885325008"
        assert result["type_code"] == "0"
        assert result["type_name"] == "单选题"
        assert result["total"] == 10
        assert result["index"] == 0
        assert result["remain"] == "5251"
        assert result["media"] == "vue3第一章测试题"
        assert result["finished"] is False
        assert result["blocked"] == ""
        assert "Vue.js 的作者来自中国哪个城市" in result["stem"]
        assert "单选题" not in result["stem"]
        assert result["stem"].startswith("Vue.js")
        assert result["options"] == [
            {"key": "A", "text": "北京"}, {"key": "B", "text": "上海"},
            {"key": "C", "text": "无锡"}, {"key": "D", "text": "深圳"},
        ]

    def test_extracts_judge_question(self):
        result = page.parse_answer_page(_question_html(
            qid="900000001", type_code="3", stem="Vue3 的响应式系统使用 Proxy。",
            options=(("true", "对"), ("false", "错"))))
        assert result["type_code"] == "3"
        assert [item["key"] for item in result["options"]] == ["true", "false"]

    def test_form_action_and_fields(self):
        result = page.parse_answer_page(_question_html())
        assert "reVersionSubmitTestNew" in result["form_action"]
        assert result["fields"]["userId"] == "430052849"
        assert result["fields"]["paperId"] == "471087489"

    def test_finished_page(self):
        result = page.parse_answer_page("<html><body><h2>交卷成功</h2></body></html>")
        assert result["finished"] is True
        assert result["fields"] == {}

    def test_blocked_page(self):
        result = page.parse_answer_page("<html><body>无权限访问</body></html>")
        assert result["finished"] is False
        assert result["blocked"] == "无权限访问"


class TestQuestionFromPage:
    def test_builds_llm_question(self):
        question = page.question_from_page(page.parse_answer_page(_question_html()))
        assert question["question_id"] == "885325008"
        assert question["question_type"] == "单选题"
        assert question["options"][2] == "C. 无锡"


class TestBuildSubmission:
    def test_submit_query_drops_ui_only_param(self):
        result = page.parse_answer_page(_question_html())
        query = page.submit_query(result["form_action"], cpi="518380181", temp_save=True)
        assert "keyboardDisplayRequiresUserAction" not in query
        assert query["tempSave"] == "true"
        assert query["version"] == "1"
        assert query["cpi"] == "518380181"
        assert query["testPaperId"] == "11021171"
        assert query["testUserRelationId"] == "171477623"

    def test_submit_url_target(self):
        result = page.parse_answer_page(_question_html())
        url = page.submit_url(result["form_action"], cpi="518380181", temp_save=False)
        assert url.startswith(page.SUBMIT_HOST + page.SUBMIT_PATH + "?")
        assert "tempSave=false" in url
        assert "keyboardDisplayRequiresUserAction" not in url

    def test_submit_data_fills_answer(self):
        result = page.parse_answer_page(_question_html())
        data = page.build_submit_data(result, "C", temp_save=False)
        assert data["answer885325008"] == "C"
        assert data["tempSave"] == "false"
        assert data["isAnswered"] == "true"
        assert data["questionId"] == "885325008"

    def test_parse_submit_success(self):
        result = page.parse_submit_response(json.dumps({
            "msg": "提交成功", "realRemainTime": 5006,
            "data": "1792335632840|5006|fbcb1ede8f2077a177344eb3b2b5cd5d",
            "status": "success"}))
        assert result["ok"] is True
        assert result["data"].split("|")[2] == "fbcb1ede8f2077a177344eb3b2b5cd5d"
        assert result["real_remain_time"] == 5006

    def test_parse_submit_rejection(self):
        result = page.parse_submit_response(json.dumps({
            "status": "error", "msg": "提交失败：无效操作"}, ensure_ascii=False))
        assert result["ok"] is False
        assert "无效操作" in result["msg"]

    def test_parse_submit_html_response_is_failure(self):
        assert page.parse_submit_response("<html>login</html>")["ok"] is False

    def test_build_next_url(self):
        entry = page.parse_exam_url(URL)
        url = page.build_next_url(entry, "1792335632840|5006|fbcb1ede8f2077", 1)
        assert url.startswith(page.SUBMIT_HOST + page.ANSWER_PAGE_PATH + "?")
        assert "getTheNextQuestion=1" in url
        assert "start=1" in url
        assert "relationAnswerLastUpdateTime=1792335632840" in url
        assert "remainTimeParam=5006" in url
        assert "enc=fbcb1ede8f2077" in url
        assert "tId=11021171" in url


class TestNormalizeAnswer:
    @pytest.mark.parametrize("code,raw,expected", [
        ("0", "c", "C"),
        ("0", "B.", "B"),
        ("1", "c,a", "AC"),
        ("1", "B A", "AB"),
        ("3", "正确", "true"),
        ("3", "A", "true"),
        ("3", "错误", "false"),
        ("3", "B", "false"),
        ("3", "true", "true"),
        ("3", "false", "false"),
        ("4", "答案：组件化", "组件化"),
    ])
    def test_normalize(self, code, raw, expected):
        assert page.normalize_answer(code, raw) == expected

    def test_empty(self):
        assert page.normalize_answer("0", "  ") == ""
