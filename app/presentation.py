"""网页事件呈现：原始诊断保留，默认动态仅显示有用的业务信息。"""
from . import narrative

CATEGORIES = {'login': '账号登录', 'course': '课程读取', 'chapter': '章节解析', 'video': '视频学习',
              'audio': '音频学习', 'exam': '答题', 'homework': '作业', 'download': '资源下载',
              'progress': '学习进度', 'finish': '任务结果'}
ACTIONS = {'llm': '检查 AI 服务地址、密钥与模型权限。', 'login': '检查账号密码，打开学习通完成登录验证。',
           'font': '题目未完整识别，请打开学习通核对题目。', 'antispider': '打开学习通完成验证后继续任务。',
           'answer': '核对未作答题目与提交结果后重试。', 'chapter': '查看章节开放状态或在学习通处理此任务点。',
           'network': '检查网络连接，恢复后重试。', 'media': '核对视频任务点是否被平台确认。',
           'video': '在学习通核对视频任务状态，检查平台验证与学习限制后重试。'}

# 日志关键词 -> 分类；只用于把告警归到正确的处理类别，不再落库
LOG_CATEGORIES = (
    ('章节数为零', 'chapter'), ('[FAIL]', 'media'), ('视频未完成', 'media'),
    ('平台尚未确认视频', 'media'), ('视频播放异常', 'media'), ('字体', 'font'),
    ('图片内容', 'font'), ('尚未支持', 'chapter'), ('尚未确认任务点', 'chapter'),
    ('未作答题目', 'answer'), ('ReadTimeout', 'network'), ('连接失败', 'network'),
    ('LLM HTTP 401', 'llm'), ('LLM HTTP 403', 'llm'), ('反爬虫', 'antispider'),
    ('antispider', 'antispider'), ('验证码', 'antispider'), ('冷却中', 'antispider'),
    ('提交失败', 'answer'), ('未获取到题目', 'answer'), ('随机', 'answer'),
    ('登录凭据', 'login'), ('登录失败', 'login'), ('密码', 'login'),
    ('超时', 'network'), ('timeout', 'network'),
    ('下载', 'download'), ('导出', 'download'),
    ('章节测验', 'homework'), ('作业', 'homework'), ('测验', 'homework'),
    ('LLM', 'llm'),
)
EVENT_CATEGORIES = {'login_failed': 'login', 'task_failed': 'task', 'interrupted': 'task',
                    'force_stop': 'task', 'sync_failed': 'sync', 'worker_exit': 'worker',
                    'worker_crash': 'worker'}
# v2.4.0 T10：worker_exit 从隐藏名单移除——终局事件用户必须能看到；
# worker_crash 记录 Worker 进程异常死亡（SIGKILL/OOM/崩溃），同样可见。
HIDDEN_EVENTS = ('log', 'task_progress', 'media_progress')


def _categorize(event: str, level: str, message: str, stage: str) -> str:
    category = EVENT_CATEGORIES.get(event)
    text = str(message or '')
    # 失败原因比事件名更能说明该去修什么，所以先按关键词细化一次
    if level in ('warning', 'error') or event in ('task_failed', 'login_failed', 'sync_failed'):
        for keyword, matched in LOG_CATEGORIES:
            if keyword in text:
                return matched
    if category:
        return category
    if level in ('warning', 'error'):
        return 'general'
    return stage if stage in CATEGORIES else 'progress'


def describe(event, message, level='info', stage='', payload=None):
    payload = payload or {}
    if event == 'answer_result':
        # 逐题作答结果：分类固定为答题，标题按状态给，详情展示题型与答案
        status = str(payload.get('status') or '')
        title = {'answered': 'AI 已作答', 'skipped': '已跳过',
                 'unreadable': '题面未识别'}.get(status, 'AI 作答')
        question_type = str(payload.get('question_type') or '').strip()
        answer = str(payload.get('answer') or '').strip()
        note = str(payload.get('note') or '').strip()
        parts = [part for part in (question_type, answer) if part]
        if note and status != 'answered':
            parts.append(note)
        return {'category': 'exam', 'title': title,
                'detail': ' · '.join(parts) or narrative._clean(message),
                'action': '', 'visible': True}
    category = _categorize(event, level, message, stage)
    if event.startswith('work_'):
        category = payload.get('kind') or stage or 'progress'
        if category not in CATEGORIES:
            category = 'chapter'
        title = {'work_plan': '学习内容已读取', 'work_started': '开始处理',
                 'work_progress': '正在学习', 'work_result': {'succeeded': '已确认完成', 'failed': '尚未完成',
                 'blocked': '需要处理', 'skipped': '已跳过'}.get(payload.get('status'), '处理结果')}.get(event, '学习进度')
        if event == 'work_result' and payload.get('status') in ('failed', 'blocked'):
            category = 'answer' if stage == 'work' else category
        detail = str(payload.get('name') or '')
        if payload.get('current') is not None and payload.get('total'):
            detail += f" · {payload['current']} / {payload['total']}"
        if event == 'work_result' and payload.get('status') in ('failed', 'blocked'):
            detail += ' · ' + narrative._clean(message)
        # 平台显示「此前已交卷」时把原因写进详情，避免只看到一句「已确认完成」
        if event == 'work_result' and payload.get('already_done'):
            title = '此前已完成'
            reason = narrative._clean(payload.get('detail') or message)
            detail = ' · '.join(part for part in (detail, reason) if part)
        return {'category': category, 'title': title, 'detail': detail,
                'action': ACTIONS.get(category, '') if level in ('error', 'warning') else '',
                'visible': event != 'work_progress'}
    business = narrative.describe(event, message, level, stage, payload) or {}
    return {'category': category, 'title': business.get('title', ''),
            'detail': business.get('detail', ''),
            'action': ACTIONS.get(category, '') if level in ('error', 'warning') else '',
            'visible': level in ('warning', 'error') or event not in HIDDEN_EVENTS}
