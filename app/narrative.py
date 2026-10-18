"""
任务叙事流

设计目标：前端不再直接展示 `log`/`GET http...` 这类面向开发者的原始文本，
而是呈现"在做什么、做到哪、成功还是失败、进度多少"的人话。

每个事件被翻译成一条结构化叙事：
    {kind, actor, title, detail, progress, level, icon}

kind 取值：
    stage    阶段推进（登录 / 读取课程 / 处理章节 …）
    media    媒体任务（视频、音频、文档、直播 …）
    answer   答题与提交（含题目来源：缓存/题库/LLM/随机）
    progress 进度百分比
    result   任务级结果（完成 / 失败 / 停止）
    notice   需要提示的异常（反爬、验证码、超时）
"""

import re

# 功能名 -> 人类可读动作
FEATURE_TEXT = {
    "course_all": ("一键完成课程任务", "完成课程任务点"),
    "chapter_exam": ("章节测验答题", "完成章节测验"),
    "independent_homework": ("独立作业答题", "完成独立作业"),
    "exam": ("独立考试", "完成独立考试"),
    "video": ("刷取视频时长", "刷取视频"),
    "learn_count": ("刷取学习次数", "刷取学习次数"),
    "download": ("下载课程资源", "下载资源"),
}

# 媒体类型关键词 -> 展示名
MEDIA_KEYWORDS = (
    ("视频", "视频"), ("音频", "音频"), ("直播", "直播"), ("文档", "文档"),
    ("图书", "图书"), ("阅读", "阅读"), ("投票", "投票"), ("讨论", "讨论"),
    ("作业", "作业"), ("测验", "测验"), ("章节", "章节"), ("下载", "资源下载"),
)

# 明确的阶段事件 -> 叙事标题
STAGE_TEXT = {
    "worker_started": "启动工作进程",
    "login_started": "登录学习通",
    "login_succeeded": "登录成功",
    "courses_loaded": "读取课程列表",
    "course_started": "开始处理课程",
    "chapter_started": "处理章节",
    "stage_changed": "进入下一阶段",
}

# 任务级结果
RESULT_TEXT = {
    "task_succeeded": ("完成", "success"),
    "task_failed": ("失败", "error"),
    "task_stopped": ("已停止", "warning"),
    "interrupted": ("被中断", "warning"),
}

_HEX_LIKE = re.compile(r"\b[a-f0-9]{16,}\b", re.IGNORECASE)
_URL_LIKE = re.compile(r"https?://\S+")
_QUOTED = re.compile(r"[\"'“”]([^\"'“”]{1,60})[\"'“”]")
# 日志里常见的 HTTP 动词前缀（如 "GET https://..."）去掉 URL 后只剩下动词
_HTTP_VERB_LIKE = re.compile(r"^(GET|POST|PUT|DELETE|HEAD|PATCH)\b\s*", re.IGNORECASE)
# 形如 name=value 的查询串残留
_QUERY_LIKE = re.compile(r"\b[a-z_]+=[^\s]*", re.IGNORECASE)


def _clean(text: str) -> str:
    """去掉 URL、HTTP 动词、长哈希等开发者细节，只保留可读正文"""
    text = _URL_LIKE.sub("", str(text or ""))
    text = _HEX_LIKE.sub("", text)
    text = _HTTP_VERB_LIKE.sub("", text)
    text = _QUERY_LIKE.sub("", text)
    text = re.sub(r"[?&]\S*", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" \t-|·?:&")


def _extract_name(message: str) -> str:
    """从日志里抽取媒体/任务名称（优先引号内内容）"""
    match = _QUOTED.search(str(message or ""))
    if match:
        return _clean(match.group(1))[:60]
    return ""


def _media_kind(text: str) -> str:
    for keyword, label in MEDIA_KEYWORDS:
        if keyword in text:
            return label
    return ""


