"""CourseExecution 在「发现阶段没有任何任务点」时的收尾语义。

旧行为是无论平台还有多少待完成任务点都静默 succeeded，用户重开程序后
会看到「已完成，不做了」。这里固定三种分支的行为。
"""

import pytest

from core.exceptions import RequestException
from functions.course_execution import CourseExecution


class FakeLog:
    def __init__(self):
        self.lines = []

    def _record(self, message):
        self.lines.append(message)

    def debug(self, message, *a, **k):
        self._record(message)

    info = debug
    warning = debug

    def success(self, message, *a, **k):
        self._record(message)

    def error(self, message, *a, **k):
        self._record(message)


class FakeCourse:
    if_open = True
    course_name = "测试课程"

    def __init__(self, mission_fn=0, mission_all=0):
        self.mission_fn = mission_fn
        self.mission_all = mission_all


class FakeHandler:
    def __init__(self, course):
        self.course = course
        self.course_id = "c1"
        self.class_id = "k1"
        self.cpi = "cpi1"
        self.ui = None
        self.log = FakeLog()
        self.mission_list = []


def _execution(course):
    handler = FakeHandler(course)
    execution = CourseExecution(handler)
    return execution, handler


def test_kinds_filtered_out_returns_quietly():
    execution, handler = _execution(FakeCourse(mission_fn=109, mission_all=125))
    result = execution._finish_without_jobs({"work"})
    assert result["no_pending"] is True
    assert result["chapters"] == 0
    assert any("本次没有需要处理的" in line for line in handler.log.lines)


def test_pending_mission_points_without_jobs_fails_loudly():
    execution, handler = _execution(FakeCourse(mission_fn=109, mission_all=125))
    with pytest.raises(RequestException) as excinfo:
        execution._finish_without_jobs(None)
    message = str(excinfo.value)
    assert "16 个任务点未完成" in message
    assert "109/125" in message


def test_all_mission_points_done_reports_no_pending():
    execution, handler = _execution(FakeCourse(mission_fn=27, mission_all=27))
    result = execution._finish_without_jobs(None)
    assert result["no_pending"] is True
    assert any("已完成" in line and "没有需要处理" in line for line in handler.log.lines)


def test_course_without_mission_points_reports_no_pending():
    execution, handler = _execution(FakeCourse())
    result = execution._finish_without_jobs(None)
    assert result["no_pending"] is True
    assert any("暂无任务点" in line for line in handler.log.lines)


def test_quiz_blocked_reason_prefers_platform_submit_error():
    """平台在提交阶段给的原文（code-2、作业已过期等）必须原样透出。"""
    reason = CourseExecution._quiz_blocked_reason(
        {"questions": 10, "submit_ok": 0, "submit_error": "平台拒绝提交：无效的参数：code-2！"})
    assert reason == "平台拒绝提交：无效的参数：code-2！"


def test_quiz_blocked_reason_explains_unreadable_questions():
    reason = CourseExecution._quiz_blocked_reason(
        {"questions": 10, "submit_ok": 0, "unreadable": 10})
    assert reason == "10 道题的题干或选项未能识别，未提交答案，请在网页端核对"


def test_quiz_blocked_reason_explains_partial_acceptance():
    reason = CourseExecution._quiz_blocked_reason({"questions": 26, "submit_ok": 15})
    assert reason == "平台只接受 15/26 题答案，其余题未能作答或提交失败"


def test_quiz_blocked_reason_explains_empty_page():
    """2026-11 实机：api/work 与详情页都没有题目时，不能只说「测验有未作答题目」。"""
    reason = CourseExecution._quiz_blocked_reason({"questions": 0, "submit_ok": 0})
    assert "平台没有返回题目内容" in reason
