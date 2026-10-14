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
        self.assertEqual(exam._normalize_answer("多选题", "A, C, E"), "ACE")

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


if __name__ == "__main__":
    unittest.main()