def describe(event: str, message: str, level: str = "info", stage: str = "",
             payload: dict = None, feature: str = "") -> dict:
    """把一条原始事件翻译成前端可直接渲染的叙事条目"""
    payload = payload or {}
    text = _clean(message)
    name = _extract_name(message)

    # ---- 任务级结果 ----
    if event in RESULT_TEXT:
        label, result_level = RESULT_TEXT[event]
        stats = payload.get("stats") or {}
        detail = text or label
        return {
            "kind": "result",
            "actor": "任务",
            "title": f"任务{label}",
            "detail": detail,
            "level": result_level if level != "error" else "error",
            "progress": 100 if label == "完成" else None,
            "stats": stats,
        }

    # ---- 登录 / 课程阶段 ----
    if event in STAGE_TEXT:
        title = STAGE_TEXT[event]
        if event == "login_succeeded" and name:
            title = f"登录成功（{name}）"
        if event == "courses_loaded":
            count = payload.get("courses")
            title = f"读取到 {count} 门课程" if count is not None else title
        if event == "course_started" and name:
            title = f"开始处理课程：{name}"
        return {
            "kind": "stage",
            "actor": "学习通",
            "title": title,
            "detail": text if text and text != title else "",
            "level": "info",
        }

    # ---- 章节 ----
    if event == "chapter_started":
        current, total = payload.get("current"), payload.get("total")
        chapter = payload.get("chapter") or name or "章节"
        progress = round(current / total * 100) if current and total else None
        return {
            "kind": "stage",
            "actor": "课程",
            "title": f"处理章节：{chapter}",
            "detail": f"第 {current}/{total} 个章节" if current and total else "",
            "level": "info",
            "progress": progress,
        }

    # ---- 视频 / 媒体进度 ----
    if event == "media_progress":
        media = payload.get("media") or name or "媒体"
        current, total = payload.get("current"), payload.get("total")
        percent = payload.get("percent")
        if percent is None and current and total:
            percent = round(current / total * 100)
        if percent is None and payload.get("target_seconds"):
            played, duration = payload.get("playing_time"), payload.get("target_seconds")
            if duration:
                percent = round(min(played or 0, duration) / duration * 100)
        if total:
            detail = f"已完成 {current}/{total} 项"
        elif payload.get("playing_time") is not None:
            detail = f"已播放 {int(payload['playing_time'] // 60)} 分钟"
        else:
            detail = text
        return {
            "kind": "media",
            "actor": _media_kind(f"{media} {text}") or "媒体",
            "title": f"处理：{media}",
            "detail": detail,
            "level": "info" if level == "info" else level,
            "progress": percent,
        }

    # ---- 答题 ----
    if event == "exam_stats":
        media = payload.get("media") or name or "测验"
        total = payload.get("total")
        current = payload.get("current")
        if payload.get("submit_ok") is not None:
            ok = payload.get("submit_ok", 0)
            fail = payload.get("submit_fail", 0)
            return {
                "kind": "answer",
                "actor": "答题",
                "title": f"提交答案：{media}",
                "detail": f"服务器已接受 {ok} 题" + (f" · {fail} 题未成功" if fail else ""),
                "level": "success" if ok and not fail else "warning",
                "progress": 100,
            }
        progress = round(current / total * 100) if current and total else None
        scope = f"进度 {current}/{total} 题" if (current and total) else "开始作答"
        sources = []
        if payload.get("cache_hits"):
            sources.append(f"答题缓存 {payload['cache_hits']}")
        # tiku_hits 仅为兼容旧事件保留 key，v2.1 已删除在线题库，不再展示
        if payload.get("llm_calls"):
            sources.append(f"AI 作答 {payload['llm_calls']}")
        if payload.get("random_answers"):
            sources.append(f"随机作答 {payload['random_answers']}")
        if stage == "exam":
            title = f"AI 正在作答考试：{media}"
        else:
            title = f"正在作答：{media}"
        return {
            "kind": "answer",
            "actor": "答题",
            "title": title,
            "detail": scope + (" · " + " · ".join(sources) if sources else ""),
            "level": "info",
            "progress": progress,
        }

    # ---- 逐题作答结果 ----
    if event == "answer_result":
        media = payload.get("media") or name or "作业"
        index, total = payload.get("index"), payload.get("total")
        status = str(payload.get("status") or "")
        scope = f"第 {index}/{total} 题" if (index and total) else (f"第 {index} 题" if index else "")
        question_type = str(payload.get("question_type") or "")
        answer = str(payload.get("answer") or "")
        note = str(payload.get("note") or "")
        if status == "answered":
            title, level_text = "AI 已作答", "info"
            detail = " · ".join(part for part in (scope, question_type,
                                                 f"答案 {answer}" if answer else "") if part)
        elif status == "skipped":
            title, level_text = "已跳过", "warning"
            detail = " · ".join(part for part in (scope, note or "未作答") if part)
        else:
            title, level_text = "题面未识别", "warning"
            detail = " · ".join(part for part in (scope, note, question_type) if part)
        progress = round(index / total * 100) if index and total else None
        return {
            "kind": "answer",
            "actor": "答题",
            "title": f"{title}：{media}",
            "detail": detail,
            "level": level_text,
            "progress": progress,
        }

    # ---- 汇总进度 ----
    if event == "task_progress":
        payload_progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else None
        source = payload_progress or payload
        success = source.get("success")
        failed = source.get("failed")
        parts = []
        if success is not None:
            parts.append(f"成功 {success}")
        if failed:
            parts.append(f"失败 {failed}")
        if source.get("already_done"):
            parts.append(f"此前已完成 {source['already_done']}")
        if source.get("questions"):
            parts.append(f"题目 {source['questions']} 道")
        if source.get("skipped"):
            parts.append(f"跳过 {source['skipped']}")
        total = source.get("total")
        done = source.get("current")
        progress = round(done / total * 100) if done and total else None
        return {
            "kind": "progress",
            "actor": FEATURE_TEXT.get(feature, ("", "任务"))[1] if feature else "任务",
            "title": "进度更新",
            "detail": " · ".join(parts),
            "level": "info",
            "progress": progress,
        }

    # ---- 需要关注的问题 ----
    if level in ("warning", "error"):
        title = _notice_title(text, level)
        # 主语已由标题表达时不再重复整句（例如"触发反爬虫限制" + 同义长句）
        detail = "" if (not text or text == title) else text
        return {
            "kind": "notice",
            "actor": "注意",
            "title": title,
            "detail": detail,
            "level": level,
        }

    # ---- 其余日志：尝试识别媒体动作 ----
    if event == "log":
        media = _media_kind(text)
        if media:
            return {
                "kind": "media",
                "actor": media,
                "title": _shorten(text) or f"处理{media}",
                "detail": "",
                "level": level,
            }
        return {
            "kind": "log",
            "actor": "运行",
            "title": _shorten(text),
            "detail": "",
            "level": level,
        }

    if event == "worker_exit":
        return None
    return {
        "kind": "log",
        "actor": "运行",
        "title": _shorten(text) or event,
        "detail": "",
        "level": level,
    }


def _notice_title(text: str, level: str) -> str:
    if 'LLM HTTP 401' in text or 'LLM HTTP 403' in text:
        return 'AI 接口认证或权限失败，请检查设置'
    if "反爬" in text or "202" in text or "403" in text:
        return "触发反爬虫限制"
    if "验证码" in text:
        return "需要验证码"
    if "超时" in text or "timeout" in text.lower():
        return "请求超时"
    if "登录" in text and level == "error":
        return "登录失败"
    if "题目" in text:
        return "题目获取异常"
    return "运行告警" if level == "warning" else "运行错误"


def _shorten(text: str, limit: int = 80) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def feature_label(feature: str) -> str:
    return FEATURE_TEXT.get(feature, (feature, feature))[1]
