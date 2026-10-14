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
from utils.tiku_provider import TikuProvider


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

    def test_tiku_letter_matching_supports_more_than_abcd(self):
        self.assertEqual(TikuProvider.match_answer_to_options("E", ["A", "B", "C", "D", "E"]), "E")
        self.assertEqual(TikuProvider.match_answer_to_options("A, C, E", ["A", "B", "C", "D", "E"]), "ACE")

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

    def test_submit_uses_form_body_and_correct_endpoint(self):
        """
        回归：提交曾 POST 到 addStudentWorkNewWeb 并把参数拼在查询串，
        服务端返回“无效的参数：code-2”。
        正确做法：POST addStudentWorkNew，参数全部放在表单体。
        """
        import json as _json
        from unittest.mock import patch

        from core.config import Config
        from functions import deal_exam as mod
        from functions.deal_exam import DealExam, SUBMIT_URL

        self.assertEqual(
            SUBMIT_URL, "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew")
        self.assertNotIn("addStudentWorkNewWeb", SUBMIT_URL)

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

        captured = {}

        def fake_post(url, headers=None, data=None, if_full_back=False):
            captured["url"] = url
            captured["data"] = data
            return _json.dumps({"status": True})

        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                ok, fail = exam._submit_answers(
                    work_id="55459339",
                    answered=[{
                        "question_id": "111", "question_type": "单选题",
                        "answer": "B", "question_text": "题", "options": [],
                    }],
                    defaults={"clazzId": "151893764", "knowledgeid": "1219259997"},
                    jobid="work-ccda3756a98e4e78956fb88f4ae515ef",
                    enc="2c292aeb00e3f15e16910622fc0070cd",
                    ktoken=None,
                    hidden_fields={"totalQuestionNum":
                                   "6eaca1bf84b6b650bc4b09d8f8805f1e"},
                )
        finally:
            Config._data = old_data

        self.assertEqual(fail, 0)
        self.assertEqual(ok, 1)
        # 端点上不带查询参数
        self.assertNotIn("?", captured["url"])
        # 关键参数在表单体里
        body = captured["data"]
        self.assertEqual(body["answer111"], "B")
        self.assertEqual(body["answertype111"], "0")
        self.assertEqual(body["courseId"], "266056498")
        self.assertEqual(body["classId"], "151893764")
        self.assertEqual(body["workid"], "55459339")
        # totalQuestionNum 必须原样透传服务端下发的值，而不是被改写
        self.assertEqual(body["totalQuestionNum"],
                         "6eaca1bf84b6b650bc4b09d8f8805f1e")


class _StubLog:
    def __getattr__(self, _name):
        return lambda *a, **k: None


if __name__ == "__main__":
    unittest.main()
