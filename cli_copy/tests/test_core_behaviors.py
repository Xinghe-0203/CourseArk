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

    def test_relative_action_resolves_against_page_url(self):
        """回归（2026-11）：章节测验提交打到 /addStudentWorkNewWeb 直接 404。

        根因：测验表单内嵌在 /mooc-ans/work/doHomeWorkNew 文档里，action 是
        不带前导斜杠的相对地址；此前 absolute_action 一律按域名根解析，
        丢掉 /mooc-ans/work/ 前缀后 POST 被 302→404。
        """
        from core.work_form import absolute_action, parse_form

        # 1) 带 base_url 的相对 action：按页面文档地址解析
        resolved = absolute_action(
            "addStudentWorkNewWeb?_classId=151670988&courseid=244694077&token=t",
            "https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?workId=1")
        self.assertEqual(
            resolved,
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
            "?_classId=151670988&courseid=244694077&token=t")

        # 2) 没有 base_url 的相对 action：已知端点兜底归位到规范路径
        self.assertEqual(
            absolute_action("addStudentWorkNewWeb?_classId=1&token=t"),
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
            "?_classId=1&token=t")

        # 3) 解析到 /work/ 但缺 mooc-ans 前缀：同样归位
        self.assertEqual(
            absolute_action("/work/addStudentWorkNewWeb?_classId=1"),
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
            "?_classId=1")

        # 4) 页面本来就是规范绝对地址：原样保留
        absolute = ("https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
                    "?_classId=1&token=t")
        self.assertEqual(absolute_action(absolute), absolute)
        self.assertEqual(absolute_action(absolute, "https://x.example.com/"), absolute)

        # 5) parse_form 透传 base_url
        html = ('<form id="submitForm" method="post" '
                'action="addStudentWorkNewWeb?_classId=1&token=t">'
                '<input type="hidden" name="courseId" value="1"></form>')
        form = parse_form(html, base_url="https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew")
        self.assertTrue(form["found"])
        self.assertTrue(form["action"].startswith(
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"))

    def test_request_exception_reports_real_method(self):
        """POST 失败的日志标签必须是 POST——此前硬编码 GET 误导排查方向。"""
        from types import SimpleNamespace

        from core.request_client import RequestClient

        client = RequestClient()
        client._if_delay = False
        response = SimpleNamespace(status_code=404, url="https://x/example", text="")
        with self.assertRaises(Exception) as ctx:
            client._handle_response(response, "https://x/example", False, method=1)
        self.assertIn("Method: POST", str(ctx.exception))

    def test_judgment_answer_shorthands_are_accepted(self):
        """回归（2026-11）：LLM 答判断题返回 F/T 时被校验器判无效而随机作答。

        日志证据：LLM 原始返回 "F"（正确），重试仍 "F"，最后
        「LLM 返回内容无法用于该题型: F → true (随机)」。归一化必须收编这些变体。
        """
        from core.answer_validation import normalize_answer

        for raw, expect in [("F", "false"), ("T", "true"), ("f", "false"),
                            ("（F）", "false"), ("T.", "true"),
                            ("Ｆ", "false"),  # 全角 F
                            ("false", "false"), ("对", "true"), ("×", "false")]:
            self.assertEqual(normalize_answer("判断题", raw), expect, raw)

    def test_choice_answer_wrapped_decorations_are_accepted(self):
        from core.answer_validation import normalize_answer

        options = ["A. props", "B. state", "C. mutation"]
        self.assertEqual(normalize_answer("单选题", "（A）", options), "A")
        self.assertEqual(normalize_answer("单选题", "B。", options), "B")
        self.assertEqual(normalize_answer("单选题", "Ａ", options), "A")  # 全角

    def test_stem_normalizes_radicals_and_type_marks(self):
        """题干解析：康熙部首字符归位为常规汉字；[单选题] 类标记不再残留。"""
        from core.work_form import _clean_stem, norm_text

        # 字体解密会把「自」还原成康熙部首 ⾃（U+2F80 区段）
        self.assertEqual(norm_text("⾃定义主题"), "自定义主题")
        self.assertEqual(_clean_stem("[单选题]下列关于Vue说法错误的是?"),
                         "下列关于Vue说法错误的是?")
        self.assertEqual(_clean_stem("（判断题）Vue是渐进式框架"), "Vue是渐进式框架")

    # ---------------- 批量作答与提交重试（2026-11 完善） ----------------

    def _make_bare_exam(self, no_answer_action="random"):
        """构造只带答题链路所需属性的对象（不经 __init__ 的网络初始化）。"""
        from functions.deal_exam import DealExam

        class FakeLog:
            def info(self, *_a): pass
            def warning(self, *_a): pass
            def error(self, *_a): pass
            def debug(self, *_a): pass

        exam = DealExam.__new__(DealExam)
        exam.answer_mode = "ai"
        exam.question_bank = None
        exam.no_answer_action = no_answer_action
        exam.auto_save = False
        exam.log = FakeLog()
        exam.course_name = "HTML5 APP应用开发"
        exam.active_media_name = "12.6 章节测试6"
        exam.active_kind = "作业"
        exam.active_chapter_name = "第三章 Vuex状态管理"
        exam.active_unit_id = ""
        exam.llm_batch_size = 6
        return exam

    def test_batch_answering_resolves_in_one_call(self):
        """批量作答：6 题一次 LLM 调用解析完成，不再逐题调用。"""
        exam = self._make_bare_exam()
        questions = [
            {"question_id": f"q{i}", "question_type": "单选题",
             "question_text": f"题{i}", "options": ["A. 甲", "B. 乙"], "kind": "choice"}
            for i in range(1, 7)
        ]

        class FakeLLM:
            calls = []

            def answer(self, qs, context=None, strict=False):
                self.calls.append({"count": len(qs), "strict": strict,
                                   "context": context})
                return ["A"] * len(qs)

            def answer_single(self, *_a, **_k):  # 不应被调用
                raise AssertionError("批量成功时不应回退逐题调用")

        exam.llm = FakeLLM()
        results = exam._answer_batch(questions)
        self.assertEqual(len(FakeLLM.calls), 1)
        self.assertEqual([r["answer"] for r in results], ["A"] * 6)
        self.assertTrue(all(r["source"] == "llm" for r in results))
        # 课程 + 章节 + 作答内容都进上下文
        context = FakeLLM.calls[0]["context"]
        self.assertEqual(context["course"], "HTML5 APP应用开发")
        self.assertEqual(context["extra"], "所属章节：第三章 Vuex状态管理")

    def test_batch_answering_all_failed_falls_back_without_per_question_llm(self):
        """批量全败：不再对每题发起注定失败的 LLM 调用，直接走随机兜底。"""
        exam = self._make_bare_exam(no_answer_action="random")
        questions = [
            {"question_id": f"q{i}", "question_type": "判断题",
             "question_text": f"判断题{i}", "options": [], "kind": "choice"}
            for i in range(1, 5)
        ]

        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def answer(self, qs, context=None, strict=False):
                self.calls += 1
                return [None] * len(qs)

        exam.llm = FakeLLM()
        results = exam._answer_batch(questions)
        self.assertEqual(exam.llm.calls, 2)  # 首次 + 整批严格重试，无逐题调用
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r and r["source"] == "random" for r in results))

    def test_answerable_rejects_rare_glyph_residue(self):
        """字体加密残留的题干必须判不可读，避免模型照抄生出乱码答案。"""
        exam = self._make_bare_exam(no_answer_action="skip")
        garbled = {"question_id": "1", "question_type": "填空题",
                   "question_text": "在PLC的面板嵮, POWER嵯嵪嵰嵭表嵪", "options": []}
        clean = {"question_id": "2", "question_type": "填空题",
                 "question_text": "在PLC的面板中，POWER指示灯表示", "options": []}
        self.assertFalse(exam._answerable(garbled))
        self.assertTrue(exam._answerable(clean))

    def test_submission_retries_once_on_network_error(self):
        """提交网络异常重试一次；平台业务拒绝不重试。"""
        import json as _json
        from unittest.mock import patch

        from core.config import Config
        from core.exceptions import RequestException
        from types import SimpleNamespace

        exam = self._make_bare_exam(no_answer_action="skip")
        exam.submit_delay = 0
        exam.auto_submit = True
        exam.headers = {}
        exam.user = type("U", (), {"uid": "1"})()
        exam.class_id = "151893764"
        exam.course_id = "266056498"
        exam.cpi = "496369168"

        response_404 = SimpleNamespace(status_code=404, url="https://x/", text="")
        net_error = RequestException(response_404, 1)
        responses = [net_error, _json.dumps({"status": True})]
        calls = []

        def fake_post(url, headers=None, data=None, if_full_back=False):
            calls.append(url)
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        page_form = {
            "found": True,
            "action": ("https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb"
                       "?_classId=1&token=t&totalQuestionNum=a"),
            "method": "post",
            "controls": {"courseId": "266056498", "answerwqbid": ""},
        }
        old_data = Config._data
        Config._data = Config._default_config()
        try:
            with patch("functions.deal_exam.doPost", side_effect=fake_post), \
                 patch("functions.deal_exam.doGet", return_value=""), \
                 patch("functions.deal_exam.runtime.sleep", lambda *_: None):
                ok, fail = exam._submit_answers(
                    work_id="55459339",
                    answered=[{"question_id": "111", "question_type": "单选题",
                               "answer": "B", "question_text": "题", "options": [],
                               "kind": "choice", "answer_type": "0"}],
                    defaults={"clazzId": "1", "knowledgeid": "1"},
                    jobid="work-55459339", enc=None, ktoken=None,
                    hidden_fields={}, page_form=page_form,
                )
        finally:
            Config._data = old_data
        self.assertEqual((ok, fail), (1, 0))
        self.assertEqual(len(calls), 2)  # 第一次网络失败 + 重试成功




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
        self.assertIn("课程（学科范围）：HTML5 APP应用开发", prompt)
        self.assertIn("作答内容：作业「第4章组件」", prompt)
        self.assertIn("先根据课程名与作答内容判断本题考查的学科", prompt)
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

    def test_config_defaults_merge_overrides(self):
        """v2.4.0 T2：Config 为纯内存 schema，set_defaults 深度合并且不改默认模板。"""
        old_data = Config._data
        try:
            merged = Config.set_defaults({"video": {"max_workers": 3}})
            self.assertEqual(merged["video"]["max_workers"], 3)
            self.assertEqual(merged["video"]["mode"], "hybrid")
            # 默认模板不被污染
            fresh = Config._default_config()
            self.assertEqual(fresh["video"]["max_workers"], 8)
        finally:
            Config._data = old_data

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

    def test_submit_partial_answers_keeps_all_page_qids(self):
        """回归：只答出一部分题时，answerwqbid 仍须是页面全部题号。

        2026-11 实机日志：10 题只答出 3 题就提交，平台回「无效的参数：code-2！」；
        把题目全部答完的测验从未报该错，全库也没有任何一次「部分作答」被接受。
        页面 ready2Submit() 是把 #questionIds 填成全部题号再提交的。
        """
        import json as _json
        from unittest.mock import patch

        from core.config import Config

        exam = self._make_exam()
        captured = {}

        def fake_post(url, headers=None, data=None, if_full_back=False):
            captured["data"] = data
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
                "answertype111": "0", "answer111": "",
                "answertype222": "0", "answer222": "",
                "answertype333": "0", "answer333": "",
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
                        "question_id": "222", "question_type": "单选题",
                        "answer": "A", "question_text": "题", "options": [],
                        "kind": "choice", "answer_type": "0",
                    }],
                    defaults={"clazzId": "151893764", "knowledgeid": "1219259997"},
                    jobid="work-55459339",
                    enc="2c292aeb00e3f15e16910622fc0070cd",
                    ktoken=None,
                    hidden_fields={},
                    page_form=page_form,
                    page_url=("https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task"
                              "?courseId=266056498&workId=55459339"),
                    page_qids=["111", "222", "333"],
                )
        finally:
            Config._data = old_data

        self.assertEqual((ok, fail), (1, 0))
        body = captured["data"]
        # 题号全集来自页面控件，未作答的 111/333 也在里面
        self.assertEqual(body["answerwqbid"], "111,222,333,")
        self.assertEqual(body["answer222"], "A")

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


    def test_swap_submit_host_between_mooc1_and_api(self):
        """考试提交域互换：mooc1 ↔ mooc1-api 双向互换，无关主机原样返回。"""
        from core.exam_answer_page import swap_submit_host

        url = "https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew?a=1"
        swapped = swap_submit_host(url)
        self.assertTrue(swapped.startswith("https://mooc1-api.chaoxing.com/"))
        self.assertIn("/exam-ans/exam/test/reVersionSubmitTestNew?a=1", swapped)
        self.assertEqual(swap_submit_host(swapped), url)  # 双向互换回到原址
        self.assertEqual(swap_submit_host("https://other.example.com/x"), "https://other.example.com/x")

    def test_chapter_page_fetch_failure_emits_visible_event(self):
        """章节页抓取最终失败：从静默 debug 升级为 warning + chapter_warning 事件。"""
        from types import SimpleNamespace
        from unittest.mock import patch

        from core.exceptions import RequestException
        from functions.deal_course import DealCourse

        class FakeLog:
            def __init__(self):
                self.warnings = []

            def info(self, *_a): pass
            def debug(self, *_a): pass
            def warning(self, *a): self.warnings.append(a[0] if a else "")
            def error(self, *_a): pass

        course = DealCourse.__new__(DealCourse)
        course.class_id = "151670988"
        course.course_id = "244694077"
        course.cpi = "518380181"
        course.log = FakeLog()
        course.user = SimpleNamespace(headers={})
        course._safe_read_card_count = lambda knowledge_id: 1  # 单页章节

        emitted = []
        with patch("functions.deal_course.doGet",
                   side_effect=RequestException(SimpleNamespace(
                       status_code=404, url="https://x/", text=""), 0)), \
             patch("core.runtime.emit",
                   side_effect=lambda *a, **k: emitted.append((a, k))):
            attach = course.deal_chapter({"knowledge_id": "1278369537",
                                          "name": "第三章 Vuex状态管理"})

        self.assertEqual(attach, [])
        self.assertTrue(any("任务数据读取失败" in w for w in course.log.warnings))
        self.assertEqual(len(emitted), 1)
        args, kwargs = emitted[0]
        self.assertEqual(args[0], "chapter_warning")
        payload = kwargs.get("payload") or {}
        self.assertEqual(payload.get("chapter"), "第三章 Vuex状态管理")
        self.assertEqual(payload.get("failed_pages"), "1")


if __name__ == "__main__":
    unittest.main()


class _StubLog:
    def __getattr__(self, _name):
        return lambda *a, **k: None
