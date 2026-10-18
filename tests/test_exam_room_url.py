"""ExamRoomByUrl 逐题作答流程的单元测试（不访问真实平台）。

用合成答题页驱动「保存本题 → 打开下一题 → 末题交卷」的完整分支。
"""

import json
from types import SimpleNamespace

import pytest

from core import exam_answer_page as page
from functions import exam_room_url as flow

URL = ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?"
       "courseId=244694077&classId=151670988&tId=11021171&id=171477623&p=1&tag=1"
       "&enc=b4acbaa84dfa579ce1c7884985a2eeee&cpi=518380181"
       "&openc=05cd1269b1538587b7c2bbe77668dee9&newMooc=true")


class FakeLog:
    def __init__(self):
        self.lines = []
        self.success_lines = []

    def _record(self, message, *a, **k):
        self.lines.append(str(message))

    debug = _record
    info = _record
    warning = _record
    error = _record

    def success(self, message, *a, **k):
        self._record(message)
        self.success_lines.append(str(message))


class FakeExam:
    """替代 DealExam：只保留 URL 流程用到的接口"""

    def __init__(self, answers=None):
        self.answers = answers or ["C", "true"]
        self.active_unit_id = ""
        self.active_media_name = ""
        self.active_kind = "考试"
        self.emitted = []
        self.saved = []

    def _answer_question(self, question, idx=0, total=0):
        value = self.answers[min(idx - 1, len(self.answers) - 1)]
        if value is None:
            return None
        return {**question, "answer": value, "source": "llm"}

    def _emit_answer_result(self, question, answer, index, total, media_name):
        self.emitted.append((index, total, (answer or {}).get("answer")))

    def _save_submitted_answers(self, answered):
        self.saved = list(answered)


def _question_html(qid, type_code, total, start, stem="题干", options=(("A", "北京"), ("B", "上海"))):
    option_html = "".join(
        f'<div class="clearfix answerBg singleoption" onclick="addChoice(this);">'
        f'<span data="{key}" qid="{qid}" class="addChoice num_option">{key}</span>'
        f'<div class="fl answer_p">{text}</div></div>'
        for key, text in options)
    action = ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew?"
              "keyboardDisplayRequiresUserAction=1&amp;classId=151670988"
              "&amp;courseId=244694077&amp;testPaperId=11021171"
              "&amp;testUserRelationId=171477623")
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{value}">' for name, value in (
            ("remainTime", "5006"), ("encRemainTime", "5006"),
            ("encLastUpdateTime", "1792335387949"), ("type", "0"),
            ("start", str(start)), ("enc", "13a6b9cdffbecb97643971f0e2172706"),
            ("questionId", qid), (f"type{qid}", type_code),
            (f"score{qid}", "10.0"), (f"typeName{qid}", "单选题"),
            (f"answer{qid}", ""), ("tempSave", "false"), ("subCount", ""),
            ("timeOver", "false"), ("paperId", "471087489"), ("userId", "430052849"),
        ))
    return f"""<html><body>
<h2 class="h2_subject">vue3第一章测试题</h2>
<div class="test-info">题量：{total}</div>
<div class="singleQuesId" data="{qid}">
  <h3 class="mark_name colorDeep">{start + 1}.<span class="colorShallow">(单选题, 10.0分)</span> {stem}</h3>
  <div class="splitS-right">{option_html}</div>
</div>
<form id="submitTest" action="{action}" method="post">{hidden}</form>
</body></html>"""


PAGE1 = _question_html("885325008", "0", 10, 0, "Vue.js 的作者来自中国哪个城市?( )",
                       (("A", "北京"), ("B", "上海"), ("C", "无锡"), ("D", "深圳")))
PAGE2 = _question_html("900000001", "3", 2, 1, "Vue3 的响应式系统使用 Proxy。",
                       (("true", "对"), ("false", "错")))


def _room(answers=None, course_id="244694077"):
    room = object.__new__(flow.ExamRoomByUrl)
    room.user = SimpleNamespace(headers={})
    room.course = SimpleNamespace(course_id=course_id, course_name="Vue3 前端开发")
    room.course_name = "Vue3 前端开发"
    room.log = FakeLog()
    room.ui = None
    room.entry = page.parse_exam_url(URL)
    room.exam = FakeExam(answers)
    return room


