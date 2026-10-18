"""学习通「考试」逐题答题页（reVersionTestStartNew）的解析与报文构造。

PC 端考试默认是「一题一提交」的逐题模式：一个页面只渲染当前题目，点
「下一题」时先用 ``#submitTest`` 隐藏表单把本题答案 save 到服务器，再用返回
的 ``data="lastUpdateTime|remainTime|enc"`` 跳转到下一题；最后一题用
``tempSave=false`` 提交即交卷。

实测协议（2026-10，见 docs/research-exam.md）：

- 答题页 URL 自带 ``enc`` 时可直接打开，不会触发 ``examcheck`` 安全验证；
  该 URL 由用户在浏览器里进入考试后复制而来（程序不绕过任何验证）
- 提交端点 ``/exam-ans/exam/test/reVersionSubmitTestNew``，query 必须包含
  ``classId/courseId/testPaperId/testUserRelationId/cpi/tempSave/version``；
  多带未知参数（如 ``keyboardDisplayRequiresUserAction``）会被判「无效操作」
- 请求体是 ``#submitTest`` 的表单字段 + ``answer<qid>`` + ``tempSave`` +
  ``isAnswered``；``pos`` 签名可省略，服务器接受
- 成功响应 ``{"status":"success","data":"<lastUpdateTime>|<remainTime>|<enc>"}``；
  最后一次提交返回 ``{"status":"success","msg":"提交成功","consumeMinutes":N}``

本模块只做纯解析/构造，不发任何网络请求（便于单测与安全审计）。
"""

import json
import re
import urllib.parse
from html import unescape as html_unescape

ANSWER_PAGE_PATH = "/exam-ans/exam/test/reVersionTestStartNew"
SUBMIT_PATH = "/exam-ans/exam/test/reVersionSubmitTestNew"
SUBMIT_HOST = "https://mooc1.chaoxing.com"

# 题型码（与作业页一致）
TYPE_LABELS = {
    "0": "单选题", "1": "多选题", "2": "填空题", "3": "判断题", "4": "简答题",
    "5": "名词解释", "6": "论述题", "7": "计算题", "8": "其他", "9": "完形填空",
    "10": "阅读理解", "18": "简答题",
}

# 交卷后页面/说明页会出现的文案，用于幂等判断
FINISHED_MARKERS = ("交卷成功", "试卷已提交", "考试已完成")
# 无法继续的口径
BLOCKED_MARKERS = ("无权限访问", "考试已结束", "不在考试时间", "请重新登录",
                   "验证码", "安全验证不通过", "该考试已过期", "参数传递不正确")


class ExamUrlError(ValueError):
    """答题页 URL 不可用（格式、状态或服务器拒绝）"""


def parse_exam_url(url: str) -> dict:
    """解析并校验用户粘贴的考试答题页 URL。

    Returns:
        dict: course_id/class_id/exam_id/relation_id/cpi/openc/enc/new_mooc，
              url 原值
    Raises:
        ExamUrlError: 不是 PC 端逐题答题页 URL
    """
    raw = (url or "").strip()
    if not raw:
        raise ExamUrlError("请先粘贴考试答题页地址（在浏览器进入考试后复制地址栏 URL）")
    if raw.startswith("//"):
        raw = "https:" + raw
    parts = urllib.parse.urlsplit(raw)
    if not parts.scheme.startswith("http") or "chaoxing.com" not in parts.netloc:
        raise ExamUrlError("地址不是学习通（chaoxing.com）考试答题页")
    if ANSWER_PAGE_PATH not in parts.path:
        raise ExamUrlError("地址不是考试答题页：请在浏览器里点进考试、看到题目后复制地址栏 URL")
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    course_id = query.get("courseId", "")
    class_id = query.get("classId", "")
    exam_id = query.get("tId", "")
    relation_id = query.get("id", "")
    if not (course_id and class_id and exam_id and relation_id):
        raise ExamUrlError("答题页地址缺少 courseId/classId/tId/id 参数，请复制完整地址")
    return {
        "url": raw,
        "course_id": course_id,
        "class_id": class_id,
        "exam_id": exam_id,
        "relation_id": relation_id,
        "cpi": query.get("cpi", ""),
        "openc": query.get("openc", ""),
        "enc": query.get("enc", ""),
        "new_mooc": query.get("newMooc", ""),
    }


