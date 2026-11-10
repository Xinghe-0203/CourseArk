"""直播任务点：心跳必须带 Referer，未开播的直播按「跳过」处理而不是失败。

2026-11 实机日志：saveTimePc 全部返回 @fail，10 场直播被记成 failed，
整门课因此判失败。根因是 Media 基类只保留 User-Agent，直播心跳缺 Referer。
"""

from unittest.mock import Mock

import pytest

from media.live import Live


def _live(**property_extra):
    attachment = {
        "jobid": "live-1",
        "property": {
            "title": "7.2 第二次直播课",
            "streamName": "NEWLIVEabc",
            "vdoid": "vdoid123",
            **property_extra,
        },
    }
    return Live(attachment, {"User-Agent": "ua"}, {"userid": "413263029"}, "214685336")


def test_heartbeat_sends_referer_and_reports_success(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers or {}
        return "@success"

    monkeypatch.setattr("media.live.doGet", fake_get)
    live = _live()

    assert live.do_finish() is True
    assert live.last_error == ""
    assert "zhibo.chaoxing.com/saveTimePc" in captured["url"]
    assert "streamName=NEWLIVEabc" in captured["url"]
    # 缺 Referer 时平台直接回 @fail，这一条是本次修复的核心
    assert captured["headers"]["Referer"].startswith("https://mooc1.chaoxing.com/ananas/modules/live/index.html")
    assert captured["headers"]["User-Agent"] == "ua"


def test_heartbeat_rejection_keeps_platform_answer(monkeypatch):
    monkeypatch.setattr("media.live.doGet", lambda url, headers=None, **kwargs: "@fail")
    live = _live()

    assert live.do_finish() is False
    assert "平台拒绝直播心跳" in live.last_error
    assert "@fail" in live.last_error


def test_heartbeat_empty_response_explains_login(monkeypatch):
    monkeypatch.setattr("media.live.doGet", lambda url, headers=None, **kwargs: "")
    live = _live()

    assert live.do_finish() is False
    assert "登录状态" in live.last_error


def test_missing_stream_name_is_explained(monkeypatch):
    live = Live({"jobid": "live-1", "property": {"title": "无流"}}, {"User-Agent": "ua"}, {}, "c1")
    monkeypatch.setattr("media.live.doGet", lambda *a, **k: "@success")

    assert live.do_finish() is False
    assert "streamName" in live.last_error


class FakeLog:
    def __init__(self):
        self.lines = []

    def _record(self, message, *a, **k):
        self.lines.append(str(message))

    debug = info = warning = success = error = _record


def test_live_without_duration_is_skipped_not_failed(monkeypatch):
    from functions.deal_video import DealVideo

    live = _live()
    live.get_status = Mock(return_value={"temp": {"data": {"duration": 0}}})
    live.do_finish = Mock(return_value=True)

    assert DealVideo.run_live(live, Mock(), FakeLog()) is False
    assert live.skipped is True
    assert "尚未开播" in live.last_error
    live.do_finish.assert_not_called()


def test_batch_marks_unstarted_live_as_skipped(monkeypatch):
    from functions.deal_video import DealVideo

    events = []
    monkeypatch.setattr("core.runtime.emit", lambda event, *args, **kwargs: events.append((event, args, kwargs)))
    live = _live()
    live.name = "7.3 第三次直播课"
    live.get_status = Mock(return_value={"temp": {"data": {"duration": None}}})

    result = DealVideo(Mock(), Mock(), FakeLog()).batch_run_videos([{"video": live, "mode": "live"}], 1)

    assert result["failed"] == 0
    payload = [k["payload"] for e, a, k in events if e == "work_result"][0]
    assert payload["status"] == "skipped"
