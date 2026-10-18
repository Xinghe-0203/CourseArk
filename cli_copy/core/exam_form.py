"""
学习通「考试」答题页解析与提交报文探测。

考试页与作业页并不完全同构，且不同考试系统版本差异较大，因此本模块采用
「多形态兼容 + 显式失败」策略：

1. 题目解析：先复用 `core.work_form`（新版作业/考试同构页面），失败再按
   经典考试结构（每题一个 `div.TiMu`，题干 `div.Zy_TItle`、选项
   `ul.Zy_ulTop`, 作答控件 `input[name=answer<qid>]`）解析。
2. 逐题模式识别：部分考试一页只显示一道题，靠「下一题」按钮前进并逐题保存。
   这种模式无法用整卷表单提交，必须识别出来并安全中止（不提交半份答案）。
3. 提交入口探测：优先使用页面里真实存在的 `<form action>`；没有表单时，
   从页面内联 JS 中探测已知的提交接口（只做候选收集，是否可用由调用方验证）。

约定：本模块只做纯解析，不发起任何网络请求。
"""

import re

from lxml import etree

from core import work_form

# 经典考试页的题目容器（每题一个 TiMu）；整页外壳 fanyaMarking.TiMu 必须排除
EXAM_QUESTION_XPATHS = (
    "//div[contains(@class,'singleQuesId')]",
    "//div[contains(@class,'questionLi')]",
    "//div[contains(@class,'mark_item')]",
    "//div[contains(@class,'TiMu')]",
)

_SHELL_IDS = {"fanyamarking"}

# 已知的考试提交/保存接口关键词（仅用于在 JS 里定位候选，不代表一定可用）。
# 其中 `reVersionSubmitTestNew` 是手机客户端协议里经上游源码验证的提交端点
# （见 docs/research-exam.md）；PC 端提交端点无可靠证据，只能靠页面表单回放
# 或此处运行时探测。
SUBMIT_TOKENS = (
    "reVersionSubmitTestNew",
    "reVersionTestSubmitNew",
    "reVersionTestSaveNew",
    "addStudentExam",
    "saveExamAnswer",
    "saveStudentAnswer",
    "submitTest",
    "exam/test/submit",
    "exam/test/save",
)

_URL_RE = re.compile(r"""["']((?:https?:)?//[^"'\s<>]+|/(?:exam|exam-ans|mooc-ans)/[^"'\s<>]+)["']""")
_TOTAL_RE = re.compile(r"(?:共\s*(\d+)\s*题|totalQuestionNum\s*[:=]\s*['\"]?(\d+)|questionCount\s*[:=]\s*(\d+))")


def _exclude_shell(nodes: list) -> list:
    """排除整页外壳（div#fanyaMarking.TiMu）与被其它候选包裹的嵌套命中。

    注意：真实题目就在外壳内部，因此只排除外壳节点本身，不排除其后代。
    """
    result = []
    for node in nodes:
        ident = (node.get("id") or "").lower()
        classes = (node.get("class") or "").lower()
        if ident in _SHELL_IDS or "fanyamarking" in classes:
            continue
        result.append(node)
    if len(result) > 1:
        matched = {id(node) for node in result}
        result = [
            node for node in result
            if not any(id(ancestor) in matched for ancestor in node.iterancestors())
        ]
    return result


def parse_questions(html: str) -> list:
    """解析考试答题页中的题目；结构与 `work_form.parse_questions` 一致。"""
    if not html:
        return []
    questions = work_form.parse_questions(html)
    if questions:
        return questions
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError):
        return []
    if tree is None:
        return []

    nodes = []
    for path in EXAM_QUESTION_XPATHS:
        nodes.extend(tree.xpath(path))
    nodes = _exclude_shell(nodes)
    if not nodes:
        return []

    questions = []
    for q_el in nodes:
        qid = str(q_el.get("data") or "")
        if not qid:
            match = re.search(r"(\d{5,})", q_el.get("id") or "")
            qid = match.group(1) if match else ""
        if not qid:
            for control in q_el.xpath(".//input[@name] | .//textarea[@name]"):
                match = re.search(
                    r"^(?:answertype|tiankongsize|answerEditor|answer)(\d{5,})",
                    control.get("name") or "")
                if match:
                    qid = match.group(1)
                    break

        type_code = ""
        if qid:
            codes = q_el.xpath(f".//input[@name='answertype{qid}']")
            if codes:
                type_code = str(codes[0].get("value") or "")
        q_type = work_form.resolve_type(q_el.get("typename") or "", type_code)
        if not type_code:
            type_code = work_form.TYPE_TO_CODE.get(q_type, "0")

        options, reasons = work_form._options_of(q_el, qid)
        unreadable, font_reason = work_form._unreadable_of(q_el)
        unreadable = unreadable or bool(reasons)
        all_reasons = [r for r in [font_reason] + reasons if r]

        stem = work_form._stem_of(q_el)
        blank_count = 0
        if qid:
            sizes = q_el.xpath(f".//input[@name='tiankongsize{qid}']")
            if sizes:
                blank_count = work_form._safe_int(sizes[0].get("value"), 0)
            if not blank_count:
                blank_count = len(q_el.xpath(f".//textarea[starts-with(@name,'answerEditor{qid}')]"))
        if not blank_count and stem.count("____"):
            blank_count = stem.count("____")

        kind = work_form._kind_of(q_type, type_code)
        if kind == work_form.KIND_CHOICE and not options:
            unreadable = True
            all_reasons.append("选择题未解析出选项")

        questions.append({
            "question_id": qid,
            "question_type": q_type,
            "question_text": stem,
            "options": options,
            "unreadable": unreadable,
            "unreadable_reason": "；".join(dict.fromkeys(all_reasons)),
            "answer_type": type_code,
            "kind": kind,
            "blank_count": blank_count,
        })
    return questions