def _strip_color_span(html: str) -> str:
    return re.sub(r'<span[^>]*class="colorShallow"[^>]*>[\s\S]*?</span>', " ", html or "")


def _text_of(html: str) -> str:
    value = _strip_color_span(html)
    value = re.sub(r'<div[^>]*style="display:none"[^>]*>[\s\S]*?</div>', " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    for entity, plain in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                          ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        value = value.replace(entity, plain)
    return re.sub(r"\s+", " ", value).strip()


def _extract_form(html: str) -> tuple:
    start = html.find('<form id="submitTest"')
    if start < 0:
        return "", {}
    end = html.find("</form>", start)
    segment = html[start:end if end > 0 else len(html)]
    fields = {}
    for match in re.finditer(r"<input[^>]*>", segment):
        tag = match.group(0)
        name = re.search(r'name=["\']([^"\']+)["\']', tag)
        if not name:
            continue
        value = re.search(r'value=["\']([^"\']*)["\']', tag)
        fields.setdefault(name.group(1), html_unescape(value.group(1)) if value else "")
    action = re.search(r'<form id="submitTest" action="([^"]+)"', segment)
    action_text = action.group(1) if action else ""
    return html_unescape(action_text), fields


def _extract_media_title(html: str) -> str:
    match = re.search(r'<h2[^>]*class="h2_subject"[^>]*>([\s\S]*?)</h2>', html)
    return _text_of(match.group(1)) if match else ""


def _extract_total(html: str) -> int:
    match = re.search(r"题量[：:]\s*(\d+)", html)
    return int(match.group(1)) if match else 0


def _extract_options(html: str) -> list:
    options = []
    pattern = re.compile(r'<div class="clearfix answerBg[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>')
    for match in pattern.finditer(html):
        chunk = match.group(1)
        key = re.search(r'<span[^>]*data="([^"]+)"', chunk)
        text = re.search(r'<div class="fl answer_p">([\s\S]*)', chunk)
        if key and text:
            options.append({"key": key.group(1), "text": _text_of(text.group(1))})
    return options


def _extract_stem(html: str, qid: str) -> str:
    start = html.find('data="' + qid + '"')
    block = ""
    if start >= 0:
        right = html.find('<div class="splitS-right">', start)
        block = html[start:right if right > start else start + 4000]
    match = re.search(r'<h3 class="mark_name[^"]*"[^>]*>([\s\S]*?)</h3>', block or html)
    stem = _text_of(match.group(1)) if match else ""
    return re.sub(r"^\d+[.、]\s*", "", stem).strip()


def parse_answer_page(html: str) -> dict:
    """解析一页答题页（逐题模式下即当前这一题）。

    Returns:
        dict: form_action/fields/qid/type_code/type_name/stem/options/total/
              index/remain/media/finished/blocked
    """
    html = html or ""
    finished = any(marker in html for marker in FINISHED_MARKERS)
    action, fields = _extract_form(html)
    qid = fields.get("questionId", "")
    type_code = fields.get("type" + qid, "0") if qid else ""
    type_name = fields.get("typeName" + qid, "") if qid else ""
    try:
        index = int(fields.get("start", "0") or 0)
    except ValueError:
        index = 0
    blocked = ""
    if not finished and not fields:
        for marker in BLOCKED_MARKERS:
            if marker in html:
                blocked = marker
                break
    return {
        "form_action": action,
        "fields": fields,
        "qid": qid,
        "type_code": type_code,
        "type_name": type_name,
        "stem": _extract_stem(html, qid) if qid else "",
        "options": _extract_options(html),
        "total": _extract_total(html),
        "index": index,
        "remain": fields.get("remainTime", ""),
        "media": _extract_media_title(html),
        "finished": finished,
        "blocked": blocked,
    }


def question_from_page(page: dict) -> dict:
    """把答题页转换为答题器/LLM 使用的题目结构。"""
    type_code = str(page.get("type_code") or "0")
    question_type = TYPE_LABELS.get(type_code, page.get("type_name") or "简答题")
    options = []
    for option in page.get("options") or []:
        text = option.get("text", "")
        key = option.get("key", "")
        options.append(f"{key}. {text}" if key else text)
    return {
        "question_id": page.get("qid", ""),
        "question_type": question_type,
        "question_text": page.get("stem", ""),
        "options": options,
    }


def submit_query(form_action: str, cpi: str = "", temp_save: bool = True) -> dict:
    """构造提交/保存接口的 query。

    只取页面表单 action 里的已知参数；``keyboardDisplayRequiresUserAction`` 这类
    展示参数会被服务器判为「无效操作」，必须剔除。
    """
    query = dict(urllib.parse.parse_qsl(
        form_action.split("?", 1)[1] if "?" in form_action else ""))
    query.pop("keyboardDisplayRequiresUserAction", None)
    query.setdefault("cpi", cpi or "")
    query["tempSave"] = "true" if temp_save else "false"
    query["version"] = "1"
    return query


def submit_url(form_action: str, cpi: str = "", temp_save: bool = True) -> str:
    query = submit_query(form_action, cpi=cpi, temp_save=temp_save)
    return SUBMIT_HOST + SUBMIT_PATH + "?" + urllib.parse.urlencode(query)


def build_submit_data(page: dict, answer: str, temp_save: bool) -> dict:
    """构造提交请求体：页面隐藏字段 + 本题答案 + 保存/交卷标记。"""
    data = dict(page.get("fields") or {})
    data["answer" + page.get("qid", "")] = answer or ""
    data["tempSave"] = "true" if temp_save else "false"
    data["isAnswered"] = "true"
    return data


def parse_submit_response(text: str) -> dict:
    """解析保存/交卷接口的 JSON 响应。"""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {"ok": False, "status": "unparseable", "msg": (text or "")[:200], "data": ""}
    if not isinstance(data, dict):
        return {"ok": False, "status": "unparseable", "msg": "响应不是 JSON 对象", "data": ""}
    status = str(data.get("status") or "")
    msg = str(data.get("msg") or "")
    ok = status in ("success", "submitted", "forceSubmitted") or "提交成功" in msg
    return {
        "ok": ok,
        "status": status,
        "msg": msg,
        "data": str(data.get("data") or ""),
        "real_remain_time": data.get("realRemainTime"),
    }


def build_next_url(entry: dict, data: str, start: int) -> str:
    """用保存接口返回的 data 构造下一题地址（与页面 getTheNextQuestion 一致）。"""
    pieces = (data or "").split("|")
    last_update = pieces[0] if len(pieces) > 0 else ""
    remain = pieces[1] if len(pieces) > 1 else ""
    enc = pieces[2] if len(pieces) > 2 else ""
    query = [
        ("keyboardDisplayRequiresUserAction", "1"),
        ("getTheNextQuestion", "1"),
        ("courseId", entry.get("course_id", "")),
        ("classId", entry.get("class_id", "")),
        ("tId", entry.get("exam_id", "")),
        ("id", entry.get("relation_id", "")),
        ("p", "1"),
        ("start", str(start)),
        ("remainTimeParam", remain),
        ("relationAnswerLastUpdateTime", last_update),
        ("enc", enc),
        ("monitorStatus", "0"), ("monitorOp", "-1"), ("examsystem", "0"),
        ("qbanksystem", "0"), ("qbankbackurl", ""),
        ("cpi", entry.get("cpi", "")),
        ("openc", entry.get("openc", "")),
        ("newMooc", "true"), ("webSnapshotMonitor", "0"),
    ]
    return SUBMIT_HOST + ANSWER_PAGE_PATH + "?" + urllib.parse.urlencode(query)


def normalize_answer(type_code: str, answer: str) -> str:
    """按题型把 LLM 文本归一成平台需要的字段值。"""
    value = (answer or "").strip()
    if not value:
        return ""
    code = str(type_code or "")
    if code in ("0", "1"):
        letters = re.findall(r"[A-Za-z]", value.upper())
        return "".join(sorted(set(letters)))
    if code == "3":
        low = value.lower()
        if low in ("true", "正确", "对", "是", "t", "a", "√", "1"):
            return "true"
        if low in ("false", "错误", "错", "否", "f", "b", "×", "0"):
            return "false"
        return "true" if ("正确" in value or value.upper() == "A") else "false"
    return re.sub(r"^答案[：:]\s*", "", value)
