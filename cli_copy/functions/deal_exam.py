"""
AutoChaoxingCLI - 答题/作业处理器

负责：
1. 获取课程中所有待完成的作业（含章节测验和独立作业）
2. 解析作业页面中的题目
3. 三级回退答题：本地缓存 → 在线题库 → LLM
4. 提交答案到服务器

支持的题型：单选题、多选题、判断题、填空题、简答题
"""

import json
import random
import re
import time
from urllib.parse import urlencode

from loguru import logger
from lxml import etree

from core import runtime
from core.config import Config
from core.font_decoder import FontDecoder, SECRET_FONT_PREDICATE
from functions.deal_course import _clean_name
from core.request_client import get as doGet, post as doPost, xpath_first
from utils.llm_client import LLMClient
from utils.question_bank import QuestionBank
from utils.tiku_provider import TikuProvider

# 题型图标
TYPE_ICONS = {
    "单选题": "单选", "多选题": "多选", "判断题": "判断",
    "填空题": "填空", "简答题": "简答",
}

# 题型编码映射
QUESTION_TYPE_MAP = {
    "0": "单选题", "1": "多选题", "2": "填空题",
    "3": "判断题", "4": "简答题",
}
QUESTION_TYPE_REVERSE = {v: k for k, v in QUESTION_TYPE_MAP.items()}

SUBMIT_URL = "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew"
WORK_API_URL = "https://mooc1.chaoxing.com/mooc-ans/api/work"


def job_id_from_work(work_id: str) -> str:
    """由 workId 推导 jobid（独立作业无 jobid 时的兜底）"""
    work_id = str(work_id or "")
    if work_id.startswith("work-"):
        return work_id
    return f"work-{work_id}" if work_id else ""


