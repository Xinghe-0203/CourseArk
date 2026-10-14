"""真实日志与状态缺陷的隔离回归测试。"""

import asyncio
import io
import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_platform_workers(monkeypatch):
    from app.task_manager import TaskManager
    monkeypatch.setattr(TaskManager, '_tick', lambda self: None)


def make_tasks(client, count=1):
    account = client.post('/api/accounts', json={
        'username': '13800001122', 'password': 'test-password',
    }).json()
    from app import main
    tasks = []
    for index in range(count):
        tasks.append({
            'id': f'reliability-{index}', 'run_id': 'reliability-run',
            'account_id': account['id'], 'account_label': account['label'],
            'course_id': f'c{index}', 'class_id': 'class', 'cpi': '',
            'course_name': f'课程 {index}', 'feature': 'video', 'status': 'pending',
            'params': {},
        })
    main.manager.create_run(tasks, 'reliability-run')
    return account, tasks


def test_overview_keeps_account_ownership(app_client):
    account, _ = make_tasks(app_client)
    data = app_client.get('/api/overview').json()
    assert data['queue'][0].get('account_id') == account['id']


def test_overview_counts_beyond_display_limit(app_client):
    make_tasks(app_client, 65)
    assert app_client.get('/api/overview').json()['tasks']['pending'] == 65


def stream_endpoint():
    from app.main import create_app
    return next(route.endpoint for route in create_app().routes
                if getattr(route, 'path', '') == '/api/events/stream')


async def collect_stream(headers, last_id=0):
    async def disconnected():
        return True
    request = SimpleNamespace(headers=headers, is_disconnected=disconnected)
    response = await stream_endpoint()(request, last_event_id=last_id)
    return [chunk async for chunk in response.body_iterator]


def test_sse_recovers_database_events_with_header(app_client):
    from app import main
    first = main.db.add_event('t', 'a', 'log', '已经看过')
    second = main.db.add_event('t', 'a', 'log', '重启期间的消息')
    chunks = asyncio.run(collect_stream({'last-event-id': str(first)}))
    assert any(f'id: {second}\n' in chunk for chunk in chunks)
    assert all('已经看过' not in chunk for chunk in chunks)
    assert main.hub.subscriber_count() == 0


def test_sse_replays_more_than_one_page(app_client):
    from app import main
    for index in range(505):
        main.db.add_event('t', 'a', 'log', f'消息 {index}')
    chunks = asyncio.run(collect_stream({}))
    assert len([chunk for chunk in chunks if chunk.startswith('id:')]) == 505


@pytest.mark.parametrize('header', ['invalid', '-1'])
def test_sse_invalid_cursor_is_rejected(app_client, header):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as raised:
        asyncio.run(collect_stream({'last-event-id': header}))
    assert raised.value.status_code == 400


class SessionProcess:
    def __init__(self, output, code=0):
        self.stdout = io.BytesIO(output)
        self.code = code

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code


@pytest.mark.parametrize('output,code', [
    (b'', 0),
    (b'[]\n42\n', 0),
    (b'{"event":"session_result","payload":{"cookies":[]}}\n', 0),
    (b'{"event":"session_result","payload":{"cookies":[{"name":"x","value":"y"}]}}\n', 1),
])
def test_session_requires_valid_success_result(sandbox, monkeypatch, output, code):
    from app import accounts, session_service
    account = accounts.create_account('13800003344', 'test-password')
    process = SessionProcess(output, code)
    monkeypatch.setattr(session_service.subprocess, 'Popen', lambda *a, **kw: process)
    service = session_service.SessionService()
    service.fetch(account['id'], blocking=True)
    assert service.last_result(account['id'])['ok'] is False
    assert service.status(account['id'])['has_session'] is False


def test_browser_launch_failure_returns_error(sandbox, monkeypatch):
    from app import session_service
    service = session_service.SessionService()
    service.save('a', [{'name': 'x', 'value': 'y'}])

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(
        sync_playwright=Context, Error=RuntimeError,
    ))
    def fail(_):
        raise RuntimeError('browser missing')
    monkeypatch.setattr(service, '_launch_browser', fail)
    with pytest.raises(RuntimeError, match='browser missing'):
        service.open_browser('a')


