"""新版作业页面解析与提交报文构造（cli_copy.core.work_form）的单元测试。

页面结构全部为合成 HTML，参数名与真实页面一致但不含任何真实课程/账号数据。
"""

import sys
import os

import pytest

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (WEBUI_ROOT, CLI_COPY):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import work_form  # noqa: E402


PAGE = """
<html><body>
<form id="submitForm" name="submitForm" method="post"
      action="/mooc-ans/work/addStudentWorkNewWeb?_classId=111&courseid=222&token=abcd&totalQuestionNum=deadbeef&wMicroNodeId=">
  <input type="hidden" name="courseId" value="222">
  <input type="hidden" name="classId" value="111">
  <input type="hidden" name="cpi" value="3333">
  <input type="hidden" name="workRelationId" value="4444">
  <input type="hidden" name="answerwqbid" value="">
  <input type="submit" name="ignore-me" value="提交">

  <div class="padBom50 questionLi fontLabel singleQuesId" typename="单选题"
       id="question900001" data="900001">
    <input type="hidden" name="answertype900001" value="0">
    <input type="hidden" name="answer900001" value="">
    <h3 class="mark_name colorDeep fontLabel workTextWrap">1.
      <span class="colorShallow">(单选题)</span> Vue 组件的 data 必须是？</h3>
    <div class="stem_answer qtDetail">
      <div class="clearfix answerBg workTextWrap" qid="900001" qtype="0" aria-label="A 函数选择">
        <span data="A" class="choice900001 num_option fl">A</span>
        <div class="fl answer_p"><p>函数</p></div>
      </div>
      <div class="clearfix answerBg workTextWrap" qid="900001" qtype="0" aria-label="B 对象选择">
        <span data="B" class="choice900001 num_option fl">B</span>
        <div class="fl answer_p"><p>对象</p></div>
      </div>
    </div>
  </div>

  <div class="padBom50 questionLi fontLabel singleQuesId" typename="填空题"
       id="question900002" data="900002">
    <input type="hidden" name="answertype900002" value="2">
    <input type="hidden" name="tiankongsize900002" value="2">
    <h3 class="mark_name colorDeep fontLabel workTextWrap">2.
      <span class="colorShallow">(填空题)</span> 组合式 API 的入口函数是 ____。</h3>
    <p>请在下方填写函数名</p>
    <div class="eidtDiv">
      <textarea name="answerEditor9000021"></textarea>
      <textarea name="answerEditor9000022"></textarea>
    </div>
  </div>
</form>
</body></html>
"""


def test_parse_questions_reads_stem_and_options():
    questions = work_form.parse_questions(PAGE)
    assert [q["question_id"] for q in questions] == ["900001", "900002"]

    choice = questions[0]
    assert choice["question_type"] == "单选题"
    assert "Vue 组件的 data 必须是？" in choice["question_text"]
    assert "(单选题)" not in choice["question_text"]
    assert not choice["question_text"].startswith("1.")
    assert choice["options"] == ["A. 函数", "B. 对象"]
    assert choice["kind"] == work_form.KIND_CHOICE
    assert choice["unreadable"] is False

    blank = questions[1]
    assert blank["question_type"] == "填空题"
    assert blank["kind"] == work_form.KIND_BLANK
    assert blank["blank_count"] == 2
    # 题干可以带直接子 <p>，但不能再把选项区吞进来
    assert "组合式 API" in blank["question_text"]
    assert "请在下方填写函数名" in blank["question_text"]


def test_parse_questions_marks_choice_without_options_unreadable():
    html = PAGE.replace('typename="单选题"', 'typename="单选题"').replace(
        '<div class="stem_answer qtDetail">', '<div class="stem_answer qtDetail" hidden="hidden">'
    )
    stripped = "\n".join(
        line for line in html.splitlines()
        if "answerBg" not in line and "answer_p" not in line and "num_option" not in line
    )
    questions = work_form.parse_questions(stripped)
    assert questions[0]["options"] == []
    assert questions[0]["unreadable"] is True
    assert "选项" in questions[0]["unreadable_reason"]


def test_parse_questions_returns_empty_for_legacy_or_noise():
    assert work_form.parse_questions("") == []
    assert work_form.parse_questions("<html><body><div class='TiMu'>旧版</div></body></html>") == []


VARIANT_B = """
<html><body>
<div class="mark_item">
  <div class="Zy_TItle clearfix">
    <div class="fontLabel">
      <i class="fl">2.</i><span class="newZy_TItle">（多选题）</span>以下哪些属于 Vue 3 的组合式 API？
    </div>
  </div>
  <ul class="Zy_ulTop">
    <li><i class="fl">A</i><a class="after">ref</a></li>
    <li><i class="fl">B</i><a class="after">reactive</a></li>
    <li><i class="fl">C</i><a class="after">computed</a></li>
  </ul>
  <input type="hidden" name="answertype555001" value="1">
  <input type="hidden" name="answer555001" value="">
</div>
</body></html>
"""


