"""
持久化通知中心

解决的问题：原来错误只以前端 toast 呈现（4 秒后自动消失），
刷新页面更是彻底看不到，用户根本来不及处理。

现在把“需要人处理的信息”落库保存：
- 只有 warning / error 级别、且属于需要关注类别的事件才进通知中心
- 通知不会自动消失，必须由用户手动标记已读或清空
- 同一类问题按来源去重累积（计数 + 最近时间），避免刷屏
- 页面刷新、服务重启后依然存在
"""

# 进入通知中心的事件类型 -> (分类, 标题模板)
NOTIFY_EVENTS = {
    "login_failed": ("login", "学习通登录失败"),
    "task_failed": ("task", "任务执行失败"),
    "task_stopped": ("task", "任务被停止"),
    "interrupted": ("task", "任务被中断"),
    "stop_requested": ("task", "已请求停止任务"),
    "force_stop": ("task", "Worker 被强制终止"),
    "sync_failed": ("sync", "课程同步失败"),
    "worker_exit": ("worker", "Worker 异常退出"),
}

# 需要进入通知中心的日志关键词（反爬、验证码、题库、LLM 等外部依赖问题）
NOTIFY_LOG_PATTERNS = (
    ('章节数为零', 'chapter', '课程暂无章节', 'warning'),
    ('[FAIL]', 'media', '视频尚未被平台确认', 'warning'),
    ('(随机)', 'answer', '随机答案需要核对', 'warning'),
    ('（随机）', 'answer', '随机答案需要核对', 'warning'),
    ('视频未完成', 'media', '视频尚未被平台确认', 'warning'),
    ('平台尚未确认视频', 'media', '视频尚未被平台确认', 'warning'),
    ('视频播放异常', 'media', '视频播放异常', 'warning'),
    ('字体', 'font', '题目字体未完整识别', 'warning'),
    ('图片内容', 'font', '题目图片未完整识别', 'warning'),
    ('尚未支持', 'chapter', '章节含待处理的任务点', 'warning'),
    ('尚未确认任务点', 'chapter', '任务点尚未被平台确认', 'warning'),
    ('未作答题目', 'answer', '测验存在未完成内容', 'warning'),
    ('ReadTimeout', 'network', '平台响应超时', 'warning'),
    ('连接失败', 'network', '网络连接失败', 'warning'),
    ("LLM HTTP 401", "llm", "AI 接口认证失败，请检查设置", "error"),
    ("LLM HTTP 403", "llm", "AI 接口认证或权限失败，请检查设置", "error"),
    ("反爬虫", "antispider", "触发反爬虫限制", "warning"),
    ("antispider", "antispider", "触发反爬虫限制", "warning"),
    ("验证码", "antispider", "遇到验证码拦截", "warning"),
    ("冷却中", "antispider", "进入反爬冷却等待", "warning"),
    ("答案提交失败", "answer", "答题提交失败", "error"),
    ("提交失败", "answer", "答题提交失败", "error"),
    ("未获取到题目", "answer", "未能获取到题目", "warning"),
    ("LLM 调用异常", "llm", "LLM 调用异常", "error"),
    ("LLM 请求超时", "llm", "LLM 请求超时", "error"),
    ("LLM 连接失败", "llm", "LLM 连接失败", "error"),
    ("题库写入重试耗尽", "bank", "题库写入失败", "warning"),
)

# 高噪声但不需要用户处理的日志，明确排除
IGNORE_PATTERNS = (
    "GET http", "POST http", "重定向解析", "RequestClient 初始化",
    "添加课程", "课程列表", "已启用", "未配置在线题库", "refreshed",
)


def classify(event: str, level: str, message: str, stage: str = ""):
    """
    判断一条事件是否应该进入通知中心

    Returns:
        (category, title, level) 或 None
    """
    if event in ('task_stopped', 'stop_requested') or (event == 'worker_exit' and level not in ('warning', 'error')):
        return None
    if event == 'work_result' and level in ('warning', 'error'):
        category = 'answer' if stage in ('exam', 'work', 'homework') else 'media' if stage in ('video', 'audio', 'live', 'download') else 'chapter'
        return category, {'answer': '测验或作业有未完成内容', 'media': '视频或资源尚未完成', 'chapter': '章节任务点需要处理'}[category], level
    if event in NOTIFY_EVENTS:
        category, title = NOTIFY_EVENTS[event]
        # 用消息内容细化标题，让用户一眼看出是哪一类失败
        text = str(message or "")
        if event in ("task_failed", "task_stopped", "interrupted", "login_failed"):
            if "登录" in text:
                title = "学习通登录失败"
            elif "反爬" in text or "验证" in text:
                title = "被反爬虫拦截而中断"
            elif "提交" in text:
                title = "答案提交失败"
            elif "题目" in text:
                title = "题目处理失败"
        return category, title, ("error" if level == "error" else "warning")

    if level not in ("warning", "error"):
        return None

    text = str(message or "")
    if any(pattern in text for pattern in IGNORE_PATTERNS):
        return None
    for keyword, category, title, fallback_level in NOTIFY_LOG_PATTERNS:
        if keyword in text:
            return category, title, ("error" if level == "error" else fallback_level)

    # 其余 warning/error 也保留，但归到通用分类
    return "general", "运行告警", level


class NotificationCenter:
    """通知的读写与去重"""

    def __init__(self, db):
        self.db = db
        self.db.repair_notification_labels(classify)

    def record(self, *, event: str, level: str, message: str, task_id: str = "",
               account_id: str = "", account_label: str = "", course_name: str = "",
               feature_label: str = "", stage: str = "") -> dict:
        """按去重键累积一条通知；返回写入结果（未入库时为 None）"""
        classified = classify(event, level, message, stage)
        if not classified:
            return None
        category, title, final_level = classified

        detail = str(message or "").strip()[:500]
        context = {
            "task_id": task_id,
            "account_id": account_id,
            "account_label": account_label,
            "course_name": course_name,
            "feature_label": feature_label,
            "stage": stage,
        }
        return self.db.upsert_notification(
            category=category, title=title, detail=detail, level=final_level,
            dedupe_key=f"{category}:{account_id}:{course_name}:{detail[:80]}",
            context=context,
        )

    def list(self, include_read: bool = False, limit: int = 200, offset: int = 0, category: str = '') -> dict:
        items = self.db.list_notifications(include_read=include_read, limit=limit, offset=offset, category=category)
        return {
            "items": items,
            "filtered_total": self.db.count_notifications(unread_only=not include_read, category=category),
            "unread": self.db.count_notifications(unread_only=True),
            "total": self.db.count_notifications(),
            "by_level": self.db.notification_counts_by_level(),
        }

    def mark_read(self, notification_id: int = None, category: str = "") -> int:
        return self.db.mark_notifications_read(notification_id, category)

    def clear(self, only_read: bool = True) -> int:
        return self.db.clear_notifications(only_read=only_read)
