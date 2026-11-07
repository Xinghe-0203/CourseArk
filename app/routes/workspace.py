"""多账号工作台聚合路由。"""

from fastapi import APIRouter

from .. import accounts, sync_service
from .. import main

router = APIRouter()


@router.get('/api/workspace/accounts')
def account_workspace():
    """多账号工作台，一次读取各账号课程、当前任务和最近结果。"""
    db = main.db
    items = []
    current_states = 'pending,starting,logging_in,loading_courses,running,pausing,paused,stopping'
    for account in accounts.list_accounts():
        account_id = account['id']
        course_rows = db.list_courses(account_id)
        filters = {'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': current_states}
        current, offset = [], 0
        while True:
            page = db.list_tasks(filters, limit=500, offset=offset)
            current.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        recent = db.list_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'succeeded,failed,stopped,interrupted'}, limit=12)
        # T5：本账号 current+recent 一次性批量预取未完成单元数，消灭逐行 N+1
        batch_all = [t for t in current + recent
                     if t['feature'] in ('course_all', 'independent_homework')]
        precomputed = main._unfinished_units_batch(batch_all)
        items.append({'account': {**account, 'syncing': sync_service.is_syncing(account_id),
                                  'session': main.sessions.status(account_id)},
                      'courses': [{'course_id': c['course_id'], 'class_id': c['class_id'], 'cpi': c['cpi'],
                                   'name': c['name'], 'author': c['author'], 'if_open': bool(c['if_open']),
                                   'mission_fn': c['mission_fn'], 'mission_all': c['mission_all'],
                                   'synced_at': c['synced_at']} for c in course_rows],
                      'tasks': [main._task_view(t, precomputed) for t in current if t['feature'] in ('course_all', 'independent_homework')],
                      'recent': [main._task_view(t, precomputed) for t in recent if t['feature'] in ('course_all', 'independent_homework')],
                      'counts': {'active': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'running,starting,logging_in,loading_courses,pausing,stopping'}),
                                 'pending': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'pending'}),
                                 'paused': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'paused'}),
                                 'succeeded': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'succeeded'}),
                                 'failed': db.count_tasks({'account_id': account_id, 'feature': 'course_all,independent_homework', 'status': 'failed,interrupted'})}})
    return {'items': items}
