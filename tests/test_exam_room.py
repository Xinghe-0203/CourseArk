"""DealExamRoom 平台安全验证（examcheck）处理的单元测试。

只校验「验证通过后如何补齐入口地址」与「未通过时保持中止」，不发真实请求。
"""

import json

from functions import deal_exam_room as room_module


class FakeLog:
    def __init__(self):
        self.lines = []

    def _record(self, message, *a, **k):
        self.lines.append(str(message))

    debug = _record
    info = _record
    warning = _record
    error = _record

    def success(self, message, *a, **k):
        self._record(message)


def _room():
    room = object.__new__(room_module.DealExamRoom)
    room.log = FakeLog()
    room.course_id = "244694077"
    room.class_id = "151670988"
    room.cpi = "518380181"
    return room


NOTES = {
    "found": True,
    "exam_id": "11021171",
    "answer_id": "171477623",
    "start_url": ("https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?"
                  "courseId=244694077&tId=11021171&id=171477623&enc=?&newMooc=true"),
}


def _patch_get(monkeypatch, payload):
    def fake_get(url, headers=None, **kwargs):
        assert "exam/test/examcheck" in url
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(room_module, "doGet", fake_get)


def test_verified_examcheck_fills_enc(monkeypatch):
    _patch_get(monkeypatch, {"status": True, "enc": "abc123"})
    url = _room()._try_examcheck(dict(NOTES))
    assert url == NOTES["start_url"].replace("enc=?", "enc=abc123")


def test_rejected_examcheck_keeps_abort(monkeypatch):
    _patch_get(monkeypatch, {"status": False, "msg": "安全验证不通过，请重新验证",
                             "type": "captchaVerify"})
    room = _room()
    assert room._try_examcheck(dict(NOTES)) == ""
    assert any("安全验证仍未通过" in line for line in room.log.lines)


def test_missing_enc_is_treated_as_not_passed(monkeypatch):
    _patch_get(monkeypatch, {"status": True})
    assert _room()._try_examcheck(dict(NOTES)) == ""


def test_request_error_is_safe(monkeypatch):
    def boom(url, headers=None, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr(room_module, "doGet", boom)
    room = _room()
    assert room._try_examcheck(dict(NOTES)) == ""
    assert any("考试校验请求失败" in line for line in room.log.lines)


def test_without_start_url_skips_request(monkeypatch):
    def fail(url, headers=None, **kwargs):
        raise AssertionError("不应发请求")
    monkeypatch.setattr(room_module, "doGet", fail)
    notes = dict(NOTES)
    notes["start_url"] = ""
    assert _room()._try_examcheck(notes) == ""
