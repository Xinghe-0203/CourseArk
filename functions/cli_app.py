"""CLI 多账号操作流程，网络会话与菜单职责分离。"""
import copy
import time
from loguru import logger
from rich.live import Live

from core.account_session import AccountSessions, open_account
from core.batch_runner import run_account_jobs, execute_course
from core.config import Config
from functions.account_menu import select_accounts
from functions.tui import TUI, console

FEATURES = {1: 'course_all', 2: 'chapter_exam', 3: 'video',
            4: 'learn_count', 7: 'independent_homework'}


class CLIApplication:
    def __init__(self, store, tui=None):
        self.store = store
        self.tui = tui or TUI()
        self.selected = []
        self.sessions = AccountSessions(store)

    def prepare_jobs(self, feature):
        jobs = []
        for account_id in self.selected:
            account = self.store.get(account_id)
            label = account.get('label') or next(a['username'] for a in self.store.list_accounts() if a['id'] == account_id)
            try:
                self.tui.account_heading(label)
                user = self.sessions.open(account_id)
                courses = self.tui.select_courses(user.course_list)
                if courses:
                    jobs.append({'account': self.store.get(account_id), 'feature': feature,
                                 'config': copy.deepcopy(Config.data()),
                                 'courses': [{'course_id': c.course_id, 'class_id': c.class_id,
                                              'name': c.course_name} for c in courses]})
            except EOFError:
                raise
            except Exception as exc:
                logger.error(f'[{label}] 课程读取失败：{exc}')
        return jobs

    def run_batch(self, feature):
        jobs = self.prepare_jobs(feature)
        if not jobs:
            return
        if feature == 'learn_count':
            self.run_inline(jobs)
            return
        if feature in ('course_all', 'video'):
            video = self.tui.video_config()
            Config.set('video.mode', video['mode'])
            Config.set('video.max_workers', video['max_workers'])
            for job in jobs:
                job['config']['video'].update(video)
        if Config.get('answer.mode') == 'manual' and feature in ('course_all', 'chapter_exam', 'independent_homework'):
            # 交互输入只能由主进程读取，按账号激活独立会话。
            self.run_inline(jobs)
            return
        rows = {job['account']['id']: {'label': job['account'].get('label') or '账号 ' + str(i),
                                      'message': '等待执行', 'stats': {}}
                for i, job in enumerate(jobs, 1)}
        started = time.time()
        with Live(self.tui.batch_table(rows), console=console, refresh_per_second=4) as live:
            def event(value):
                row = rows[value['account_id']]
                kind = value['event']
                if kind == 'started':
                    row['message'] = '正在启动'
                elif kind == 'stage':
                    row['message'] = value['message']
                elif kind == 'progress':
                    row['stats'] = value['stats']
                elif kind == 'result':
                    result = value['result']
                    row['stats'] = result.get('stats', {})
                    row['message'] = {'succeeded': '所选内容处理完成', 'prepared': '答案已生成，按配置尚未提交'}.get(
                        result['status'], '有未完成项，请查看告警')
                    if result.get('errors'):
                        row['message'] = '未完成：' + result['errors'][0]
                    if result.get('error'):
                        logger.error(f"[{row['label']}] {result['error']}")
                elif kind == 'log':
                    level = value.get('level', 'info').upper()
                    if level == 'INFO' and '当前刷取时长' in value['message']:
                        row['message'] = value['message']
                    log = logger if level in ('WARNING', 'ERROR', 'CRITICAL') else logger.bind(name='debug')
                    log.log(level, f"[{row['label']}] {value['message']}")
                live.update(self.tui.batch_table(rows))
            try:
                results = run_account_jobs(jobs, Config.get('accounts.max_workers', 3), event)
            except KeyboardInterrupt:
                logger.warning('本批任务已中止，所有账号子进程已退出')
                return
        report = TUI()
        report.start_time = started
        for result in results:
            if result.get('session'):
                try:
                    self.store.save_session(result['account_id'], result['session'])
                except OSError as exc:
                    logger.error(f'保存登录会话失败：{exc}')
            for key in report.stats:
                report.stats[key] += result.get('stats', {}).get(key, 0)
            if result['status'] == 'failed' and not result.get('stats', {}).get('tasks_failed'):
                report.stats['tasks_failed'] += 1
        report.run_report()
        failed = sum(r['status'] == 'failed' for r in results)
        prepared = sum(r['status'] == 'prepared' for r in results)
        logger.info(f'账号批次结束：{len(results) - failed - prepared} 个账号处理完成，{prepared} 个账号保留待提交，{failed} 个账号有未完成项')

    def run_inline(self, jobs):
        report = TUI()
        for job in jobs:
            account_id = job['account']['id']
            try:
                user = open_account(job['account'])
                for target in job['courses']:
                    course = next(c for c in user.course_list if c.course_id == target['course_id'] and c.class_id == target['class_id'])
                    if job['feature'] == 'download':
                        self.download(user, course)
                    else:
                        execute_course(job['feature'], user, course, report)
                self.store.save_session(account_id, user.export_session())
            except EOFError:
                raise
            except Exception as exc:
                logger.error(f'账号任务未完成：{exc}')
                report.count_failed()
        report.run_report()

    @staticmethod
    def download(user, course):
        from functions.deal_media import MediaDownload
        md = MediaDownload(user, course, logger)
        md.deal_course()
        if not md.chapter_all:
            return
        scope = input('下载范围(all=全部章节，其它=选择章节，默认all): ').strip().lower() or 'all'
        path = input('保存路径(默认为./download): ').strip() or './download'
        if scope == 'all':
            md.download_all(path)
            return
        index = int(input('请选择要下载的章节序号: ')) - 1
        if not 0 <= index < len(md.chapter_all):
            raise ValueError('无效的章节序号')
        for item in md.deal_chapter(md.chapter_all[index]):
            for media in item.get('attachments', []):
                md.do_download(path, media)

    def run(self):
        self.tui.banner(version='3.1')
        self.selected = select_accounts(self.tui, self.store)
        if not self.selected:
            return 0
        while True:
            try:
                choice = self.tui.main_menu()
                if choice == 0:
                    return 0
                if choice == 6:
                    selected = select_accounts(self.tui, self.store, self.selected)
                    if selected:
                        self.selected = selected
                    else:
                        # 删除账号后 q 返回时不得保留已经删除的 ID。
                        valid = {a['id'] for a in self.store.list_accounts()}
                        self.selected = [i for i in self.selected if i in valid]
                    continue
                if not self.selected:
                    self.selected = select_accounts(self.tui, self.store)
                    if not self.selected:
                        continue
                if choice in FEATURES:
                    self.run_batch(FEATURES[choice])
                elif choice == 5:
                    self.run_inline(self.prepare_jobs('download'))
                else:
                    logger.error('无效的功能序号')
            except EOFError:
                logger.info('输入结束，正在退出')
                return 0
            except KeyboardInterrupt:
                logger.info('操作已取消，返回菜单')
            except Exception as exc:
                logger.error(f'操作未完成：{exc}')
