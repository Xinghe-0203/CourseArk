"""
AutoChaoxingCLI - 课程模型

管理课程信息、章节列表、学习统计等。
"""

import json
import re
import time
from urllib import parse

from loguru import logger
from lxml import etree

from core.request_client import get as doGet, post as doPost, xpath_first
from core.exceptions import RequestException


class Course:
    """
    课程类

    Attributes:
        course_id (str): 课程ID
        class_id (str): 班级ID
        url (str): 课程URL
        course_name (str): 课程名称
        course_author (str): 课程教师
        cpi (str): CPI参数
        chapter_list (list): 章节列表
        mission_all (int): 总任务数
        mission_fn (int): 已完成任务数
        headers (dict): 请求头
        if_open (bool): 课程是否开放
    """

    def __init__(self, course_id: str, class_id: str, url: str, course_name: str,
                 course_author: str, cpi: str = "", headers: dict = None, if_open: bool = True):
        self.course_id = course_id
        self.class_id = class_id
        self.url = url
        self.course_name = course_name
        self.course_author = course_author

        # 从URL中提取cpi
        if not cpi:
            query_params = parse.parse_qs(parse.urlparse(self.url).query)
            cpi_list = query_params.get("cpi")
            self.cpi = cpi_list[0] if cpi_list else ""
        else:
            self.cpi = cpi

        self.chapter_list = []
        self.mission_all = 0
        self.mission_fn = 0
        self._child_chapter_list = []
        self.url_log = ""
        self.headers = headers or {}
        self.if_open = if_open
        self._jobEnc = None

    def __str__(self):
        return (f"CourseName: {self.course_name}\n"
                f"Author: {self.course_author}\n"
                f"CourseId: {self.course_id}\n"
                f"ClazzId: {self.class_id}\n"
                f"Cpi: {self.cpi}")

    def get_chapter(self):
        """获取课程章节列表"""
        self.chapter_list.clear()
        html_text = doGet(
            url=f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={self.course_id}&clazzid={self.class_id}&cpi={self.cpi}&ut=s&t={int(time.time())}",
            headers=self.headers
        )
        if not html_text:
            raise RequestException('课程章节读取失败：平台返回空响应')

        ele = etree.HTML(html_text)
        ele_root = xpath_first(ele, "//div[contains(concat(' ',normalize-space(@class),' '),' fanyaChapterWhite ')]")
        if not hasattr(ele_root, 'xpath'):
            raise RequestException('课程章节页面无法识别，请检查登录状态或平台验证')

        # 提取任务完成进度
        mission_text = xpath_first(ele_root, "./div[1]/h2/span/text()") or "0/0"
        mission_parts = str(mission_text).split("/")
        try:
            self.mission_fn = int(mission_parts[0]) if mission_parts else 0
            self.mission_all = int(mission_parts[1]) if len(mission_parts) > 1 else 0
        except (ValueError, TypeError):
            self.mission_fn = 0
            self.mission_all = 0

        logger.info(f"任务进度: {self.mission_fn}/{self.mission_all}")

        # 提取章节
        ele_units = ele_root.xpath(".//div[contains(concat(' ',normalize-space(@class),' '),' chapter_unit ')]")
        for unit in ele_units:
            unit_catalog_name = xpath_first(unit, "./div[1]/div[1]/div[@class='catalog_name newCatalog_name']/a/span/text()").strip()
            for item_li in unit.xpath("./div[2]/ul/li"):
                self._recursion_chapter_item(item_li, 0)
            self.chapter_list.append({
                "catalog_name": unit_catalog_name,
                "child_chapter": self._child_chapter_list.copy()
            })
            self._child_chapter_list.clear()
        if self.mission_all > 0 and not self.chapter_list:
            raise RequestException('课程有任务点，但未识别到章节列表，请核对平台页面')

    def _recursion_chapter_item(self, element, depth: int):
        """递归解析章节列表项"""
        click_data = xpath_first(element, "./div/@onclick")
        knowledge_id = element.get('data-knowledgeid') or element.get('data-knowledge-id') or ''
        if not knowledge_id and click_data:
            args = re.findall(r'["\']([^"\']*)["\']', click_data)
            candidate = args[1] if len(args) > 1 else args[0] if args else ''
            knowledge_id = candidate if re.fullmatch(r'[A-Za-z0-9_-]+', candidate) else ''

        name_element = xpath_first(element, ".//a[contains(concat(' ',normalize-space(@class),' '),' clicktitle ')]")
        name_text = xpath_first(name_element, "string(.)").strip() if hasattr(name_element, 'xpath') else ""
        count = xpath_first(element, "./div//div[contains(concat(' ',normalize-space(@class),' '),' catalog_task ')]/input/@value")
        count_match = re.search(r'\d+', str(count))

        self._child_chapter_list.append({
            "name": ("[锁] " if knowledge_id == '' else '') + name_text,
            "depth": depth,
            "knowledge_id": knowledge_id,
            "job_count": int(count_match.group()) if count_match else 0,
            "job_count_known": bool(count_match),
            "available": knowledge_id != ''
        })

        # 递归处理子章节
        for chapter_item in element.xpath("./ul/li"):
            self._recursion_chapter_item(chapter_item, depth + 1)

    def get_url_log(self) -> str:
        """获取课程学习记录URL"""
        if not self.url_log:
            _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={self.course_id}&clazzid={self.class_id}&cpi={self.cpi}&ut=s&t=1678608658539"
            _rsp = doGet(url=_url, headers=self.headers)
            if _rsp:
                matches = re.findall(r"(https://fystat-ans.chaoxing.com/log/setlog(.)+)\"></script>", _rsp)
                self.url_log = matches[0][0] if matches else ""
            if not self.url_log:
                logger.warning("未找到课程学习记录链接")
        return self.url_log

    def _get_work_enc_params(self) -> dict:
        """
        获取独立作业所需的加密参数

        从课程中间页提取 enc / workEnc / examEnc / openc / t 等隐藏字段，
        这些参数是访问"作业"标签页列表接口的必要条件。

        Returns:
            dict: 加密参数字典，获取失败时返回空字典
        """
        _url = (f"https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?"
                f"courseid={self.course_id}&clazzid={self.class_id}&vc=1"
                f"&cpi={self.cpi}&ismooc2=1&v=2")
        _headers = {"Referer": "https://mooc1-1.chaoxing.com/visit/courselistdata"}
        _headers.update(self.headers)
        try:
            html = doGet(url=_url, headers=_headers)
        except Exception as e:
            logger.debug(f"获取作业加密参数失败: {e}")
            return {}
        if not html:
            return {}

        ele = etree.HTML(html)
        params = {}
        if ele is None:
            return params
        for name in ("enc", "workEnc", "examEnc", "openc", "t"):
            # 依次尝试 name= / id= 两种属性
            value = xpath_first(ele, f"//input[@name='{name}']/@value")
            if not value:
                value = xpath_first(ele, f"//input[@id='{name}']/@value")
            if value:
                params[name] = str(value)

        # 部分页面把 enc/t 放在跳转链接里，兜底从整页正则提取
        if not params.get("enc"):
            match = re.search(r'[?&]enc=([a-fA-F0-9]{16,})', html)
            if match:
                params["enc"] = match.group(1)
        if not params.get("t"):
            match = re.search(r'[?&]t=(\d{10,})', html)
            if match:
                params["t"] = match.group(1)
        return params

    def get_work_list(self) -> list[dict]:
        """
        获取课程的独立作业列表

        注意：此处的"作业"指课程作业标签页中的独立作业，
        与章节内的"章节测验"（任务点）是不同概念：
        - 独立作业：有独立截止时间，需单独提交，入口在课程作业页
        - 章节测验：嵌入章节任务点，完成即计入任务点进度

        会依次尝试两个已知列表接口，任一成功即返回。

        Returns:
            list[dict]: 作业列表，每项包含 work_id/answer_id/enc/title/status/
                        time_left/valid/url
        """
        enc_params = self._get_work_enc_params()
        enc = enc_params.get("enc", "")
        work_enc = enc_params.get("workEnc") or enc
        openc = enc_params.get("openc", "")
        t = enc_params.get("t", str(int(time.time() * 1000)))

        # 接口1：getAllWork（PC端作业标签页，兼容性最好）
        url1 = (f"https://mooc1-1.chaoxing.com/mooc-ans/work/getAllWork?"
                f"classId={self.class_id}&courseId={self.course_id}"
                f"&isdisplaytable=2&mooc=1&ut=s"
                f"&enc={enc}&cpi={self.cpi}&openc={openc}")
        try:
            html1 = doGet(url=url1, headers=self.headers)
        except Exception as e:
            logger.debug(f"getAllWork接口异常: {e}")
            html1 = ""
        parse_errors = []
        try:
            items = self._parse_work_list(html1)
        except RequestException as exc:
            parse_errors.append(str(exc))
            logger.debug(f'getAllWork列表解析失败，继续尝试新版接口：{exc}')
            items = []
        if items:
            return items

        # 接口2：mooc2/work/list（新版列表）
        url2 = (f"https://mooc1.chaoxing.com/mooc2/work/list?"
                f"courseId={self.course_id}&classId={self.class_id}"
                f"&cpi={self.cpi}&ut=s&t={t}&stuenc={enc}&enc={work_enc}")
        try:
            html2 = doGet(url=url2, headers=self.headers)
        except Exception as e:
            logger.debug(f"mooc2作业列表接口异常: {e}")
            html2 = ""
        try:
            items = self._parse_work_list(html2)
        except RequestException as exc:
            parse_errors.append(str(exc))
            logger.debug(f'新版作业列表解析失败：{exc}')
            items = []
        if items:
            return items
        for html in (html1, html2):
            if not html or any(marker in html.lower() for marker in ('antispider', 'captcha', 'login required')):
                continue
            root = etree.HTML(html)
            containers = root.xpath('//*[contains(@class,"bottomList") or contains(@class,"workList")]') if root is not None else []
            populated = root.xpath('//*[contains(@class,"bottomList") or contains(@class,"workList")]//li') if root is not None else []
            if root is not None and not root.xpath('//input[@type="password"]') and (
                (containers and not populated) or any(text in html for text in ('暂无作业', '没有作业', '无作业'))):
                return []
        reason = '无法读取独立作业列表，请检查网络、登录状态或平台验证'
        if parse_errors:
            reason += '；' + '；'.join(dict.fromkeys(parse_errors))
        raise RequestException(reason)

    @staticmethod
    def _parse_work_list(html: str) -> list[dict]:
        """解析作业列表HTML，提取作业条目"""
        if not html:
            return []
        ele = etree.HTML(html)
        if ele is None:
            return []

        items = []
        seen_ids = set()
        # 兼容两种结构：div.bottomList 下的 li，或带 data 属性的 li
        candidates = ele.xpath("//*[contains(@class,'bottomList') or contains(@class,'workList')]//li")
        if not candidates:
            candidates = ele.xpath("//li[@data or @data-url]")

        for li in candidates:
            data_url = li.get("data") or li.get("data-url") or ""
            if not data_url:
                if any(text in html for text in ('暂无作业', '没有作业', '无作业')):
                    continue
                raise RequestException('作业列表包含无法识别的条目，请核对平台页面')

            work_id = ""
            answer_id = ""
            enc = ""
            match = re.search(r'workId=([^&"]+)', data_url)
            if match:
                work_id = match.group(1)
            match = re.search(r'(?:answerId|workAnswerId)=([^&"]*)', data_url)
            if match:
                answer_id = match.group(1)
            match = re.search(r'[?&]enc=([^&"]*)', data_url)
            if match:
                enc = match.group(1)

            if not work_id:
                raise RequestException('作业列表条目缺少workId，无法确认完整作业范围')
            if work_id in seen_ids:
                continue
            seen_ids.add(work_id)

            title = "".join(li.xpath(
                ".//p[contains(@class,'overHidden2')]//text()"
            )).strip()
            if not title:
                title = "".join(li.xpath(".//p[contains(@class,'title')]//text()")).strip()
            if not title:
                link = li.xpath(".//a/@title")
                title = link[0].strip() if link else "未命名作业"

            status = "".join(li.xpath(".//p[contains(@class,'status')]//text()")).strip()
            time_left = "".join(li.xpath(
                ".//div[contains(@class,'time')]//text()"
            )).strip()

            # 过期标志：图标类名以 -g 结尾（如 icon-before-g）
            expired_icons = li.xpath(".//div[contains(@class,'-g')]")
            valid = not bool(expired_icons)

            items.append({
                "work_id": work_id,
                "answer_id": answer_id,
                "enc": enc,
                "title": title,
                "status": status,
                "time_left": time_left,
                "valid": valid,
                "url": data_url,
            })
        return items

    def get_count_log(self) -> int:
        """获取课程学习次数"""
        _headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Host': 'stat2-ans.chaoxing.com'
        }
        _headers.update(self.headers)
        import datetime
        now = datetime.datetime.now()
        _rsp = doPost(
            url="https://stat2-ans.chaoxing.com/stat2/study-pv/chart",
            headers=_headers,
            data=f"clazzid={self.class_id}&courseid={self.course_id}&cpi={self.cpi}&ut=s&year={now.year}&month={now.month:02d}"
        )
        if not _rsp:
            return 0
        try:
            return json.loads(_rsp).get("total") or 0
        except json.JSONDecodeError:
            return 0

    def get_time_log(self) -> list[float]:
        """获取课程视频观看时长 [累计观看, 总时长]（分钟）"""
        _url = f"https://stat2-ans.chaoxing.com/stat2/task/s/index?courseid={self.course_id}&cpi={self.cpi}&clazzid={self.class_id}&ut=s&pEnc={self.jobEnc}&"
        _rsp = doGet(url=_url, headers=self.headers)
        if not _rsp:
            return [0.0, 0.0]
        _ele = etree.HTML(_rsp)
        _acc = xpath_first(_ele, "//div[@class='fl min']/span/text()")
        all_matches = re.findall(r'总时长(\d+)', _rsp)
        _all = all_matches[0] if all_matches else "0"
        return [float(_acc or 0), float(_all)]

    def get_progress_data(self) -> list:
        """获取课程学习进度数据"""
        _url = f"https://stat2-ans.chaoxing.com/stat2/task/s/progress/detail?clazzid={self.class_id}&courseid={self.course_id}&cpi={self.cpi}&ut=s&pEnc={self.jobEnc}&page=1&pageSize=16&status=0"
        _rsp = doGet(url=_url, headers=self.headers)
        if not _rsp:
            return []
        try:
            data = json.loads(_rsp).get("data") or {}
            return data.get("results") or []
        except json.JSONDecodeError:
            return []

    @property
    def jobEnc(self) -> str:
        """获取任务加密参数jobEnc"""
        if self._jobEnc is None:
            _url = f"https://stat2-ans.chaoxing.com/study-data/index?courseid={self.course_id}&clazzid={self.class_id}&cpi={self.cpi}&ut=s&t=1683984845824"
            _data = doGet(url=_url, headers=self.headers)
            if _data:
                matches = re.findall(r"jobEnc = '(.*)';", _data)
                self._jobEnc = matches[0] if matches else ""
            else:
                self._jobEnc = ""
            if not self._jobEnc:
                logger.warning("未找到jobEnc")
        return self._jobEnc