def test_llm_auth_failure_is_not_repeated(sandbox, monkeypatch):
    import requests
    from utils import llm_client
    calls = []
    response = requests.Response()
    response.status_code = 401
    def post(*args, **kwargs):
        calls.append(args)
        return response
    monkeypatch.setattr(llm_client, 'get_external_session', lambda: SimpleNamespace(post=post))
    client = llm_client.LLMClient('https://example.test/v1', 'test-key')
    question = {'question_text': 'test', 'options': [], 'question_type': '单选'}
    assert client.answer([question]) == [None]
    assert client.answer([question]) == [None]
    assert len(calls) == 1


def test_auth_problem_points_to_settings():
    from app.notifications import classify
    category, title, _ = classify('log', 'error', 'LLM HTTP 401: API Key 无效')
    assert category == 'llm'
    assert '认证' in title


def test_task_logs_can_be_downloaded(app_client):
    _, tasks = make_tasks(app_client)
    from app import main
    main.db.add_event(tasks[0]['id'], '', 'log', '中文诊断日志')
    response = app_client.get(f"/api/tasks/{tasks[0]['id']}/logs")
    assert response.status_code == 200
    assert '中文诊断日志' in response.text
    assert 'attachment' in response.headers.get('content-disposition', '')


def test_failed_task_keeps_worker_error(app_client):
    account, tasks = make_tasks(app_client)
    from app import main
    main.db.set_task_status(tasks[0]['id'], 'running')
    main.manager._handle_line(tasks[0]['id'], account['id'], json.dumps({
        'event': 'task_failed', 'message': '课程读取超时', 'payload': {'stats': {}},
    }))
    assert main.db.get_task(tasks[0]['id'])['error'] == '课程读取超时'


def test_scheduler_start_is_idempotent(sandbox):
    from app.task_manager import TaskManager
    from app.database import Database
    from app.events import EventHub
    db = Database()
    manager = TaskManager(db, EventHub())
    manager.start()
    first = manager._thread
    manager.start()
    try:
        assert manager._thread is first
    finally:
        manager.shutdown()
        first.join(timeout=2)
        db.close()
    assert not first.is_alive()


def test_latest_logs_include_recent_events(app_client):
    _, tasks = make_tasks(app_client)
    from app import main
    for index in range(10):
        main.db.add_event(tasks[0]['id'], '', 'log', f'log-{index}')
    items = app_client.get(f"/api/tasks/{tasks[0]['id']}/events?limit=3&latest=true").json()['items']
    assert [item['message'] for item in items] == ['log-7', 'log-8', 'log-9']


def test_empty_chapter_selection_does_not_download_everything(sandbox):
    from app.task_model import DownloadParams
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match='章节'):
        DownloadParams(scope='chapters', chapters=[])


def test_settings_backup_is_inside_sandbox(sandbox):
    from app import settings
    from pathlib import Path
    assert Path(settings.storage_info()['backup']).is_relative_to(sandbox)


@pytest.mark.parametrize('status', ['logging_in', 'loading_courses'])
def test_pause_is_supported_during_initialization(app_client, status):
    _, tasks = make_tasks(app_client)
    from app import main
    main.db.set_task_status(tasks[0]['id'], status)
    assert app_client.post(f"/api/tasks/{tasks[0]['id']}/pause").status_code == 200


def test_history_only_lists_finished_tasks(app_client):
    make_tasks(app_client)
    assert app_client.get('/api/history').json()['total'] == 0


def test_sync_failure_is_persisted_in_problem_center(sandbox):
    from app import accounts, sync_service
    from app.database import Database
    from app.events import EventHub
    account = accounts.create_account('13800004455', 'test-password')
    db = Database()
    try:
        sync_service._finalize(db, EventHub(), account['id'], None, '课程同步超时', 1)
        assert db.count_notifications(unread_only=True) == 1
        assert db.list_notifications()[0]['category'] == 'sync'
    finally:
        db.close()


def test_sync_nonzero_exit_keeps_previous_course_cache(sandbox):
    from app import accounts, sync_service
    from app.database import Database
    from app.events import EventHub
    account = accounts.create_account('13800005566', 'test-password')
    db = Database()
    try:
        db.replace_courses(account['id'], [{'course_id': 'old', 'name': '旧课程'}])
        sync_service._finalize(db, EventHub(), account['id'], {'courses': []}, None, 1)
        assert len(db.list_courses(account['id'])) == 1
    finally:
        db.close()


