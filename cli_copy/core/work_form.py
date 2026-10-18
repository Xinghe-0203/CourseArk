"""
学习通作业/测验页面（mooc2 work/task）解析与表单构造。

2026 版页面结构（实测）：

    <form id="submitForm" action="/mooc-ans/work/addStudentWorkNewWeb?_classId=..&courseid=..&token=..&totalQuestionNum=..&wMicroNodeId=" method="post">
        <input type="hidden" name="courseId">
        ...
        <input type="hidden" name="answertype<qid>" value="0">
        <input type="hidden" name="answer<qid>" value="">
        <div class="padBom50 questionLi fontLabel singleQuesId" typename="单选题" id="question<qid>" data="<qid>">
            <h3 class="mark_name colorDeep fontLabel workTextWrap">
                1.<span class="colorShallow">(单选题)</span> 题干文字
            </h3>
            <div class="clear"></div>
            <div class="stem_answer qtDetail">
                <div class="clearfix answerBg workTextWrap" qid="<qid>" qtype="0" aria-label="A props选择">
                    <span data="A" class="choice<qid> num_option fl">A</span>
                    <div class="fl answer_p"><p>props</p></div>
                </div>
                ...
            </div>
        </div>
        <textarea name="answer<qid>">          # 简答题
        <textarea name="answerEditor<qid>1">    # 填空题第 1 空
        <input type="hidden" name="tiankongsize<qid>" value="2">
    </form>

浏览器提交时执行 `$("#submitForm").serialize()`，并在 URL 上追加
`&ua=pc&formType=post&saveStatus=1&version=1`。本模块复用同一套语义，
因此服务端收到的报文与真实浏览器一致。
"""

import re
from copy import deepcopy

from lxml import etree

MOOC_HOST = "https://mooc1.chaoxing.com"

# typename / answertype 编码 → 内部题型名
CODE_TO_TYPE = {
    "0": "单选题",
    "1": "多选题",
    "2": "填空题",
    "3": "判断题",
    "4": "简答题",
    "5": "简答题",   # 名词解释
    "6": "简答题",   # 论述题
    "7": "简答题",   # 计算题
    "8": "简答题",   # 其他
    "9": "填空题",   # 完形填空
    "10": "填空题",  # 阅读理解（填空式）
    "18": "简答题",
}

TYPE_TO_CODE = {
    "单选题": "0", "多选题": "1", "填空题": "2", "判断题": "3", "简答题": "4",
}

TYPE_WORDS = (
    "单选题", "多选题", "判断题", "填空题", "简答题", "名词解释",
    "论述题", "计算题", "完形填空", "阅读理解", "其他",
)

# 作答控件类别
KIND_CHOICE = "choice"
KIND_BLANK = "blank"
KIND_TEXT = "text"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_LEAD_INDEX_RE = re.compile(r"^\s*\d+\s*[.、．)）]\s*")
_TYPE_MARK_RE = re.compile(r"[\(（]\s*(?:%s)\s*[\)）]" % "|".join(TYPE_WORDS))


