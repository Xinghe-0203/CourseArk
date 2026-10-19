"""网页事件呈现：原始诊断保留，默认动态仅显示有用的业务信息。"""
from . import narrative, notifications

CATEGORIES = {'login': '账号登录', 'course': '课程读取', 'chapter': '章节解析', 'video': '视频学习',
              'audio': '音频学习', 'exam': '答题', 'homework': '作业', 'download': '资源下载',
              'progress': '学习进度', 'finish': '任务结果'}
ACTIONS = {'llm': '检查 AI 服务地址、密钥与模型权限。', 'login': '检查账号密码，打开学习通完成登录验证。',
           'font': '题目未完整识别，请打开学习通核对题目。', 'antispider': '打开学习通完成验证后继续任务。',
           'answer': '核对未作答题目与提交结果后重试。', 'chapter': '查看章节开放状态或在学习通处理此任务点。',
           'network': '检查网络连接，恢复后重试。', 'media': '核对视频任务点是否被平台确认。',
           'video': '在学习通核对视频任务状态，检查平台验证与学习限制后重试。'}


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
    notice = notifications.classify(event, level, message, stage)
    category = notice[0] if notice else stage if stage in CATEGORIES else 'progress'
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
    return {'category': category, 'title': notice[1] if notice else business.get('title', ''),
            'detail': narrative._clean(message) if notice else business.get('detail', ''),
            'action': ACTIONS.get(category, '') if notice else '',
            'visible': bool(notice) or event not in ('log', 'task_progress', 'media_progress', 'worker_exit')}
