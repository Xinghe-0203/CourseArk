"""重构链路回归：不访问平台、不执行真实课程。"""
from unittest.mock import Mock
import pytest


@pytest.fixture(autouse=True)
def config_isolation(monkeypatch, tmp_path):
    from core.config import Config
    from app.task_manager import TaskManager
    monkeypatch.setattr(TaskManager, 'start', lambda self: None)
    monkeypatch.setenv('AUTOCXWEBUI_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, '_data', Config._default_config())
    monkeypatch.setattr(Config, '_config_path', str(tmp_path / 'config.yml'))


def test_work_progress_is_deduplicated_and_not_last_video_percent():
    from app.work_progress import reduce_progress, summarize
    state = reduce_progress({}, 'work_plan', {'units': [{'id': 'v1'}, {'id': 'v2'}], 'sealed': True})
    state = reduce_progress(state, 'work_progress', {'id': 'v1', 'current': 90, 'total': 100})
    assert summarize(state)['percent'] == 45
    state = reduce_progress(state, 'work_result', {'id': 'v1', 'status': 'succeeded'})
    state = reduce_progress(state, 'work_result', {'id': 'v1', 'status': 'succeeded'})
    assert summarize(state)['completed'] == 1
    assert summarize(state)['percent'] == 50


def test_discovery_and_failed_units_never_claim_complete():
    from app.work_progress import reduce_progress, summarize
    state = reduce_progress({}, 'work_plan', {'units': [{'id': 'v1'}]})
    assert summarize(state)['percent'] is None
    state = reduce_progress(state, 'work_plan', {'sealed': True})
    state = reduce_progress(state, 'work_result', {'id': 'v1', 'status': 'failed'})
    assert summarize(state)['percent'] == 0
    assert summarize(state)['failed'] == 1


def test_attachment_json_is_found_in_any_script_and_nested_strings():
    from core.chapter_parser import parse_cards
    html = '<script>analytics()</script><script>var mArg={"attachments":[{"property":{"name":"a }catch b"},"job":true}],"defaults":{}}; after();</script>'
    assert parse_cards(html)[0]['attachments'][0]['property']['name'] == 'a }catch b'


def test_font_decode_is_scoped_and_handles_entities_and_tails(monkeypatch):
    from core.font_decoder import FontDecoder
    from lxml import etree
    decoder = FontDecoder()
    monkeypatch.setattr(decoder, 'extract_font_data', lambda _: b'font')
    monkeypatch.setattr(decoder, '_build_mapping_via_contour', lambda _: {'错': '对'})
    html = '<div><p>错</p><p class="font-cxsecret">&#38169;<b>错</b>错</p></div>'
    root = etree.HTML(decoder.decode_page(html))
    assert root.xpath('//p[1]/text()') == ['错']
    assert ''.join(root.xpath('//p[2]//text()')) == '对对对'


def test_instant_video_uses_silent_realtime_fallback(monkeypatch):
    from functions.deal_video import DealVideo
    video = Mock(name='video')
    video.name = '测试视频'
    video.do_finish.return_value = False
    log = Mock()
    fallback = Mock(return_value=True)
    monkeypatch.setattr(DealVideo, 'run_video', fallback)
    result = DealVideo(Mock(), Mock(), log).batch_run_videos([{'video': video, 'mode': 'instant'}], 1)
    assert result['success'] == 1 and result['failed'] == 0
    fallback.assert_called_once()
    log.error.assert_not_called()


def test_reasoning_letters_are_not_guessed_as_answers():
    from core.answer_validation import normalize_answer
    assert normalize_answer('单选题', 'B because A is incorrect', ['A.甲', 'B.乙']) == ''
    assert normalize_answer('多选题', '答案：A、B', ['A.甲', 'B.乙']) == 'AB'
    assert normalize_answer('单选题', 'D', ['A.甲', 'B.乙']) == ''
    assert normalize_answer('判断题', '不正确') == 'false'


def test_nested_secret_nodes_are_decoded_once(monkeypatch):
    from core.font_decoder import FontDecoder
    from lxml import etree
    decoder = FontDecoder()
    monkeypatch.setattr(decoder, 'extract_font_data', lambda _: b'font')
    monkeypatch.setattr(decoder, '_build_mapping_via_contour', lambda _: {'A': 'B', 'B': 'C'})
    root = etree.HTML(decoder.decode_page('<div class="font-cxsecret"><span class="font-cxsecret">A</span></div>'))
    assert root.xpath('//span/text()') == ['B']


def test_stop_signal_is_not_swallowed_by_media():
    from core import runtime
    from functions.deal_video import DealVideo
    video = Mock()
    video.get_status.side_effect = runtime.StopRequested('stop')
    import pytest
    with pytest.raises(runtime.StopRequested):
        DealVideo.run_video(video, Mock(), Mock())


def test_instant_exception_still_reaches_realtime(monkeypatch):
    from functions.deal_video import DealVideo
    video = Mock(); video.name = '视频';video.do_finish.side_effect = RuntimeError('network')
    fallback = Mock(return_value=True)
    monkeypatch.setattr(DealVideo, 'run_video', fallback)
    result = DealVideo(Mock(), Mock(), Mock()).batch_run_videos([{'video': video, 'mode': 'instant'}], 1)
    assert result['success'] == 1


def test_submission_acceptance_is_strict():
    from core.answer_validation import accepted_response
    assert accepted_response({'status': True})
    assert accepted_response({'status': 'true'})
    assert not accepted_response({'status': 'false'})
    assert not accepted_response({'status': 'error'})


def test_multi_answer_text_does_not_drop_selections():
    from core.answer_validation import normalize_answer
    assert normalize_answer('多选题', '甲#乙', ['A.甲', 'B.乙']) == 'AB'
    assert normalize_answer('单选题', 'Apple', ['A. Banana', 'B. Apple']) == 'B'


def test_unresolved_root_font_blocks_question():
    from functions.deal_exam import DealExam
    from lxml import etree
    element = etree.HTML('<div class="TiMu" data-font-unresolved="true"><div class="Zy_TItle">乱码题目</div><input name="answertype12345"/></div>').xpath('//div[@class="TiMu"]')[0]
    assert DealExam.__new__(DealExam)._parse_single_question(element)['unreadable']


def test_bitmap_reference_and_ambiguous_match():
    from core.font_bitmap import reference_table, match
    table = reference_table()
    assert len(table[0]) == 7027
    assert match(0, 0, ([ord('甲'), ord('乙')], [0, 0], [0, 0], 30)) is None
    assert match(0, 0, ([ord('甲'), ord('乙')], [0, 31], [0, 63], 30)) == '甲'


def test_progress_api_failure_is_not_empty_course(monkeypatch):
    from models.course import Course
    from core.exceptions import RequestException
    course = Course.__new__(Course)
    course.class_id, course.course_id, course.cpi, course.headers, course._jobEnc = 'c', 'k', 'p', {}, 'enc'
    monkeypatch.setattr('models.course.doGet', lambda **kwargs: '<html>login required</html>')
    with pytest.raises(RequestException):
        course.get_progress_data()


def test_video_progress_reads_all_pages(monkeypatch):
    import json
    from models.course import Course
    course = Course.__new__(Course)
    course.class_id, course.course_id, course.cpi, course.headers, course._jobEnc = 'c', 'k', 'p', {}, 'enc'
    calls = []
    def get(**kwargs):
        calls.append(kwargs['url'])
        result = list(range(16)) if 'page=1&' in kwargs['url'] else [16]
        return json.dumps({'data': {'results': result, 'total': 17, 'totalPage': 2}})
    monkeypatch.setattr('models.course.doGet', get)
    assert course.get_progress_data() == list(range(17))
    assert len(calls) == 2


def test_unavailable_homework_list_is_not_no_homework(monkeypatch):
    from models.course import Course
    from core.exceptions import RequestException
    course = Course.__new__(Course)
    course.class_id, course.course_id, course.cpi, course.headers = 'c', 'k', 'p', {}
    monkeypatch.setattr(course, '_get_work_enc_params', lambda: {})
    monkeypatch.setattr('models.course.doGet', Mock(side_effect=TimeoutError('network')))
    with pytest.raises(RequestException):
        course.get_work_list()


def test_login_html_is_not_empty_chapters(monkeypatch):
    from models.course import Course
    from core.exceptions import RequestException
    course = Course('k', 'c', '', '课程', '', 'p', {})
    monkeypatch.setattr('models.course.doGet', lambda **kwargs: '<html>login required</html>')
    with pytest.raises(RequestException):
        course.get_chapter()


def test_notifications_use_full_unread_count_and_paginate(app_client):
    from app import main
    unread = main.db.upsert_notification(category='llm', title='old unread', detail='test',
                                        level='warning', dedupe_key='old')
    for i in range(205):
        row = main.db.upsert_notification(category='network', title='read', detail='test',
                                          level='warning', dedupe_key=f'read-{i}')
        main.db.mark_notifications_read(row['id'])
    result = app_client.get('/api/notifications?include_read=false').json()
    assert result['unread'] == 1 and len(result['items']) == 1
    result = app_client.get('/api/notifications?include_read=true&offset=200&limit=100').json()
    assert len(result['items']) == 6 and result['filtered_total'] == 206
    result = app_client.get('/api/notifications?include_read=true&category=llm').json()
    assert result['filtered_total'] == 1 and result['items'][0]['id'] == unread['id']


def test_multi_account_workspace_preserves_account_boundaries(app_client):
    accounts = [app_client.post('/api/accounts', json={'username': f'1380000000{i}', 'password': 'test-only', 'label': f'账号{i}'}).json() for i in (1, 2)]
    targets = [{'account_id': a['id'], 'course_id': 'shared', 'class_id': f'c{i}', 'course_name': '同名课程'} for i, a in enumerate(accounts)]
    result = app_client.post('/api/runs', json={'feature': 'course_all', 'targets': targets}).json()
    assert result['count'] == 2
    profiles = app_client.get('/api/workspace/accounts').json()['items']
    assert len(profiles) == 2
    assert {p['tasks'][0]['class_id'] for p in profiles} == {'c0', 'c1'}
    assert all('password' not in p['account'] for p in profiles)


def test_unused_download_settings_do_not_block_course_tasks(app_client):
    app_client.patch('/api/settings', json={'defaults': {'download': {'scope': 'chapters', 'chapters': []}}})
    account = app_client.post('/api/accounts', json={'username': '13800000001', 'password': 'test-only'}).json()
    response = app_client.post('/api/runs', json={'feature': 'course_all', 'targets': [{'account_id': account['id'], 'course_id': 'c'}]})
    assert response.status_code == 201


def test_launcher_reads_configured_port_without_writes(tmp_path):
    import sqlite3, json
    from tools.launcher import configured_port, existing_service
    data = tmp_path / 'data';data.mkdir()
    database = data / 'webui.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE app_settings (key TEXT, value TEXT)')
        conn.execute('INSERT INTO app_settings VALUES (?,?)', ('global', json.dumps({'server': {'port': 8897}})))
    before = database.stat().st_mtime_ns
    assert configured_port(tmp_path) == 8897
    assert database.stat().st_mtime_ns == before


