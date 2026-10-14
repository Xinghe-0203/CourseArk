"""多账号、会话隔离与播放故障回归；不连接真实学习通。"""
import json
from unittest.mock import Mock

import pytest
from loguru import logger

from core.config import Config
from core.request_client import get_session
from functions.deal_video import DealVideo


@pytest.fixture(autouse=True)
def isolated_config():
    data, path = Config._data, Config._config_path
    Config._data = Config._default_config()
    Config.set('video.random_progress', False)
    get_session().cookies.clear()
    yield
    Config._data, Config._config_path = data, path
    get_session().cookies.clear()


def test_saved_accounts_survive_restart_and_hide_credentials(tmp_path):
    from core.account_store import AccountStore
    path = tmp_path / 'accounts.json'
    store = AccountStore(path)
    a = store.upsert('13800000001', 'secret-a', '账号 A')
    b = store.upsert('13800000002', 'secret-b', '账号 B')
    store.set_selected([b['id'], a['id'], b['id']])
    resumed = AccountStore(path)
    assert resumed.selected_ids == [b['id'], a['id']]
    assert resumed.get(a['id'])['password'] == 'secret-a'
    public = json.dumps(resumed.list_accounts(), ensure_ascii=False)
    assert 'secret-' not in public and '13800000001' not in public
    assert len(resumed.list_accounts()) == 2


def test_password_update_invalidates_only_that_session(tmp_path):
    from core.account_store import AccountStore
    store = AccountStore(tmp_path / 'accounts.json')
    a = store.upsert('13800000001', 'old')
    b = store.upsert('13800000002', 'other')
    store.save_session(a['id'], {'uid': 'a', 'cookies': []})
    store.save_session(b['id'], {'uid': 'b', 'cookies': []})
    store.upsert('13800000001', 'new', '更名')
    assert not store.get(a['id'])['session']
    assert store.get(b['id'])['session']['uid'] == 'b'
    store.set_selected([a['id'], b['id']])
    store.delete(a['id'])
    assert store.selected_ids == [b['id']]


def test_corrupt_account_store_is_never_overwritten(tmp_path):
    from core.account_store import AccountStore
    path = tmp_path / 'accounts.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='账号'):
        AccountStore(path)
    assert path.read_text(encoding='utf-8') == '{broken'


def test_old_config_import_does_not_overwrite_saved_password(tmp_path):
    from core.account_store import AccountStore
    store = AccountStore(tmp_path / 'accounts.json')
    a = store.upsert('13800000001', 'new')
    store.import_legacy({'phone': '13800000001', 'password': 'old'})
    assert store.get(a['id'])['password'] == 'new'


def test_cookie_restore_clears_previous_account_and_preserves_scope():
    from models.user import User
    get_session().cookies.set('_uid', 'previous', domain='.chaoxing.com')
    user = User.from_session('13800000001', {
        'uid': 'new', 'name': '甲', 'cookies': [
            {'name': '_uid', 'value': 'new', 'domain': '.chaoxing.com', 'path': '/', 'secure': True, 'expires': None},
            {'name': 'external', 'value': 'bad', 'domain': '.example.com', 'path': '/'},
        ],
    })
    cookies = list(get_session().cookies)
    assert len(cookies) == 1 and cookies[0].value == 'new'
    assert cookies[0].domain == '.chaoxing.com' and cookies[0].secure
    assert user.export_session()['uid'] == 'new'


def test_valid_saved_session_does_not_password_login(monkeypatch, tmp_path):
    from core.account_store import AccountStore
    from core.account_session import AccountSessions
    from models.user import User
    store = AccountStore(tmp_path / 'accounts.json')
    a = store.upsert('13800000001', 'unused')
    store.save_session(a['id'], {'uid': 'one', 'name': '甲', 'cookies': [
        {'name': '_uid', 'value': 'one', 'domain': '.chaoxing.com', 'path': '/', 'expires': None},
    ]})
    login = Mock(side_effect=AssertionError('不得重新认证'))
    monkeypatch.setattr(User, '_login_with_password', login)
    monkeypatch.setattr('core.request_client.get', lambda **kwargs: '<ul id="courseList"></ul>')
    assert AccountSessions(store).open(a['id']).uid == 'one'
    login.assert_not_called()


