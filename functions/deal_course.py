"""
AutoChaoxingCLI - 课程任务处理器

负责：
1. 获取课程章节列表
2. 解析每个章节的任务点
3. 根据任务类型分发给对应处理器
4. 管理视频刷取的 ThreadPoolExecutor 并发任务
5. 对作业/测验自动调用AI答题
"""

import time

from loguru import logger
from lxml import etree

from core.config import Config
from core.exceptions import AntispiderException, RequestException
from core.request_client import get as doGet, get_client, xpath_first
from media.video import Video
from media.work import Work
from media.book import Book
from media.document import Document
from media.read import Read
from media.live import Live
from media.vote import Vote
from media.bbs import Bbs


class DealCourse:
    """
    课程任务处理器

    Attributes:
        user: 用户对象
        course: 课程对象
        log: 日志对象
        mission_list: 待完成任务列表
        video_mode: 视频完成模式 (instant/real_time)
        max_workers: 最大并发线程数
    """

    def __init__(self, user, course, log, ui=None):
        self.user = user
        self.course = course
        self.log = log
        self.ui = ui
        self.course_name = course.course_name
        self.class_id = course.class_id
        self.course_id = course.course_id
        self.cpi = course.cpi
        self.mission_list = []
        self.video_mode = Config.get("video.mode", "hybrid")
        self.max_workers = Config.get("video.max_workers", 20)

    def do_finish(self):
        """执行课程任务完成的主流程"""
        if not self.course.if_open:
            self.log.warning("本课程已结课或锁定，将自动跳过")
            return

        from functions.deal_video import DealVideo

        # 获取章节列表
        self.deal_course()

        # 统计数据
        total_tasks = 0
        already_done_count = 0
        success_count = 0
        failed_count = 0
        type_counts = {}

        # 收集视频任务和作业任务
        video_tasks = []
        work_tasks_for_ai = []

        if self.mission_list:
            pending_chapters = [m for m in self.mission_list if
                                (m.get('job_count', 0) > 0 or m.get('job_count_known') is False) and m.get('available')]
            self.log.info(f"共读取到 {len(self.mission_list)} 个章节，其中 {len(pending_chapters)} 个有待完成任务")

            for chapter_idx, mission_item in enumerate(self.mission_list, 1):
                chapter_name = mission_item.get('name')

                # 无待完成任务或已锁定，跳过
                if (mission_item.get('job_count', 0) == 0 and mission_item.get('job_count_known', True)) or not mission_item.get('available'):
                    if self.ui:
                        self.ui.task_already_done(chapter_name, '')
                    continue

                if self.ui:
                    self.ui.start_section(chapter_name, chapter_idx, len(self.mission_list))
                else:
                    self.log.info(f"[{chapter_idx}/{len(self.mission_list)}] 章节: {chapter_name}")

                # 获取章节媒体附件
                try:
                    attach_list = self.deal_chapter(mission_item)
                except AntispiderException as e:
                    self.log.warning(f"章节'{chapter_name}'触发反爬虫: {e}，跳过")
                    failed_count += 1
                    continue

                if not attach_list or not any(card.get('attachments') for card in attach_list):
                    # 章节未开放：无法完成，跳过且不计入失败
                    if mission_item.get("_not_open"):
                        if self.ui:
                            self.ui.count_skipped()
                        continue
                    # 章节声明有待完成任务点，但未解析到任何附件：
                    # 可能是"空页面"任务点（进入章节即计为完成），尝试访问章节页面完成
                    if mission_item.get('job_count', 0) > 0 or mission_item.get('job_count_known') is False:
                        if self._study_empty_page(mission_item):
                            success_count += 1
                            self.log.success(f"  [OK] 空页面任务点: {chapter_name}")
                        else:
                            failed_count += 1
                            self.log.warning(f"  空页面任务点处理失败: {chapter_name}")
                    continue

                for attach_item in attach_list:
                    medias = attach_item.get("attachments") or []
                    defaults = attach_item.get("defaults") or {}
                    for media in medias:
                        media_type = media.get("type")
                        media_property = media.get('property')
                        media_module = media_property.get('module') if media_property else None
                        media_name = media_property.get('name') if media_property else None

                        task_type_key = media_module if media_module in ("insertaudio", "insertvote", "insertbbs") else (media_type or "unknown")
                        type_counts[task_type_key] = type_counts.get(task_type_key, 0) + 1
                        total_tasks += 1

                        # 已完成的任务点直接跳过
                        if media.get("job") is None:
                            already_done_count += 1
                            if self.ui:
                                self.ui.task_already_done(media_name or "未命名", task_type_key)
                            continue

                        # 处理未完成的任务点
                        try:
                            if media_type == "video":
                                if media_module == "insertaudio":
                                    _video = Video(media, self.user.headers, defaults, self.course_id, "Audio", name=media_name or "音频")
                                else:
                                    _video = Video(media, self.user.headers, defaults, self.course_id, name=media_name)

                                # 所有入口复用静默探测与真实播放，不在扫描阶段直接结算。
                                video_tasks.append({"video": _video, "mode": self.video_mode})

                            elif media_type == "read":
                                finish_status = Read(media, self.user.headers, defaults, self.course_id).do_finish()
                                success_count += 1 if finish_status else 0
                                failed_count += 0 if finish_status else 1

                            elif media_type == "document":
                                finish_status = Document(media, self.user.headers, defaults, self.course_id).do_finish()
                                success_count += 1 if finish_status else 0
                                failed_count += 0 if finish_status else 1

                            elif media_type == "live":
                                _live = Live(media, self.user.headers, defaults, self.course_id)
                                video_tasks.append({"video": _live, "mode": "live"})

                            elif media_type in ("work", "workid") or media_module == "work":
                                # 作业/测验：收集起来稍后AI答题
                                work_tasks_for_ai.append({
                                    "media": media,
                                    "defaults": defaults,
                                    "chapter": mission_item,
                                    "media_name": media_name or "未命名",
                                })
                            elif media_type == "vote" or media_module == "insertvote":
                                # 投票任务点：随机选择选项并提交
                                finish_status = Vote(media, self.user.headers, defaults, self.course_id).do_finish()
                                success_count += 1 if finish_status else 0
                                failed_count += 0 if finish_status else 1

                            elif media_type is None:
                                # type为None的任务点：通常是嵌入的交互式模块（投票、讨论等）
                                # 优先根据 module 字段判断具体类型
                                if media_module == "insertvote":
                                    finish_status = Vote(media, self.user.headers, defaults, self.course_id).do_finish()
                                    success_count += 1 if finish_status else 0
                                    failed_count += 0 if finish_status else 1
                                elif media_module == "insertbbs":
                                    finish_status = Bbs(media, self.user.headers, defaults, self.course_id).do_finish()
                                    success_count += 1 if finish_status else 0
                                    failed_count += 0 if finish_status else 1
                                elif "bookname" in (media.get("property") or {}):
                                    finish_status = Book(media, self.user.headers, defaults, self.course_id).do_finish()
                                    success_count += 1 if finish_status else 0
                                    failed_count += 0 if finish_status else 1
                                else:
                                    # 未知None类型，尝试通过 simple job finish 通用接口完成
                                    self.log.info(f"  尝试通用接口完成任务点: {media_name or '未命名'} (module={media_module})")
                                    jtoken = media.get("jtoken")
                                    if jtoken:
                                        # 创建匿名具体子类以绕过Media的抽象限制
                                        from models.media import Media as _MediaBase
                                        class _AnonymousMedia(_MediaBase):
                                            def do_finish(self) -> bool:
                                                return self._do_simple_job_finish(
                                                    api_path='job',
                                                    referer='https://mooc1-2.chaoxing.com/ananas/modules/',
                                                    task_name='Unknown(None)'
                                                )
                                        _anon = _AnonymousMedia(media, self.user.headers, defaults, self.course_id)
                                        finish_status = _anon.do_finish()
                                        success_count += 1 if finish_status else 0
                                        failed_count += 0 if finish_status else 1
                                    else:
                                        self.log.warning(f"不支持的任务点类型: None (module={media_module}, name={media_name})")
                                        failed_count += 1

                            elif "bookname" in media.get("property", {}):
                                finish_status = Book(media, self.user.headers, defaults, self.course_id).do_finish()
                                success_count += 1 if finish_status else 0
                                failed_count += 0 if finish_status else 1
                            else:
                                self.log.warning(f"不支持的任务点类型: {media_type}")
                                failed_count += 1

                        except AntispiderException as e:
                            self.log.warning(f"任务点'{media_name or '未知'}'触发反爬虫: {e}")
                            failed_count += 1
                        except Exception as e:
                            self.log.error(f"任务点'{media_name or '未知'}'处理异常: {e}")
                            failed_count += 1

        # 批量并发处理视频，静默即时尝试后按需真实播放。
        if video_tasks:
            deal_video = DealVideo(self.user, self.course, self.log)
            video_result = deal_video.batch_run_videos(video_tasks, self.max_workers)
            success_count += video_result["success"]
            failed_count += video_result["failed"]

        # AI自动答题
        if work_tasks_for_ai:
            exam_result = self._do_ai_exam(work_tasks_for_ai)
            success_count += exam_result["success"]
            failed_count += exam_result["failed"]

        # 课程汇总
        self.log.info(f"课程汇总: {len(self.mission_list)}个章节 | "
                      f"已完成{already_done_count}个 | 本次成功{success_count}个 | "
                      f"失败{failed_count}个")
        if self.ui:
            self.ui.record_course_result(success_count, failed_count, already_done_count)

    def _do_ai_exam(self, work_tasks: list):
        """对收集到的作业/测验执行AI自动答题"""
        from functions.deal_exam import DealExam
        exam = DealExam(self.user, self.course, self.log, self.ui)
        self.log.info(f"[AI答题] 共 {len(work_tasks)} 个作业/测验需要处理")

        total_q = total_cache = total_tiku = total_llm = total_random = total_submit_ok = total_submit_fail = 0
        work_success = work_failed = 0

        for i, task in enumerate(work_tasks, 1):
            media_name = task["media_name"]
            self.log.info(f"[AI答题] [{i}/{len(work_tasks)}] {media_name}")
            stats = exam.answer_work(task["media"], task["defaults"], task["chapter"])
            if stats:
                total_q += stats.get("questions", 0)
                total_cache += stats.get("cache_hits", 0)
                total_tiku += stats.get("tiku_hits", 0)
                total_llm += stats.get("llm_calls", 0)
                total_random += stats.get("random_answers", 0)
                total_submit_ok += stats.get("submit_ok", 0)
                total_submit_fail += stats.get("submit_fail", 0)
                if stats.get("submit_ok", 0) > 0 and stats.get("submit_fail", 0) == 0:
                    work_success += 1
                    # 答案已提交后再标记任务点，避免未答先完成
                    Work(task["media"], self.user.headers, task["defaults"], self.course_id).do_finish()
                elif stats.get("submit_fail", 0) > 0:
                    work_failed += 1
            else:
                work_failed += 1

        if total_q > 0:
            source_parts = [f"缓存={total_cache}"]
            if total_tiku > 0:
                source_parts.append(f"题库={total_tiku}")
            source_parts.append(f"LLM={total_llm}")
            if total_random > 0:
                source_parts.append(f"随机={total_random}")
            self.log.success(
                f"[AI答题汇总] 共{total_q}题 | {' | '.join(source_parts)} | "
                f"提交成功={total_submit_ok}" + (f" | 失败={total_submit_fail}" if total_submit_fail else "")
            )
        if self.ui:
            self.ui.record_exam_result(
                total_q, total_cache, total_tiku, total_llm, total_random,
                total_submit_ok, total_submit_fail,
            )
        return {"success": work_success, "failed": work_failed}

    def deal_course(self):
        """获取并展示课程章节列表"""
        self.mission_list.clear()
        self.log.info(f"正在获取'{self.course_name}'课程的章节...")
        self.course.get_chapter()

        if self.course.chapter_list:
            self.log.success(f"'{self.course_name}'课程章节获取成功")
            time.sleep(0.4)
            for catalog_item in self.course.chapter_list:
                print(f"  [+] {catalog_item.get('catalog_name')}")
                for chapter_item in catalog_item.get("child_chapter"):
                    self.mission_list.append(chapter_item)
                    indent = "    " + "  " * chapter_item.get("depth", 0)
                    job_count = chapter_item.get("job_count", 0)
                    job_str = f" [{job_count}个待完成]" if job_count > 0 else " [全部完成]"
                    locked = "[锁] " if not chapter_item.get("available") else ""
                    print(f"{indent}{locked}{chapter_item.get('name')}{job_str}")
            self.log.success(f"'{self.course_name}'课程章节展示完毕 (共{len(self.mission_list)}个章节)")
        else:
            self.log.warning(f"'{self.course_name}'课程章节数为零")

    def _study_empty_page(self, chapter_item: dict) -> bool:
        """
        完成"空页面"任务点

        部分章节的任务点是"进入章节即完成"（无具体多媒体附件）。
        通过访问 studentstudyAjax 接口即可将该任务点标记为已完成。

        Args:
            chapter_item: 章节信息，需包含knowledge_id

        Returns:
            bool: 完成成功返回True
        """
        knowledge_id = chapter_item.get("knowledge_id")
        if not knowledge_id:
            return False
        _url = (f"https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax?"
                f"courseId={self.course_id}&clazzid={self.class_id}"
                f"&chapterId={knowledge_id}&cpi={self.cpi}"
                f"&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0")
        rsp = self._safe_doGet(_url, self.user.headers)
        if not rsp:
            return False
        # 页面返回正常也不能代表通过，刷新列表核对该任务是否清零。
        self.course.get_chapter()
        for catalog in self.course.chapter_list:
            for chapter in catalog.get('child_chapter', []):
                if chapter.get('knowledge_id') == knowledge_id:
                    return chapter.get('job_count_known', False) and chapter.get('job_count') == 0
        return False

    def deal_chapter(self, chapter_item: dict) -> list:
        """
        处理单个章节，获取其媒体附件列表

        Args:
            chapter_item: 章节字典，需包含knowledge_id

        Returns:
            list: 媒体附件列表
        """
        page_count = self._safe_read_card_count(chapter_item.get("knowledge_id"))
        attach_list = []
        not_open = False
        for page in range(page_count):
            try:
                medias_url = (f"https://mooc1.chaoxing.com/knowledge/cards?"
                              f"clazzid={self.class_id}&courseid={self.course_id}"
                              f"&knowledgeid={chapter_item.get('knowledge_id')}"
                              f"&num={page}&ut=s&cpi={self.cpi}&v=20160407-1")
                medias_rsp = self._safe_doGet(medias_url, self.user.headers)
                if not medias_rsp:
                    raise RequestException('平台返回空的章节卡片，无法确认完整任务范围')
                if "章节未开放" in medias_rsp:
                    not_open = True
                    break
                from core.chapter_parser import parse_cards
                cards = parse_cards(medias_rsp)
                if not cards:
                    raise RequestException('未解析到章节任务数据，请核对登录状态或平台页面')
                attach_list.extend(cards)
            except Exception as e:
                raise RequestException(f'章节第{page + 1}页任务数据读取失败：{e}') from e
        if not_open:
            self.log.info(f"  章节'{chapter_item.get('name')}'未开放，跳过")
            chapter_item["_not_open"] = True
        return attach_list

    def _safe_doGet(self, url: str, headers: dict, max_retries: int = 3) -> str:
        """安全的GET请求（遇错跳过，重试3次）"""
        for attempt in range(max_retries + 1):
            try:
                return doGet(url=url, headers=headers)
            except AntispiderException as e:
                if attempt < max_retries:
                    # 读取全局冷却剩余时间，避免在冷却期内重试
                    client = get_client()
                    with client.lock:
                        remaining = client.antispider_until - time.monotonic()
                    wait_time = max(remaining + 5, 30)
                    logger.warning(f"触发反爬虫({e})，等待{wait_time:.0f}秒后重试")
                    time.sleep(wait_time)
                else:
                    logger.error("反爬虫重试后仍失败，放弃此请求")
                    raise
            except RequestException:
                raise
        return ""

    def _safe_read_card_count(self, knowledge_id) -> int:
        """安全获取章节的总页码数"""
        _url = 'https://mooc1.chaoxing.com/mycourse/studentstudyAjax?'
        data = (f"courseId={self.course_id}&clazzid={self.class_id}"
                f"&chapterId={knowledge_id}&cpi={self.cpi}"
                f"&verificationcode=&mooc2=1")
        rsp = self._safe_doGet(_url + data, self.user.headers)
        if not rsp:
            raise RequestException('章节页码读取失败：平台返回空响应')
        rsp_HTML = etree.HTML(rsp)
        card_count_str = xpath_first(rsp_HTML, "//input[@id='cardcount']/@value")
        if not card_count_str:
            raise RequestException('未识别到章节页码，请检查登录状态或平台验证')
        try:
            return int(card_count_str)
        except (ValueError, TypeError):
            raise RequestException('平台返回的章节页码格式无效')
