"""
Worker 功能分发测试

用 Mock 替换 User 与媒体处理器，验证六种功能类型分发正确，
以及暂停/停止控制、事件协议与统计口径。全程不访问真实超星。
"""

import json
import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (os.path.join(WEBUI_ROOT, "worker"), WEBUI_ROOT,
             os.path.join(WEBUI_ROOT, "cli_copy")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime  # noqa: E402


class RecordingSink:
    """收集事件，兼容 loguru 风格的日志调用"""

    def __init__(self):
        self.records = []
        self._lock = threading.Lock()

    def emit(self, event, message="", level="info", stage="", payload=None):
        with self._lock:
            self.records.append({
                "event": event, "message": message, "level": level,
                "stage": stage, "payload": payload or {},
            })

    def debug(self, message="", *a, **k):
        self.emit("log", str(message), level="debug")

    def info(self, message="", *a, **k):
        self.emit("log", str(message), level="info")

    def success(self, message="", *a, **k):
        self.emit("log", str(message), level="success")

    def warning(self, message="", *a, **k):
        self.emit("log", str(message), level="warning")

    def error(self, message="", *a, **k):
        self.emit("log", str(message), level="error")

    def exception(self, message="", *a, **k):
        self.emit("log", str(message), level="error")

    def events(self, name):
        return [item for item in self.records if item["event"] == name]

    def messages(self, level=None):
        return [item["message"] for item in self.records
                if level is None or item["level"] == level]


@pytest.fixture()
def runner_module(sandbox):
    import importlib

    import runner
    importlib.reload(runner)
    return runner


@pytest.fixture()
def sink():
    recorded = RecordingSink()
    runtime.set_sink(recorded)
    yield recorded
    runtime.set_sink(None)


def _task(feature, params=None, course_id="c1", class_id="k1"):
    return {
        "task_id": "task-test",
        "feature": feature,
        "username": "13800000000",
        "password": "pwd",
        "account_label": "账号 01",
        "course_id": course_id,
        "class_id": class_id,
        "cpi": "cpi1",
        "course_name": "测试课程",
        "params": params or {},
        "control_path": "",
        "task_dir": ".",
        "log_dir": ".",
        "question_bank_path": os.path.join(WEBUI_ROOT, "data", "question_bank.db"),
    }


class FakeCourse:
    course_name = "测试课程"
    course_id = "c1"
    class_id = "k1"
    cpi = "cpi1"
    if_open = True
    chapter_list = []


class FakeUser:
    headers = {}
    uid = "u1"
    name = "测试用户"


# ============================================================
# 功能分发
# ============================================================

def test_course_all_dispatches_and_reports_stats(runner_module, sink):
    calls = {}

    def fake_do_finish(self):
        if self.ui:
            self.ui.start_section("第一章", 1, 2)
            self.ui.record_course_result(success=5, failed=1, already_done=2)
        calls["course"] = True

    class FakeHomework:
        def __init__(self, *a, **k):
            pass

        def do_finish(self):
            calls["homework"] = True

    with patch("functions.deal_course.DealCourse.do_finish", fake_do_finish), \
         patch("functions.deal_homework.DealHomework", FakeHomework):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("course_all", {
            "course_all": {}, "video": {}, "answer": {},
        }), ui, sink)

    assert calls.get("course") is True
    assert ui.stats["success"] == 5
    assert ui.stats["failed"] == 1
    assert ui.stats["already_done"] == 2
    assert sink.events("chapter_started")
    assert sink.events("task_progress")


def test_course_all_never_touches_independent_homework(runner_module, sink):
    """一键完成课程任务点只处理章节任务点，绝不提交独立作业"""
    calls = {}

    class FakeHomework:
        def __init__(self, *a, **k):
            pass

        def do_finish(self):
            calls["homework"] = True

    with patch("functions.deal_course.DealCourse.do_finish", lambda self: None), \
         patch("functions.deal_homework.DealHomework", FakeHomework):
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("course_all", {
            "course_all": {},
        }), runner_module.TaskStatsUI(sink), sink)

    assert "homework" not in calls, "course_all 不应触发独立作业"