def test_expired_session_reauthenticates_with_saved_password(monkeypatch, tmp_path):
    from core.account_store import AccountStore
    from core.account_session import AccountSessions
    from models.user import User
    store = AccountStore(tmp_path / 'accounts.json')
    a = store.upsert('13800000001', 'saved-secret')
    store.save_session(a['id'], {'uid': 'old', 'cookies': [
        {'name': '_uid', 'value': 'old', 'domain': '.chaoxing.com', 'path': '/'},
    ]})
    responses = iter(['<form><input type="password"></form>', '<ul id="courseList"></ul>'])
    monkeypatch.setattr('core.request_client.get', lambda **kwargs: next(responses))
    seen = []
    def login(self, username, password):
        seen.append((username, password))
        assert not list(get_session().cookies)
        self.uid, self.name = 'fresh', '甲'
        get_session().cookies.set('_uid', 'fresh', domain='.chaoxing.com')
    monkeypatch.setattr(User, '_login_with_password', login)
    assert AccountSessions(store).open(a['id']).uid == 'fresh'
    assert seen == [('13800000001', 'saved-secret')]
    assert store.get(a['id'])['session']['uid'] == 'fresh'


def test_unconfirmed_end_cache_really_replays(monkeypatch):
    video = Mock(name='测试视频', attachment={'playTime': 120000, 'isPassed': False})
    video.get_status.return_value = {'duration': 120, 'dtoken': 'test'}
    clock = [0.0]
    video.get_url.side_effect = lambda playing, *args: str(playing)
    calls = []
    monkeypatch.setattr('functions.deal_video.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('functions.deal_video.time.sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def report(url, *args):
        calls.append((int(url), clock[0]))
        return json.dumps({'isPassed': clock[0] >= 120})
    monkeypatch.setattr('functions.deal_video._doGet_with_retry', report)
    assert DealVideo.run_video(video, Mock(headers={}), Mock())
    assert calls[0] == (0, 0) and calls[-1][1] >= 120


def test_final_confirmation_is_bounded_and_truthful(monkeypatch):
    video = Mock(attachment={}, name='测试视频')
    video.get_status.return_value = {'duration': 30, 'dtoken': 'test'}
    report = Mock(return_value='{"isPassed":false}')
    monkeypatch.setattr('functions.deal_video._doGet_with_retry', report)
    monkeypatch.setattr('functions.deal_video.time.sleep', Mock())
    assert DealVideo.run_video(video, Mock(headers={}), Mock()) is False
    assert report.call_count == 5
    assert '平台' in video.last_error


@pytest.mark.parametrize('mode', ['instant', 'hybrid'])
def test_instant_failure_silently_falls_back_for_both_modes(monkeypatch, mode):
    video = Mock(name='测试视频')
    video.do_finish.return_value = False
    real = Mock(return_value=True)
    monkeypatch.setattr(DealVideo, 'run_video', real)
    log = Mock()
    result = DealVideo(Mock(), Mock(), log).batch_run_videos([{'video': video, 'mode': mode}], 1)
    assert result == {'success': 1, 'failed': 0, 'total': 1}
    real.assert_called_once()
    log.error.assert_not_called()


def test_log_suppresses_probe_and_redacts_credentials(tmp_path):
    from main import setup_logging
    path = tmp_path / 'safe.log'
    config = Config._default_config()
    config['advanced']['log_file'] = str(path)
    try:
        setup_logging(config)
        with logger.contextualize(instant_probe=True):
            logger.error('probe-declined')
        logger.debug('POST login data: uname=13800000001&password=saved-secret&token=signed-token')
        contents = path.read_text(encoding='utf-8')
        assert 'probe-declined' not in contents
        assert 'saved-secret' not in contents and 'signed-token' not in contents
    finally:
        logger.remove()
        logger.configure(patcher=None)


def test_selection_rejects_invalid_and_deduplicates():
    from core.selection import parse_selection
    assert parse_selection('2，1,2', 3) == [1, 0]
    assert parse_selection('all', 3) == [0, 1, 2]
    assert parse_selection('q', 3) == []
    for text in ['0', '-1', '4', '1,nope', ',,']:
        with pytest.raises(ValueError):
            parse_selection(text, 3)


def test_account_jobs_use_separate_processes_and_sessions():
    from core.batch_runner import run_account_jobs
    from tests.cli_worker_fixture import isolated_worker
    get_session().cookies.set('_uid', 'parent', domain='.chaoxing.com')
    jobs = [{'account': {'id': i, 'label': i}} for i in ['A', 'B']]
    results = run_account_jobs(jobs, max_workers=2, worker=isolated_worker)
    assert {r['status'] for r in results} == {'succeeded'}
    assert len({r['pid'] for r in results}) == 2
    assert all(r['cookie_uid'] == r['account_id'] == r['config_id'] for r in results)
    assert get_session().cookies.get('_uid') == 'parent'


def test_one_failed_account_does_not_abort_other_account():
    from core.batch_runner import run_account_jobs
    from tests.cli_worker_fixture import isolated_worker
    jobs = [{'account': {'id': 'A'}, 'fail': True}, {'account': {'id': 'B'}}]
    results = run_account_jobs(jobs, max_workers=2, worker=isolated_worker)
    by_id = {r['account_id']: r for r in results}
    assert by_id['A']['status'] == 'failed' and '模拟故障' in by_id['A']['error']
    assert by_id['B']['status'] == 'succeeded'


def test_cancelled_batch_reaps_all_child_processes():
    import multiprocessing
    from core.batch_runner import run_account_jobs
    from tests.cli_worker_fixture import slow_worker
    before = {p.pid for p in multiprocessing.active_children()}
    def interrupt(event):
        if event.get('event') == 'stage':
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_account_jobs([{'account': {'id': 'A'}}], on_event=interrupt, worker=slow_worker)
    assert {p.pid for p in multiprocessing.active_children()} == before


@pytest.mark.parametrize('mode', ['instant', 'hybrid'])
def test_course_entry_uses_same_silent_playback_pipeline(monkeypatch, mode):
    from functions.deal_course import DealCourse
    Config.set('video.mode', mode)
    course = Mock(if_open=True, course_name='测试课程', class_id='k', course_id='c', cpi='p')
    user, ui, log = Mock(headers={}), Mock(), Mock()
    dc = DealCourse(user, course, log, ui)
    monkeypatch.setattr(dc, 'deal_course', lambda: dc.mission_list.append({'name': '章节', 'job_count': 1, 'available': True}))
    monkeypatch.setattr(dc, 'deal_chapter', lambda _: [{'attachments': [
        {'type': 'video', 'job': True, 'objectId': 'v', 'property': {'name': '视频'}}]}])
    video = Mock(); video.name = '视频'; video.do_finish.return_value = False
    monkeypatch.setattr('functions.deal_course.Video', lambda *args, **kwargs: video)
    replay = Mock(return_value=True); monkeypatch.setattr(DealVideo, 'run_video', replay)
    dc.do_finish()
    replay.assert_called_once()
    ui.record_course_result.assert_called_once_with(1, 0, 0)
    assert not any('instant失败' in str(c) or 'instant异常' in str(c) for c in log.method_calls)


def test_swallowed_homework_fetch_error_is_failed_account(monkeypatch):
    from core.batch_runner import run_account_job
    course = Mock(course_id='c', class_id='k', if_open=True, course_name='测试课程')
    course.get_work_list.side_effect = RuntimeError('作业读取失败')
    user = Mock(course_list=[course], headers={})
    user.export_session.return_value = {}
    monkeypatch.setattr('core.account_session.open_account', lambda _: user)
    result = run_account_job({'account': {'id': 'A'}, 'config': Config._default_config(),
                              'feature': 'independent_homework', 'courses': [
                                  {'course_id': 'c', 'class_id': 'k', 'name': '测试课程'}]}, Mock())
    assert result['status'] == 'failed'
    assert result['stats']['tasks_failed'] == 1
    assert '作业读取失败' in result['errors'][0]


def test_learn_count_keeps_interactive_input_in_parent(monkeypatch, tmp_path):
    from functions.cli_app import CLIApplication
    from core.account_store import AccountStore
    app = CLIApplication(AccountStore(tmp_path / 'accounts.json'), Mock())
    jobs = [{'account': {'id': 'A'}, 'feature': 'learn_count'}]
    monkeypatch.setattr(app, 'prepare_jobs', lambda feature: jobs)
    inline = Mock(); monkeypatch.setattr(app, 'run_inline', inline)
    spawn = Mock(); monkeypatch.setattr('functions.cli_app.run_account_jobs', spawn)
    app.run_batch('learn_count')
    inline.assert_called_once_with(jobs)
    spawn.assert_not_called()


def test_closed_input_exits_menu_once(monkeypatch, tmp_path):
    from functions.cli_app import CLIApplication
    from core.account_store import AccountStore
    ui = Mock(); ui.main_menu.side_effect = [EOFError(), 0]
    app = CLIApplication(AccountStore(tmp_path / 'accounts.json'), ui)
    monkeypatch.setattr('functions.cli_app.select_accounts', lambda *args: ['A'])
    assert app.run() == 0
    ui.main_menu.assert_called_once()


def test_invalid_course_page_is_not_empty_course(monkeypatch):
    from models.course import Course
    from core.exceptions import RequestException
    course = Course('c', 'k', 'https://example.invalid', '课程', '教师')
    monkeypatch.setattr('models.course.doGet', lambda **kwargs: '<html>login required</html>')
    with pytest.raises(RequestException):
        course.get_chapter()


def test_unavailable_work_list_is_not_no_homework(monkeypatch):
    from models.course import Course
    from core.exceptions import RequestException
    course = Course('c', 'k', 'https://example.invalid', '课程', '教师')
    monkeypatch.setattr(course, '_get_work_enc_params', lambda: {})
    monkeypatch.setattr('models.course.doGet', lambda **kwargs: '')
    with pytest.raises(RequestException):
        course.get_work_list()


def test_partial_answers_are_not_submitted_as_complete():
    from functions.deal_exam import DealExam
    exam = DealExam.__new__(DealExam)
    exam.log = Mock(); exam.auto_submit = True
    exam.question_bank = None
    exam._answer_question = Mock(side_effect=[{'question_id': '1', 'answer': 'A'}, None])
    exam._submit_answers = Mock(return_value=(1, 0))
    result = exam._answer_and_submit([{'question_id': '1'}, {'question_id': '2'}], {}, '作业', 'w', {}, 'job', None, None)
    assert result['submit_ok'] == 0 and result['submit_fail'] > 0
    exam._submit_answers.assert_not_called()


def test_unverified_submission_does_not_poison_shared_answer_cache():
    from functions.deal_exam import DealExam
    exam = DealExam.__new__(DealExam)
    exam.question_bank, exam.auto_save, exam.course_id = Mock(), True, 'c'
    exam._save_submitted_answers([{'question_text': '测试', 'question_type': '单选题', 'answer': 'A', 'source': 'llm'}])
    exam.question_bank.save.assert_not_called()


def test_choice_validation_rejects_out_of_range_and_multiple_single_answers():
    from functions.deal_exam import DealExam
    exam = DealExam.__new__(DealExam)
    assert exam._normalize_answer('单选题', 'E', ['A. 甲', 'B. 乙']) == ''
    assert exam._normalize_answer('单选题', 'AB', ['A. 甲', 'B. 乙']) == ''
    assert exam._normalize_answer('多选题', 'AC', ['A. 甲', 'B. 乙']) == ''


def test_cards_parse_any_script_and_nested_braces():
    from core.chapter_parser import parse_cards
    html = '<script>analytics()</script><script>mArg = {"attachments":[{"property":{"name":"}catch 测试"}}],"defaults":{}}; end();</script>'
    assert parse_cards(html)[0]['attachments'][0]['property']['name'] == '}catch 测试'


def test_chapter_multiple_classes_and_double_quote_calls(monkeypatch):
    from models.course import Course
    course = Course('c', 'k', 'https://example.invalid', '课程', '教师')
    html = '''<div class="other fanyaChapterWhite"><div><h2><span>0/1</span></h2></div><div>
    <div class="chapter_td"><div class="extra chapter_unit"><div><div><div class="catalog_name newCatalog_name"><a><span>单元</span></a></div></div></div>
    <div><ul><li><div onclick='click("c", "knowledge-1")'><div><div class="catalog_name newCatalog_name"><a class="extra clicktitle">测试章节</a></div>
    <div class="extra catalog_task"><input value="1"></div></div></div></li></ul></div></div></div></div></div>'''
    monkeypatch.setattr('models.course.doGet', lambda **kwargs: html)
    course.get_chapter()
    chapter = course.chapter_list[0]['child_chapter'][0]
    assert chapter['knowledge_id'] == 'knowledge-1' and chapter['job_count'] == 1


def test_unrecognized_cards_are_not_successful_empty_tasks(monkeypatch):
    from functions.deal_course import DealCourse
    from core.exceptions import RequestException
    dc = DealCourse(Mock(headers={}), Mock(), Mock())
    monkeypatch.setattr(dc, '_safe_read_card_count', lambda _: 1)
    monkeypatch.setattr(dc, '_safe_doGet', lambda *args: '<html>login required</html>')
    with pytest.raises(RequestException):
        dc.deal_chapter({'knowledge_id': 'k'})


def test_empty_page_request_needs_platform_confirmation(monkeypatch):
    from functions.deal_course import DealCourse
    course = Mock(chapter_list=[{'child_chapter': [{'knowledge_id': 'k', 'job_count': 1}]}])
    dc = DealCourse(Mock(headers={}), course, Mock())
    monkeypatch.setattr(dc, '_safe_doGet', lambda *args: '<html>正常页面</html>')
    assert dc._study_empty_page({'knowledge_id': 'k'}) is False


def test_manual_answer_mode_really_reads_answer(monkeypatch):
    from functions.deal_exam import DealExam
    exam = DealExam.__new__(DealExam)
    exam.answer_mode, exam.log = 'manual', Mock()
    monkeypatch.setattr('rich.prompt.Prompt.ask', lambda *args, **kwargs: 'B')
    answer = exam._answer_question({'question_id': '1', 'question_text': '选择乙',
                                    'question_type': '单选题', 'options': ['A. 甲', 'B. 乙']})
    assert answer['answer'] == 'B' and answer['source'] == 'manual'


def test_real_terminal_roundtrip_selects_saved_accounts_and_separate_courses(tmp_path):
    import os
    import subprocess
    import sys
    import yaml
    from pathlib import Path
    from core.account_store import AccountStore
    path = tmp_path / 'accounts.json'
    store = AccountStore(path)
    for i, uid in enumerate(['A', 'B'], 1):
        a = store.upsert(f'1380000000{i}', 'test-only-do-not-print', '账号 ' + uid)
        store.save_session(a['id'], {'uid': uid, 'cookies': [
            {'name': '_uid', 'value': uid, 'domain': '.chaoxing.com', 'path': '/'}]})
    config = Config._default_config()
    config['advanced']['log_file'] = str(tmp_path / 'terminal.log')
    config_path = tmp_path / 'config.yml'
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    code = 'import sys; from tests.cli_worker_fixture import run_terminal_fixture; sys.exit(run_terminal_fixture(sys.argv[1], sys.argv[2]))'
    result = subprocess.run([sys.executable, '-c', code, str(config_path), str(path)],
                            input='all\n1\n1\n1\n3\n2\n0\n', text=True, encoding='utf-8',
                            capture_output=True, timeout=30, cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert result.returncode == 0, result.stderr[-800:]
    assert '多账号任务进度' in result.stdout and '2 个账号处理完成' in result.stdout
    assert 'test-only-do-not-print' not in result.stdout
    assert len(AccountStore(path).selected_ids) == 2


def test_parsed_empty_cards_still_require_confirmation(monkeypatch):
    from functions.deal_course import DealCourse
    dc = DealCourse(Mock(headers={}), Mock(if_open=True), Mock(), Mock())
    monkeypatch.setattr(dc, 'deal_course', lambda: dc.mission_list.append(
        {'knowledge_id': 'k', 'job_count': 1, 'available': True, 'name': '空章节'}))
    monkeypatch.setattr(dc, 'deal_chapter', lambda _: [{'attachments': []}])
    confirm = Mock(return_value=False); monkeypatch.setattr(dc, '_study_empty_page', confirm)
    dc.do_finish()
    confirm.assert_called_once()
    dc.ui.record_course_result.assert_called_once_with(0, 1, 0)


def test_missing_second_card_page_is_not_partial_success(monkeypatch):
    from functions.deal_course import DealCourse
    from core.exceptions import RequestException
    dc = DealCourse(Mock(headers={}), Mock(), Mock())
    monkeypatch.setattr(dc, '_safe_read_card_count', lambda _: 2)
    replies = iter(['<script>mArg={"attachments":[{"type":"document"}]}</script>', ''])
    monkeypatch.setattr(dc, '_safe_doGet', lambda *args: next(replies))
    with pytest.raises(RequestException):
        dc.deal_chapter({'knowledge_id': 'k'})


def test_unknown_count_is_inspected_instead_of_skipped(monkeypatch):
    from functions.deal_course import DealCourse
    from functions.deal_exam import DealExam
    chapter = {'knowledge_id': 'k', 'job_count': 0, 'job_count_known': False, 'available': True, 'name': '待核对'}
    course = Mock(if_open=True, chapter_list=[{'child_chapter': [chapter]}])
    dc = DealCourse(Mock(headers={}), course, Mock(), Mock())
    monkeypatch.setattr(dc, 'deal_course', lambda: dc.mission_list.append(chapter))
    read = Mock(return_value=[]); monkeypatch.setattr(dc, 'deal_chapter', read)
    monkeypatch.setattr(dc, '_study_empty_page', lambda _: False)
    dc.do_finish()
    read.assert_called_once()
    dc.ui.record_course_result.assert_called_once_with(0, 1, 0)
    exam = DealExam.__new__(DealExam); exam.course = course
    assert len(exam._find_work_tasks()) == 1


def test_work_list_supports_data_url_and_rejects_unparsed_pending_rows():
    from models.course import Course
    from core.exceptions import RequestException
    good = '<ul class="workList"><li data-url="https://example.invalid/?workId=w1"><p class="title">作业</p></li></ul>'
    assert Course._parse_work_list(good)[0]['work_id'] == 'w1'
    bad = '<ul class="workList"><li><p class="title">待交作业</p><p class="status">未完成</p></li></ul>'
    with pytest.raises(RequestException):
        Course._parse_work_list(bad)


def test_work_list_parser_failure_still_tries_valid_fallback(monkeypatch):
    from models.course import Course
    course = Course('c', 'k', 'https://example.invalid', '课程', '教师')
    monkeypatch.setattr(course, '_get_work_enc_params', lambda: {})
    bad = '<ul class="workList"><li>旧接口结构无法识别</li></ul>'
    good = '<ul class="workList"><li data-url="https://example.invalid/?workId=w1"><p class="title">作业</p></li></ul>'
    request = Mock(side_effect=[bad, good])
    monkeypatch.setattr('models.course.doGet', request)
    assert course.get_work_list()[0]['work_id'] == 'w1'
    assert request.call_count == 2
