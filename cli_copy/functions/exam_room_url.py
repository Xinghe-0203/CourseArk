"""考试「答题页 URL」直连作答（B 方案）。

用户在浏览器里进入考试后，把地址栏的 ``reVersionTestStartNew?...&enc=...`` 地址
粘贴到页面；程序用同一份登录态打开该地址，逐题 AI 作答、点「下一题」、最后
交卷。程序不绕过任何平台验证：地址里的 ``enc`` 由浏览器侧的真人操作产生。

与 `deal_exam_room.DealExamRoom` 的分工：
- DealExamRoom：从考试列表进入（需要 start 接口 + examcheck 安全验证）
- ExamRoomByUrl：URL 直达（带 enc 的答题页本身即可作答），复用 DealExam 的
  LLM/答题缓存/逐题上报链路

安全约定：
- 只在任务运行中调用（worker/runner.py 分发 feature=exam 且带 URL 时）
- 任何平台错误都显式中止并说明原因，不静默成功、不伪造答案
- 只有整卷交卷被服务器接受后才写入答题缓存
"""

import time

from loguru import logger

from core import runtime
from core.exam_answer_page import (
    ExamUrlError, build_next_url, build_submit_data, normalize_answer,
    parse_answer_page, parse_exam_url, parse_submit_response, question_from_page,
    submit_url,
)
from core.request_client import get as doGet, post as doPost
from functions.deal_exam import DealExam
from functions.deal_exam_room import exam_unit

_REFERER = "https://mooc1.chaoxing.com/exam/test"
_SUBMIT_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://mooc1.chaoxing.com",
}
_MAX_QUESTIONS = 200  # 防御异常页面导致死循环


