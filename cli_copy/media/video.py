"""
AutoChaoxingCLI - 视频媒体类

处理视频任务点的完成逻辑，包括：
- 获取视频状态（时长、dtoken）
- 生成播放记录提交URL
- 完成视频任务点
"""

import hashlib
import json
import time
from urllib.parse import quote

from loguru import logger

from models.media import Media
from core.request_client import get as doGet

# 视频播放器Referer版本号
VIDEO_REFERER_VERSION = "2025-0725-1842"
VIDEO_STATUS_HOST = "mooc1-1.chaoxing.com"


class Video(Media):
    """
    视频媒体类

    Attributes:
        objectId (str): 视频对象ID
        reportUrl (str): 播放记录提交URL
        dtype (str): 媒体类型（Video/Audio）
        name (str): 视频名称
        rt (float): 播放速率参数
    """

    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str = "",
                 dtype: str = "Video", name: str = ""):
        super().__init__(attachment, headers, defaults, course_id)
        self.objectId = attachment.get("objectId")
        self.reportUrl = defaults.get("reportUrl")
        self.dtype = dtype
        self.name = name

        # 解析播放速率参数
        other_info = attachment.get("otherInfo") or ""
        if "-rt_1" in other_info:
            self.rt = 1
        elif "-rt_d" in other_info:
            self.rt = 0.9
        else:
            self.rt = (attachment.get("property") or {}).get("rt") or 0.9

    def get_status(self) -> dict | None:
        """获取视频状态信息（时长、dtoken等）"""
        if not self.objectId:
            logger.error("Video get_status: objectId为空")
            return None

        status_url = f"https://{VIDEO_STATUS_HOST}/ananas/status/{self.objectId}?k=&flag=normal&_dc={int(time.time() * 1000)}"
        mission_headers = {
            "Referer": f"https://mooc1.chaoxing.com/ananas/modules/video/index.html?v={VIDEO_REFERER_VERSION}"
        }
        mission_headers.update(self.headers)
        try:
            status_text = doGet(url=status_url, headers=mission_headers)
            if not status_text:
                logger.warning(f"视频状态请求返回空: objectId={self.objectId}")
                return None
            return json.loads(status_text)
        except json.JSONDecodeError as e:
            logger.error(f"视频状态解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取视频状态异常: {e}")
            return None

    def _rt_candidates(self) -> list:
        """返回播放速率候选值：优先实例解析出的rt，缺失时回退 0.9 / 1"""
        return [self.rt] if self.rt else [0.9, 1]

    def do_finish(self) -> bool:
        """完成视频任务点（立即完成模式）

        流程：
        1. 先发送 isdrag=3（开始播放信号），playingTime=0
        2. 再发送 isdrag=4（播放完成），playingTime=duration
        参考：多个开源项目（XilyFeAAAA/Chaoxing、Samueli924/chaoxing）均采用此流程

        若返回验证码拦截（403/captcha），会切换 rt 参数重试，避免误判为失败。
        """
        video_status = self.get_status()
        if not video_status:
            logger.error(f"无法获取视频状态: objectId={self.objectId}")
            return False

        duration = video_status.get('duration')
        dtoken = video_status.get('dtoken')

        if duration is None or dtoken is None:
            logger.error(f"视频缺少duration或dtoken: objectId={self.objectId}")
            return False
        try:
            duration = int(float(duration))
        except (TypeError, ValueError):
            logger.error(f"视频时长格式无效({duration}): objectId={self.objectId}")
            return False
        if duration <= 0:
            logger.error(f"视频时长无效({duration}): objectId={self.objectId}")
            return False

        # 检查 reportUrl 是否有效
        if not self.reportUrl:
            logger.error(f"视频缺少reportUrl: objectId={self.objectId}")
            return False

        _headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Sec-Fetch-Dest': 'empty',
            'Host': 'mooc1.chaoxing.com',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Referer': f'https://mooc1-2.chaoxing.com/ananas/modules/video/index.html?v={VIDEO_REFERER_VERSION}'
        }
        _headers.update(self.headers)

        # 依次尝试rt候选值：成功或非拦截失败即停止，全部被拦截才判定失败
        last_rsp = ""
        for rt in self._rt_candidates():
            # 第一步：发送开始播放信号（isdrag=3, playingTime=0）
            start_url = self.get_url(0, duration, dtoken, 3, rt=rt)
            _start_rsp = doGet(url=start_url, headers=_headers)
            logger.debug(f"视频开始信号响应(rt={rt}): {_start_rsp}")

            if self.is_forbidden_response(_start_rsp):
                last_rsp = _start_rsp
                continue

            # 第二步：发送播放完成（isdrag=4, playingTime=duration）
            _url = self.get_url(duration, duration, dtoken, 4, rt=rt)
            _rsp = doGet(url=_url, headers=_headers)
            logger.debug(f"视频完成响应(rt={rt}): {_rsp}")
            last_rsp = _rsp

            if self.is_forbidden_response(_rsp):
                continue

            # 非拦截响应：直接以服务器 isPassed 作为最终结果
            return self.is_passed_response(_rsp)

        if self.is_forbidden_response(last_rsp):
            logger.warning(f"视频'{self.name}'进度上报被验证码拦截，需稍后重试")
        return False

    @staticmethod
    def is_passed_response(response_text) -> bool:
        """严格判断视频完成响应，避免把空响应或失败状态计为成功。"""
        if not response_text:
            return False
        response_lower = str(response_text).lower()
        if "antispider" in response_lower or "captcha" in response_lower:
            return False
        try:
            response = response_text if isinstance(response_text, dict) else json.loads(response_text)
            is_passed = response.get("isPassed")
        except (json.JSONDecodeError, TypeError, AttributeError):
            return False
        if isinstance(is_passed, bool):
            return is_passed
        if isinstance(is_passed, str):
            return is_passed.lower() == "true"
        return False

    @staticmethod
    def is_forbidden_response(response_text: str) -> bool:
        """
        判断响应是否被验证码/403拦截（需要恢复会话后重试）

        超星在进度上报过于频繁时会返回验证码页面，此时不应计为"未通过"而是应恢复后重试。
        """
        if response_text is None:
            return False
        text = str(response_text).lower()
        return ("antispider" in text or "captcha" in text
                or "验证码" in str(response_text) or "validate" in text)

    def get_url(self, time_end: int, duration: int, dtoken: str, play_type: int,
                rt: float | str | None = None) -> str:
        """
        生成视频播放记录提交URL

        Args:
            time_end: 当前播放时间（秒）
            duration: 视频总时长（秒）
            dtoken: 视频播放验证token
            play_type: 播放状态（0=播放中, 3=开始, 4=完成）
            rt: 播放速率参数，None则使用实例默认值

        Returns:
            str: 完整的提交URL
        """
        time_end = int(time_end)
        duration = int(duration)

        # 构建加密字符串并计算MD5
        enc_raw = (f"[{self.defaults.get('clazzId')}]"
                   f"[{self.defaults.get('userid')}]"
                   f"[{self.jobid}]"
                   f"[{self.objectId}]"
                   f"[{time_end * 1000}]"
                   f"[d_yHJ!$pdA~5]"
                   f"[{duration * 1000}]"
                   f"[0_{duration}]")
        enc = hashlib.md5(enc_raw.encode()).hexdigest()

        # 部分视频启用了防拖拽/人脸识别校验，需回传这些校验参数
        extra_params = ""
        face_capture_enc = self.attachment.get("videoFaceCaptureEnc")
        att_duration = self.attachment.get("attDuration")
        att_duration_enc = self.attachment.get("attDurationEnc")
        if face_capture_enc:
            extra_params += f"&videoFaceCaptureEnc={quote(str(face_capture_enc), safe='')}"
        if att_duration:
            extra_params += f"&attDuration={quote(str(att_duration), safe='')}"
        if att_duration_enc:
            extra_params += f"&attDurationEnc={quote(str(att_duration_enc), safe='')}"

        url_former = self.reportUrl
        url_later = (f"/{dtoken}?"
                     f"clazzId={self.defaults.get('clazzId')}"
                     f"&playingTime={time_end}"
                     f"&duration={duration}"
                     f"&clipTime=0_{duration}"
                     f"&objectId={self.objectId}"
                     f"&otherInfo={self.attachment.get('otherInfo')}"
                     f"&courseId={self.course_id}"
                     f"&jobid={self.jobid}"
                     f"&userid={self.defaults.get('userid')}"
                     f"&isdrag={play_type}"
                     f"&view=pc"
                     f"&enc={enc}"
                     f"&rt={self.rt if rt is None else rt}"
                     f"&dtype={self.dtype}"
                     f"{extra_params}"
                     f"&_t={int(time.time() * 1000)}")
        return url_former + url_later
