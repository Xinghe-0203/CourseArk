"""
投票媒体类 - 处理超星投票任务点
通过访问投票页面并提交随机选项完成投票任务
"""
import json
import re
import time

from loguru import logger
from models.media import Media
from core.request_client import get as doGet, post as doPost


class Vote(Media):
    """投票媒体类 - 自动完成超星课程中的投票任务点"""

    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)
        _property = attachment.get("property") or {}
        self.name = _property.get("name", "投票")

    def do_finish(self) -> bool:
        """
        完成投票任务点

        流程：
        1. 先通过 _do_simple_job_finish 标记任务点完成
        2. 访问投票页面获取投票详情
        3. 随机选择选项并提交投票

        Returns:
            bool: 完成成功返回True
        """
        # 先标记任务点完成
        job_result = self._do_simple_job_finish(
            api_path='job/vote',
            referer='https://mooc1-2.chaoxing.com/ananas/modules/vote/index.html',
            task_name='Vote'
        )

        # 尝试提交投票内容
        vote_result = self._submit_vote()
        if vote_result:
            logger.success(f"  投票'{self.name}'完成成功")
        else:
            # 任务点标记成功但投票提交失败，仍视为成功（任务点已完成）
            if job_result:
                logger.info(f"  投票'{self.name}'任务点已标记完成（投票内容未提交）")
            else:
                logger.warning(f"  投票'{self.name}'完成失败")

        return job_result

    def _submit_vote(self) -> bool:
        """
        提交投票选项

        通过访问投票页面获取投票ID和选项，随机选择一个选项提交

        Returns:
            bool: 提交成功返回True
        """
        _property = self.attachment.get("property") or {}
        vote_id = _property.get("voteid") or _property.get("voteId")

        if not vote_id:
            logger.debug("投票任务缺少voteid，跳过投票内容提交")
            return False

        try:
            # 方式1：通过 goQVote 页面访问投票
            vote_page_url = (
                f"https://mobilelearn.chaoxing.com/widget/quickvote/goQVote?"
                f"courseId={self.course_id}&classId={self.defaults.get('clazzId')}"
            )
            _headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': 'https://mooc1.chaoxing.com/',
            }
            _headers.update(self.headers)
            page_rsp = doGet(url=vote_page_url, headers=_headers)

            if page_rsp:
                # 尝试从页面中解析投票信息
                vote_info = self._parse_vote_page(page_rsp, vote_id)
                if vote_info:
                    return self._do_submit_vote(vote_info)

            # 方式2：通过 API 获取投票详情并提交
            return self._submit_vote_via_api(vote_id)

        except Exception as e:
            logger.debug(f"投票提交异常: {e}")
            return False

    def _parse_vote_page(self, page_html: str, vote_id: str) -> dict | None:
        """
        从投票页面HTML中解析投票信息

        Args:
            page_html: 投票页面HTML内容
            vote_id: 投票ID

        Returns:
            解析出的投票信息字典，或None
        """
        try:
            from lxml import etree
            html_tree = etree.HTML(page_html)

            # 尝试从页面JS中提取投票数据
            # 超星投票页面通常包含 questionlist 变量
            scripts = html_tree.xpath("//script/text()")
            for script in scripts:
                if 'questionlist' in script or 'voteList' in script:
                    # 尝试提取投票选项信息
                    options_match = re.findall(r'"optionId"\s*:\s*"(\d+)"', script)
                    if options_match:
                        return {
                            "vote_id": vote_id,
                            "option_ids": options_match
                        }

            # 尝试从HTML表单中提取选项
            option_inputs = html_tree.xpath("//input[@type='radio' or @type='checkbox']/@value")
            if option_inputs:
                return {
                    "vote_id": vote_id,
                    "option_ids": option_inputs
                }

        except Exception as e:
            logger.debug(f"投票页面解析异常: {e}")

        return None

    def _do_submit_vote(self, vote_info: dict) -> bool:
        """
        使用解析到的投票信息提交投票

        Args:
            vote_info: 包含vote_id和option_ids的字典

        Returns:
            bool: 提交成功返回True
        """
        import random

        vote_id = vote_info.get("vote_id", "")
        option_ids = vote_info.get("option_ids", [])

        if not option_ids:
            return False

        # 随机选择一个选项
        selected_option = random.choice(option_ids)

        submit_url = "https://mobilelearn.chaoxing.com/widget/quickvote/doQuestion"
        data = {
            "course_id": self.course_id,
            "class_id": self.defaults.get("clazzId", ""),
            "active_id": vote_id,
            "question_id": vote_id,
            "option": selected_option,
        }

        _headers = {
            'Accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://mobilelearn.chaoxing.com/widget/quickvote/goQVote',
            'X-Requested-With': 'XMLHttpRequest',
        }
        _headers.update(self.headers)

        try:
            rsp = doPost(url=submit_url, headers=_headers, data=data)
            if rsp:
                try:
                    result = json.loads(rsp)
                    status = result.get("status") or result.get("result")
                    if status is True or status == "true":
                        return True
                except json.JSONDecodeError:
                    pass
                # 即使解析失败，只要请求发出就认为可能成功
                return True
        except Exception as e:
            logger.debug(f"投票提交请求异常: {e}")

        return False

    def _submit_vote_via_api(self, vote_id: str) -> bool:
        """
        通过API接口获取投票详情并提交

        Args:
            vote_id: 投票ID

        Returns:
            bool: 提交成功返回True
        """
        import random

        try:
            # 获取投票详情
            detail_url = (
                f"https://mobilelearn.chaoxing.com/widget/apis/vote/getVoteDetail?"
                f"active_id={vote_id}"
            )
            _headers = {
                'Accept': 'application/json',
                'Referer': 'https://mooc1.chaoxing.com/',
            }
            _headers.update(self.headers)

            rsp = doGet(url=detail_url, headers=_headers)
            if not rsp:
                return False

            try:
                detail = json.loads(rsp)
                # 从投票详情中提取选项
                options = []
                vote_data = detail.get("data", detail)
                if isinstance(vote_data, dict):
                    option_list = vote_data.get("options", vote_data.get("optionList", []))
                    for opt in option_list:
                        opt_id = opt.get("optionId") or opt.get("id") or opt.get("option_id")
                        if opt_id:
                            options.append(str(opt_id))

                if not options:
                    # 尝试从题目中提取
                    questions = vote_data.get("questions", [])
                    for q in questions:
                        for opt in q.get("options", []):
                            opt_id = opt.get("optionId") or opt.get("id")
                            if opt_id:
                                options.append(str(opt_id))

                if options:
                    # 随机选择并提交
                    selected = random.choice(options)
                    submit_url = "https://mobilelearn.chaoxing.com/widget/apis/vote/submitVote"
                    submit_data = {
                        "active_id": vote_id,
                        "option_ids": selected,
                    }
                    _submit_headers = {
                        'Accept': 'application/json',
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Referer': 'https://mooc1.chaoxing.com/',
                        'X-Requested-With': 'XMLHttpRequest',
                    }
                    _submit_headers.update(self.headers)

                    rsp = doPost(url=submit_url, headers=_submit_headers, data=submit_data)
                    if rsp:
                        try:
                            result = json.loads(rsp)
                            status = result.get("status") or result.get("result")
                            if status is True or status == "true":
                                return True
                        except json.JSONDecodeError:
                            pass
                        return True

            except json.JSONDecodeError as e:
                logger.debug(f"投票详情解析失败: {e}")

        except Exception as e:
            logger.debug(f"API投票提交异常: {e}")

        return False
