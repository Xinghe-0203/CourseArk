"""考试说明页解析与「进入考试」地址构造（models.course）的单元测试。

夹具均为合成 HTML，不含任何真实账号/学号/页面内容。
"""

from models.course import Course

NOTES_HTML = """
<html><head><title>考试</title></head>
<body>
  <span class="overHidden2">vue3第一章测试题</span>
  <input type="hidden" id="examId" value="11021171" />
  <input type="hidden" id="answerId" value="171477623" />
  <input type="hidden" id="needCode" value="0" />
  <input type="hidden" id="examCheck" value="1" />
  <input type="hidden" id="captchaCheck" value="1" />
  <input type="hidden" id="cpi" value="518380181" />
  <a id="startBtn" data="/exam-ans/exam/test/reVersionTestStartNew?courseId=1&amp;classId=2
     &amp;tId=11021171&amp;id=171477623&amp;p=1&amp;tag=1&amp;enc=?&amp;cpi=3&amp;openc=abc&amp;newMooc=true">开始考试</a>
</body></html>
"""

NOTES_HTML_SAFE = """
<html><body>
  <input type="hidden" id="examCheck" value="0" />
  <input type="hidden" id="captchaCheck" value="0" />
  <a id="startBtn" data="https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?tId=9">开始</a>
</body></html>
"""


def test_parse_exam_notes_reads_entry_and_risk_flags():
    info = Course.parse_exam_notes(NOTES_HTML)
    assert info["found"] is True
    assert info["start_url"].startswith("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?")
    assert "tId=11021171" in info["start_url"]
    assert info["exam_check"] == 1
    assert info["captcha_check"] == 1
    assert info["need_code"] == 0
    assert info["exam_id"] == "11021171"
    assert info["answer_id"] == "171477623"
    assert info["title"] == "vue3第一章测试题"


def test_parse_exam_notes_keeps_absolute_url_and_zero_flags():
    info = Course.parse_exam_notes(NOTES_HTML_SAFE)
    assert info["found"] is True
    assert info["start_url"].startswith("https://mooc1.chaoxing.com/")
    assert info["exam_check"] == 0
    assert info["captcha_check"] == 0


def test_parse_exam_notes_without_entry_returns_not_found():
    for html in ("", None, "<html><body>参数错误</body></html>"):
        info = Course.parse_exam_notes(html)
        assert info["found"] is False
        assert info["start_url"] == ""


def test_exam_notes_url_shape():
    url = Course.exam_notes_url("244694077", "151670988", "518380181", "11021171")
    assert url.startswith("https://mooc1.chaoxing.com/exam/test/examcode/examnotes?")
    for part in ("courseId=244694077", "classId=151670988",
                 "examId=11021171", "cpi=518380181"):
        assert part in url


def test_exam_start_url_uses_exam_id_and_new_mooc_host():
    url = Course.exam_start_url("1", "2", "3", "openc1", "course-enc",
                                "11021171", "171477623")
    assert url.startswith("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?")
    assert "tId=11021171" in url
    assert "id=171477623" in url
    assert "newMooc=true" in url
    assert "enc=course-enc" in url
    assert "openc=openc1" in url
    assert "examsystem" not in url


def test_exam_start_url_retest_keeps_legacy_host():
    url = Course.exam_start_url("1", "2", "3", "openc1", "course-enc",
                                "11021171", "171477623", exam_enc="exam-enc",
                                is_retest=True)
    assert url.startswith("https://mooc1.chaoxing.com/exam/test/reVersionTestStartNew?")
    assert "enc=exam-enc" in url
    assert "examsystem=0" in url
    assert "id=171477623" in url
