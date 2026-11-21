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
from urllib.parse import urljoin

from lxml import etree

from core.answer_quality import encoding_issues as _encoding_issues
from core.text_norm import normalize_radicals

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
# 题干里的题型标记：既有圆括号 (单选题) 也有方括号/书名号形态 [单选题]【判断题】
_TYPE_MARK_RE = re.compile(
    r"[\(（\[【]\s*(?:%s)题?\s*[\)）\]】]" % "|".join(TYPE_WORDS))


# 字体解密会把部分汉字还原成部首码位（U+2F00–2FDF 康熙部首、U+2E80–U+2EFF 部首补充、
# U+F900–U+FAD9 兼容表意）。归一逻辑集中在 core/text_norm.py，解析层只负责调用。
_normalize_radicals = normalize_radicals


def norm_text(value: str) -> str:
    """压缩空白，归一部首变体，保留换行语义与全角标点。

    字体解密会把部分汉字还原成康熙部首区字符（⾃ U+2F42 等），
    逐字符归位到常规汉字后，LLM 阅读更稳、答题缓存的 key 也一致
    （同一道题不再因部首变体而缓存不命中）。
    """
    if not value:
        return ""
    value = _normalize_radicals(value)
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
            match = re.search(r"(\d+)", ident)
            qid = match.group(1) if match else ""
        if not qid:
            # 兜底：从题内作答控件名里取题号（answertype<qid> / tiankongsize<qid> /
            # answer<qid>）。真实 qid 可能只有 3 位，不能用 \d{6,} 过滤。
            # answerEditor<qid><空序号> 末尾还有空序号，无法与题号区分，故不作为兜底。
            for control in q_el.xpath(".//input[@name] | .//textarea[@name]"):
                match = re.search(
                    r"^(?:answertype|tiankongsize|answer)(\d+)",
                    control.get("name") or "")
                if match:
                    qid = match.group(1)
                    break

        type_code = ""
        if qid:
            codes = q_el.xpath(f".//input[@name='answertype{qid}']")
            if codes:
                type_code = str(codes[0].get("value") or "")

        page_type_code = type_code
        q_type = resolve_type(q_el.get("typename") or "", type_code)
        if not type_code:
            type_code = TYPE_TO_CODE.get(q_type, "0")

        options, option_reasons = _options_of(q_el, qid)
        unreadable, font_reason = _unreadable_of(q_el)
        unreadable = unreadable or bool(option_reasons)
        reasons = [r for r in [font_reason] + option_reasons if r]

        stem = _stem_of(q_el)
        # 字体数据缺失/轮廓微扰时，题干会留下「能显示的生僻字」而不是私用区字符；
        # 这类题必须判不可读，否则模型会照着乱码答出乱码，提交后在学习通上就是
        # 用户看到的「乱码答案」。
        residue = _encoding_issues(stem + " " + " ".join(options), label="题干")
        if residue:
            unreadable = True
            reasons.extend(residue)
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
            # 页面常把主观题标成单选题（typename 缺失、answertype 缺省成 0）：
            # 这类题没有选项，但作答区是填空框/文本框，能正常作答。
            # 直接判「选择题未解析出选项」会把整道题丢掉，实测导致 35 个测验
            # 因题目答不全被平台判 code-2（2026-11 实机日志）。
            has_text_area = bool(q_el.xpath(".//textarea")) or bool(
                q_el.xpath(".//*[@contenteditable='true']"))
            if blank_count or has_text_area:
                kind = KIND_BLANK if blank_count else KIND_TEXT
                q_type = "填空题" if kind == KIND_BLANK else "简答题"
                if not page_type_code:
                    type_code = TYPE_TO_CODE.get(q_type, type_code)
            else:
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


def parse_form(html: str, base_url: str = "") -> dict:
    """提取作业提交表单：action、method 与全部具名控件。

    Args:
        html: 页面 HTML
        base_url: 这份 HTML 实际渲染所在的页面地址。章节测验的表单内嵌在
            /mooc-ans/work/doHomeWorkNew 文档里，浏览器按文档地址解析相对
            action；缺省时按域名根解析（旧语义，可能丢路径前缀）。
    """
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
    action = absolute_action(action, base_url)

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


# 已知作业提交端点名：真实端点固定在 /mooc-ans/work/ 下
# （2026-10 真实页面抓包与旧版拼装路径一致，见 docs/research-github.md §1）。
_WORK_ENDPOINT_RE = re.compile(r"(addStudentWorkNewWeb|addStudentWorkNew)(?=[?#/]|$)")