def test_parse_questions_supports_exported_page_variant():
    """作业页导出结构（.Zy_TItle + ul.Zy_ulTop>li）也要能解析，且剥离题号与题型标记。"""
    questions = work_form.parse_questions(VARIANT_B)
    assert len(questions) == 1
    question = questions[0]
    assert question["question_id"] == "555001"
    assert question["question_type"] == "多选题"
    assert question["question_text"] == "以下哪些属于 Vue 3 的组合式 API？"
    assert question["options"] == ["A. ref", "B. reactive", "C. computed"]


def test_parse_questions_ignores_outer_TiMu_shell():
    """旧选择器命中的整页外壳（含「举报」）不能当成题干。"""
    page = """
    <html><body>
    <div class="fanyaMarking TiMu" id="fanyaMarking">
      <a class="report">举报</a>
      <h2 class="mark_title">第4章组件</h2>
      <div class="padBom50 questionLi fontLabel singleQuesId" typename="单选题" data="600001">
        <h3 class="mark_name colorDeep">1.<span class="colorShallow">(单选题)</span>Vue 中的响应式原理是？</h3>
        <div class="stem_answer qtDetail">
          <div class="clearfix answerBg" qid="600001" aria-label="A 依赖收集">
            <span data="A" class="choice600001 num_option fl">A</span>
            <div class="fl answer_p"><p>依赖收集</p></div>
          </div>
        </div>
        <input type="hidden" name="answertype600001" value="0">
      </div>
    </div>
    </body></html>
    """
    questions = work_form.parse_questions(page)
    assert len(questions) == 1
    assert "举报" not in questions[0]["question_text"]
    assert questions[0]["question_text"] == "Vue 中的响应式原理是？"
    assert questions[0]["options"] == ["A. 依赖收集"]


def test_parse_form_collects_controls_and_absolute_action():
    form = work_form.parse_form(PAGE)
    assert form["found"] is True
    assert form["method"] == "post"
    assert form["action"].startswith("https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb?")
    assert "token=abcd" in form["action"]
    controls = form["controls"]
    assert controls["courseId"] == "222"
    assert controls["classId"] == "111"
    assert controls["tiankongsize900002"] == "2"
    assert "ignore-me" not in controls


def test_parse_form_reports_missing_form():
    form = work_form.parse_form("<html><body><p>没有表单</p></body></html>")
    assert form["found"] is False
    assert form["controls"] == {}


def test_build_submit_url_appends_browser_version_params():
    url = work_form.build_submit_url(
        "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb?_classId=111&courseid=222")
    assert url.endswith("&ua=pc&formType=post&saveStatus=1&version=1")

    upgraded = work_form.build_submit_url(
        "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb?_classId=111&version=3")
    assert "version=4" in upgraded
    assert "version=3" not in upgraded
    assert upgraded.endswith("&ua=pc&formType=post&saveStatus=1")


def test_split_blanks_prefers_semicolon_then_comma():
    assert work_form.split_blanks("a;b", 2) == ["a", "b"]
    assert work_form.split_blanks("a；b", 2) == ["a", "b"]
    assert work_form.split_blanks("a,b", 2) == ["a", "b"]
    assert work_form.split_blanks("单个答案", 1) == ["单个答案"]
    assert work_form.split_blanks("a", 2) == ["a", ""]


def test_build_submission_writes_answers_like_the_browser():
    form = work_form.parse_form(PAGE)
    answered = [
        {"question_id": "900001", "question_type": "单选题", "answer": "A",
         "kind": work_form.KIND_CHOICE, "answer_type": "0"},
        {"question_id": "900002", "question_type": "填空题", "answer": "setup;onMounted",
         "kind": work_form.KIND_BLANK, "answer_type": "2", "blank_count": 2},
    ]
    url, body = work_form.build_submission(form, answered)
    assert url.startswith("https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNewWeb?")
    assert "ua=pc" in url
    assert body["answerwqbid"] == "900001,900002,"
    assert body["answer900001"] == "A"
    assert body["answertype900002"] == "2"
    assert body["tiankongsize900002"] == "2"
    assert body["answerEditor9000021"] == "setup"
    assert body["answerEditor9000022"] == "onMounted"
    # 页面其他隐藏域必须原样保留
    assert body["courseId"] == "222"
    assert body["workRelationId"] == "4444"


def test_build_submission_falls_back_to_legacy_when_no_form():
    answered = [{"question_id": "900001", "question_type": "单选题", "answer": "B"}]
    url, body = work_form.build_submission({"found": False, "action": "", "controls": {}}, answered)
    assert url == ""
    assert body["answer900001"] == "B"
    assert body["answerwqbid"] == "900001,"


def test_build_submission_uses_fallback_qids():
    url, body = work_form.build_submission(
        {"found": True, "action": "/mooc-ans/work/addStudentWorkNewWeb?x=1", "controls": {}},
        [],
        fallback_qids=["900001", "900002"],
    )
    assert body["answerwqbid"] == "900001,900002,"
    assert url.startswith("https://mooc1.chaoxing.com/")
