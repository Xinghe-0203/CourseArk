"""
AutoChaoxingCLI - 课程任务处理器

负责：
1. 获取课程章节列表
2. 解析每个章节的任务点
3. 根据任务类型分发给对应处理器
4. 管理视频刷取的 ThreadPoolExecutor 并发任务
5. 对作业/测验自动调用AI答题
"""

import re
import time

from loguru import logger
from lxml import etree

from core import runtime
from core.chapter_parser import parse_cards
from core.config import Config
from core.exceptions import AntispiderException, RequestException
from core.request_client import get as doGet, get_client, xpath_first


_TAG_LIKE = re.compile(r"<[^>]{1,120}>")


def _clean_name(value):
    """去掉名称里的 HTML 标签与多余空白（字体反爬会在名称中留下 <font> 标记）"""
    if not value:
        return value
    text = _TAG_LIKE.sub("", str(value))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s{2,}", " ", text).strip() or None


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

    clean_name = staticmethod(_clean_name)

    def do_finish(self):
        from functions.course_execution import CourseExecution
        return CourseExecution(self).run()

    def deal_course(self):
        """获取并展示课程章节列表"""
        self.mission_list.clear()
        self.log.info(f"正在获取'{self.course_name}'课程的章节...")
        self.course.get_chapter()

        if self.course.chapter_list:
            self.log.success(f"'{self.course_name}'课程章节获取成功")
            time.sleep(0.4)
            for catalog_item in self.course.chapter_list:
                self.log.info(f"  [+] {catalog_item.get('catalog_name')}")
                for chapter_item in catalog_item.get("child_chapter"):
                    self.mission_list.append(chapter_item)
                    indent = "    " + "  " * chapter_item.get("depth", 0)
                    job_count = chapter_item.get("job_count", 0)
                    job_str = f" [{job_count}个待完成]" if job_count > 0 else " [全部完成]"
                    locked = "[锁] " if not chapter_item.get("available") else ""
                    self.log.info(f"{indent}{locked}{chapter_item.get('name')}{job_str}")
            self.log.success(f"'{self.course_name}'课程章节展示完毕 (共{len(self.mission_list)}个章节)")
            runtime.emit("course_started", f"课程'{self.course_name}'章节已就绪", stage="course", payload={
                "course_name": self.course_name,
                "chapter_total": len(self.mission_list),
            })
        else:
            self.log.info(f"'{self.course_name}'当前暂无章节与课程任务点")

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
        if not rsp or 'login' in rsp.lower() or 'antispider' in rsp.lower():
            return False
        # 页面访问不等于完成；重新获取章节，确认待完成数量确实归零。
        self.course.get_chapter()
        for catalog in self.course.chapter_list or []:
            for item in catalog.get('child_chapter') or []:
                if str(item.get('knowledge_id')) == str(knowledge_id):
                    return item.get('job_count') == 0
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
                    continue
                if "章节未开放" in medias_rsp:
                    not_open = True
                    break
                attach_list.extend(parse_cards(medias_rsp))
            except Exception as e:
                self.log.debug(f"章节第{page + 1}页任务数据解析失败: {e}")
                continue
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
                    return ""
            except RequestException:
                return ""
        return ""

    def _safe_read_card_count(self, knowledge_id) -> int:
        """安全获取章节的总页码数"""
        _url = 'https://mooc1.chaoxing.com/mycourse/studentstudyAjax?'
        data = (f"courseId={self.course_id}&clazzid={self.class_id}"
                f"&chapterId={knowledge_id}&cpi={self.cpi}"
                f"&verificationcode=&mooc2=1")
        rsp = self._safe_doGet(_url + data, self.user.headers)
        if not rsp:
            return 0
        rsp_HTML = etree.HTML(rsp)
        card_count_str = xpath_first(rsp_HTML, "//input[@id='cardcount']/@value")
        if not card_count_str:
            match = re.search(r'\bcardcount\s*[:=]\s*["\']?(\d+)', rsp, re.I)
            # 新页面没有旧的隐藏 input 时仍读取第一页卡片，不能直接判为空章节。
            return int(match.group(1)) if match else 1
        try:
            return int(card_count_str)
        except (ValueError, TypeError):
            return 0