def test_login_failure_sequence_finishes_with_reason(app_client):
    account, tasks = make_tasks(app_client)
    from app import main
    for event in ['login_started', 'login_failed', 'task_failed']:
        main.manager._handle_line(tasks[0]['id'], account['id'], json.dumps({
            'event': event, 'stage': 'login', 'message': '登录失败：密码错误', 'payload': {},
        }))
    row = main.db.get_task(tasks[0]['id'])
    assert row['error'] == '登录失败：密码错误'
    assert row['finished_at'] is not None


def test_stale_queue_item_cannot_restart_stopped_task(app_client, monkeypatch):
    _, tasks = make_tasks(app_client)
    from app import main
    main.manager.stop(tasks[0]['id'])
    spawned = []
    def refuse(*args, **kwargs):
        spawned.append(args)
        raise RuntimeError('should not spawn')
    monkeypatch.setattr('app.task_manager.subprocess.Popen', refuse)
    main.manager._launch(tasks[0])
    assert not spawned
    assert main.db.get_task(tasks[0]['id'])['status'] == 'stopped'


def test_sse_out_of_order_publish_does_not_drop_persisted_event(app_client):
    from app import main
    subscriber = main.hub.subscribe()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(main.hub, 'subscribe', lambda: subscriber)
    calls = 0
    async def disconnected():
        nonlocal calls
        calls += 1
        if calls == 1:
            first = main.db.add_event('t', 'a', 'log', '第一条')
            second = main.db.add_event('t', 'a', 'log', '第二条')
            for event_id in [second, first]:
                subscriber.put(main._event_view(main.db.events_after(event_id - 1, limit=1)[0]))
        return calls >= 3
    async def read():
        response = await stream_endpoint()(SimpleNamespace(headers={}, is_disconnected=disconnected), last_event_id=0)
        return [chunk async for chunk in response.body_iterator]
    try:
        chunks = asyncio.run(read())
        assert len(chunks) == 2
        assert '第一条' in chunks[0] and '第二条' in chunks[1]
    finally:
        monkeypatch.undo()


def test_sync_reserves_account_before_spawning(sandbox, monkeypatch):
    from app import accounts, sync_service
    from app.database import Database
    from app.events import EventHub
    account = accounts.create_account('13800006677', 'test-password')
    db, hub = Database(), EventHub()
    spawned, nested = [], []
    monkeypatch.setattr(sync_service, '_running', {})
    def spawn(*args, **kwargs):
        spawned.append(args)
        if len(spawned) == 1:
            nested.append(sync_service.sync_account(db, hub, account['id'], blocking=True))
        return SessionProcess(b'{"event":"sync_result","payload":{"courses":[]}}\n')
    monkeypatch.setattr(sync_service.subprocess, 'Popen', spawn)
    try:
        sync_service.sync_account(db, hub, account['id'], blocking=True)
        assert len(spawned) == 1
        assert nested[0]['started'] is False
    finally:
        db.close()


def test_sync_reservation_lasts_until_result_saved(sandbox, monkeypatch):
    from app import sync_service
    monkeypatch.setattr(sync_service, '_running', {'a': {'process': SessionProcess(b'')}})
    assert sync_service.is_syncing('a') is True


def test_initial_sse_backlog_recovers_out_of_order_arrivals(app_client, monkeypatch):
    from app import main
    def replay(*args, **kwargs):
        first = main.db.add_event('t', 'a', 'log', '第一条')
        second = main.db.add_event('t', 'a', 'log', '第二条')
        return [main._event_view(main.db.events_after(i - 1, limit=1)[0]) for i in [second, first]]
    monkeypatch.setattr(main.hub, 'replay_since', replay)
    chunks = asyncio.run(collect_stream({}))
    assert len(chunks) == 2
    assert '第一条' in chunks[0] and '第二条' in chunks[1]


def test_transient_sse_event_does_not_reset_reconnect_cursor():
    from app.main import _sse
    assert not _sse({'id': 0, 'message': '课程同步中'}).startswith('id:')


@pytest.mark.parametrize('code', [401, 403])
def test_ai_auth_failure_is_not_labeled_platform_block(code):
    from app.narrative import describe
    item = describe('log', f'LLM HTTP {code}: AI 接口认证失败', level='error')
    assert 'AI' in item['title'] and '认证' in item['title']
    assert '反爬' not in item['title']
