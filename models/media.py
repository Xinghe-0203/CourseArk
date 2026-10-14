"""
AutoChaoxingCLI - 媒体基类

所有媒体类型（视频、阅读、文档、图书、直播、作业）的抽象基类。
"""

import json
import time
from abc import ABC, abstractmethod

from loguru import logger

from core.request_client import get as doGet


class Media(ABC):
    """
    媒体抽象基类

    Attributes:
        name (str): 媒体名称
        attachment (dict): 附件数据
        type (str): 媒体类型
        jobid (str): 任务ID
        headers (dict): 请求头
        defaults (dict): 默认参数
        course_id (str): 课程ID
    """

    def __init__(self, attachment: dict, headers: dict, defaults: dict = None, course_id: str = ""):
        self.name = ""
        self.attachment = attachment
        self.type = attachment.get("type")
        self.jobid = attachment.get("jobid")
        self.headers = {"User-Agent": headers.get("User-Agent")} if headers else {}
        self.defaults = defaults or {}
        self.course_id = course_id

    @abstractmethod
    def do_finish(self) -> bool:
        """完成媒体任务（子类实现）"""
        pass

    def _do_simple_job_finish(self, api_path: str, referer: str, task_name: str) -> bool:
        """
        通用的简单任务完成方法

        适用于阅读、文档、图书等简单任务。

        Args:
            api_path: API路径（如'job/readv2'）
            referer: Referer请求头
            task_name: 任务名称（用于日志）

        Returns:
            bool: 完成成功返回True
        """
        jtoken = self.attachment.get("jtoken")
        if not jtoken:
            logger.warning(f"{task_name} 任务缺少jtoken，跳过标记")
            return False

        _headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Host': 'mooc1-2.chaoxing.com',
            'Referer': referer,
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'X-Requested-With': 'XMLHttpRequest'
        }
        _headers.update(self.headers)

        _url = (f'https://mooc1-2.chaoxing.com/ananas/{api_path}?'
                f'jobid={self.jobid}&knowledgeid={self.defaults.get("knowledgeid")}'
                f'&courseid={self.course_id}&clazzid={self.defaults.get("clazzId")}'
                f'&jtoken={self.attachment.get("jtoken")}&_dc={int(time.time() * 1000)}')

        _rsp = doGet(url=_url, headers=_headers)
        logger.debug(_rsp)
        if not _rsp:
            logger.warning(f"{task_name} 任务请求返回空响应")
            return False
        try:
            rsp_json = json.loads(_rsp)
            status_val = rsp_json.get("status")
            # 严格检查：只有 True 或 "true" 才算成功，避免 bool("false") 误判
            if isinstance(status_val, bool):
                return status_val
            if isinstance(status_val, str):
                return status_val.lower() == "true"
            return False
        except json.JSONDecodeError as e:
            logger.error(f"解析{task_name}任务响应失败: {e}")
            return False