class TestAnswerAll:
    def test_saves_each_question_and_submits_final(self, monkeypatch):
        calls = {"get": [], "post": []}
        pages = [PAGE2]  # 当前页由调用方传入，GET 只用于取下一题

        def fake_get(url, headers=None, **kwargs):
            calls["get"].append(url)
            return pages.pop(0)

        def fake_post(url, headers=None, data=None, **kwargs):
            calls["post"].append((url, dict(data or {})))
            if "tempSave=false" in url:
                return json.dumps({"msg": "提交成功", "status": "success"}, ensure_ascii=False)
            return json.dumps({"status": "success", "realRemainTime": 5006,
                               "data": "1792335632840|5006|fbcb1ede8f2077a177344eb3b2b5cd5d"},
                              ensure_ascii=False)

        monkeypatch.setattr(flow, "doGet", fake_get)
        monkeypatch.setattr(flow, "doPost", fake_post)
        monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

        room = _room(answers=["C", "true"])
        stats = room._answer_all(page.parse_answer_page(PAGE1), "vue3第一章测试题")

        assert stats["questions"] == 2
        assert stats["submit_ok"] == 2
        assert stats["llm_calls"] == 2
        # 每题先保存（3 次：2 题 + 末题保存后再交卷 1 次）
        assert len(calls["post"]) == 3
        assert "tempSave=true" in calls["post"][0][0]
        assert "tempSave=true" in calls["post"][1][0]
        assert "tempSave=false" in calls["post"][2][0]
        assert calls["post"][0][1]["answer885325008"] == "C"
        assert calls["post"][2][1]["answer900000001"] == "true"
        assert "start=1" in calls["get"][0]
        assert [item[2] for item in room.exam.emitted] == ["C", "true"]
        assert len(room.exam.saved) == 2
        assert any("已交卷" in line for line in room.log.success_lines)

    def test_rejected_save_aborts(self, monkeypatch):
        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE1)
        monkeypatch.setattr(flow, "doPost", lambda url, headers=None, data=None, **k:
                            json.dumps({"status": "error", "msg": "提交失败：无效操作"},
                                       ensure_ascii=False))

        room = _room()
        with pytest.raises(page.ExamUrlError) as err:
            room._answer_all(page.parse_answer_page(PAGE1), "考试")
        assert "无效操作" in str(err.value)
        assert room.exam.saved == []

    def test_already_submitted_stops(self, monkeypatch):
        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE1)
        monkeypatch.setattr(flow, "doPost", lambda url, headers=None, data=None, **k:
                            json.dumps({"status": "submitted"}))

        room = _room()
        stats = room._answer_all(page.parse_answer_page(PAGE1), "考试")
        assert stats["questions"] == 1
        assert stats["submit_ok"] == 1
        assert len(room.exam.saved) == 1

    def test_next_page_not_advancing_aborts(self, monkeypatch):
        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE1)
        monkeypatch.setattr(flow, "doPost", lambda url, headers=None, data=None, **k:
                            json.dumps({"status": "success", "data": "1|2|enc"}))
        monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

        room = _room()
        with pytest.raises(page.ExamUrlError) as err:
            room._answer_all(page.parse_answer_page(PAGE1), "考试")
        assert room.exam.saved == []
        assert "没有前进" in str(err.value)

    def test_missing_answer_aborts_before_submit(self, monkeypatch):
        posts = []
        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE1)
        monkeypatch.setattr(flow, "doPost", lambda url, headers=None, data=None, **k:
                            posts.append(url) or json.dumps({"status": "success"}))

        room = _room(answers=[None])
        with pytest.raises(page.ExamUrlError) as err:
            room._answer_all(page.parse_answer_page(PAGE1), "考试")
        assert "没有拿到可用答案" in str(err.value)
        assert posts == []
        assert room.exam.saved == []

    def test_answer_outside_options_aborts(self, monkeypatch):
        posts = []
        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE1)
        monkeypatch.setattr(flow, "doPost", lambda url, headers=None, data=None, **k:
                            posts.append(url) or json.dumps({"status": "success"}))

        room = _room(answers=["Z"])
        with pytest.raises(page.ExamUrlError) as err:
            room._answer_all(page.parse_answer_page(PAGE1), "考试")
        assert "不在选项" in str(err.value)
        assert posts == []


class TestDoFinish:
    def test_finished_exam_is_reported_without_answering(self, monkeypatch):
        monkeypatch.setattr(flow, "doGet",
                            lambda url, headers=None, **k: "<html><h2>交卷成功</h2></html>")
        room = _room()
        room.do_finish(URL)
        assert any("已交卷完成" in line for line in room.log.lines)
        assert room.exam.emitted == []

    def test_blocked_page_raises(self, monkeypatch):
        monkeypatch.setattr(flow, "doGet",
                            lambda url, headers=None, **k: "<html>无权限访问</html>")
        room = _room()
        with pytest.raises(page.ExamUrlError) as err:
            room.do_finish(URL)
        assert "无权限访问" in str(err.value)

    def test_course_mismatch_raises(self):
        room = _room(course_id="1")
        with pytest.raises(page.ExamUrlError) as err:
            room.do_finish(URL)
        assert "不一致" in str(err.value)

    def test_manual_mode_is_rejected_before_network(self):
        room = _room()
        room.exam.answer_mode = "manual"
        with pytest.raises(page.ExamUrlError) as err:
            room.do_finish(URL)
        assert "AI 作答模式" in str(err.value)

    def test_takes_title_from_page(self, monkeypatch):
        posts = []

        def fake_post(url, headers=None, data=None, **k):
            posts.append(url)
            if "tempSave=false" in url:
                return json.dumps({"msg": "提交成功", "status": "success"}, ensure_ascii=False)
            return json.dumps({"status": "success", "data": "1|2|enc"})

        monkeypatch.setattr(flow, "doGet", lambda url, headers=None, **k: PAGE2)
        monkeypatch.setattr(flow, "doPost", fake_post)
        room = _room(answers=["true"])
        room.do_finish(URL)
        assert room.exam.active_media_name == "vue3第一章测试题"
        assert any("已交卷" in line for line in room.log.success_lines)