def norm_text(value: str) -> str:
    """压缩空白，保留换行语义。"""
    if not value:
        return ""
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = _WS_RE.sub(" ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


def _text_of(node) -> str:
    if node is None:
        return ""
    return norm_text(" ".join(node.itertext()))


def _clean_stem(text: str) -> str:
    text = norm_text(text)
    text = _LEAD_INDEX_RE.sub("", text)
    text = _TYPE_MARK_RE.sub(" ", text)
    return norm_text(text)


def _safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def resolve_type(typename: str, code: str) -> str:
    """由页面 typename 或 answertype 编码推断题型。"""
    typename = norm_text(typename)
    for word in TYPE_WORDS:
        if word in typename:
            if word in ("名词解释", "论述题", "计算题", "其他", "完形填空", "阅读理解"):
                return CODE_TO_TYPE.get(str(code), "简答题")
            return word
    return CODE_TO_TYPE.get(str(code), "单选题")


def _kind_of(q_type: str, code: str) -> str:
    if str(code) in ("2", "9", "10"):
        return KIND_BLANK
    if str(code) in ("4", "5", "6", "7", "8", "18"):
        return KIND_TEXT
    if q_type in ("填空题",):
        return KIND_BLANK
    if q_type in ("简答题",):
        return KIND_TEXT
    return KIND_CHOICE


def _remove_keep_tail(node):
    """删除节点但保留其后的文本（lxml 的 remove 会连 tail 一起丢掉）。"""
    parent = node.getparent()
    if parent is None:
        return
    tail = node.tail or ""
    if tail:
        prev = node.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(node)


def _text_excluding(node, drop_xpath: str) -> str:
    """取节点文本，但剔除指定后代（题型标记、题号、举报链接等噪声）。"""
    if node is None:
        return ""
    clone = deepcopy(node)
    for victim in clone.xpath(drop_xpath):
        _remove_keep_tail(victim)
    return _text_of(clone)


# 题干区里的噪声：题型标记、题号、举报/纠错链接
_STEM_NOISE = (
    ".//*[contains(@class,'newZy_TItle')] | .//i[contains(@class,'fl')] | "
    ".//*[contains(@class,'colorShallow')] | .//a[contains(@class,'report')]"
)


def _stem_of(q_el) -> str:
    """题干。

    兼容两代页面结构：
    - 本机 2026 版：h3.mark_name（题干含在内层 span/文本节点）
    - 作业页导出结构：div.Zy_TItle > div.fontLabel
    """
    parts = []
    heads = q_el.xpath("./h3[contains(@class,'mark_name')] | "
                       "./div[contains(@class,'mark_name')]")
    if heads:
        parts.append(_text_excluding(heads[0], _STEM_NOISE))
    else:
        heads = q_el.xpath(".//div[contains(@class,'Zy_TItle')]")
        if heads:
            parts.append(_text_excluding(heads[0], _STEM_NOISE))
    for p in q_el.xpath("./p"):
        value = _text_of(p)
        if value:
            parts.append(value)
    if not parts:
        # 兜底：整块文本去掉选项区
        clone = deepcopy(q_el)
        for path in (".//div[contains(@class,'stem_answer')]",
                     ".//div[contains(@class,'answerBg')]",
                     ".//ul[contains(@class,'Zy_ulTop')]"):
            for node in clone.xpath(path):
                _remove_keep_tail(node)
        parts.append(_text_of(clone))
    return _clean_stem(" ".join(parts))


def _option_parts(block, idx: int) -> tuple:
    """单个选项的 (字母, 正文)。兼容 div.answerBg 与 ul.Zy_ulTop>li 两种结构。"""
    label = ""
    label_nodes = block.xpath(".//span[contains(@class,'num_option')]")
    if label_nodes:
        label = norm_text(label_nodes[0].get("data") or "") or _text_of(label_nodes[0])
    if not label:
        tag_nodes = block.xpath(".//i[contains(@class,'fl')]")
        if tag_nodes:
            label = _text_of(tag_nodes[0])
    if not label:
        aria = block.get("aria-label") or ""
        match = re.match(r"\s*([A-Za-z])", aria)
        label = match.group(1) if match else chr(65 + idx)
    label = re.sub(r"[^A-Za-z]", "", label) or chr(65 + idx)

    text = ""
    for path in (".//div[contains(@class,'answer_p')]",
                 ".//a[contains(@class,'after')]",
                 ".//*[contains(@class,'after')]"):
        nodes = block.xpath(path)
        if nodes:
            text = _text_of(nodes[0])
            if text:
                break
    if not text:
        plain = _text_excluding(block, ".//span[contains(@class,'num_option')] | "
                                       ".//i[contains(@class,'fl')]")
        text = plain
    if not text:
        aria = block.get("aria-label") or ""
        text = re.sub(r"\s*选择$", "", aria.strip())
        text = re.sub(r"^\s*[A-Za-z]\s*", "", text)
    return label.upper()[:1], text


def _options_of(q_el, qid: str) -> tuple:
    """选项列表（'A. 文本'）与不可读原因。"""
    options = []
    reasons = []
    blocks = q_el.xpath(".//div[contains(@class,'answerBg')]")
    if not blocks:
        blocks = q_el.xpath(".//ul[contains(@class,'Zy_ulTop')]/li")
    if not blocks:
        blocks = q_el.xpath(".//div[contains(@class,'stem_answer')]/ul/li")
    for idx, block in enumerate(blocks):
        label, text = _option_parts(block, idx)
        images = block.xpath(".//img")
        for img in images:
            alt = (img.get("alt") or "").strip()
            if alt:
                text = f"{text} {alt}".strip()
            else:
                reasons.append("选项图片内容没有可读说明")
        options.append(f"{label}. {norm_text(text)}")
    return options, reasons


def _unreadable_of(q_el) -> tuple:
    """字体未解码/图片无说明的题目不可靠作答。"""
    nodes = q_el.xpath(
        "self::*[@data-font-unresolved='true'] | .//*[@data-font-unresolved='true']"
    )
    if not nodes:
        return False, ""
    reasons = []
    for node in nodes:
        reasons.append(node.get("data-font-reason") or "题目字体尚未完成可靠解码")
    return True, "；".join(dict.fromkeys(reasons))


def parse_questions(html: str) -> list:
    """解析作业页面中的全部题目（新结构）。

    Returns:
        list[dict]: 每项含 question_id / question_type / question_text /
        options / unreadable / unreadable_reason / answer_type / kind /
        blank_count
    """
    if not html:
        return []
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError):
        return []
    if tree is None:
        return []

    questions = []
    # 题目容器：2026 版是 div.singleQuesId[data]（常同时带 questionLi 类），
    # 旧版/导出页是 div.mark_item；绝不能用 div.TiMu —— 它命中的是整页外壳
    # （fanyaMarking.TiMu），会把「举报」和课程标题当成题干。
    containers = tree.xpath(
        "//div[contains(@class,'singleQuesId')] | "
        "//div[contains(@class,'questionLi')] | "
        "//div[contains(@class,'mark_item')]"
    )
    # 去掉被其它容器包裹的嵌套命中，避免同一道题被解析两次
    if len(containers) > 1:
        matched = {id(node) for node in containers}
        containers = [
            node for node in containers
            if not any(id(ancestor) in matched for ancestor in node.iterancestors())
        ]
    for q_el in containers:
        qid = str(q_el.get("data") or "")
        if not qid:
            ident = q_el.get("id") or ""
            match = re.search(r"(\d{6,})", ident)
            qid = match.group(1) if match else ""
        if not qid:
            # 兜底：从题内作答控件名里取题号（answertype<qid> / answer<qid> / answerEditor<qid>N）
            for control in q_el.xpath(".//input[@name] | .//textarea[@name]"):
                match = re.search(
                    r"^(?:answertype|tiankongsize|answerEditor|answer)(\d{6,})",
                    control.get("name") or "")
                if match:
                    qid = match.group(1)
                    break

        type_code = ""
        if qid:
            codes = q_el.xpath(f".//input[@name='answertype{qid}']")
            if codes:
                type_code = str(codes[0].get("value") or "")

        q_type = resolve_type(q_el.get("typename") or "", type_code)
        if not type_code:
            type_code = TYPE_TO_CODE.get(q_type, "0")

        options, option_reasons = _options_of(q_el, qid)
        unreadable, font_reason = _unreadable_of(q_el)
        unreadable = unreadable or bool(option_reasons)
        reasons = [r for r in [font_reason] + option_reasons if r]

        stem = _stem_of(q_el)
        blank_count = 0
        if qid:
            sizes = q_el.xpath(f".//input[@name='tiankongsize{qid}']")
            if sizes:
                blank_count = _safe_int(sizes[0].get("value"), 0)
            if not blank_count:
                blank_count = len(q_el.xpath(f".//textarea[starts-with(@name,'answerEditor{qid}')]"))
        if not blank_count and stem.count("____"):
            blank_count = stem.count("____")

        kind = _kind_of(q_type, type_code)
        if kind == KIND_CHOICE and not options:
            unreadable = True
            reasons.append("选择题未解析出选项")

        questions.append({
            "question_id": qid,
            "question_type": q_type,
            "question_text": stem,
            "options": options,
            "unreadable": unreadable,
            "unreadable_reason": "；".join(dict.fromkeys(reasons)),
            "answer_type": type_code,
            "kind": kind,
            "blank_count": blank_count,
        })
    return questions