class ExamRoomByUrl:
    """按用户粘贴的答题页地址完成一场 PC 端考试。"""

    def __init__(self, user, course, log, ui=None):
        self.user = user
        self.course = course
        self.log = log
        self.ui = ui
        self.course_name = course.course_name if course else ""
        self.exam = DealExam(user, course, log, ui)
        self.exam.active_kind = "考试"
        self.entry = {}

    # ------------------------------------------------------------------ 入口
    def do_finish(self, url: str):
        """读取答题页 -> 逐题作答 -> 交卷。失败抛 ExamUrlError（可读原因）。"""
        entry = parse_exam_url(url)
        if self.course and str(self.course.course_id) != entry["course_id"]:
            raise ExamUrlError(
                f"粘贴的考试属于课程 {entry['course_id']}，与任务课程"
                f"（{self.course.course_id}）不一致；请选择对应课程后重试")
        self.entry = entry
        if str(getattr(self.exam, "answer_mode", "ai") or "ai") == "manual":
            raise ExamUrlError("答题页直连需要 AI 作答模式：请到设置里把作答模式改为「AI」后重试")
        unit = exam_unit({"exam_id": entry["exam_id"]})
        self.exam.active_unit_id = unit

        runtime.emit("work_plan", "考试答题页已读取", stage="exam", payload={
            "units": [{"id": unit, "name": "考试", "kind": "exam"}], "sealed": True})

        html = self._fetch(entry["url"])
        page = parse_answer_page(html)
        title = page["media"] or "考试"
        self.exam.active_media_name = title
        self.log.info(f"[考试] {title}（题量 {page['total'] or '未知'}，剩余约 "
                      f"{self._minutes(page['remain'])} 分钟）")

        if page["finished"]:
            self.log.info("该场考试已交卷完成，无需重复作答")
            runtime.emit("work_result", "该场考试已交卷完成", stage="exam", payload={
                "id": unit, "name": title, "kind": "exam", "status": "succeeded"})
            runtime.emit("task_progress", "考试统计", stage="exam", payload={
                "course_name": self.course_name, "success": 1, "failed": 0, "total": 1})
            if self.ui:
                self.ui.record_course_result(1, 0, 0)
            return

        if page["blocked"] or not page["fields"]:
            hint = page["blocked"] or "页面里没有答题表单"
            raise ExamUrlError(
                f"答题页不可用（{hint}）。请在浏览器里重新进入考试，确认能看到题目后"
                "再复制地址栏 URL")

        runtime.emit("work_started", "开始作答", stage="exam", payload={
            "id": unit, "name": title, "kind": "exam", "status": "running"})
        stats = self._answer_all(page, title)
        self._report(unit, title, stats)

    # ------------------------------------------------------------------ 作答
    def _answer_all(self, page: dict, title: str) -> dict:
        total = page["total"] or 1
        stats = {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                 "random_answers": 0, "submit_ok": 0, "submit_fail": 0}
        answered = []
        submitted = False
        seen_qids = set()

        for _ in range(_MAX_QUESTIONS):
            runtime.checkpoint()
            qid = page["qid"]
            if qid and qid in seen_qids:
                raise ExamUrlError("答题页没有前进（下一题仍是同一题），已中止；"
                                   "请在浏览器里刷新考试后重新复制地址")
            if qid:
                seen_qids.add(qid)
            total = page["total"] or total or 1
            index = min(page["index"] + 1, total)
            question = question_from_page(page)
            answer = self.exam._answer_question(question, index, total)
            value = normalize_answer(page["type_code"], (answer or {}).get("answer", ""))
            if not value:
                raise ExamUrlError(
                    f"第 {index} 题没有拿到可用答案，已中止（已保存的题不受影响）；"
                    "可在任务详情查看 AI 作答失败原因后重试")
            keys = [str(item.get("key", "")) for item in page["options"] or []]
            if str(page["type_code"]) in ("0", "1") and keys:
                letters = [c for c in value if c.isalpha()]
                bad = [c for c in letters if c not in keys]
                if not letters or bad:
                    raise ExamUrlError(
                        f"第 {index} 题答案「{value}」不在选项（{'/'.join(keys)}）内，"
                        "已中止，避免提交无效答案")
            source = (answer or {}).get("source", "")
            if source == "cache":
                stats["cache_hits"] += 1
            elif source == "llm":
                stats["llm_calls"] += 1
            elif source == "random":
                stats["random_answers"] += 1
            is_last = page["index"] >= total - 1

            self.exam._emit_answer_result(question, answer, index, total, title)
            runtime.emit("work_progress", "正在作答", stage="exam", payload={
                "id": self.exam.active_unit_id, "name": title,
                "current": index, "total": total})
            runtime.emit("exam_stats", "答题进度", stage="exam", payload={
                "media": title, "questions": index, "submit_ok": stats["submit_ok"],
                "submit_fail": stats["submit_fail"]})

            result = self._submit(page, value, temp_save=True)
            if result["status"] in ("submitted", "forceSubmitted"):
                self.log.info("服务器显示该场考试已交卷，停止作答")
                submitted = True
                stats["submit_ok"] += 1
                stats["questions"] += 1
                if value:
                    answered.append({**question, **answer})
                break
            if not result["ok"]:
                raise ExamUrlError(
                    f"第 {index} 题保存被服务器拒绝：{result['msg'] or result['status']}"
                    "（考试计时不会重置，请在浏览器里核对该考试状态）")

            stats["questions"] += 1
            stats["submit_ok"] += 1
            if value:
                answered.append({**question, **answer})
            self.log.info(f"  第 {index}/{total} 题已保存：{value or '（空）'}")

            if is_last:
                final = self._submit(page, value, temp_save=False)
                if not final["ok"]:
                    raise ExamUrlError(f"交卷被服务器拒绝：{final['msg'] or final['status']}")
                self.log.success(f"考试「{title}」已交卷（共 {index} 题）")
                submitted = True
                break

            html = self._fetch(build_next_url(self.entry, result["data"], page["index"] + 1))
            page = parse_answer_page(html)
            if page["finished"]:
                self.log.success(f"考试「{title}」已交卷")
                submitted = True
                break
            if page["blocked"]:
                raise ExamUrlError(f"考试被平台中止（{page['blocked']}），"
                                   "请回到浏览器确认考试状态")
            if not page["qid"]:
                raise ExamUrlError("读取下一题失败：请确认考试仍在进行中，"
                                   "并重新复制答题页地址")
            time.sleep(1.0)

        if not submitted:
            self.exam._save_submitted_answers(answered)
            raise ExamUrlError("题量超过安全上限，已中止（答卷已按题保存）")
        self.exam._save_submitted_answers(answered)
        return stats

    # ------------------------------------------------------------------ 网络
    def _fetch(self, url: str) -> str:
        try:
            return doGet(url=url, headers={**(self.user.headers or {}), "Referer": _REFERER})
        except Exception as exc:
            raise ExamUrlError(f"打开答题页失败：{exc}") from exc

    def _submit(self, page: dict, answer: str, temp_save: bool) -> dict:
        target = submit_url(page["form_action"], cpi=self.entry.get("cpi", ""),
                            temp_save=temp_save)
        headers = {**(self.user.headers or {}), "Referer": self.entry["url"], **_SUBMIT_HEADERS}
        try:
            body = doPost(url=target, headers=headers,
                          data=build_submit_data(page, answer, temp_save))
        except Exception as exc:
            raise ExamUrlError(f"提交第 {page['index'] + 1} 题失败：{exc}") from exc
        return parse_submit_response(body)

    # ------------------------------------------------------------------ 汇总
    def _report(self, unit: str, title: str, stats: dict):
        cache = stats.get("cache_hits", 0)
        ai = stats.get("llm_calls", 0)
        self.log.success(
            f"[考试汇总] {title}：共 {stats.get('questions', 0)} 题 | 缓存={cache}"
            f" | AI={ai} | 已交卷")
        runtime.emit("work_result", "考试已交卷", stage="exam", payload={
            "id": unit, "name": title, "kind": "exam", "status": "succeeded"})
        runtime.emit("task_progress", "考试统计", stage="exam", payload={
            "course_name": self.course_name, "success": 1, "failed": 0, "total": 1})
        if self.ui:
            self.ui.record_exam_result(
                stats.get("questions", 0), cache, 0, ai,
                stats.get("random_answers", 0), stats.get("submit_ok", 0),
                stats.get("submit_fail", 0))
            self.ui.record_course_result(1, 0, 0)

    @staticmethod
    def _minutes(remain: str) -> int:
        try:
            return max(0, int(float(remain or 0)) // 60)
        except (TypeError, ValueError):
            return 0


def run(user, course, log, ui=None, url=""):
    """兼容 runner 的函数式调用。"""
    return ExamRoomByUrl(user, course, log, ui).do_finish(url)
