"""可被 spawn 导入的离线账号处理器。"""
import os
import time
from core.config import Config
from core.request_client import get_session


def isolated_worker(job, emit):
    get_session().cookies.set('_uid', job['account']['id'], domain='.chaoxing.com')
    Config._data = {'account_probe': job['account']['id']}
    time.sleep(0.1)
    if job.get('fail'):
        raise ValueError('离线模拟故障')
    return {'account_id': job['account']['id'], 'status': 'succeeded',
            'pid': os.getpid(), 'cookie_uid': get_session().cookies.get('_uid'),
            'config_id': Config.get('account_probe'), 'stats': {'tasks_success': 1}}


def slow_worker(job, emit):
    emit({'event': 'stage', 'message': '已开始'})
    time.sleep(60)


def run_terminal_fixture(config_path, accounts_path):
    """驱动真实菜单和 spawn 流程，所有平台边界均为离线数据。"""
    from models.user import User
    from models.course import Course
    import core.batch_runner as batch
    import functions.cli_app as app
    from main import main

    def courses(user):
        user.course_list = [Course('same-course', 'class-' + user.uid, 'https://example.invalid',
                                    '测试课程', '教师', cpi='test')]
    def no_login(*args):
        raise AssertionError('有效会话不得重新登录')
    User.get_courses, User._login_with_password = courses, no_login
    app.run_account_jobs = lambda jobs, max_workers, on_event: batch.run_account_jobs(
        jobs, max_workers, on_event, worker=isolated_worker)
    return main(['-c', config_path, '--accounts-file', accounts_path])