def test_activity_survives_diagnostic_log_flood(app_client):
    from app import main
    main.db.create_task({'id': 'activity-test', 'account_id': 'a', 'feature': 'course_all'})
    main.db.add_event('activity-test', 'a', 'work_started', '开始处理视频',
                      stage='video', payload={'id': 'v', 'name': '第一讲'})
    for i in range(80):
        main.db.add_event('activity-test', 'a', 'log', f'debug {i}', level='debug')
    detail = app_client.get('/api/tasks/activity-test').json()
    assert len(detail['events']) == 50
    assert [e['event'] for e in detail['activity_events']] == ['work_started']


def test_hidden_narrative_events_still_have_safe_presentation():
    from app.presentation import describe
    for event in ('task_progress', 'media_progress', 'worker_exit'):
        value = describe(event, 'progress', stage='progress')
        assert value['visible'] is False


def test_account_bulk_stop_covers_all_pages_and_preserves_other_accounts(app_client):
    from app import main
    account = app_client.post('/api/accounts', json={'username': '13800000001', 'password': 'test-only'}).json()
    for i in range(550):
        main.db.create_task({'id': f'bulk-{i}', 'account_id': account['id'],
                             'feature': 'course_all', 'status': 'pending'})
    main.db.create_task({'id': 'other-account', 'account_id': 'other', 'feature': 'course_all', 'status': 'pending'})
    main.db.create_task({'id': 'legacy-module', 'account_id': account['id'], 'feature': 'download', 'status': 'pending'})
    assert len(app_client.get('/api/workspace/accounts').json()['items'][0]['tasks']) == 550
    result = app_client.post(f"/api/accounts/{account['id']}/tasks/stop").json()
    assert result['accepted'] == 550 and result['changed'] == 0
    assert main.db.count_tasks({'account_id': account['id'], 'status': 'stopped'}) == 550
    assert main.db.get_task('other-account')['status'] == 'pending'
    assert main.db.get_task('legacy-module')['status'] == 'pending'


