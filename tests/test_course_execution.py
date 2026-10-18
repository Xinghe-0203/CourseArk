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
