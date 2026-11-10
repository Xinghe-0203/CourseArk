"""
直播媒体类 - 处理直播任务点
通过 saveTimePc 接口记录观看时间
"""

import json
import time

from core import runtime
from core.runtime import logger
from models.media import Media
from core.request_client import get as doGet


class Live(Media):
    """直播媒体类"""

    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)
        self.name = (self.attachment.get("property") or {}).get("title", "")
        # 失败原因：批量执行时由 deal_video 读出来写进任务详情，
        # 避免所有失败都落到「平台尚未确认视频任务点」这句笼统文案上。
        self.last_error = ""
        # 未开播/已结束的直播没有可刷时长，属于「跳过」而不是「失败」，
        # 否则整门课会被判成 failed。
        self.skipped = False

    def do_finish(self) -> bool:
        """完成直播任务点"""
        _property = self.attachment.get("property") or {}
        _stream_name = _property.get("streamName")
        _vdoid = _property.get("vdoid")
        if not _stream_name or not _vdoid:
            self.last_error = "直播任务缺少 streamName 或 vdoid，无法上报观看时长"
            logger.warning("直播任务缺少streamName或vdoid")
            return False

        _url = (f"https://zhibo.chaoxing.com/saveTimePc?"
                f"streamName={_stream_name}&vdoid={_vdoid}"
                f"&userId={self.defaults.get('userid')}"
                f"&isStart=0&t={int(time.time() * 1000)}"
                f"&courseId={self.course_id}")
        # Media 基类只保留 User-Agent，Referer/Origin 会被丢掉；
        # 直播心跳是跨域 GET（mooc1 页面 → zhibo.chaoxing.com），
        # 缺 Referer 时平台直接回 @fail，所以这里显式补齐。
        _headers = {
            "Accept": "*/*",
            "Referer": "https://mooc1.chaoxing.com/ananas/modules/live/index.html?v=2022-1214-1139",
            "X-Requested-With": "XMLHttpRequest",
        }
        _headers.update(self.headers)
        _rsp = doGet(url=_url, headers=_headers)
        logger.debug(_rsp)
        if not _rsp:
            self.last_error = "直播时长上报没有返回内容，可能是登录状态失效"
            logger.warning(f"直播'{self.name}'完成请求返回空响应")
            return False
        if _rsp.strip() == "@success":
            self.last_error = ""
            return True
        self.last_error = f"平台拒绝直播心跳（{_rsp.strip()[:40]}），直播可能已结束或需要在网页端观看"
        return False

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