def test_account_bulk_pause_resume_and_invalid_commands(app_client):
    from app import main
    account = app_client.post('/api/accounts', json={'username': '13800000001', 'password': 'test-only'}).json()
    main.db.create_task({'id': 'pause-me', 'account_id': account['id'], 'feature': 'course_all', 'status': 'running'})
    main.db.create_task({'id': 'resume-me', 'account_id': account['id'], 'feature': 'independent_homework', 'status': 'paused'})
    assert app_client.post(f"/api/accounts/{account['id']}/tasks/pause").json()['accepted'] == 1
    assert main.db.get_task('pause-me')['status'] == 'pausing'
    assert app_client.post(f"/api/accounts/{account['id']}/tasks/resume").json()['accepted'] == 1
    assert main.db.get_task('resume-me')['status'] == 'running'
    assert app_client.post(f"/api/accounts/{account['id']}/tasks/delete").status_code == 400
    assert app_client.post('/api/accounts/missing/tasks/stop').status_code == 404


def test_homework_fetch_failure_and_empty_result_finish_work_units(monkeypatch):
    from functions.deal_homework import DealHomework
    course = Mock(course_name='测试课程', if_open=True)
    course.get_work_list.return_value = [{'work_id':'1','title':'网络异常作业'}, {'work_id':'2','title':'未读取作业'}]
    exam = Mock()
    exam.answer_independent_work.side_effect = [TimeoutError('network'), {}]
    monkeypatch.setattr('functions.deal_homework.DealExam', lambda *args: exam)
    events = []
    monkeypatch.setattr('core.runtime.emit', lambda event, *args, **kwargs: events.append((event, kwargs.get('payload', {}))))
    ui = Mock()
    DealHomework(Mock(), course, Mock(), ui).do_finish()
    results = [p for event,p in events if event == 'work_result']
    assert len(results) == 2 and all(p['status'] == 'failed' for p in results)
    assert {p['id'] for p in results} == {'homework:1','homework:2'}
    ui.record_course_result.assert_called_once_with(0, 2, 0)


