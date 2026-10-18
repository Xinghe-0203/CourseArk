import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import Config
from core.request_client import RequestClient, xpath_first
from functions.deal_exam import DealExam
from functions.deal_media import MediaDownload
from functions.deal_video import DealVideo
from media.video import Video
from utils.llm_client import LLMClient


class _FakeXPathElement:
    def xpath(self, _path):
        return ["first", "second"]


class CoreBehaviorTests(unittest.TestCase):
    def test_xpath_first_really_returns_first_match(self):
        self.assertEqual(xpath_first(_FakeXPathElement(), "ignored"), "first")

    def test_video_finish_response_is_strict(self):
        self.assertTrue(Video.is_passed_response('{"isPassed": true}'))
        self.assertTrue(Video.is_passed_response('{"isPassed": "true"}'))
        self.assertFalse(Video.is_passed_response('{"isPassed": "false"}'))
        self.assertFalse(Video.is_passed_response(""))
        self.assertFalse(Video.is_passed_response("<html>captcha</html>"))

    def test_realtime_video_exact_minute_sends_finish_signal(self):
        class FakeVideo:
            name = "demo"
            calls = []

            def get_status(self):
                return {"duration": 60, "dtoken": "token"}

            def get_url(self, playing_time, duration, _token, play_type):
                self.calls.append((playing_time, duration, play_type))
                return f"https://example.invalid/{play_type}"

        class FakeLog:
            def info(self, *_args): pass
            def error(self, *_args): pass

        class FakeUser:
            headers = {}

        old_data = Config._data
        Config._data = Config._default_config()
        Config._data["video"]["random_progress"] = False
        video = FakeVideo()
        try:
            with patch("functions.deal_video.time.sleep"), patch(
                "functions.deal_video._doGet_with_retry",
                side_effect=["{}", '{"isPassed": true}'],
            ):
                self.assertTrue(DealVideo.run_video(video, FakeUser(), FakeLog()))
        finally:
            Config._data = old_data
        self.assertEqual([call[2] for call in video.calls], [3, 4])

    def test_external_session_has_no_chaoxing_cookie_or_post_retry(self):
        client = RequestClient()
        client.init_from_config(Config._default_config())
        client.session.cookies.set("cx", "secret", domain=".chaoxing.com", path="/")
        prepared = client.external_session.prepare_request(
            __import__("requests").Request("GET", "https://api.example.com/")
        )
        self.assertNotIn("Cookie", prepared.headers)
        retries = client.session.get_adapter("https://").max_retries
        self.assertNotIn("POST", retries.allowed_methods)

    def test_llm_parser_accepts_common_markdown(self):
        client = LLMClient("https://example.invalid", "unused")
        result = client._parse_response("**第1题：E**\n2. AC", 2)
        self.assertEqual(result, ["E", "AC"])

    def test_llm_prompt_carries_course_context(self):
        client = LLMClient("https://example.invalid", "unused")
        prompt = client._build_prompt(
            [{"question_type": "单选题", "question_text": "题干", "options": ["A. 甲", "B. 乙"]}],
            context={"course": "HTML5 APP应用开发", "media": "第4章组件", "kind": "作业"},
        )
        self.assertIn("课程：HTML5 APP应用开发", prompt)
        self.assertIn("作答内容：作业「第4章组件」", prompt)
        self.assertIn("共 1 题", prompt)

    def test_llm_prompt_without_context_has_no_course_line(self):
        client = LLMClient("https://example.invalid", "unused")
        prompt = client._build_prompt([{"question_type": "判断题", "question_text": "题干"}])
        self.assertNotIn("课程：", prompt)
        self.assertTrue(prompt.startswith("共 1 题"))

    def test_llm_strict_mode_appends_instructions(self):
        client = LLMClient("https://example.invalid", "key")
        captured = {}

        def fake_call(prompt, strict=False):
            captured["prompt"] = prompt
            captured["strict"] = strict
            return '{"answers":[{"index":1,"answer":"B"}]}'

        client._call_api = fake_call
        client.answer([{"question_type": "单选题", "question_text": "题干"}], strict=True)
        self.assertTrue(captured["strict"])

    def test_llm_cleans_common_answer_decorations(self):
        client = LLMClient("https://example.invalid", "unused")
        self.assertEqual(client._clean_value("答案：B."), "B")
        self.assertEqual(client._clean_value("(C)"), "C")
        self.assertEqual(client._clean_value("**D**"), "D")
        self.assertEqual(client._clean_value("ABD"), "ABD")     # 多选原样保留
        self.assertEqual(client._clean_value("正确"), "正确")
        self.assertIsNone(client._clean_value("   "))

    def test_llm_parse_ignores_reason_and_fences(self):
        client = LLMClient("https://example.invalid", "unused")
        text = '```json\n{"answers":[{"index":1,"answer":"C","reason":"因为 C 正确"}]}\n```'
        self.assertEqual(client._parse_response(text, 1), ["C"])
        self.assertEqual(client._parse_response('{"answers":[{"index":1,"answer":""}]}', 1), [None])

    def test_deal_exam_answers_with_context_and_retries_strict(self):
        class FakeLLM:
            def __init__(self):
                self.calls = []

            def answer_single(self, question, context=None, strict=False):
                self.calls.append({"context": context, "strict": strict})
                return "" if len(self.calls) == 1 else "B"

        class FakeLog:
            def info(self, *_a): pass
            def warning(self, *_a): pass

        exam = DealExam.__new__(DealExam)
        exam.answer_mode = "ai"
        exam.question_bank = None
        exam.no_answer_action = "skip"
        exam.auto_save = False
        exam.log = FakeLog()
        exam.course_name = "HTML5 APP应用开发"
        exam.active_media_name = "第4章组件"
        exam.active_kind = "作业"
        exam.llm = FakeLLM()
        result = exam._answer_question({
            "question_id": "404552708", "question_type": "单选题",
            "question_text": "挂载完成后调用的是？", "options": ["A. created", "B. mounted"],
            "kind": "choice",
        })
        self.assertEqual(result["answer"], "B")
        self.assertEqual(result["source"], "llm")
        self.assertEqual(len(exam.llm.calls), 2)
        self.assertFalse(exam.llm.calls[0]["strict"])
        self.assertTrue(exam.llm.calls[1]["strict"])
        context = exam.llm.calls[0]["context"]
        self.assertEqual(context["course"], "HTML5 APP应用开发")
        self.assertEqual(context["media"], "第4章组件")
        self.assertEqual(context["kind"], "作业")

    def test_answer_normalization_rejects_ambiguous_judgment(self):
        exam = DealExam.__new__(DealExam)
        self.assertEqual(exam._normalize_answer("判断题", "不确定"), "")
        self.assertEqual(exam._normalize_answer("单选题", "E", ["A", "B", "C", "D", "E"]), "E")
        self.assertEqual(exam._normalize_answer("多选题", "A, C, E", ['A.甲', 'B.乙', 'C.丙', 'D.丁', 'E.戊']), "ACE")
        self.assertEqual(exam._normalize_answer("多选题", "AZ", ['A.甲', 'B.乙']), '')

    def test_invalid_config_is_not_overwritten(self):
        old_data, old_path = Config._data, Config._config_path
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "broken.yml"
                original = "answer: [\n"
                path.write_text(original, encoding="utf-8")
                Config.load(str(path))
                self.assertEqual(path.read_text(encoding="utf-8"), original)
        finally:
            Config._data, Config._config_path = old_data, old_path

    def test_download_path_component_is_sanitized(self):
        self.assertEqual(MediaDownload._safe_component("../course", "fallback"), "course")
        self.assertEqual(MediaDownload._safe_component("CON", "fallback"), "fallback")

    def test_video_get_url_includes_face_capture_params(self):
        attachment = {
            "objectId": "obj1",
            "otherInfo": "nodeId_1",
            "videoFaceCaptureEnc": "face-enc",
            "attDuration": 120,
            "attDurationEnc": "att-enc",
        }
        defaults = {"clazzId": "c1", "userid": "u1", "reportUrl": "https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/cpi"}
        video = Video(attachment, {"User-Agent": "t"}, defaults, "course1")
        url = video.get_url(0, 120, "dtoken", 3)
        self.assertIn("videoFaceCaptureEnc=face-enc", url)
        self.assertIn("attDuration=120", url)
        self.assertIn("attDurationEnc=att-enc", url)
        self.assertIn("isdrag=3", url)

    def test_video_get_url_omits_absent_face_capture_params(self):
        attachment = {"objectId": "obj1", "otherInfo": "nodeId_1"}
        defaults = {"clazzId": "c1", "userid": "u1", "reportUrl": "https://x/log/a/cpi"}
        video = Video(attachment, {"User-Agent": "t"}, defaults, "course1")
        url = video.get_url(0, 120, "dtoken", 4)
        self.assertNotIn("videoFaceCaptureEnc", url)
        self.assertNotIn("attDuration", url)
        self.assertIn("isdrag=4", url)

    def test_video_rt_override_applies_to_url(self):
        attachment = {"objectId": "obj1", "otherInfo": "nodeId_1"}
        defaults = {"clazzId": "c1", "userid": "u1", "reportUrl": "https://x/log/a/cpi"}
        video = Video(attachment, {"User-Agent": "t"}, defaults, "course1")
        self.assertIn("&rt=1&", video.get_url(0, 10, "d", 3, rt=1))
        self.assertIn("&rt=0.9&", video.get_url(0, 10, "d", 3, rt=0.9))

    def test_video_forbidden_detection(self):
        self.assertTrue(Video.is_forbidden_response("<html>antispiderShowVerify</html>"))
        self.assertTrue(Video.is_forbidden_response("请输入验证码"))
        self.assertFalse(Video.is_forbidden_response('{"isPassed": false}'))

    def test_video_do_finish_falls_back_to_next_rt_on_captcha(self):
        class _Log:
            def debug(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): pass

        attachment = {"objectId": "obj1", "otherInfo": "nodeId_1"}
        defaults = {"clazzId": "c1", "userid": "u1", "reportUrl": "https://x/log/a/cpi"}
        video = Video(attachment, {"User-Agent": "t"}, defaults, "course1")
        # 强制无rt解析结果，触发 [0.9, 1] 两轮候选
        video.rt = None

        calls = []

        def fake_get(url, headers):
            calls.append(url)
            # 第一轮（rt=0.9）被验证码拦截，第二轮（rt=1）成功
            if "rt=0.9" in url:
                return "antispiderShowVerify"
            return '{"isPassed": true}'

        with patch("media.video.Video.get_status", return_value={"duration": 60, "dtoken": "d"}), \
             patch("media.video.doGet", side_effect=fake_get):
            self.assertTrue(video.do_finish())
        self.assertTrue(any("rt=0.9" in u for u in calls))
        self.assertTrue(any("rt=1" in u for u in calls))


    def test_realtime_video_resumes_from_recorded_playtime(self):
        class FakeVideo:
            name = "demo"
            calls = []
            attachment = {"playTime": 30000}  # 已观看30秒

            def get_status(self):
                return {"duration": 60, "dtoken": "token"}

            def get_url(self, playing_time, duration, _token, play_type, rt=None):
                self.calls.append((playing_time, play_type))
                return f"https://example.invalid/{play_type}"

        class FakeLog:
            def info(self, *_args): pass
            def error(self, *_args): pass

        class FakeUser:
            headers = {}

        old_data = Config._data
        Config._data = Config._default_config()
        Config._data["video"]["random_progress"] = False
        video = FakeVideo()
        try:
            with patch("functions.deal_video.time.sleep"), patch(
                "functions.deal_video._doGet_with_retry",
                side_effect=["{}", '{"isPassed": true}'],
            ):
                self.assertTrue(DealVideo.run_video(video, FakeUser(), FakeLog()))
        finally:
            Config._data = old_data
        # 起始信号从断点30秒开始，随后到达终点结算
        self.assertEqual(video.calls[0], (30, 3))
        self.assertEqual(video.calls[-1], (60, 4))

    def test_parse_work_list_extracts_independent_homework(self):
        html = """
        <div class="bottomList">
          <ul>
            <li data="https://mooc1.chaoxing.com/mooc2/work/dowork?courseId=1&classId=2&workId=555&answerId=999&enc=abc">
              <p class="overHidden2 fl">第一次平时作业</p>
              <p class="status">未交</p>
              <div class="time notOver">剩余3天</div>
            </li>
            <li data="https://mooc1.chaoxing.com/mooc2/work/dowork?courseId=1&classId=2&workId=556&answerId=1000&enc=def">
              <p class="overHidden2 fl">第二次平时作业</p>
              <p class="status">已完成</p>
              <div class="time notOver icon-before-g">已过期</div>
            </li>
          </ul>
        </div>
        """
        from models.course import Course
        items = Course._parse_work_list(html)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["work_id"], "555")
        self.assertEqual(items[0]["answer_id"], "999")
        self.assertEqual(items[0]["title"], "第一次平时作业")
        self.assertTrue(items[0]["valid"])
        # 第二条带 icon-*-g 过期标记
        self.assertFalse(items[1]["valid"])

    def test_work_list_does_not_mark_normal_items_expired(self):
        """
        回归：过期判定曾用 contains(@class,'-g')，任何含 "-g" 子串的 class 都会命中，
        导致正常作业被判为已过期而整批跳过（表现为“共 N 个独立作业，其中 0 个待处理”）。
        """
        from models.course import Course
        html = """
        <div class="bottomList">
          <ul>
            <li data="?workId=601&answerId=1">
              <p class="overHidden2">正常作业A</p>
              <p class="status">未交</p>
              <div class="time notOver icon-before">剩余5天</div>
            </li>
            <li data="?workId=602&answerId=2">
              <p class="overHidden2">正常作业B</p>
              <p class="status">未交</p>
              <div class="time notOver icon-group">剩余2天</div>
            </li>
          </ul>
        </div>
        """
        items = Course._parse_work_list(html)
        self.assertEqual(len(items), 2)
        # 只有以 -g 结尾的 class 才代表过期，-before / -group 不应命中
        self.assertTrue(items[0]["valid"], "icon-before 不应被判为过期")
        self.assertTrue(items[1]["valid"], "icon-group 不应被判为过期")

    def test_work_list_marks_expired_by_class_suffix_or_text(self):
        from models.course import Course
        html = """
        <div class="bottomList">
          <ul>
            <li data="?workId=701&answerId=1">
              <p class="overHidden2">过期作业</p>
              <div class="time notOver icon-before-g">剩余0天</div>
            </li>
            <li data="?workId=702&answerId=2">
              <p class="overHidden2">文案过期作业</p>
              <div class="time">已过期</div>
            </li>
          </ul>
        </div>
        """
        items = Course._parse_work_list(html)
        self.assertFalse(items[0]["valid"])
        self.assertFalse(items[1]["valid"])

    def test_parse_work_list_deduplicates_and_handles_empty(self):
        from models.course import Course
        self.assertEqual(Course._parse_work_list(""), [])
        html = ('<div class="bottomList"><ul>'
                '<li data="?workId=1"><p class="overHidden2">A</p></li>'
                '<li data="?workId=1"><p class="overHidden2">A重复</p></li>'
                '</ul></div>')
        items = Course._parse_work_list(html)
        self.assertEqual(len(items), 1)

    def test_job_id_from_work(self):
        from functions.deal_exam import job_id_from_work
        self.assertEqual(job_id_from_work("555"), "work-555")
        self.assertEqual(job_id_from_work("work-555"), "work-555")
        self.assertEqual(job_id_from_work(""), "")

    def test_media_name_strips_font_encryption_html(self):
        """
        回归：字体反爬会在任务点名称里留下 <font color=Red> 之类的标签，
        日志与界面会直接显示成源码（例如 “[FAIL] <font color=Red>材料</font>制备…”）。
        """
        from functions.deal_course import _clean_name
        self.assertEqual(
            _clean_name("<font color=Red>材料</font>制备新技术绪论（上）"),
            "材料制备新技术绪论（上）")
        self.assertEqual(_clean_name("正常视频名"), "正常视频名")
        self.assertEqual(_clean_name("A&nbsp;B"), "A B")
        self.assertIsNone(_clean_name(None))
        self.assertIsNone(_clean_name("   "))

    def _make_exam(self):
        from functions.deal_exam import DealExam

        exam = DealExam.__new__(DealExam)
        exam.course_id = "266056498"
        exam.class_id = "151893764"
        exam.cpi = "496369168"
        exam.headers = {}
        exam.log = _StubLog()
        exam.submit_delay = 0
        exam.auto_save = False
        exam.question_bank = None
        exam.user = type("U", (), {"uid": "413263029"})()
        return exam

    def test_submit_replays_page_form(self):
        """
        回归：学习通作业页的真实表单是
        action="/mooc-ans/work/addStudentWorkNewWeb?_classId=..&courseid=..&token=..&totalQuestionNum=.."
        且浏览器提交前会用 version() 追加 ua/formType/saveStatus/version 参数。
        忽略页面表单（改打别处或丢掉查询串里的令牌）会得到“无效的参数：code-2”。
        """
        import json as _json
        from unittest.mock import patch

        from core.config import Config
        from functions.deal_exam import DealExam

        exam = self._make_exam()
        captured = {}

        def fake_post(url, headers=None, data=None, if_full_back=False):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return _json.dumps({"status": True})

        page_form = {
            "found": True,
            "action": ("https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
                       "?_classId=151893764&courseid=266056498&token=2c292aeb00e3f15e"
                       "&totalQuestionNum=6eaca1bf84b6b650bc4b09d8f8805f1e&wMicroNodeId="),
            "method": "post",
            "controls": {
                "courseId": "266056498", "classId": "151893764",
                "cpi": "496369168", "workRelationId": "55459339",
                "totalQuestionNum": "6eaca1bf84b6b650bc4b09d8f8805f1e",
                "answerwqbid": "",
            },
        }

        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.doGet", return_value=""), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                ok, fail = exam._submit_answers(
                    work_id="55459339",
                    answered=[{
                        "question_id": "111", "question_type": "单选题",
                        "answer": "B", "question_text": "题", "options": [],
                        "kind": "choice", "answer_type": "0",
                    }],
                    defaults={"clazzId": "151893764", "knowledgeid": "1219259997"},
                    jobid="work-55459339",
                    enc="2c292aeb00e3f15e16910622fc0070cd",
                    ktoken=None,
                    hidden_fields={"totalQuestionNum":
                                   "6eaca1bf84b6b650bc4b09d8f8805f1e"},
                    page_form=page_form,
                    page_url=("https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task"
                              "?courseId=266056498&workId=55459339"),
                )
        finally:
            Config._data = old_data

        self.assertEqual((ok, fail), (1, 0))
        # 端点与令牌来自页面表单
        self.assertTrue(captured["url"].startswith(
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb?"))
        self.assertIn("token=2c292aeb00e3f15e", captured["url"])
        self.assertIn("version=1", captured["url"])
        self.assertIn("ua=pc", captured["url"])
        body = captured["data"]
        self.assertEqual(body["answer111"], "B")
        self.assertEqual(body["answertype111"], "0")
        self.assertEqual(body["courseId"], "266056498")
        self.assertEqual(body["answerwqbid"], "111,")
        self.assertEqual(body["totalQuestionNum"],
                         "6eaca1bf84b6b650bc4b09d8f8805f1e")
        self.assertIn("mooc-ans/mooc2/work/task", captured["headers"]["Referer"])

    def test_submit_falls_back_to_legacy_endpoint(self):
        """页面拿不到表单时，回退到兼容端点，参数全部放表单体。"""
        import json as _json
        from unittest.mock import patch

        from core.config import Config
        from functions.deal_exam import SUBMIT_URL

        exam = self._make_exam()
        captured = {}

        def fake_post(url, headers=None, data=None, if_full_back=False):
            captured["url"] = url
            captured["data"] = data
            return _json.dumps({"status": True})

        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.doGet", return_value=""), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                ok, fail = exam._submit_answers(
                    work_id="55459339",
                    answered=[{
                        "question_id": "111", "question_type": "单选题",
                        "answer": "B", "question_text": "题", "options": [],
                    }],
                    defaults={"clazzId": "151893764", "knowledgeid": "1219259997"},
                    jobid="work-55459339",
                    enc="2c292aeb00e3f15e16910622fc0070cd",
                    ktoken=None,
                    hidden_fields={"totalQuestionNum":
                                   "6eaca1bf84b6b650bc4b09d8f8805f1e"},
                )
        finally:
            Config._data = old_data

        self.assertEqual((ok, fail), (1, 0))
        self.assertEqual(captured["url"], SUBMIT_URL)
        self.assertNotIn("?", captured["url"])
        body = captured["data"]
        self.assertEqual(body["answer111"], "B")
        self.assertEqual(body["answertype111"], "0")
        self.assertEqual(body["courseId"], "266056498")
        self.assertEqual(body["workid"], "55459339")
        self.assertEqual(body["totalQuestionNum"],
                         "6eaca1bf84b6b650bc4b09d8f8805f1e")

    def test_submit_blocked_when_captcha_required(self):
        """提交前校验返回 2（需要验证码）时不发提交请求，给出可读原因。"""
        import json as _json
        from unittest.mock import patch

        from core.config import Config

        exam = self._make_exam()
        posted = []

        def fake_post(url, headers=None, data=None, if_full_back=False):
            posted.append(url)
            return _json.dumps({"status": True})

        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.doGet",
                       return_value=_json.dumps({"status": 2})), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                ok, fail = exam._submit_answers(
                    work_id="55459339",
                    answered=[{"question_id": "111", "question_type": "单选题",
                               "answer": "B", "question_text": "题", "options": []}],
                    defaults={"clazzId": "151893764", "knowledgeid": ""},
                    jobid="work-55459339",
                    enc="x",
                    ktoken=None,
                    hidden_fields={"totalQuestionNum": "6eaca1bf84b6b650bc4b09d8f8805f1e"},
                )
        finally:
            Config._data = old_data

        self.assertEqual((ok, fail), (0, 1))
        self.assertEqual(posted, [])

    def test_submit_prefers_page_form_token_over_question_count(self):
        """totalQuestionNum 是服务端令牌：缺表单时不能拿题数顶替。"""
        import json as _json
        from unittest.mock import patch

        from core.config import Config

        exam = self._make_exam()
        captured = {}

        def fake_post(url, headers=None, data=None, if_full_back=False):
            captured["data"] = data
            return _json.dumps({"status": True})

        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.doGet", return_value=""), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                exam._submit_answers(
                    work_id="55459339",
                    answered=[{"question_id": "111", "question_type": "单选题",
                               "answer": "B", "question_text": "题", "options": []},
                              {"question_id": "222", "question_type": "单选题",
                               "answer": "A", "question_text": "题2", "options": []}],
                    defaults={"clazzId": "151893764", "knowledgeid": ""},
                    jobid="work-55459339",
                    enc="x",
                    ktoken=None,
                    hidden_fields={},
                )
        finally:
            Config._data = old_data

        self.assertNotEqual(captured["data"].get("totalQuestionNum"), "2")


class _StubLog:
    def __getattr__(self, _name):
        return lambda *a, **k: None


if __name__ == "__main__":
    unittest.main()
