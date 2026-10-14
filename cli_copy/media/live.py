"""
直播媒体类 - 处理直播任务点
通过 saveTimePc 接口记录观看时间
"""

import json
import time

from loguru import logger
from models.media import Media
from core.request_client import get as doGet


class Live(Media):
    """直播媒体类"""

    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)
        self.name = (self.attachment.get("property") or {}).get("title", "")

    def do_finish(self) -> bool:
        """完成直播任务点"""
        _property = self.attachment.get("property") or {}
        _stream_name = _property.get("streamName")
        _vdoid = _property.get("vdoid")
        if not _stream_name or not _vdoid:
            logger.warning("直播任务缺少streamName或vdoid")
            return False

        _url = (f"https://zhibo.chaoxing.com/saveTimePc?"
                f"streamName={_stream_name}&vdoid={_vdoid}"
                f"&userId={self.defaults.get('userid')}"
                f"&isStart=0&t={int(time.time() * 1000)}"
                f"&courseId={self.course_id}")
        _rsp = doGet(url=_url, headers=self.headers)
        logger.debug(_rsp)
        if not _rsp:
            logger.warning(f"直播'{self.name}'完成请求返回空响应")
            return False
        return _rsp == "@success"

    def get_status(self) -> dict | None:
        """获取直播状态信息"""
        _property = self.attachment.get("property") or {}
        live_id = _property.get('liveId')
        if not live_id:
            logger.warning("Live get_status: missing liveId")
            return None
        jobid = _property.get('_jobid') or self.jobid or ""

        status_url = (f"https://mooc1.chaoxing.com/ananas/live/liveinfo?"
                      f"liveid={live_id}&userid={self.defaults.get('userid')}"
                      f"&clazzid={self.defaults.get('clazzId')}"
                      f"&knowledgeid={self.defaults.get('knowledgeid')}"
                      f"&courseid={self.course_id}&jobid={jobid}&ut=s")
        mission_headers = {
            "Referer": "https://mooc1.chaoxing.com/ananas/modules/live/index.html?v=2022-1214-1139"
        }
        mission_headers.update(self.headers)
        status_text = doGet(url=status_url, headers=mission_headers)
        if not status_text:
            return None
        try:
            return json.loads(status_text)
        except json.JSONDecodeError as e:
            logger.error(f"直播状态解析失败: {e}")
            return None
