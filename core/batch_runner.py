"""每账号一个 spawn 进程，隔离 Config 和网络会话。"""
import copy
import io
import multiprocessing
import os
import queue
import re
from contextlib import redirect_stdout
from pathlib import Path

from loguru import logger
from core.logging_utils import patch_log, visible_log, redact


class BatchStats:
    """处理器的 TUI 回调；在主进程展示，每次批次重新统计。"""
    def __init__(self, emit):
        from functions.tui import TUI
        self.stats = TUI().stats
        self.emit = emit

    def update(self):
        self.emit({'event': 'progress', 'stats': dict(self.stats)})

    def start_course(self, name, index=1, total=1):
        self.emit({'event': 'stage', 'message': f'[{index}/{total}] {name}'})

    def start_section(self, name, index=1, total=1):
        self.emit({'event': 'stage', 'message': f'[{index}/{total}] 章节：{name}'})

    def task_already_done(self, *args):
        pass  # record_course_result 统一计数，避免重复。

    def count_success(self, n=1):
        self.stats['tasks_success'] += n; self.update()

    def count_failed(self, n=1):
        self.stats['tasks_failed'] += n; self.update()

    def count_skipped(self, n=1):
        self.stats['tasks_skipped'] += n; self.update()

    def record_course_result(self, success, failed, already_done=0):
        self.stats['courses_processed'] += 1
        self.stats['tasks_success'] += success
        self.stats['tasks_failed'] += failed
        self.stats['tasks_already_done'] += already_done
        self.update()

    def record_exam_result(self, questions, cache, tiku, llm, random_answers, submit_ok, submit_fail):
        for key, value in zip(('exam_total', 'exam_cache', 'exam_tiku', 'exam_llm', 'exam_random',
                               'exam_submit_ok', 'exam_submit_fail'),
                              (questions, cache, tiku, llm, random_answers, submit_ok, submit_fail)):
            self.stats[key] += value
        self.update()


def execute_course(feature, user, course, ui, log=logger):
    if feature == 'course_all':
        from functions.deal_course import DealCourse
        return DealCourse(user, course, log, ui).do_finish()
    elif feature == 'independent_homework':
        from functions.deal_homework import DealHomework
        return DealHomework(user, course, log, ui).do_finish()
    elif feature == 'chapter_exam':
        from functions.deal_exam import DealExam
        return DealExam(user, course, log, ui).do_finish()
    elif feature == 'video':
        from core.config import Config
        from functions.deal_video import DealVideo
        dv = DealVideo(user, course, log)
        tasks = [{'video': v, 'mode': Config.get('video.mode')} for v in dv.get_videos()]
        result = dv.batch_run_videos(tasks, Config.get('video.max_workers', 20))
        ui.record_course_result(result['success'], result['failed'])
    elif feature == 'learn_count':
        from functions.deal_time import run
        run(user, course, log, ui)
    else:
        raise ValueError('不支持的批处理功能')


class _LogOutput(io.TextIOBase):
    def __init__(self):
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip():
                logger.info(line)
        return len(text)

    def flush(self):
        if self.pending.strip():
            logger.info(self.pending)
        self.pending = ''


def run_account_job(job, emit):
    """独立进程执行一个账号，不写账号库，由主进程合并会话。"""
    from core.config import Config
    from core.request_client import init_client
    from core.account_session import open_account
    Config._data = copy.deepcopy(job['config'])
    init_client(Config.data())
    ui = BatchStats(emit)
    emit({'event': 'stage', 'message': '恢复登录会话，读取课程'})
    user = open_account(job['account'])
    selected = job['courses']
    errors = []
    for index, target in enumerate(selected, 1):
        try:
            course = next((c for c in user.course_list
                           if str(c.course_id) == str(target['course_id'])
                           and str(c.class_id) == str(target['class_id'])), None)
            if course is None:
                raise ValueError(f"课程 {target['name']} 已不在此账号中，请重新选择")
            if not course.if_open:
                raise ValueError(f"课程 {target['name']} 尚未开放")
            ui.start_course(course.course_name, index, len(selected))
            output = _LogOutput()
            try:
                with redirect_stdout(output):
                    outcome = execute_course(job['feature'], user, course, ui)
                if isinstance(outcome, dict) and outcome.get('reason'):
                    errors.append(redact(outcome['reason']))
            finally:
                output.flush()
        except Exception as exc:
            message = redact(str(exc))
            errors.append(message)
            logger.error(message)
            ui.count_failed()
    failed = bool(errors or ui.stats['tasks_failed'] or ui.stats['exam_submit_fail'])
    prepared = not Config.get('answer.auto_submit', True) and job['feature'] in ('course_all', 'chapter_exam', 'independent_homework')
    return {'account_id': job['account']['id'], 'status': 'failed' if failed else 'prepared' if prepared else 'succeeded',
            'stats': dict(ui.stats), 'errors': errors, 'session': user.export_session()}