def test_chapter_exam_dispatches(runner_module, sink):
    seen = {}

    class FakeExam:
        def __init__(self, user, course, log, ui=None):
            seen["ui"] = ui

        def do_finish(self):
            seen["called"] = True
            if seen["ui"]:
                seen["ui"].record_exam_result(10, 4, 2, 3, 1, 9, 1)

    with patch("functions.deal_exam.DealExam", FakeExam):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("chapter_exam"), ui, sink)

    assert seen["called"] is True
    assert ui.stats["questions"] == 10
    assert ui.stats["cache_hits"] == 4
    assert ui.stats["tiku_hits"] == 2
    assert ui.stats["llm_calls"] == 3
    assert ui.stats["random_answers"] == 1
    assert ui.stats["submit_ok"] == 9
    assert ui.stats["submit_fail"] == 1


def test_independent_homework_dispatches(runner_module, sink):
    seen = {}

    class FakeHomework:
        def __init__(self, user, course, log, ui=None):
            seen["ui"] = ui

        def do_finish(self):
            seen["called"] = True
            seen["ui"].record_course_result(2, 1, 0)

    with patch("functions.deal_homework.DealHomework", FakeHomework):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("independent_homework"), ui, sink)

    assert seen["called"] is True
    assert ui.stats["success"] == 2 and ui.stats["failed"] == 1


def test_video_feature_collects_and_runs_batch(runner_module, sink):
    captured = {}

    class FakeVideo:
        name = "视频1"

    class FakeDealVideo:
        def __init__(self, user, course, log):
            pass

        def get_videos(self):
            return [FakeVideo(), FakeVideo()]

        def batch_run_videos(self, tasks, workers):
            captured["tasks"] = tasks
            captured["workers"] = workers
            return {"success": 2, "failed": 0, "total": 2}

    with patch("functions.deal_video.DealVideo", FakeDealVideo):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("video", {
            "video": {"mode": "real_time", "max_workers": 12},
        }), ui, sink)

    assert captured["workers"] == 12
    assert all(item["mode"] == "real_time" for item in captured["tasks"])
    assert ui.stats["success"] == 2


def test_video_feature_handles_empty_course(runner_module, sink):
    class FakeDealVideo:
        def __init__(self, *a, **k):
            pass

        def get_videos(self):
            return []

    with patch("functions.deal_video.DealVideo", FakeDealVideo):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("video"), ui, sink)

    assert ui.stats["success"] == 0
    assert any("没有待刷取的视频" in item for item in sink.messages())


def test_learn_count_passes_times_from_snapshot(runner_module, sink):
    captured = {}

    def fake_run(user, course, log, ui=None, times=0, params=None):
        captured["times"] = times
        captured["dwell"] = params["dwell"]
        return 7

    with patch("functions.deal_time.run", fake_run):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("learn_count", {
            "learn_count": {"times": 25, "dwell": 12},
            "advanced": {"request_delay": 2.5},
        }), ui, sink)

    assert captured["times"] == 25
    assert captured["dwell"] == 12
    assert ui.stats["success"] == 7


def test_download_feature_all_chapters(runner_module, sink):
    captured = {}

    class FakeDownload:
        chapter_all = [{"name": "第一章", "knowledge_id": "k1"}]

        def __init__(self, user, course, log):
            pass

        def deal_course(self):
            captured["listed"] = True

        def download_all(self, path):
            captured["path"] = path
            return {"ok": 3, "fail": 1, "skipped": 2}

    with patch("functions.deal_media.MediaDownload", FakeDownload):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("download", {
            "download": {"path": "data/downloads", "scope": "all"},
        }), ui, sink)

    assert captured["listed"] is True
    assert captured["path"].endswith("downloads")
    assert ui.stats["success"] == 3 and ui.stats["failed"] == 1
    assert ui.stats["skipped"] == 2