def absolute_action(action: str, base_url: str = "") -> str:
    """把页面里的相对 action 补全为绝对地址。

    - 无前导斜杠的相对 action 优先按 base_url（页面真实地址）解析：
      章节测验表单内嵌在 /mooc-ans/work/doHomeWorkNew 文档里，浏览器按文档
      地址解析相对 action；此前一律按域名根解析会丢掉 /mooc-ans/work/ 前缀，
      提交打到 /addStudentWorkNewWeb 被 302→404（2026-11 实机日志）。
    - 兜底：已知作业端点解析后若不在 /mooc-ans/ 下，归位到规范路径。
    """
    action = (action or "").strip()
    if not action:
        return ""
    if action.startswith("//"):
        resolved = "https:" + action
    elif action.startswith("http"):
        resolved = action
    elif action.startswith("/"):
        resolved = MOOC_HOST + action
    elif base_url:
        resolved = urljoin(base_url, action)
    else:
        resolved = f"{MOOC_HOST}/{action.lstrip('./')}"
    return _canonical_work_endpoint(resolved)


def _canonical_work_endpoint(url: str) -> str:
    """已知作业端点不在 /mooc-ans/ 下时归位（仅限 mooc1 主站）。"""
    if not url.startswith(MOOC_HOST) or "/mooc-ans/" in url:
        return url
    match = _WORK_ENDPOINT_RE.search(url)
    if not match:
        return url
    endpoint = match.group(1)
    query_start = url.find("?")
    query = url[query_start:] if query_start >= 0 else ""
    return f"{MOOC_HOST}/mooc-ans/work/{endpoint}{query}"


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


# 题号只从题型/填空数量这类「一题一个」的控件名里取：
# answerEditor<qid><n> 末尾还有空序号，无法与题号区分。
_TYPE_CONTROL_RE = re.compile(r"^(?:answertype|tiankongsize)(\d+)$")
_ANSWER_CONTROL_RE = re.compile(r"^answer(\d+)$")


def page_question_ids(controls: dict) -> list:
    """按表单控件名收集页面上的全部题号（保持页面顺序、去重）。"""
    qids = []
    seen = set()
    for pattern in (_TYPE_CONTROL_RE, _ANSWER_CONTROL_RE):
        for name in controls or {}:
            match = pattern.match(str(name or ""))
            if not match:
                continue
            qid = match.group(1)
            if qid not in seen:
                seen.add(qid)
                qids.append(qid)
        if qids:
            return qids
    return qids


def build_submission(form: dict, answered: list, fallback_qids: list = None) -> tuple:
    """把答案写回表单控件，返回 (url, body)。

    Args:
        form: parse_form() 的结果
        answered: 答题结果列表（含 question_id/question_type/answer/kind/blank_count）
        fallback_qids: 页面控件里读不到题号时的题目 ID 顺序

    `answerwqbid` 必须与页面题目集合一致：页面 `ready2Submit()` 会把它填成
    「全部题号 + 尾逗号」，浏览器即使有题没答也照样提交全部题号。此前只写
    已作答题号，服务端判定参数不完整，返回「无效的参数：code-2」——2026-11
    实机日志里 35 个测验全数如此，而把题目全部答完的 25 个测验一次都没出现
    该错误，也没有任何一次「部分作答」被接受。
    """
    controls = dict(form.get("controls") or {})
    qids = page_question_ids(controls)
    for qid in [str(item.get("question_id")) for item in answered if item.get("question_id")]:
        if qid not in qids:
            qids.append(qid)
    for qid in (fallback_qids or []):
        qid = str(qid)
        if qid not in qids:
            qids.append(qid)

    if qids:
        controls["answerwqbid"] = ",".join(qids) + ","

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
            # 页面控件值是权威；但值为 0/空时不能沿用（否则只填第一空，
            # 其余空留空会被平台判为未作答），回退到解析器数出来的空数。
            page_size = _safe_int(controls.get(f"tiankongsize{qid}"), 0)
            if page_size > 0:
                blank_count = page_size
            else:
                controls[f"tiankongsize{qid}"] = str(blank_count)
            for idx, part in enumerate(split_blanks(answer, blank_count), 1):
                controls[f"answerEditor{qid}{idx}"] = part
        else:
            controls[f"answer{qid}"] = answer

    return build_submit_url(form.get("action") or ""), controls