def parse_form(html: str) -> dict:
    """提取作业提交表单：action、method 与全部具名控件。"""
    result = {"found": False, "action": "", "method": "post", "controls": {}}
    if not html:
        return result
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError):
        return result
    if tree is None:
        return result

    forms = tree.xpath("//form")
    target = None
    for form in forms:
        action = form.get("action") or ""
        if "addStudentWork" in action or "work/submit" in action:
            target = form
            break
    if target is None and forms:
        target = forms[0]
    if target is None:
        return result

    action = (target.get("action") or "").strip()
    action = absolute_action(action)

    controls = {}
    for node in target.xpath(".//input[@name] | .//textarea[@name] | .//select[@name]"):
        name = (node.get("name") or "").strip()
        if not name:
            continue
        # 与 jQuery serialize() 保持一致：disabled 控件不参与提交
        if node.get("disabled") is not None:
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

    return {"found": bool(action), "action": action, "method": (target.get("method") or "post").lower(),
            "controls": controls}


def absolute_action(action: str) -> str:
    """把页面里的相对 action 补全为绝对地址。"""
    action = (action or "").strip()
    if not action:
        return ""
    if action.startswith("//"):
        return "https:" + action
    if action.startswith("/"):
        return MOOC_HOST + action
    if action.startswith("http"):
        return action
    return f"{MOOC_HOST}/{action.lstrip('./')}"