def test_download_feature_selected_chapters_only(runner_module, sink):
    captured = {"downloaded": []}

    class FakeDownload:
        chapter_all = [
            {"name": "第一章", "knowledge_id": "k1"},
            {"name": "第二章", "knowledge_id": "k2"},
        ]

        def __init__(self, *a, **k):
            pass

        def deal_course(self):
            pass

        def deal_chapter(self, chapter):
            return [{"attachments": [{"type": "document", "objectId": f"obj-{chapter['knowledge_id']}",
                                      "property": {"objectid": f"obj-{chapter['knowledge_id']}"}}]}]

        def _is_downloadable(self, media):
            return True

        def do_download(self, path, media):
            captured["downloaded"].append(media["objectId"])
            return True

        def download_all(self, path):
            raise AssertionError("不应走全量下载分支")

    with patch("functions.deal_media.MediaDownload", FakeDownload):
        ui = runner_module.TaskStatsUI(sink)
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("download", {
            "download": {"path": "data/downloads", "scope": "chapters", "chapters": ["k2"]},
        }), ui, sink)

    assert captured["downloaded"] == ["obj-k2"]


def test_unknown_feature_is_rejected(runner_module, sink):
    with pytest.raises(runner_module.TaskAborted):
        runner_module.run_feature(FakeUser(), FakeCourse(), _task("nonsense"),
                                  runner_module.TaskStatsUI(sink), sink)


# ============================================================
# 课程匹配
# ============================================================

def test_locate_course_requires_matching_class(runner_module):
    class Course:
        def __init__(self, cid, kid):
            self.course_id = cid
            self.class_id = kid

    class User:
        course_list = [Course("c1", "k1"), Course("c1", "k2"), Course("c2", "k1")]

    found = runner_module.locate_course(User(), {"course_id": "c1", "class_id": "k2"})
    assert found.class_id == "k2"
    assert runner_module.locate_course(User(), {"course_id": "c9", "class_id": "k1"}) is None


# ============================================================
# 控制状态
# ============================================================

def _control_file(tmp_path, command="run", version=1):
    path = os.path.join(tmp_path, f"ctl-{command}-{version}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"command": command, "version": version}, f)
    return path


def test_control_sleep_is_interruptible_by_stop(tmp_path, sink):
    path = _control_file(str(tmp_path), "run")
    control = runtime.ControlState(path, poll_interval=0.05, sink=sink)

    def signal_stop():
        time.sleep(0.3)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"command": "stop", "version": 2}, f)

    threading.Thread(target=signal_stop, daemon=True).start()
    started = time.time()
    with pytest.raises(runtime.StopRequested):
        control.sleep(30)
    assert time.time() - started < 5
    assert sink.events("stop_requested")


def test_control_pause_blocks_until_resume(tmp_path, sink):
    path = _control_file(str(tmp_path), "run")
    control = runtime.ControlState(path, poll_interval=0.05, sink=sink)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"command": "pause", "version": 2}, f)

    def resume_later():
        time.sleep(0.4)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"command": "run", "version": 3}, f)

    threading.Thread(target=resume_later, daemon=True).start()
    started = time.time()
    control.check()  # 应阻塞至 resume
    elapsed = time.time() - started
    assert 0.2 < elapsed < 5
    assert sink.events("paused") and sink.events("resumed")


def test_control_stop_inside_pause_raises(tmp_path, sink):
    path = _control_file(str(tmp_path), "pause")
    control = runtime.ControlState(path, poll_interval=0.05, sink=sink)

    def stop_later():
        time.sleep(0.3)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"command": "stop", "version": 5}, f)

    threading.Thread(target=stop_later, daemon=True).start()
    with pytest.raises(runtime.StopRequested):
        control.sleep(30)
    assert sink.events("paused")


def test_runtime_checkpoint_is_noop_without_control():
    runtime.set_control(None)
    runtime.checkpoint()          # 不应抛错
    runtime.sleep(0)              # 不应阻塞


def test_sink_emits_json_lines_protocol(tmp_path):
    import io

    buffer = io.StringIO()
    sink = runtime.EventSink(task_id="t-1", stream=buffer)
    sink.emit("task_progress", "进度", level="info", stage="video",
              payload={"current": 1})
    record = json.loads(buffer.getvalue().strip())
    assert record["event"] == "task_progress"
    assert record["task_id"] == "t-1"
    assert record["payload"]["current"] == 1
    assert "timestamp" in record


def test_control_file_missing_is_treated_as_run(tmp_path, sink):
    control = runtime.ControlState(os.path.join(str(tmp_path), "absent.json"), sink=sink)
    control.check()
    assert control.command == "run"
