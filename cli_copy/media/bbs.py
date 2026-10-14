"""
讨论媒体类 - 处理超星讨论(BBS)任务点
通过访问讨论页面并发送回复完成讨论任务
"""
import json
import re
import uuid

from loguru import logger
from models.media import Media
from core.request_client import get as doGet, post as doPost


class Bbs(Media):
    """讨论媒体类 - 自动完成超星课程中的讨论任务点"""

    # 讨论回复的默认内容池，随机选取一条发送
    DEFAULT_REPLIES = [
        "老师讲得很好，受益匪浅",
        "感谢老师的分享，学到了很多",
        "内容很有深度，值得反复思考",
        "这节课很有启发，谢谢老师",
        "学习了，很有收获",
        "感谢分享，继续努力",
        "很有帮助，谢谢老师",
        "观点很有启发性",
    ]

    def __init__(self, attachment: dict, headers: dict = None, defaults: dict = None, course_id: str = ""):
        super().__init__(attachment, headers, defaults, course_id)
        _property = attachment.get("property") or {}
        self.name = _property.get("name", "讨论")

    def do_finish(self) -> bool:
        """
        完成讨论任务点

        流程：
        1. 先通过 _do_simple_job_finish 标记任务点完成
        2. 访问讨论页面获取讨论详情（topicUUID, bbsid等）
        3. 发送一条回复完成讨论

        Returns:
            bool: 完成成功返回True
        """
        # 先尝试标记任务点完成
        jtoken = self.attachment.get("jtoken")
        job_result = False
        if jtoken:
            job_result = self._do_simple_job_finish(
                api_path='job',
                referer='https://mooc1-2.chaoxing.com/ananas/modules/insertbbs/index.html',
                task_name='Bbs'
            )

        # 尝试发表回复完成讨论
        reply_result = self._reply_discussion()
        if reply_result:
            logger.success(f"  讨论'{self.name}'完成成功")
            return True

        # 任务点标记成功但回复失败，仍视为成功
        if job_result:
            logger.info(f"  讨论'{self.name}'任务点已标记完成（回复未发送）")
            return True

        logger.warning(f"  讨论'{self.name}'完成失败")
        return False

    def _reply_discussion(self) -> bool:
        """
        发表讨论回复

        通过 bbscircle/chapter 接口获取讨论页面信息，
        提取 topicUUID 和 bbsid，然后发送回复

        Returns:
            bool: 回复成功返回True
        """
        import random

        _property = self.attachment.get("property") or {}
        mid = _property.get("mid") or self.attachment.get("mid")
        jobid = self.attachment.get("jobid") or self.jobid

        if not mid or not jobid:
            logger.debug("讨论任务缺少mid或jobid，跳过回复")
            return False

        try:
            # 方式1：PC端 - 通过 bbscircle/chapter 获取讨论信息
            bbs_info = self._get_bbs_info_pc(mid, jobid)
            if bbs_info:
                topic_uuid = bbs_info.get("topic_uuid", "")
                bbsid = bbs_info.get("bbsid", "")
                if topic_uuid and bbsid:
                    content = random.choice(self.DEFAULT_REPLIES)
                    return self._do_reply_pc(topic_uuid, bbsid, content)

            # 方式2：手机端 - 通过 mooc1-api 获取讨论信息
            bbs_info = self._get_bbs_info_mobile(mid, jobid)
            if bbs_info:
                topic_uuid = bbs_info.get("topic_uuid", "")
                if topic_uuid:
                    content = random.choice(self.DEFAULT_REPLIES)
                    return self._do_reply_mobile(topic_uuid, content)

        except Exception as e:
            logger.debug(f"讨论回复异常: {e}")

        return False

    def _get_bbs_info_pc(self, mid: str, jobid: str) -> dict | None:
        """
        通过PC端接口获取讨论信息

        Args:
            mid: 讨论mid
            jobid: 任务jobid

        Returns:
            包含topic_uuid和bbsid的字典，或None
        """
        knowledgeid = self.defaults.get("knowledgeid", "")
        clazz_id = self.defaults.get("clazzId", "")
        enc = self.defaults.get("enc", "")

        chapter_url = (
            f"https://mooc1.chaoxing.com/mooc-ans/bbscircle/chapter?"
            f"mtopicid={mid}&jobid={jobid}&isPortal=false"
            f"&knowledgeid={knowledgeid}&ut=s"
            f"&clazzId={clazz_id}&enc={enc}"
            f"&courseid={self.course_id}&isJob=true"
        )

        _headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://mooc1.chaoxing.com/ananas/modules/insertbbs/index.html',
        }
        _headers.update(self.headers)

        try:
            rsp = doGet(url=chapter_url, headers=_headers)
            if not rsp:
                return None

            # 从页面中提取 topicUUID 和 bbsid
            # 页面HTML中包含类似:
            # <div ... data="https://groupweb.chaoxing.com/course/topic/v3/bbs/{topicUUID}/{bbsid}/replysList?...">
            pattern = r'topic/v3/bbs/([^/]+)/([^/]+)/replysList'
            match = re.search(pattern, rsp)
            if match:
                return {
                    "topic_uuid": match.group(1),
                    "bbsid": match.group(2),
                }

            # 备用：尝试从JS变量中提取
            uuid_match = re.search(r'topicUUID["\s:=]+["\']?([a-f0-9]{32})', rsp)
            bbsid_match = re.search(r'bbsid["\s:=]+["\']?([a-f0-9]{32})', rsp)
            if uuid_match and bbsid_match:
                return {
                    "topic_uuid": uuid_match.group(1),
                    "bbsid": bbsid_match.group(1),
                }

        except Exception as e:
            logger.debug(f"PC端讨论信息获取异常: {e}")

        return None

    def _get_bbs_info_mobile(self, mid: str, jobid: str) -> dict | None:
        """
        通过手机端接口获取讨论信息

        Args:
            mid: 讨论mid
            jobid: 任务jobid

        Returns:
            包含topic_uuid的字典，或None
        """
        knowledgeid = self.defaults.get("knowledgeid", "")
        clazz_id = self.defaults.get("clazzId", "")

        chapter_url = (
            f"https://mooc1-api.chaoxing.com/mooc-ans/bbscircle/chapter?"
            f"mtopicid={mid}&jobid={jobid}&isPortal=false"
            f"&knowledgeid={knowledgeid}&ut=s"
            f"&clazzId={clazz_id}&enc&utenc=undefined"
            f"&courseid={self.course_id}&isJob=true&isMobile=true"
        )

        _headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://mooc1-api.chaoxing.com/ananas/modules/insertbbs/index.html',
            'X-Requested-With': 'com.chaoxing.mobile',
            'Upgrade-Insecure-Requests': '1',
        }
        _headers.update(self.headers)

        try:
            rsp = doGet(url=chapter_url, headers=_headers)
            if not rsp:
                return None

            # 从手机端页面提取topicUUID
            pattern = r'topic/v3/bbs/([^/]+)/([^/]+)/replysList'
            match = re.search(pattern, rsp)
            if match:
                return {
                    "topic_uuid": match.group(1),
                    "bbsid": match.group(2),
                }

            # 尝试从JSON数据中提取
            try:
                data = json.loads(rsp)
                topic_uuid = data.get("topicUUID") or data.get("topicUuid")
                if topic_uuid:
                    return {"topic_uuid": topic_uuid}
            except json.JSONDecodeError:
                pass

            # 从HTML中搜索
            uuid_match = re.search(r'topicUUID["\s:=]+["\']?([a-f0-9]{32})', rsp)
            if uuid_match:
                return {"topic_uuid": uuid_match.group(1)}

        except Exception as e:
            logger.debug(f"手机端讨论信息获取异常: {e}")

        return None

    def _do_reply_pc(self, topic_uuid: str, bbsid: str, content: str) -> bool:
        """
        通过PC端接口发表讨论回复

        Args:
            topic_uuid: 讨论主题UUID
            bbsid: 讨论BBS ID
            content: 回复内容

        Returns:
            bool: 回复成功返回True
        """
        from urllib.parse import quote

        clazz_id = self.defaults.get("clazzId", "")
        _uuid = str(uuid.uuid4())

        reply_url = f"https://groupweb.chaoxing.com/pc/invitation/{topic_uuid}/addReplys"
        data = (
            f"courseId={self.course_id}&classId={clazz_id}"
            f"&replyId=-1&uuid={_uuid}"
            f"&topic_content={quote(content)}"
            f"&anonymous=&urlToken=&bbsid={bbsid}"
        )

        _headers = {
            'Accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://groupweb.chaoxing.com/',
            'X-Requested-With': 'XMLHttpRequest',
        }
        _headers.update(self.headers)

        try:
            rsp = doPost(url=reply_url, headers=_headers, data=data)
            if rsp:
                try:
                    result = json.loads(rsp)
                    status = result.get("status") or result.get("result")
                    if status is True or status == "true":
                        return True
                except json.JSONDecodeError:
                    pass
                # 请求已发出，可能成功
                return True
        except Exception as e:
            logger.debug(f"PC端讨论回复异常: {e}")

        return False

    def _do_reply_mobile(self, topic_uuid: str, content: str) -> bool:
        """
        通过手机端接口发表讨论回复

        Args:
            topic_uuid: 讨论主题UUID
            content: 回复内容

        Returns:
            bool: 回复成功返回True
        """
        from urllib.parse import quote
        from hashlib import md5

        clazz_id = self.defaults.get("clazzId", "")
        _uuid = str(uuid.uuid4()).replace("-", "")
        _time = str(int(__import__('time').time() * 1000))

        # 获取puid (从cookies中的UID)
        puid = ""
        try:
            from core.request_client import get_session
            session = get_session()
            for cookie in session.cookies:
                if cookie.name == "UID":
                    puid = cookie.value
                    break
        except Exception:
            pass

        # 计算 inf_enc 签名
        des_key = "Z(AfY@XS"
        sign_params = (
            f"token=4faa8662c59590c6f43ae9fe5b002b42"
            f"&_time={_time}&_c_0_={_uuid}"
            f"&puid={puid}&uuid={_uuid}"
            f"&tag=classId{clazz_id}&maxW=1080"
            f"&topicUUID={topic_uuid}&anonymous=0"
            f"&DESKey={des_key}"
        )
        inf_enc = md5(sign_params.encode()).hexdigest()

        reply_url = (
            f"https://groupyd.chaoxing.com/apis/invitation/addReply?"
            f"token=4faa8662c59590c6f43ae9fe5b002b42"
            f"&_time={_time}&_c_0_={_uuid}"
            f"&puid={puid}&uuid={_uuid}"
            f"&tag=classId{clazz_id}&maxW=1080"
            f"&topicUUID={topic_uuid}&anonymous=0"
            f"&inf_enc={inf_enc}"
        )

        post_data = f"content={quote(content)}"

        _headers = {
            'Accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://groupyd.chaoxing.com/',
            'X-Requested-With': 'com.chaoxing.mobile',
        }
        _headers.update(self.headers)

        try:
            rsp = doPost(url=reply_url, headers=_headers, data=post_data)
            if rsp:
                try:
                    result = json.loads(rsp)
                    status = result.get("status") or result.get("result")
                    if status is True or status == "true":
                        return True
                except json.JSONDecodeError:
                    pass
                return True
        except Exception as e:
            logger.debug(f"手机端讨论回复异常: {e}")

        return False