def build_submit_url(action: str) -> str:
    """按页面 version() 逻辑追加固定查询参数。"""
    action = absolute_action(action)
    if not action:
        return ""
    sep = "&" if "?" in action else "?"
    match = re.search(r"&version=(\d+)", action)
    if match:
        version = int(match.group(1)) + 1
        base = re.sub(r"&version=\d+", f"&version={version}", action)
        return f"{base}&ua=pc&formType=post&saveStatus=1"
    return f"{action}{sep}ua=pc&formType=post&saveStatus=1&version=1"


def split_blanks(answer: str, blank_count: int) -> list:
    """把一道填空题的答案拆成各空。"""
    answer = (answer or "").strip()
    if blank_count <= 1:
        return [answer]
    parts = [p.strip() for p in re.split(r"[;；]", answer) if p.strip()]
    if len(parts) < blank_count:
        parts = [p.strip() for p in re.split(r"[;；,，、]", answer) if p.strip()]
    while len(parts) < blank_count:
        parts.append("")
    return parts[:blank_count]


def build_submission(form: dict, answered: list, fallback_qids: list = None) -> tuple:
    """把答案写回表单控件，返回 (url, body)。

    Args:
        form: parse_form() 的结果
        answered: 答题结果列表（含 question_id/question_type/answer/kind/blank_count）
        fallback_qids: 表单缺失 answerwqbid 时的题目 ID 顺序
    """
    controls = dict(form.get("controls") or {})
    qids = [str(item.get("question_id")) for item in answered if item.get("question_id")]

    if qids:
        controls["answerwqbid"] = ",".join(qids) + ","
    elif fallback_qids:
        controls["answerwqbid"] = ",".join(str(q) for q in fallback_qids) + ","

    for item in answered:
        qid = str(item.get("question_id") or "")
        if not qid:
            continue
        q_type = item.get("question_type") or "单选题"
        answer = (item.get("answer") or "").strip()
        kind = item.get("kind") or _kind_of(q_type, TYPE_TO_CODE.get(q_type, "0"))
        controls[f"answertype{qid}"] = str(item.get("answer_type") or TYPE_TO_CODE.get(q_type, "0"))

        if kind == KIND_BLANK:
            blank_count = _safe_int(item.get("blank_count"), 0) or 1
            controls.setdefault(f"tiankongsize{qid}", str(blank_count))
            blank_count = _safe_int(controls.get(f"tiankongsize{qid}"), blank_count)
            for idx, part in enumerate(split_blanks(answer, blank_count), 1):
                controls[f"answerEditor{qid}{idx}"] = part
        else:
            controls[f"answer{qid}"] = answer

    return build_submit_url(form.get("action") or ""), controls
