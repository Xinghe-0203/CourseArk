"""网页课程执行：先发现工作范围，再按稳定 ID 执行并确认结果。"""
from core import runtime
from core.chapter_parser import work_id
from media.video import Video
from media.live import Live
from media.work import Work
from media.read import Read
from media.document import Document
from media.book import Book
from media.vote import Vote
from media.bbs import Bbs


class CourseExecution:
    def __init__(self, handler):
        self.handler = handler
        self.jobs = []
        self.stats = {'success': 0, 'failed': 0, 'already_done': 0, 'skipped': 0}

    def result(self, job, status, detail=''):
        runtime.emit('work_result', detail or job['name'], stage=job['kind'],
                     level='warning' if status in ('failed', 'blocked') else 'info',
                     payload={'id': job['id'], 'name': job['name'], 'kind': job['kind'], 'status': status})
        if status == 'succeeded':
            self.stats['success'] += 1
        elif status in ('failed', 'blocked'):
            self.stats['failed'] += 1
        else:
            self.stats['skipped'] += 1

    def discover(self):
        h = self.handler
        h.deal_course()
        seen = set()
        for index, chapter in enumerate(h.mission_list, 1):
            runtime.checkpoint()
            if not chapter.get('available') or not chapter.get('job_count', 0):
                continue
            if h.ui:
                h.ui.start_section(chapter.get('name', ''), index, len(h.mission_list))
            cards = h.deal_chapter(chapter)
            if not cards:
                job = {'id': 'chapter:' + str(chapter.get('knowledge_id')), 'name': chapter.get('name', '章节'),
                       'kind': 'chapter', 'chapter': chapter, 'media': None, 'defaults': {}}
                self.jobs.append(job)
                continue
            for card in cards:
                defaults = card.get('defaults') or {}
                for media in card.get('attachments') or []:
                    if not isinstance(media, dict):
                        continue
                    prop = media.get('property') or {}
                    if media.get('job') is None and not media.get('jobid') and not prop.get('jobid') and not media.get('isPassed'):
                        # 普通资源不是任务点，不能充当“此前已完成”抬高百分比。
                        continue
                    key = work_id(media, chapter.get('knowledge_id', ''))
                    if key in seen:
                        continue
                    seen.add(key)
                    module = prop.get('module', '')
                    kind = {'insertaudio': 'audio', 'insertvideo': 'video', 'insertvote': 'vote',
                            'insertbbs': 'bbs', 'insertdoc': 'document', 'insertwork': 'work',
                            'work': 'work', 'insertbook': 'book'}.get(module, media.get('type') or '')
                    if kind == 'workid':
                        kind = 'work'
                    if not kind and prop.get('bookname'):
                        kind = 'book'
                    self.jobs.append({'id': key, 'name': h.clean_name(prop.get('name')) or chapter.get('name') or '未命名任务',
                                      'kind': kind or 'unsupported', 'chapter': chapter, 'media': media, 'defaults': defaults})
    def run(self, kinds=None):
        h = self.handler
        if not h.course.if_open:
            h.log.warning('课程已关闭，无法执行任务')
            if h.ui:
                h.ui.record_course_result(0, 1, 0)
            return {'success': 0, 'failed': 1}
        self.discover()
        if kinds is not None:
            self.jobs = [j for j in self.jobs if j['kind'] in kinds or j['kind'] == 'chapter']
        runtime.emit('work_plan', '任务范围已读取', stage='course', payload={
            'units': [{'id': j['id'], 'name': j['name'], 'kind': j['kind']} for j in self.jobs], 'sealed': True})
        videos, exams = [], []
        for job in self.jobs:
            runtime.checkpoint()
            media, kind, defaults = job['media'], job['kind'], job['defaults']
            if media is not None and (media.get('job') is None or media.get('job') is False or media.get('isPassed') is True):
                self.stats['already_done'] += 1
                runtime.emit('work_result', '此前已完成', stage=kind,
                             payload={'id': job['id'], 'name': job['name'], 'status': 'succeeded'})
                continue
            runtime.emit('work_started', '正在处理任务', stage=kind,
                         payload={'id': job['id'], 'name': job['name'], 'kind': kind, 'status': 'running'})
            try:
                if kind in ('video', 'audio', 'live'):
                    cls = Live if kind == 'live' else Video
                    args = (media, h.user.headers, defaults, h.course_id)
                    obj = cls(*args) if kind == 'live' else cls(*args, dtype='Audio' if kind == 'audio' else 'Video', name=job['name'])
                    obj.name = job['name']
                    obj.work_unit_id = job['id']
                    videos.append({'video': obj, 'mode': 'live' if kind == 'live' else h.video_mode})
                elif kind == 'work':
                    exams.append(job)
                elif kind == 'chapter':
                    if job['chapter'].get('_not_open'):
                        self.result(job, 'blocked', '章节未开放，请在学习通查看开放时间')
                    else:
                        self.result(job, 'succeeded' if h._study_empty_page(job['chapter']) else 'failed', '核对章节任务点结果')
                else:
                    cls = {'read': Read, 'document': Document, 'book': Book, 'vote': Vote, 'bbs': Bbs}.get(kind)
                    if cls is None:
                        self.result(job, 'blocked', f'此章节任务类型尚未支持：{kind}，请在学习通处理')
                    else:
                        ok = cls(media, h.user.headers, defaults, h.course_id).do_finish()
                        self.result(job, 'succeeded' if ok else 'failed', '任务点已确认完成' if ok else '平台尚未确认任务点完成')
            except Exception as exc:
                self.result(job, 'failed', f'任务点处理失败：{exc}')
        if videos:
            from functions.deal_video import DealVideo
            result = DealVideo(h.user, h.course, h.log).batch_run_videos(videos, h.max_workers)
            self.stats['success'] += result['success']
            self.stats['failed'] += result['failed']
        if exams:
            from functions.deal_exam import DealExam
            exam = DealExam(h.user, h.course, h.log, h.ui)
            for job in exams:
                runtime.checkpoint()
                try:
                    exam.active_unit_id = job['id']
                    result = exam.answer_work(job['media'], job['defaults'], job['chapter']) or {}
                    if h.ui:
                        h.ui.record_exam_result(*(result.get(k, 0) for k in ('questions', 'cache_hits', 'tiku_hits', 'llm_calls', 'random_answers', 'submit_ok', 'submit_fail')))
                    answered_all = result.get('questions', 0) > 0 and result.get('submit_ok', 0) == result.get('questions') and not result.get('submit_fail')
                    ok = answered_all and Work(job['media'], h.user.headers, job['defaults'], h.course_id).do_finish()
                    self.result(job, 'succeeded' if ok else 'blocked', '测验任务点已确认' if ok else '测验有未作答题目或平台未确认完成，请核对')
                except Exception as exc:
                    self.result(job, 'failed', f'测验处理失败：{exc}')
        if h.ui:
            h.ui.record_course_result(self.stats['success'], self.stats['failed'], self.stats['already_done'])
        return {**self.stats, 'chapters': len(h.mission_list)}
