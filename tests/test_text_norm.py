# -*- coding: utf-8 -*-
"""字体解密残留部首码位的归位（cli_copy.core.text_norm）单元测试。

背景：学习通的加密字体把真实汉字换成某个部首的字形，轮廓反查只能查到部首码位，
于是题干与选项里会出现 ⽤（U+2F64）、⻚（U+2EDA）这类「看着像字、其实是部首」的
字符。2026-11 实机日志里 `常⻅热处理缺陷` 就因此被判成不可读。
"""

import os
import sys

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (WEBUI_ROOT, CLI_COPY):
    if path not in sys.path:
        sys.path.insert(0, path)

from core.text_norm import normalize_radicals  # noqa: E402


def test_kangxi_radicals_are_normalized():
    """U+2F00–U+2FDF：NFKC 能覆盖 214 个，逐字归位成常规汉字。"""
    assert normalize_radicals("使⽤Axios") == "使用Axios"
    assert normalize_radicals("唯⼀⽅法") == "唯一方法"
    assert normalize_radicals("项⽬依赖") == "项目依赖"


def test_supplemental_radicals_are_normalized():
    """U+2E80–U+2EFF：NFKC 基本无效，靠内置表归位（简体优先）。"""
    assert normalize_radicals("常⻅热处理缺陷") == "常见热处理缺陷"
    assert normalize_radicals("⻚面") == "页面"
    assert normalize_radicals("⻮⻋⻔⻢⻥⻦⻓⻛⻜⻩⻬⻰⻳") == "齿车门马鱼鸟长风飞黄齐龙龟"


def test_compatibility_ideographs_are_normalized():
    assert normalize_radicals("漢字") == "漢字"  # 不在兼容区，原样保留
    assert normalize_radicals("⼾") == "戶"  # U+2F3E 康熙部首 → 繁體戶（NFKC 行为）


def test_plain_text_is_untouched():
    text = "正常文本 ABC 123，标点！（全角）"
    assert normalize_radicals(text) == text
    assert normalize_radicals("") == ""


def test_normalization_is_idempotent():
    once = normalize_radicals("常⻅⽤⻚⻅")
    assert normalize_radicals(once) == once
    assert not any(0x2E80 <= ord(ch) <= 0x2FDF for ch in once)


def test_stem_and_options_are_clean_after_parse():
    """题干与选项都要经过归位，不能把部首带进 LLM 与答题缓存。"""
    from core import work_form

    html = """
<html><body><form id="submitForm" method="post" action="/mooc-ans/work/addStudentWorkNewWeb?_classId=1">
  <div class="questionLi singleQuesId" data="900801" typename="单选题">
    <input type="hidden" name="answertype900801" value="0">
    <h3 class="mark_name">1. 常⻅热处理缺陷有哪些？</h3>
    <div class="stem_answer qtDetail">
      <div class="answerBg" aria-label="A 使⽤温度">
        <span data="A" class="num_option fl">A</span>
        <div class="fl answer_p"><p>使⽤温度过⾼</p></div>
      </div>
    </div>
  </div>
</form></body></html>
"""
    question = work_form.parse_questions(html)[0]
    assert question["question_text"] == "常见热处理缺陷有哪些？"
    assert question["options"] == ["A. 使用温度过高"]
    for text in [question["question_text"], *question["options"]]:
        assert not any(0x2E80 <= ord(ch) <= 0x2FDF for ch in text), text