def test_chapter_double_quotes_and_multiple_classes_are_parsed():
    from models.course import Course
    from lxml import etree
    course = Course('k', 'c', '', '课程', '', 'p', {})
    course._child_chapter_list = []
    node = etree.HTML('<li><div onclick=\'jump("course", "chapter-42")\'><a class="leaf clicktitle more">第一章</a><div class="catalog_task other"><input value="3"/></div></div></li>').xpath('//li')[0]
    course._recursion_chapter_item(node, 0)
    assert course._child_chapter_list[0]['knowledge_id'] == 'chapter-42'
    assert course._child_chapter_list[0]['name'] == '第一章'
    assert course._child_chapter_list[0]['job_count'] == 3


def test_unconfirmed_video_at_end_replays_in_real_time(monkeypatch):
    from functions.deal_video import DealVideo
    from core.config import Config
    Config.set('video.random_progress', False)
    video=Mock();video.name='未确认的视频';video.attachment={'playTime':120000,'isPassed':False}
    video.get_status.return_value={'duration':120,'dtoken':'test-token'}
    video.get_url.side_effect=lambda playing,*args: str(playing)
    clock=[0.0];calls=[]
    monkeypatch.setattr('functions.deal_video.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('core.runtime.sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    def report(url,*args):
        calls.append((int(url),clock[0]))
        return '{"isPassed":true}' if clock[0]>=120 else '{"isPassed":false}'
    monkeypatch.setattr('functions.deal_video._doGet_with_retry',report)
    assert DealVideo.run_video(video,Mock(headers={}),Mock())
    assert calls[0][0]==0 and calls[-1][1]>=120


def test_realtime_end_waits_for_delayed_confirmation(monkeypatch):
    from functions.deal_video import DealVideo
    from core.config import Config
    Config.set('video.random_progress',False)
    video=Mock();video.name='延迟确认';video.attachment={}
    video.get_status.return_value={'duration':30,'dtoken':'t'}
    video.get_url.return_value='test://video'
    monkeypatch.setattr('core.runtime.sleep',Mock())
    monkeypatch.setattr('functions.deal_video._doGet_with_retry',Mock(side_effect=['{}','{"isPassed":false}','{"isPassed":true}']))
    assert DealVideo.run_video(video,Mock(headers={}),Mock())


def test_video_final_failure_is_a_specific_page_notice(monkeypatch):
    from functions.deal_video import DealVideo
    video=Mock();video.name='视频';video.last_error='视频完整播放后，平台尚未确认任务点完成'
    video.do_finish.return_value=False
    monkeypatch.setattr(DealVideo,'run_video',Mock(return_value=False))
    emit=Mock();monkeypatch.setattr('core.runtime.emit',emit)
    log=Mock()
    assert DealVideo(Mock(),Mock(),log).batch_run_videos([{'video':video,'mode':'hybrid'}],1)['failed']==1
    result=[c for c in emit.call_args_list if c.args[0]=='work_result'][0]
    assert result.kwargs['level']=='warning'
    assert '平台尚未确认' in result.args[1]
    log.error.assert_not_called()


def test_instant_probe_diagnostics_are_absent_from_both_logs(monkeypatch,tmp_path):
    from functions.deal_video import DealVideo
    from worker.runner import setup_logging,add_file_logger
    from loguru import logger
    sink=Mock();setup_logging(sink);add_file_logger(str(tmp_path),'quiet-probe')
    video=Mock();video.name='静默回退'
    def probe():
        logger.error('instant-probe-declined');logger.debug('instant-probe-response');return False
    video.do_finish.side_effect=probe
    monkeypatch.setattr(DealVideo,'run_video',Mock(return_value=True))
    try:
        DealVideo(Mock(),Mock(),logger).batch_run_videos([{'video':video,'mode':'instant'}],1)
        assert all('instant-probe' not in c.args[1] for c in sink.emit.call_args_list)
        assert 'instant-probe' not in (tmp_path/'quiet-probe.log').read_text(encoding='utf-8')
    finally:
        logger.remove();logger.configure(patcher=None)


def test_notifications_identify_video_and_random_answers():
    from app.notifications import classify
    assert classify('log','error','[FAIL] 测试.mp4','log')[0]=='media'
    assert classify('log','warning','判断题 -> true (随机)','log')[0]=='answer'


def test_existing_problem_labels_are_repaired_without_losing_history(tmp_path):
    from app.database import Database
    from app.notifications import NotificationCenter
    db = Database(str(tmp_path / 'labels.db'))
    try:
        item = db.upsert_notification(category='general', title='运行告警', detail='[FAIL] 货物保险.mp4', level='error', dedupe_key='legacy-video', context={'task_id': 'historical-task'})
        db.mark_notifications_read(item['id'])
        before = db.list_notifications(include_read=True)[0]
        center = NotificationCenter(db)
        after = center.list(include_read=True)['items'][0]
        assert after['category'] == 'media'
        assert '视频' in after['title']
        for field in ('id', 'detail', 'count', 'read_at', 'first_seen', 'last_seen', 'context_json'):
            assert after[field] == before[field]
        NotificationCenter(db)
        assert db.count_notifications() == 1
    finally:
        db.close()


def test_video_final_confirmation_is_bounded_and_preserves_partial_resume(monkeypatch):
    from functions.deal_video import DealVideo, FINAL_CONFIRM_DELAYS
    from core.config import Config
    Config.set('video.random_progress', False)
    video = Mock(); video.name = '货物保险'; video.attachment = {'playTime': 60000}
    video.get_status.return_value = {'duration': 120, 'dtoken': 'test-only'}
    video.get_url.return_value = 'test://video'
    sleeps = Mock(); monkeypatch.setattr('core.runtime.sleep', sleeps)
    report = Mock(return_value='{"isPassed":false,"videoTimeLimit":false,"hasJobLimit":false}')
    monkeypatch.setattr('functions.deal_video._doGet_with_retry', report)
    assert not DealVideo.run_video(video, Mock(headers={}), Mock())
    assert video.get_url.call_args_list[0].args[0] == 60
    assert report.call_count == 2 + len(FINAL_CONFIRM_DELAYS)
    assert '平台尚未确认' in video.last_error
    assert [call.args[0] for call in sleeps.call_args_list[-3:]] == list(FINAL_CONFIRM_DELAYS)


def test_control_sleep_excludes_time_spent_paused(monkeypatch, tmp_path):
    from core.runtime import ControlState
    clock = [0.0]; waits = []; checked = [False]
    control = ControlState(str(tmp_path / 'absent-control.json'))
    def check():
        if not checked[0]:
            checked[0] = True
            clock[0] += 120  # 检查点等待暂停恢复
    def sleep(seconds):
        waits.append(seconds); clock[0] += seconds
    monkeypatch.setattr(control, 'check', check)
    monkeypatch.setattr('core.runtime.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('core.runtime.time.sleep', sleep)
    control.sleep(1)
    assert sum(waits) == pytest.approx(1)
    assert clock[0] == pytest.approx(121)


def test_video_pause_does_not_skip_remaining_playback(monkeypatch):
    from functions.deal_video import DealVideo
    from core.config import Config
    Config.set('video.random_progress', False)
    video = Mock(); video.name = '暂停恢复'; video.attachment = {}
    video.get_status.return_value = {'duration': 120, 'dtoken': 'test-only'}
    video.get_url.side_effect = lambda playing, *args: str(playing)
    clock = [0.0]; waits = []; reports = []
    def sleep(seconds):
        if not waits: clock[0] += 120  # 一次暂停耗时
        waits.append(seconds); clock[0] += seconds
    def report(url, *args):
        reports.append((int(url), clock[0]))
        return '{"isPassed":true}' if int(url) == 120 else '{}'
    monkeypatch.setattr('functions.deal_video.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('core.runtime.sleep', sleep)
    monkeypatch.setattr('functions.deal_video._doGet_with_retry', report)
    assert DealVideo.run_video(video, Mock(headers={}), Mock())
    assert sum(waits) >= 120
    assert reports[-1] == (120, 240)


def test_task_log_redacts_credentials_in_worker_and_historical_download(app_client, tmp_path):
    from app import main
    from worker.runner import setup_logging, add_file_logger
    from loguru import logger
    secret = "test-password-cipher"
    token = "test-playback-token"
    raw = f"POST https://example.invalid/report?dtoken={token}&playingTime=60 data: {{'password': '{secret}', 'username': 'test-user'}}"
    sink = Mock(); setup_logging(sink); add_file_logger(str(tmp_path), 'redaction')
    try:
        logger.debug(raw)
        message = sink.emit.call_args.args[1]
        assert secret not in message and token not in message
        assert 'playingTime=60' in message
        file_text = (tmp_path / 'redaction.log').read_text(encoding='utf-8')
        assert secret not in file_text and token not in file_text
    finally:
        logger.remove(); logger.configure(patcher=None)
    main.db.create_task({'id': 'old-sensitive-log', 'account_id': 'a', 'feature': 'course_all'})
    main.db.add_event('old-sensitive-log', 'a', 'log', raw, level='debug')
    response = app_client.get('/api/tasks/old-sensitive-log').json()
    assert secret not in str(response['events']) and token not in str(response['events'])
    text = app_client.get('/api/tasks/old-sensitive-log/logs').text
    assert secret not in text and token not in text
    assert 'playingTime=60' in text


def test_video_url_path_and_structured_failure_are_redacted(app_client):
    import json
    from app import main
    from app.log_redaction import redact
    token = 'synthetic-path-token'
    raw = f'GET https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/cpi/{token}?playingTime=60&enc=synthetic-signature password=synthetic-password'
    assert token not in redact(raw)
    main.db.create_task({'id': 'structured-sensitive-log', 'account_id': 'a', 'feature': 'course_all', 'status': 'running'})
    main.manager._handle_line('structured-sensitive-log', 'a', json.dumps({
        'task_id': 'structured-sensitive-log', 'event': 'task_failed', 'level': 'error', 'message': raw,
        'payload': {'reason': raw, 'traceback': raw, 'dtoken': token, 'current': 60},
    }))
    stored = main.db.get_task('structured-sensitive-log')
    assert token not in stored['error'] and 'synthetic-password' not in stored['error']
    event = main.db.list_events('structured-sensitive-log')[0]
    assert token not in event['payload_json']
    # 旧数据展示与下载兜底同样脱敏，原始数据库内容不修改。
    main.db.update_task('structured-sensitive-log', error=raw)
    main.db.add_event('structured-sensitive-log', 'a', 'log', raw, payload={'traceback': raw, 'dtoken': token})
    response = app_client.get('/api/tasks/structured-sensitive-log').json()
    assert token not in str(response) and 'synthetic-password' not in str(response)
    assert response['events'][0]['payload']['current'] == 60


def test_plain_questions_with_font_css_class_are_not_blocked():
    from core.font_decoder import FontDecoder
    from functions.deal_exam import DealExam
    from lxml import etree
    html = '<div class="TiMu font-cxsecret"><div class="Zy_TItle">【判断】Flash可以制作动画</div><input name="answertype12345"/></div>'
    decoded = FontDecoder().decode_page(html)
    question = DealExam.__new__(DealExam)._parse_single_question(etree.HTML(decoded).xpath('//div[contains(@class,"TiMu")]')[0])
    assert question and not question['unreadable']
    assert 'Flash可以制作动画' in question['question_text']


def test_missing_encryption_font_still_blocks_question():
    from core.font_decoder import FontDecoder
    from functions.deal_exam import DealExam
    from lxml import etree
    html = '<style id="cxSecretStyle">@font-face{font-family:font-cxsecret;src:url(/missing.ttf)}</style><div class="TiMu font-cxsecret"><div class="Zy_TItle">【判断】未解码文字</div><input name="answertype12345"/></div>'
    decoded = FontDecoder().decode_page(html)
    node = etree.HTML(decoded).xpath('//div[contains(@class,"TiMu")]')[0]
    assert node.get('data-font-unresolved') == 'true'
    assert DealExam.__new__(DealExam)._parse_single_question(node)['unreadable']


def test_font_data_supports_wrapped_base64_and_secret_style_alias():
    from core.font_decoder import FontDecoder
    html = '<style id="cxSecretStyle">@font-face{font-family:cxsecret;src:url("data:font/ttf;base64,dGVz\n dA==")}</style>'
    assert FontDecoder().extract_font_data(html) == b'test'


def test_question_fetch_uses_ajax_headers_and_plain_font_template(monkeypatch):
    from functions.deal_exam import DealExam
    from core.font_decoder import FontDecoder
    exam = DealExam.__new__(DealExam)
    exam.headers = {'User-Agent': 'test-agent'}
    exam.course_id = 'course-test'
    exam.font_decoder = FontDecoder()
    html = '<form><div class="TiMu font-cxsecret"><div class="Zy_TItle">【判断】Flash可以制作动画</div><input name="answertype12345"/></div></form>'
    fetch = Mock(return_value=html); monkeypatch.setattr('functions.deal_exam.doGet', fetch)
    questions, hidden, form = exam._try_fetch_questions_via_api({'workId': 'work-test', 'courseid': 'course-test', 'clazzId': 'class-test'})
    headers = fetch.call_args.kwargs['headers']
    assert headers['X-Requested-With'] == 'XMLHttpRequest'
    assert 'workId=work-test' in headers['Referer'] and 'clazzid=class-test' in headers['Referer']
    assert len(questions) == 1 and not questions[0]['unreadable']
    # v2.1：同时返回表单隐藏字段与表单结构，供 AI 作答后自动提交复用
    assert hidden == {}
    assert form is not None


@pytest.mark.parametrize('worker_name', ['sync_runner', 'session_runner'])
def test_sync_and_session_logs_and_public_sse_redact_secrets(worker_name):
    import importlib
    from loguru import logger
    from app.main import _sse
    module = importlib.import_module('worker.' + worker_name)
    sink = Mock(); module.setup_logging(sink)
    raw = "data: password=synthetic-password dtoken=synthetic-token"
    try:
        logger.debug(raw)
        assert 'synthetic-password' not in sink.emit.call_args.args[1]
        assert 'synthetic-token' not in sink.emit.call_args.args[1]
        text = _sse({'id': 0, 'event': 'log', 'message': raw, 'payload': {'traceback': raw}})
        assert 'synthetic-password' not in text and 'synthetic-token' not in text
    finally:
        logger.remove(); logger.configure(patcher=None)


@pytest.mark.parametrize('prefix, marker, text', [
    ('<link rel="stylesheet" href="/font/CXSecret.css">', 'class="TiMu font-cxsecret"', '加密文字'),
    ('<style>@font-face{font-family:cxsecret;src:url(/missing.ttf)}</style>', 'class="TiMu" style="font-family:cxsecret"', '加密文字'),
    ('', 'class="TiMu" style="font-family:CXSECRET"', '\ue001'),
])
def test_missing_font_aliases_and_case_never_release_encrypted_questions(prefix, marker, text):
    from core.font_decoder import FontDecoder
    from functions.deal_exam import DealExam
    from lxml import etree
    html = prefix + f'<div {marker}><div class="Zy_TItle">【判断】{text}</div><input name="answertype12345"/></div>'
    decoded = FontDecoder().decode_page(html)
    node = etree.HTML(decoded).xpath('//div[contains(@class,"TiMu")]')[0]
    assert DealExam.__new__(DealExam)._parse_single_question(node)['unreadable']


def test_invalid_font_data_keeps_inline_alias_unresolved():
    import base64
    from core.font_decoder import FontDecoder
    from functions.deal_exam import DealExam
    from lxml import etree
    encoded = base64.b64encode(b'not-a-font').decode()
    html = f'<style>@font-face{{font-family:cxsecret;src:url("data:font/ttf;base64,{encoded}")}}</style><div class="TiMu" style="font-family:cxsecret"><div class="Zy_TItle">【判断】未解码文字</div><input name="answertype12345"/></div>'
    node = etree.HTML(FontDecoder().decode_page(html)).xpath('//div[contains(@class,"TiMu")]')[0]
    assert node.get('data-font-unresolved') == 'true'
    assert DealExam.__new__(DealExam)._parse_single_question(node)['unreadable']