def parse_form(html: str) -> dict:
    """优先找考试提交表单（action 含 exam/submit），否则沿用 work_form 的选择结果。"""
    if not html:
        return {"found": False, "action": "", "method": "post", "controls": {}}
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError):
        tree = None
    if tree is not None:
        forms = tree.xpath("//form")
        for form in forms:
            action = (form.get("action") or "").lower()
            if any(word in action for word in ("exam", "submittest", "submit")):
                return _form_controls(form, tree)
    return work_form.parse_form(html)


def _form_controls(form, tree) -> dict:
    action = work_form.absolute_action(form.get("action") or "")
    controls = {}
    for node in form.xpath(".//input[@name] | .//textarea[@name] | .//select[@name]"):
        name = (node.get("name") or "").strip()
        if not name or node.get("disabled") is not None:
            continue
        tag = node.tag.lower()
        if tag == "textarea":
            value = node.text or ""
        elif tag == "select":
            picked = node.xpath("./option[@selected]")
            value = picked[0].get("value", "") if picked else (node.get("value") or "")
        else:
            input_type = (node.get("type") or "").lower()
            if input_type in ("submit", "button", "reset", "file"):
                continue
            if input_type in ("radio", "checkbox") and node.get("checked") is None:
                continue
            value = node.get("value") or ""
        controls[name] = value
    return {"found": bool(action), "action": action,
            "method": (form.get("method") or "post").lower(), "controls": controls}


def parse_hidden_controls(html: str) -> dict:
    """收集整页的具名控件（考试页常把隐藏域放在表单外/页尾）。"""
    controls = {}
    if not html:
        return controls
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError):
        return controls
    if tree is None:
        return controls
    for node in tree.xpath("//input[@name] | //textarea[@name]"):
        name = (node.get("name") or "").strip()
        if not name or node.get("disabled") is not None:
            continue
        if (node.get("type") or "").lower() in ("submit", "button", "reset", "file"):
            continue
        controls.setdefault(name, node.get("value") or (node.text or ""))
    return controls


def detect_total_questions(html: str) -> int:
    """从页面里推断总题数（用于判断是否「一页一题」）。"""
    if not html:
        return 0
    for match in _TOTAL_RE.finditer(html):
        for group in match.groups():
            if group:
                try:
                    value = int(group)
                except ValueError:
                    continue
                if 0 < value <= 500:
                    return value
    return 0


def is_single_question_mode(html: str, question_count: int) -> bool:
    """识别「逐题作答」考试：一页一题 + 下一题按钮/逐题保存。"""
    if not html:
        return False
    if re.search(r'id="nextQuestion"|class="[^"]*nextQuestion|id="next_question"', html):
        return True
    has_next_word = "下一题" in html or "下一題" in html
    total = detect_total_questions(html)
    if has_next_word and (total > 1 or question_count <= 1):
        return True
    if "saveExamAnswer" in html or "reVersionTestSaveNew" in html:
        return True
    return False


def _urls_near(html: str, token: str, window: int = 600) -> list:
    """在关键词附近窗口内提取 URL 候选。"""
    urls = []
    start = 0
    while True:
        idx = html.find(token, start)
        if idx < 0:
            break
        start = idx + len(token)
        snippet = html[max(0, idx - window): idx + window]
        for match in _URL_RE.finditer(snippet):
            raw = match.group(1).strip()
            if not raw or raw.endswith("/"):
                continue
            url = raw
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = work_form.MOOC_HOST + url
            if url not in urls:
                urls.append(url)
    return urls


def detect_submit_endpoints(html: str) -> list:
    """探测可能的提交/保存接口（只收集候选，不保证可用）。

    Returns:
        list[dict]: [{"token","url","method","evidence"}]
    """
    if not html:
        return []
    found = []
    seen = set()
    for token in SUBMIT_TOKENS:
        if token not in html:
            continue
        for url in _urls_near(html, token):
            key = (token, url)
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "token": token,
                "url": url,
                "method": "post",
                "evidence": f"页面内联脚本出现 {token}",
            })
    return found


def describe_diagnostics(html: str, questions: list, form: dict) -> dict:
    """生成不含页面原文的结构化诊断信息（可安全写日志）。"""
    tree = None
    try:
        tree = etree.HTML(html or "")
    except (etree.ParserError, ValueError):
        tree = None
    class_hits = {}
    if tree is not None:
        for node in tree.xpath("//*[@class]"):
            for cls in (node.get("class") or "").split():
                if cls in ("TiMu", "questionLi", "singleQuesId", "mark_item", "Zy_TItle",
                           "Zy_ulTop", "answerBg", "stem_answer", "answer_p"):
                    class_hits[cls] = class_hits.get(cls, 0) + 1
    return {
        "html_length": len(html or ""),
        "questions": len(questions),
        "class_hits": class_hits,
        "form_found": bool(form.get("found")),
        "form_action": (form.get("action") or "")[:200],
        "form_fields": len(form.get("controls") or {}),
        "submit_candidates": [item["url"] for item in detect_submit_endpoints(html)][:5],
        "single_question_mode": is_single_question_mode(html, len(questions)),
        "total_questions": detect_total_questions(html),
    }