class DealExam:
    """
    课程测验与作业处理器

    支持章节测验和独立作业的自动答题。
    三级回退：本地缓存 → 在线题库 → LLM
    """

    def __init__(self, user, course, log, ui=None):
        self.user = user
        self.course = course
        self.log = log
        self.ui = ui
        self.course_name = course.course_name if course else ""
        self.class_id = course.class_id if course else ""
        self.course_id = course.course_id if course else ""
        self.cpi = course.cpi if course else ""
        self.headers = user.headers

        # 字体解密器
        self.font_decoder = FontDecoder()

        # 题库缓存
        exam_config = Config.data().get("question_bank", {})
        if exam_config.get("enabled", True):
            self.question_bank = QuestionBank(
                db_path=exam_config.get("db_path", "data/question_bank.db")
            )
        else:
            self.question_bank = None

        # 在线题库
        tiku_config = Config.data().get("tiku", {})
        if tiku_config.get("enabled", True):
            self.tiku = TikuProvider(tiku_config)
        else:
            self.tiku = None

        # LLM客户端
        llm_config = Config.data().get("llm", {})
        self.llm = LLMClient(
            api_base=llm_config.get("base_url", "https://api.deepseek.com/v1"),
            api_key=llm_config.get("api_key", ""),
            model=llm_config.get("model", "deepseek-chat"),
            temperature=float(llm_config.get("temperature", 0.1)),
            max_tokens=int(llm_config.get("max_tokens", 4096)),
            timeout=int(llm_config.get("timeout", 180)),
        )
        self.auto_submit = Config.get("answer.auto_submit", True)
        self.submit_delay = Config.get("answer.submit_delay", 2)
        self.answer_mode = str(Config.get("answer.mode", "ai")).lower()
        self.fallback_to_tiku = Config.get("answer.fallback_to_tiku", True)
        self.no_answer_action = str(Config.get("answer.no_answer_action", "skip")).lower()
        self.auto_save = exam_config.get("auto_save", True)

    def do_finish(self):
        from functions.deal_course import DealCourse
        from functions.course_execution import CourseExecution
        handler = DealCourse(self.user, self.course, self.log, self.ui)
        return CourseExecution(handler).run(kinds={'work'})

    def _find_work_tasks(self) -> list[dict]:
        """查找包含作业的章节"""
        tasks = []
        for catalog in self.course.chapter_list:
            for chapter in catalog.get("child_chapter", []):
                if chapter.get("job_count", 0) > 0 and chapter.get("available"):
                    task = dict(chapter)
                    task["catalog_name"] = catalog.get("catalog_name", "")
                    tasks.append(task)
        return tasks

    def _process_work_task(self, chapter: dict) -> dict:
        """处理单个章节的作业"""
        chapter_name = chapter.get("name", "未知章节")
        knowledge_id = chapter.get("knowledge_id", "")

        from functions.deal_course import DealCourse
        dc = DealCourse(self.user, self.course, self.log)
        attach_list = dc.deal_chapter({"knowledge_id": knowledge_id})
        if not attach_list:
            self.log.warning(f"'{chapter_name}' 没有获取到任务数据")
            return {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                    "random_answers": 0, "submit_ok": 0, "submit_fail": 0}

        stats = {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                 "random_answers": 0, "submit_ok": 0, "submit_fail": 0}
        for attach_item in attach_list:
            medias = attach_item.get("attachments", [])
            defaults = attach_item.get("defaults", {})
            for media in medias:
                media_type = media.get("type")
                media_module = media.get("property", {}).get("module")
                if media_type not in ("workid", "work") and media_module != "work":
                    continue
                if media.get("job") is None:
                    continue
                s = self.answer_work(media, defaults, chapter)
                if s:
                    for k in stats:
                        stats[k] += s.get(k, 0)
        return stats

    def answer_work(self, attachment: dict, defaults: dict, chapter: dict) -> dict:
        """
        处理单个章节测验/作业任务点（答题+提交）

        这是核心答题方法，被 DealCourse 和 DealExam 共用。
        注意：此方法用于"章节任务点内的作业/测验"，其题目通过
        jobid(work-xxx)+knowledgeid+ktoken 定位。独立的"课程作业"
        请使用 answer_independent_work()。

        Args:
            attachment: 附件数据
            defaults: 默认参数
            chapter: 章节信息

        Returns:
            dict: 统计信息
        """
        empty_stats = {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                       "random_answers": 0, "submit_ok": 0, "submit_fail": 0}
        jobid = attachment.get("jobid", "")
        work_id = jobid.replace("work-", "") if jobid.startswith("work-") else jobid
        media_name = _clean_name(
            attachment.get("property", {}).get("name")) or chapter.get("name", "未知作业")
        self.log.info(f"作业: {media_name}")

        # 获取加密参数
        enc = attachment.get("enc") or self._find_enc(jobid)
        ktoken = defaults.get("ktoken") or self._find_ktoken(jobid)

        # 获取作业题目
        result = self._fetch_work_questions(work_id, jobid, defaults, enc, ktoken)
        if not result:
            self.log.warning(f"'{media_name}' 未获取到题目")
            return empty_stats
        questions, hidden_fields = result

        return self._answer_and_submit(
            questions, hidden_fields, media_name,
            work_id=work_id, defaults=defaults, jobid=jobid, enc=enc, ktoken=ktoken,
        )

    def answer_independent_work(self, work_item: dict) -> dict:
        """
        处理课程"独立作业"（区别于章节任务点内的测验）

        独立作业位于课程"作业"标签页，有独立截止时间，需单独提交，
        通过 workId + workAnswerId 定位，不含 knowledgeid/ktoken。
        其题目页需先访问作业详情页（dowork），再从页面隐藏字段中
        还原出题目接口与提交所需的参数。

        Args:
            work_item: get_work_list() 返回的作业条目，需含 work_id/title/url

        Returns:
            dict: 统计信息
        """
        empty_stats = {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                       "random_answers": 0, "submit_ok": 0, "submit_fail": 0}
        media_name = _clean_name(work_item.get("title")) or "独立作业"
        work_id = str(work_item.get("work_id", ""))
        if not work_id:
            self.log.warning(f"独立作业'{media_name}'缺少workId，跳过")
            return empty_stats

        self.log.info(f"独立作业: {media_name} (workId={work_id})")

        # 访问作业详情页，解析题目与隐藏字段
        page_url = work_item.get("url") or ""
        result = self._fetch_independent_work_page(page_url, work_id, work_item.get("answer_id", ""))
        if not result:
            self.log.warning(f"'{media_name}' 未获取到题目")
            return empty_stats
        questions, hidden_fields = result

        if not questions:
            self.log.warning(f"'{media_name}' 题目列表为空（可能教师未创建完成该测验）")
            return empty_stats

        # 独立作业无 knowledgeid/ktoken，用隐藏字段还原上下文
        defaults = {
            "clazzId": hidden_fields.get("classId") or self.class_id,
            "knowledgeid": hidden_fields.get("knowledgeid", ""),
            "userid": str(self.user.uid or ""),
        }
        jobid = hidden_fields.get("originJobId") or hidden_fields.get("jobid") or job_id_from_work(work_id)
        enc = hidden_fields.get("enc") or work_item.get("enc", "")

        return self._answer_and_submit(
            questions, hidden_fields, media_name,
            work_id=work_id, defaults=defaults, jobid=jobid, enc=enc, ktoken=None,
        )

    def _answer_and_submit(self, questions: list, hidden_fields: dict, media_name: str,
                           work_id: str, defaults: dict, jobid: str,
                           enc: str | None, ktoken: str | None) -> dict:
        """共享的答题与提交流程（章节测验与独立作业复用）"""
        self.log.info(f"[答题] '{media_name}' 共 {len(questions)} 道题，开始答题...")

        cache_hits = tiku_hits = llm_calls = random_answers = 0
        answered = []
        for idx, q in enumerate(questions, 1):
            # 每题之间是暂停/停止的安全边界
            runtime.checkpoint()
            ans = self._answer_question(q, idx, len(questions))
            if getattr(self, 'active_unit_id', ''):
                runtime.emit('work_progress', '正在作答', stage='exam', payload={
                    'id': self.active_unit_id, 'name': media_name, 'current': idx, 'total': len(questions)})
            if ans is not None:
                answered.append(ans)
                source = ans.get("source", "")
                if source == "cache":
                    cache_hits += 1
                elif source == "tiku":
                    tiku_hits += 1
                elif source == "llm":
                    llm_calls += 1
                elif source == "random":
                    random_answers += 1
            runtime.emit("exam_stats", "答题进度", stage="exam", payload={
                "media": media_name,
                "current": idx,
                "total": len(questions),
                "cache_hits": cache_hits,
                "tiku_hits": tiku_hits,
                "llm_calls": llm_calls,
                "random_answers": random_answers,
            })

        # 提交答案：无题目ID的备用解析结果不能构造有效表单
        submit_ok = 0
        submit_fail = len(questions) - len(answered) if self.auto_submit else 0
        if answered:
            submittable = [item for item in answered if item.get("question_id")]
            missing_id_count = len(answered) - len(submittable)
            if missing_id_count:
                self.log.warning(f"  [{media_name}] {missing_id_count}题缺少题目ID，已跳过提交")

            if not self.auto_submit:
                self.log.info(f"  [{media_name}] auto_submit=false，仅生成答案，未提交")
            else:
                submit_fail += missing_id_count
            if self.auto_submit and submittable:
                ok, fail = self._submit_answers(
                    work_id, submittable, defaults, jobid, enc, ktoken, hidden_fields
                )
                submit_ok += ok
                submit_fail += fail

            if submit_ok and not submit_fail:
                self.log.success(f"  [{media_name}] 服务器已接受 {submit_ok}题答案")
                self._save_submitted_answers(submittable)
            elif submit_ok:
                self.log.warning(f"  [{media_name}] 服务器接受 {submit_ok}题，{submit_fail}题未提交")
                self._save_submitted_answers(submittable)
            elif self.auto_submit:
                self.log.error(f"  [{media_name}] 答题提交失败")
            runtime.emit("exam_stats", "提交结果", stage="exam", payload={
                "media": media_name,
                "questions": len(questions),
                "submit_ok": submit_ok,
                "submit_fail": submit_fail,
            })

        return {
            "questions": len(questions),
            "cache_hits": cache_hits,
            "tiku_hits": tiku_hits,
            "llm_calls": llm_calls,
            "random_answers": random_answers,
            "submit_ok": submit_ok,
            "submit_fail": submit_fail,
        }

    def _fetch_independent_work_page(self, page_url: str, work_id: str, answer_id: str = ""):
        """
        获取独立作业的题目与隐藏字段

        独立作业详情页(dowork)可能直接内嵌题目表单，也可能通过
        iframe / 转发到题目页。依次尝试：
        1. 访问列表给出的 data 链接，若已含题目表单则直接解析
        2. 从页面中寻找 iframe / doHomeWorkNew 链接，二次抓取
        3. 直接调用题目接口(api/work)，以 workId+workAnswerId 定位

        Returns:
            tuple(list, dict) 或 None
        """
        _headers = {"Referer": "https://mooc1.chaoxing.com/mooc2/work/list"}

        # 尝试1：直接访问详情页
        if page_url:
            try:
                html = doGet(url=page_url, headers=self.headers)
            except Exception as e:
                logger.debug(f"访问作业详情页失败: {e}")
                html = ""
            if html:
                parsed = self._extract_independent_page(html)
                if parsed:
                    return parsed
                next_url = self._find_work_question_url(html)
                if next_url:
                    try:
                        html2 = doGet(url=next_url, headers=self.headers)
                    except Exception as e:
                        logger.debug(f"访问作业题目页失败: {e}")
                        html2 = ""
                    if html2:
                        parsed = self._extract_independent_page(html2)
                        if parsed:
                            return parsed

        # 尝试2：直接调用题目接口
        return self._fetch_independent_via_api(work_id, answer_id)

    def _extract_independent_page(self, html: str):
        """从作业页面提取题目与隐藏字段，无题目时返回None"""
        if not html:
            return None
        decoded = self.font_decoder.decode_page(html)
        questions = self._parse_questions_from_html(decoded)
        if not questions:
            return None
        return (questions, self._extract_form_hidden_fields(html))

    @staticmethod
    def _find_work_question_url(html: str) -> str:
        """从作业页面中寻找真正的题目页地址（iframe 或 doHomeWorkNew 链接）"""
        if not html:
            return ""
        match = re.search(r'<iframe[^>]+src=["\']([^"\']*(?:doHomeWork|dowork)[^"\']*)["\']', html, re.I)
        if match:
            return match.group(1)
        match = re.search(r'["\'](https?://[^"\']*mooc-ans/work/doHomeWorkNew[^"\']*)["\']', html)
        if match:
            return match.group(1)
        return ""

    def _fetch_independent_via_api(self, work_id: str, answer_id: str):
        """直接以 workId+workAnswerId 调用题目接口"""
        params = {
            "api": "1", "workId": work_id, "jobid": "",
            "originJobId": "", "needRedirect": "true", "skipHeader": "true",
            "knowledgeid": "", "cpi": self.cpi, "ut": "s",
            "clazzId": self.class_id, "courseid": self.course_id,
            "type": "", "mooc2": "1",
        }
        if answer_id:
            params["workAnswerId"] = answer_id
        return self._try_fetch_questions_via_api(params)

    def _fetch_work_questions(self, work_id: str, jobid: str, defaults: dict,
                               enc: str | None = None, ktoken: str | None = None):
        """获取作业题目"""
        params = {
            "api": "1", "workId": work_id, "jobid": jobid,
            "originJobId": jobid, "needRedirect": "true",
            "skipHeader": "true",
            "knowledgeid": defaults.get("knowledgeid", ""),
            "cpi": self.cpi, "ut": "s",
            "clazzId": defaults.get("clazzId", self.class_id),
            "courseid": self.course_id, "type": "", "mooc2": "1",
        }
        if enc:
            params["enc"] = enc
        if ktoken:
            params["ktoken"] = ktoken

        return self._try_fetch_questions_via_api(params)

    def _find_enc(self, jobid: str) -> str | None:
        """查找作业的enc加密参数"""
        try:
            _url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?"
                    f"courseid={self.course_id}&clazzid={self.class_id}"
                    f"&cpi={self.cpi}&ut=s&t={int(time.time() * 1000)}")
            rsp = doGet(url=_url, headers=self.headers)
            if not rsp:
                return None
            enc_match = re.findall(rf'{re.escape(jobid)}.*?enc[=:]["\']?([a-f0-9]+)', rsp, re.IGNORECASE)
            if enc_match:
                return enc_match[0]
            enc_match = re.findall(r'"enc"\s*:\s*"([a-f0-9]+)"', rsp)
            if enc_match:
                return enc_match[0]
            enc_match = re.findall(r'enc=([a-f0-9]+)', rsp)
            if enc_match:
                return enc_match[0]
        except Exception as e:
            logger.debug(f"查找 enc 失败: {e}")
        return None

    def _find_ktoken(self, jobid: str) -> str | None:
        """查找作业的ktoken参数"""
        try:
            work_id = jobid.replace("work-", "") if jobid.startswith("work-") else jobid
            _url = (f"https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?"
                    f"workId={work_id}&courseid={self.course_id}"
                    f"&clazzid={self.class_id}&ut=s&cpi={self.cpi}"
                    f"&enc={self._find_enc(jobid) or ''}")
            rsp = doGet(url=_url, headers=self.headers)
            if not rsp:
                return None
            m = re.search(r'ktoken["\']?\s*[:=]\s*["\']([^"\']+)["\']', rsp)
            if m:
                return m.group(1)
            m = re.search(r'"ktoken"\s*:\s*"([^"]+)"', rsp)
            if m:
                return m.group(1)
            m = re.search(r'ktoken=([a-f0-9]+)', rsp)
            if m:
                return m.group(1)
        except Exception as e:
            logger.debug(f"查找 ktoken 失败: {e}")
        return None

    def _try_fetch_questions_via_api(self, params: dict):
        """通过API获取作业题目"""
        try:
            _headers = {
                "Referer": (f"https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?"
                            f"workId={params.get('workId', '')}&courseid={self.course_id}"
                            f"&clazzid={params.get('clazzId', '')}&ut=s"),
                "X-Requested-With": "XMLHttpRequest",
            }
            _headers.update(self.headers)
            query_string = urlencode(params)
            rsp = doGet(url=f"{WORK_API_URL}?{query_string}", headers=_headers)
            if not rsp:
                return None
            decoded = self.font_decoder.decode_page(rsp)
            hidden = self._extract_form_hidden_fields(rsp)
            questions = self._parse_questions_from_html(decoded)
            return (questions, hidden)
        except Exception as e:
            logger.error(f"获取作业题目失败: {e}")
            return None

    def _extract_form_hidden_fields(self, html: str) -> dict:
        """从HTML中提取表单隐藏字段"""
        try:
            ele = etree.HTML(html)
            hidden = {}
            for inp in ele.xpath("//form//input[@type='hidden']"):
                name = inp.get("name")
                value = inp.get("value", "")
                if name and name not in hidden:
                    hidden[name] = str(value)
            return hidden
        except Exception:
            return {}

    def _parse_questions_from_html(self, html: str) -> list[dict]:
        """从HTML中解析题目"""
        questions = []
        try:
            ele = etree.HTML(html)
            timu_elements = ele.xpath("//div[@class='TiMu']")
            if not timu_elements:
                timu_elements = ele.xpath("//div[contains(@class, 'TiMu')]")
            if not timu_elements:
                timu_elements = ele.xpath("//div[contains(@class, 'question')]")

            for timu in timu_elements:
                q = self._parse_single_question(timu)
                if q:
                    questions.append(q)

            if not questions:
                questions = self._parse_questions_via_regex(html)
        except Exception as e:
            logger.error(f"HTML 解析题目失败: {e}")
            questions = self._parse_questions_via_regex(html)
        return questions

    def _parse_single_question(self, element) -> dict | None:
        """解析单道题目"""
        try:
            title_text = "".join(element.xpath(
                ".//div[contains(@class, 'Zy_TItle') or contains(@class, 'questionTit')]//text()"
            )).strip()
            if not title_text:
                title_text = "".join(element.xpath(".//div[@class='clearfix']//text()")).strip()
            if not title_text:
                title_text = xpath_first(element, "string(.)").strip()[:300]

            # 识别题型
            q_type = "单选题"
            if "单选" in title_text:
                q_type = "单选题"
            elif "多选" in title_text:
                q_type = "多选题"
            elif "判断" in title_text:
                q_type = "判断题"
            elif "填空" in title_text:
                q_type = "填空题"
            elif "简答" in title_text or "问答" in title_text:
                q_type = "简答题"
            elif element.xpath(".//input[@type='checkbox']"):
                q_type = "多选题"
            elif element.xpath(".//input[@type='radio']"):
                q_type = "单选题"
            elif element.xpath(".//textarea[contains(@name, 'answerEditor')]") or element.xpath(".//input[contains(@name, 'tiankongsize')]"):
                q_type = "填空题"

            q_text = re.sub(r'[\[【（(]\s*(单选|多选|判断|填空|简答|问答)\s*[\]】）)]', '', title_text).strip()

            # 提取选项
            options = []
            font_test = '@data-font-unresolved="true" or ' + SECRET_FONT_PREDICATE
            font_nodes = element.xpath(f'self::*[{font_test}] | .//*[{font_test}] | ancestor::*[{font_test}]')
            reasons = list(dict.fromkeys(node.get('data-font-reason') or '题目字体尚未完成可靠解码' for node in font_nodes))
            unreadable = bool(font_nodes)
            option_items = element.xpath(".//li[contains(@class, 'option')] | .//div[contains(@class, 'option')]")
            if not option_items:
                option_items = element.xpath(".//li")
            for i, opt in enumerate(option_items):
                opt_text = xpath_first(opt, "string(.)").strip()
                images = opt.xpath('.//img')
                if images:
                    image_text = ' '.join(img.get('alt', '').strip() for img in images).strip()
                    if not image_text:
                        unreadable = True
                        reasons.append('选项图片内容没有可读说明')
                    opt_text += ' ' + (image_text or '[图片内容未识别]')
                label = chr(65 + i) + ". "
                opt_text = label + re.sub(r'^[A-Z][.、．:：)）]\s*', '', opt_text)
                options.append(opt_text)
            title_images = element.xpath('.//div[contains(@class,"Zy_TItle") or contains(@class,"questionTit")]//img')
            if any(not img.get('alt', '').strip() for img in title_images):
                unreadable = True
                reasons.append('题干图片内容没有可读说明')

            # 提取题目ID
            question_id = ""
            type_inputs = element.xpath(".//input[contains(@name, 'answertype')]")
            if type_inputs:
                name = type_inputs[0].get("name", "")
                qid_match = re.search(r'answertype(\d+)', name)
                if qid_match:
                    question_id = qid_match.group(1)

            if not question_id:
                tk_inputs = element.xpath(".//input[contains(@name, 'tiankongsize')]")
                if tk_inputs:
                    name = tk_inputs[0].get("name", "")
                    qid_match = re.search(r'tiankongsize(\d+)', name)
                    if qid_match:
                        question_id = qid_match.group(1)

            if not question_id:
                qid_inputs = element.xpath(
                    ".//input[contains(@name, 'answer') and not(contains(@name, 'answerEditor')) "
                    "and not(contains(@name, 'answerId')) and not(contains(@name, 'answerwqbid'))]"
                )
                if qid_inputs:
                    name = qid_inputs[0].get("name", "")
                    qid_match = re.search(r'answer\[(\d+)\]|answer(\d+)', name)
                    if qid_match:
                        question_id = qid_match.group(1) or qid_match.group(2)

            # 方式4：从div的id或data属性中提取
            if not question_id:
                for attr_name in element.attrib:
                    attr_val = element.get(attr_name, "")
                    qid_match = re.search(r'(\d{8,})', str(attr_val))
                    if qid_match:
                        question_id = qid_match.group(1)
                        break

            return {
                "question_id": question_id,
                "question_type": q_type,
                "question_text": q_text,
                "options": options,
                "unreadable": unreadable,
                "unreadable_reason": '；'.join(dict.fromkeys(reasons)),
            }
        except Exception as e:
            logger.debug(f"单题解析失败: {e}")
            return None

    def _parse_questions_via_regex(self, html: str) -> list[dict]:
        """正则表达式解析题目（备用）"""
        questions = []
        type_patterns = [
            (r'【单选[题]?】', "单选题"), (r'\[单选[题]?\]', "单选题"),
            (r'【多选[题]?】', "多选题"), (r'\[多选[题]?\]', "多选题"),
            (r'【判断[题]?】', "判断题"), (r'\[判断[题]?\]', "判断题"),
            (r'【填空[题]?】', "填空题"), (r'\[填空[题]?\]', "填空题"),
            (r'【简答[题]?】', "简答题"), (r'\[简答[题]?\]', "简答题"),
        ]
        blocks = re.split(r'<div[^>]*class="[^"]*TiMu[^"]*"[^>]*>', html)
        for block in blocks[1:]:
            block_text = re.sub(r'<[^>]+>', '', block[:500]).strip()
            q_type = "单选题"
            for pattern, t_name in type_patterns:
                if re.search(pattern, block_text):
                    q_type = t_name
                    break
            q_text = re.sub(r'[\[【（(]\s*(单选|多选|判断|填空|简答|问答)\s*[\]】）)]', '', block_text).strip()
            if q_text and len(q_text) > 5:
                questions.append({
                    "question_id": "", "question_type": q_type,
                    "question_text": q_text[:200], "options": [],
                })
        return questions

    def _answer_question(self, question: dict, idx: int = 0, total: int = 0) -> dict | None:
        """回答单道题目（三级回退：缓存→题库→LLM）"""
        q_text = question.get("question_text", "")
        q_type = question.get("question_type", "单选题")
        options = question.get("options", [])
        q_id = question.get("question_id", "")
        icon = TYPE_ICONS.get(q_type, "未知")
        progress = f"[{idx}/{total}]" if total > 0 else ""

        if not q_text:
            return None
        if question.get('unreadable'):
            reason = question.get('unreadable_reason') or '题目字体或图片内容未完整识别'
            self.log.warning(f'{reason}，请在学习通中核对后处理')
            return None

        if self.answer_mode == "manual":
            self.log.info(f"  {progress}{icon} 手动模式，跳过自动作答")
            return None

        display_text = q_text[:50] + "..." if len(q_text) > 50 else q_text

        # 第1步：查本地缓存
        if self.question_bank:
            cached = self.question_bank.lookup(q_text, options)
            if cached and self._normalize_answer(q_type, cached, options):
                cached = self._normalize_answer(q_type, cached, options)
                self.log.info(f"  {progress}{icon} {display_text} -> {cached} (缓存)")
                return {
                    "question_id": q_id, "question_text": q_text,
                    "question_type": q_type, "options": options,
                    "answer": cached, "source": "cache",
                }

        # 第2步：查在线题库（tiku模式必用，ai模式由fallback开关控制）
        use_tiku = self.answer_mode == "tiku" or (
            self.answer_mode == "ai" and self.fallback_to_tiku
        )
        if self.tiku and use_tiku:
            try:
                tiku_answer = self.tiku.query(q_text, options)
                if tiku_answer:
                    final_answer = tiku_answer
                    final_answer = self._normalize_answer(q_type, final_answer, options)
                    if not final_answer:
                        tiku_answer = None
                    else:
                        self.log.info(f"  {progress}{icon} {display_text} -> {final_answer} (题库)")
                        return {
                            "question_id": q_id, "question_text": q_text,
                            "question_type": q_type, "options": options,
                            "answer": final_answer, "source": "tiku",
                        }
            except Exception as e:
                logger.debug(f"在线题库查询异常: {e}")

        # 第3步：ai模式调用LLM
        if self.answer_mode == "ai":
            self.log.info(f"  {progress}{icon} {display_text}")
            self.log.info("    -> 调用 LLM...")
            llm_result = self.llm.answer_single(question)
            if llm_result:
                answer = self._normalize_answer(q_type, llm_result, options)
                if answer:
                    self.log.info(f"    -> 答案: {answer} (LLM)")
                    return {
                        "question_id": q_id, "question_text": q_text,
                        "question_type": q_type, "options": options,
                        "answer": answer, "source": "llm",
                    }

        random_answer = self._random_answer(q_type, options)
        if random_answer:
            self.log.warning(f"  {progress}{icon} {display_text} -> {random_answer} (随机)")
            return {
                "question_id": q_id, "question_text": q_text,
                "question_type": q_type, "options": options,
                "answer": random_answer, "source": "random",
            }

        self.log.warning(f"  {progress}{icon} {display_text} -> 获取失败")
        return None

    def _normalize_answer(self, q_type: str, answer: str, options: list = None) -> str:
        from core.answer_validation import normalize_answer
        return normalize_answer(q_type, answer, options)
    def _random_answer(self, q_type: str, options: list) -> str | None:
        """按配置在无答案时生成随机选择，非客观题仍跳过。"""
        if self.no_answer_action != "random":
            return None
        if q_type == "判断题":
            return random.choice(["true", "false"])
        if q_type == "单选题" and options:
            return chr(65 + random.randrange(min(len(options), 26)))
        if q_type == "多选题" and options:
            count = min(len(options), 26)
            chosen = random.sample(range(count), k=random.randint(1, count))
            return "".join(chr(65 + i) for i in sorted(chosen))
        return None

    def _save_submitted_answers(self, answered: list[dict]):
        """仅在服务器接受提交后写入缓存；缓存命中项无需重写。"""
        if not self.question_bank or not self.auto_save:
            return
        for item in answered:
            if not item.get('verified_correct') or not item.get("answer"):
                continue
            self.question_bank.save(
                question_text=item.get("question_text", ""),
                question_type=item.get("question_type", ""),
                answer=item.get("answer", ""),
                options=item.get("options", []),
                course_id=self.course_id,
            )

    def _submit_answers(self, work_id: str, answered: list[dict], defaults: dict,
                        jobid: str, enc: str | None, ktoken: str | None,
                        hidden_fields: dict = None) -> tuple[int, int]:
        """提交答案到服务器"""
        self.log.info(f"  提交 {len(answered)} 道题的答案...")

        type_code_map = {
            "单选题": "0", "多选题": "1", "填空题": "2", "判断题": "3", "简答题": "4",
        }

        form_data = {}
        if hidden_fields:
            form_data.update(hidden_fields)

        # 清除已有的答案字段
        keys_to_remove = [k for k in form_data if
                          k.startswith("answerEditor") or
                          (k.startswith("answer") and not k.startswith("answerwqbid")
                           and not k.startswith("answerId"))]
        for k in keys_to_remove:
            del form_data[k]

        question_ids = [str(item.get("question_id", "")) for item in answered if item.get("question_id")]

        form_data.update({
            "courseId": str(self.course_id),
            "classId": str(defaults.get("clazzId", self.class_id)),
            "jobid": str(jobid),
            "originJobId": str(jobid),
            "knowledgeid": str(defaults.get("knowledgeid", "")),
            "cpi": str(self.cpi),
            "enc": str(enc or ""),
            "answerwqbid": ",".join(question_ids) + "," if question_ids else "",
            "oldWorkId": str(work_id),
            "pyFlag": "",
            "userId": str(self.user.uid or ""),
        })

        if "totalQuestionNum" not in form_data or not form_data.get("totalQuestionNum"):
            form_data["totalQuestionNum"] = str(len(answered))

        # 添加每道题的答案
        for item in answered:
            idx = item.get("question_id", "")
            answer = item.get("answer", "")
            if not idx:
                continue
            q_type_name = item.get("question_type", "单选题")
            type_code = type_code_map.get(q_type_name, "0")

            if q_type_name == "填空题":
                blanks = re.split(r'[;；]', answer) if answer else [""]
                if len(blanks) == 1 and (',' in answer or '，' in answer):
                    blanks = re.split(r'[,，]', answer)

                tk_key = f"tiankongsize{idx}"
                tk_size = int(hidden_fields.get(tk_key, len(blanks))) if hidden_fields and hidden_fields.get(tk_key) else len(blanks)
                form_data[tk_key] = str(tk_size)

                for bi in range(1, tk_size + 1):
                    blank_answer = blanks[bi - 1].strip() if bi - 1 < len(blanks) else ""
                    form_data[f"answerEditor{idx}{bi}"] = blank_answer
            else:
                if answer:
                    form_data[f"answer{idx}"] = answer

            form_data[f"answertype{idx}"] = type_code

        # 提交端点与参数位置
        #
        # 修复：原先提交到 addStudentWorkNewWeb 并把参数拼在查询串里，
        # 服务端会返回“无效的参数：code-2”（源 CLI 日志中同样存在该失败）。
        # 改为与同类开源实现一致的做法：POST addStudentWorkNew，
        # 全部参数放在表单体中，查询串不带参数。
        submit_url = SUBMIT_URL  # https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew
        form_data.update({
            "_classId": str(defaults.get("clazzId", self.class_id)),
            "courseid": str(self.course_id),
            "token": form_data.get("enc_work", ""),
            # 独立作业可能没有 workRelationId，回退用 workId
            "workid": form_data.get("workRelationId") or str(work_id),
            "testmooc2": "1",
            "wMicroNodeId": form_data.get("wMicroNodeId", "0"),
        })
        # totalQuestionNum 保持题库页面下发的隐藏值（服务端下发的令牌，
        # 不是题目数量）；缺失时才回退为实际题数
        if not form_data.get("totalQuestionNum"):
            form_data["totalQuestionNum"] = str(len(answered))

        try:
            _headers = {
                "Referer": (f"https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?"
                            f"workId={work_id}&courseid={self.course_id}"
                            f"&clazzid={defaults.get('clazzId', self.class_id)}"
                            f"&knowledgeid={defaults.get('knowledgeid', '')}&jobid={jobid}"),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            _headers.update(self.headers)

            # 延迟提交（模拟人工操作，可配置），等待期间可暂停/停止
            runtime.sleep(self.submit_delay)
            rsp = doPost(url=submit_url, headers=_headers, data=form_data)
            if not rsp:
                self.log.error("  提交失败: 无响应")
                return (0, len(answered))
            if 'antispider' in str(rsp).lower() or '<html' in str(rsp).lower():
                self.log.error("  提交失败: 触发反爬虫验证页面")
                return (0, len(answered))
            try:
                result = json.loads(rsp)
                from core.answer_validation import accepted_response
                if accepted_response(result):
                    self.log.info("  提交成功!")
                    return (len(answered), 0)
                else:
                    msg = result.get('msg', '未知错误')
                    self.log.error(f"  提交失败! {msg}")
                    return (0, len(answered))
            except (json.JSONDecodeError, TypeError):
                self.log.warning(f"  提交响应非JSON: {rsp[:100]}")
                return (0, len(answered))
        except Exception as e:
            self.log.error(f"  提交异常: {e}")
            return (0, len(answered))
