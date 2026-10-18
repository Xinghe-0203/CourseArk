"""考试页解析（core.exam_form）的单元测试。

所有夹具均为合成 HTML，不含任何真实账号/学号/页面内容。
"""

from core import exam_form

# 变体一：新版页面（与作业页同构，work_form 直接可解析）
NEW_STYLE_HTML = """
<div class="questionLi singleQuesId" data="900001" typename="单选题">
  <h3 class="mark_name colorDeep fontLabel workTextWrap">1.组件的生命周期钩子中，挂载完成后调用的是？</h3>
  <div class="stem_answer">
    <div class="clearfix answerBg" qid="900001" qtype="0">
      <span class="num_option" data="A">A.</span><div class="answer_p">created</div>
    </div>
    <div class="clearfix answerBg" qid="900001" qtype="0">
      <span class="num_option" data="B">B.</span><div class="answer_p">mounted</div>
    </div>
  </div>
  <input type="hidden" name="answertype900001" value="0" />
  <input type="hidden" name="answer900001" value="" />
</div>
"""

# 变体二：经典考试页（每题一个 div.TiMu）；另有整页外壳 fanyaMarking.TiMu 必须排除
CLASSIC_HTML = """
<div class="fanyaMarking TiMu" id="fanyaMarking">
  <h2 class="mark_title">第一章测验</h2>
  <a class="report" href="javascript:;">举报</a>
  <div class="TiMu" data="123456" typename="单选题">
    <div class="Zy_TItle clearfix">
      <div class="fl"><i class="fl">1.</i><span class="fontLabel">(单选题)</span>下列哪个不是 Vue 的指令？</div>
    </div>
    <ul class="Zy_ulTop">
      <li><span class="num_option" data="A">A.</span><div class="answer_p">v-if</div></li>
      <li><span class="num_option" data="B">B.</span><div class="answer_p">v-for</div></li>
      <li><span class="num_option" data="C">C.</span><div class="answer_p">v-show</div></li>
    </ul>
    <input type="hidden" name="answertype123456" value="0" />
    <input type="hidden" name="answer123456" value="" />
  </div>
  <div class="TiMu" data="123457" typename="简答题">
    <div class="Zy_TItle clearfix">
      <div class="fl"><i class="fl">2.</i>简述 v-model 的作用。</div>
    </div>
    <textarea name="answer123457"></textarea>
    <input type="hidden" name="answertype123457" value="4" />
  </div>
</div>
"""

FORM_HTML = """
<form action="/exam-ans/exam/test/reVersionTestSubmitNew?courseId=1&classId=2"
      method="post" id="submitForm">
  <input type="hidden" name="courseId" value="1" />
  <input type="hidden" name="classId" value="2" />
  <input type="hidden" name="examRelationId" value="171477623" />
  <input type="text" name="answer123456" value="" />
  <input type="submit" name="go" value="提交" />
  <input type="checkbox" name="opt" value="1" />
  <input type="checkbox" name="opt" value="2" checked="checked" />
  <textarea name="answerEditor1234571"></textarea>
</form>
"""

SINGLE_MODE_HTML = """
<div class="questionLi singleQuesId" data="900009" typename="单选题">
  <h3 class="mark_name">1.一页一题示例</h3>
  <div class="stem_answer">
    <div class="clearfix answerBg"><span class="num_option" data="A">A.</span>
      <div class="answer_p">甲</div></div>
  </div>
</div>
<a id="nextQuestion" href="javascript:;">下一题</a>
<script>var totalQuestionNum = 5;</script>
"""

ENDPOINT_HTML = """
<script>
function submitPaper(){
  $.post("/exam-ans/exam/test/reVersionTestSubmitNew?courseId=1", {answer: "1"}, function(){});
}
function saveOne(){ $.post("/exam-ans/exam/test/saveExamAnswer", {}, function(){}); }
</script>
"""


def test_parse_questions_new_style_page():
    questions = exam_form.parse_questions(NEW_STYLE_HTML)
    assert len(questions) == 1
    question = questions[0]
    assert question["question_id"] == "900001"
    assert question["question_type"] == "单选题"
    assert "挂载完成" in question["question_text"]
    assert len(question["options"]) == 2
    assert question["unreadable"] is False


def test_parse_questions_classic_page_excludes_shell():
    questions = exam_form.parse_questions(CLASSIC_HTML)
    assert [q["question_id"] for q in questions] == ["123456", "123457"]
    choice, short = questions
    assert choice["question_type"] == "单选题"
    assert "不是 Vue 的指令" in choice["question_text"]
    assert "举报" not in choice["question_text"]
    assert len(choice["options"]) == 3
    assert short["question_type"] == "简答题"
    assert short["kind"] == "text"


def test_parse_questions_returns_empty_for_shell_only():
    shell_only = """
    <div class="fanyaMarking TiMu" id="fanyaMarking">
      <h2 class="mark_title">作业标题</h2><a class="report">举报</a>
    </div>
    """
    assert exam_form.parse_questions(shell_only) == []


def test_parse_form_prefers_exam_form():
    form = exam_form.parse_form(FORM_HTML)
    assert form["found"] is True
    assert "reVersionTestSubmitNew" in form["action"]
    assert form["action"].startswith("https://mooc1.chaoxing.com")
    controls = form["controls"]
    assert controls["courseId"] == "1"
    assert controls["examRelationId"] == "171477623"
    assert controls["opt"] == "2"        # 只收集已选中的 checkbox
    assert "go" not in controls           # submit 按钮不参与序列化
    assert controls["answerEditor1234571"] == ""


def test_parse_hidden_controls_collects_outside_form():
    html = """
    <div><input type="hidden" name="hiddenA" value="1" /></div>
    <form><input type="hidden" name="hiddenB" value="2" /></form>
    <input name="hiddenA" value="dup" />
    """
    controls = exam_form.parse_hidden_controls(html)
    assert controls == {"hiddenA": "1", "hiddenB": "2"}


def test_detect_total_questions():
    assert exam_form.detect_total_questions(SINGLE_MODE_HTML) == 5
    assert exam_form.detect_total_questions("<p>共 12 题</p>") == 12
    assert exam_form.detect_total_questions("") == 0


def test_single_question_mode_detection():
    assert exam_form.is_single_question_mode(SINGLE_MODE_HTML, 1) is True
    assert exam_form.is_single_question_mode(NEW_STYLE_HTML, 1) is False
    assert exam_form.is_single_question_mode(
        "<script>saveExamAnswer()</script>", 1) is True


def test_detect_submit_endpoints():
    endpoints = exam_form.detect_submit_endpoints(ENDPOINT_HTML)
    urls = {item["url"] for item in endpoints}
    tokens = {item["token"] for item in endpoints}
    assert "reVersionTestSubmitNew" in tokens
    assert any("reVersionTestSubmitNew" in url for url in urls)
    assert all(url.startswith("https://") for url in urls)
    assert exam_form.detect_submit_endpoints("<div>没有脚本</div>") == []


def test_describe_diagnostics_has_no_page_text():
    questions = exam_form.parse_questions(CLASSIC_HTML)
    form = exam_form.parse_form(FORM_HTML)
    diag = exam_form.describe_diagnostics(CLASSIC_HTML, questions, form)
    assert diag["questions"] == 2
    assert diag["class_hits"]["TiMu"] >= 3
    assert diag["submit_candidates"] == []
    assert "举报" not in str(diag)
    assert "第一章测验" not in str(diag)