def _worker_entry(job, events, worker):
    account_id = job['account']['id']
    def emit(value):
        events.put({**value, 'account_id': account_id})
    logger.remove()
    logger.configure(patcher=patch_log)
    logger.add(lambda m: emit({'event': 'log', 'level': m.record['level'].name.lower(),
                               'message': m.record['message']}),
               level='DEBUG', filter=visible_log, diagnose=False)
    log_file = job.get('config', {}).get('advanced', {}).get('log_file')
    if log_file:
        try:
            from core.paths import get_user_data_path
            path = Path(log_file if os.path.isabs(log_file) else get_user_data_path(log_file))
            safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', account_id)[:48]
            path = path.with_name(path.stem + '-' + safe_id + path.suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            logger.add(str(path), level='DEBUG', filter=visible_log, encoding='utf-8',
                       rotation='10 MB', retention='7 days', diagnose=False)
        except (OSError, ValueError) as exc:
            logger.warning(f'账号日志文件无法创建，终端继续保留运行记录：{exc}')
    try:
        result = worker(job, emit)
        emit({'event': 'result', 'result': result})
    except Exception as exc:
        emit({'event': 'result', 'result': {'account_id': account_id, 'status': 'failed',
                                          'stats': {'tasks_failed': 1}, 'error': redact(str(exc))}})
    finally:
        logger.remove()
        events.close()
        events.join_thread()


def run_account_jobs(jobs, max_workers=3, on_event=None, worker=run_account_job):
    """阻塞运行；Ctrl+C 会停止所有本批子进程，队列中的账号不再启动。"""
    if not jobs:
        return []
    ids = [job['account']['id'] for job in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError('同一批次中每个账号只能出现一次')
    ctx = multiprocessing.get_context('spawn')
    events = ctx.Queue()
    waiting, running, processes, results = list(jobs), {}, [], {}
    max_workers = max(1, min(int(max_workers), 10))

    def consume(event):
        if event.get('event') == 'result':
            results[event['account_id']] = event['result']
        if on_event:
            on_event(event)

    try:
        while waiting or running:
            while waiting and len(running) < max_workers:
                job = waiting.pop(0)
                process = ctx.Process(target=_worker_entry, args=(job, events, worker),
                                      name='CLI-account-' + job['account']['id'][:8])
                process.start()
                running[job['account']['id']] = process
                processes.append(process)
                if on_event:
                    on_event({'event': 'started', 'account_id': job['account']['id']})
            try:
                consume(events.get(timeout=0.2))
            except queue.Empty:
                pass
            exited = [i for i, p in running.items() if not p.is_alive()]
            if exited:
                # 子进程在退出前 join_thread，保证结果已写入管道。
                while True:
                    try:
                        consume(events.get_nowait())
                    except queue.Empty:
                        break
                for account_id in exited:
                    process = running.pop(account_id)
                    process.join()
                    if account_id not in results:
                        consume({'event': 'result', 'account_id': account_id, 'result': {
                            'account_id': account_id, 'status': 'failed', 'stats': {'tasks_failed': 1},
                            'error': f'账号进程异常退出（退出码 {process.exitcode}），请查看日志'}})
        return [results[i] for i in ids]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.kill(); process.join(timeout=5)
            process.close()
        events.close()
        events.join_thread()
