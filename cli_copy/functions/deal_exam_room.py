"""
AutoChaoxingCLI - 课程独立考试处理器

与「独立作业」同为独立入口，但协议不同：
1. 考试列表来自 `Course.get_exam_list()`（/exam/test 页面里的 goTest 参数）
2. 进入考试需要先访问 reVersionTestStartNew（开始计时，不可撤销）
3. 部分考试是「一页一题」的逐题模式，无法整卷提交，必须识别后安全中止

安全约定：
- 只在任务真正运行时调用（由 worker/runner.py 分发 feature=exam）
- 进入考试前记录限时与截止时间，便于用户判断是否仍在考试窗口内
- 任何异常都不提交半份答卷
"""

import json

from loguru import logger

from core import exam_form, runtime
from core.request_client import get as doGet, post as doPost
from functions.deal_exam import DealExam

# 反爬/权限异常的特征文案
_BLOCKED_WORDS = ("无权限访问", "您长时间没有操作", "请重新登录", "登录超时",
                  "验证码", "antispider", "captcha", "考试已结束", "不在考试时间",
                  "该考试已过期", "暂无权限")

_SUCCESS_WORDS = ("提交成功", "保存成功", "success", "\"status\":true", "\"status\": true",
                  "\"status\":200", "操作成功")
_FAIL_WORDS = ("失败", "错误", "error", "异常", "不能为空", "未到考试时间", "已结束")


def exam_unit(exam: dict) -> str:
    return "exam:" + str(exam.get("exam_id") or exam.get("id") or exam.get("title") or "")


class DealExamRoom:
    """独立考试处理器"""

    def __init__(self, user, course, log, ui=None):
        self.user = user
        self.course = course
        self.log = log
        self.ui = ui
        self.course_name = course.course_name if course else ""
        self.course_id = str(course.course_id) if course else ""
        self.class_id = str(course.class_id) if course else ""
        self.cpi = str(course.cpi) if course else ""
        self.exam = DealExam(user, course, log, ui)
        self.exam.active_kind = "考试"

    # ------------------------------------------------------------------ 入口
    def do_finish(self, selection: dict | None = None):
        """列出考试 -> 按选择进入 -> AI 作答 -> 提交"""
        if not self.course.if_open:
            self.log.warning("本课程已结课或锁定，将自动跳过")
            if self.ui:
                self.ui.record_course_result(0, 1, 0)
            return

        self.log.info(f"正在获取'{self.course_name}'的考试列表...")
        try:
            exams = self.course.get_exam_list()
        except Exception as e:
            self.log.error(f"获取考试列表失败: {e}")
            raise

        if not exams:
            self.log.info(f"'{self.course_name}' 没有可读取的考试（或全部已完成/已过期）")
            return

        pending = [item for item in exams if item.get("valid", True)]
        skipped_expired = len(exams) - len(pending)
        self.log.info(f"考试筛选：共 {len(exams)} 场，可作答 {len(pending)} 场"
                      + (f"，已完成/已过期 {skipped_expired} 场" if skipped_expired else ""))
        self._show_exams(exams, pending)

        pending = self._apply_selection(pending, selection)

        runtime.emit("work_plan", "考试范围已读取", stage="exam", payload={
            "units": [{"id": exam_unit(item), "name": item.get("title", "考试"), "kind": "exam"}
                      for item in pending],
            "sealed": True,
        })

        if not pending:
            if skipped_expired:
                self.log.info(f"没有可作答的考试（{skipped_expired} 场已完成或已过期）")
            elif str((selection or {}).get("mode") or "").lower() == "selected":
                self.log.info("没有可作答的考试（所勾选的考试不在可作答范围内）")
            else:
                self.log.info("没有可作答的考试")
            return

        total_q = total_cache = total_llm = total_random = 0
        submit_ok_total = submit_fail_total = 0
        success = failed = 0

        for i, item in enumerate(pending, 1):
            runtime.checkpoint()
            unit = exam_unit(item)
            self.exam.active_unit_id = unit
            self.exam.active_media_name = item.get("title") or "考试"
            runtime.emit("work_started", "开始处理考试", stage="exam", payload={
                "id": unit, "name": item.get("title"), "kind": "exam", "status": "running"})
            self.log.info(f"[考试] [{i}/{len(pending)}] {item.get('title')}")

            try:
                stats = self.answer_exam(item)
            except Exception as e:
                self.log.error(f"  考试'{item.get('title')}'处理异常: {e}")
                failed += 1
                runtime.emit("work_result", f"考试处理失败: {e}", level="warning", stage="exam",
                             payload={"id": unit, "name": item.get("title"),
                                      "kind": "exam", "status": "failed"})
                continue

            if not stats:
                failed += 1
                runtime.emit("work_result", "未能读取考试题目或提交结果", level="warning", stage="exam",
                             payload={"id": unit, "name": item.get("title"),
                                      "kind": "exam", "status": "failed"})
                continue

            total_q += stats.get("questions", 0)
            total_cache += stats.get("cache_hits", 0)
            total_llm += stats.get("llm_calls", 0)
            total_random += stats.get("random_answers", 0)
            submit_ok_total += stats.get("submit_ok", 0)
            submit_fail_total += stats.get("submit_fail", 0)

            ok = (stats.get("questions", 0) > 0
                  and stats.get("submit_ok") == stats.get("questions")
                  and not stats.get("submit_fail"))
            runtime.emit("work_result", "考试提交已接受" if ok else "考试仍有未完成内容",
                         stage="exam", level="info" if ok else "warning",
                         payload={"id": unit, "name": item.get("title"), "kind": "exam",
                                  "status": "succeeded" if ok else "blocked"})
            if ok:
                success += 1
            else:
                failed += 1

        if total_q > 0:
            parts = [f"缓存={total_cache}", f"AI={total_llm}"]
            if total_random:
                parts.append(f"随机={total_random}")
            self.log.success(
                f"[考试汇总] 共{total_q}题 | {' | '.join(parts)} | 提交成功={submit_ok_total}"
                + (f" | 失败={submit_fail_total}" if submit_fail_total else ""))

        self.log.info(f"'{self.course_name}'考试处理完毕: 成功{success}场 | 失败{failed}场")
        runtime.emit("task_progress", "考试统计", stage="exam", payload={
            "course_name": self.course_name, "success": success, "failed": failed,
            "total": len(pending),
        })
        if self.ui:
            self.ui.record_exam_result(total_q, total_cache, 0, total_llm, total_random,
                                       submit_ok_total, submit_fail_total)
            self.ui.record_course_result(success, failed, 0)

    # ------------------------------------------------------------------ 单场考试
    def answer_exam(self, item: dict) -> dict | None:
        """进入一场考试、作答并提交"""
        empty = {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
                 "random_answers": 0, "submit_ok": 0, "submit_fail": 0}
        title = item.get("title") or "考试"
        paper_id = str(item.get("paper_id") or "")
        relation_id = str(item.get("relation_id") or "")
        if not paper_id:
            self.log.warning(f"  考试'{title}'缺少试卷ID，无法进入")
            return empty

        enc_params = {}
        try:
            enc_params = self.course._get_work_enc_params() or {}
        except Exception:
            enc_params = {}
        openc = str(item.get("openc") or enc_params.get("openc") or "")
        course_enc = str(enc_params.get("examEnc") or enc_params.get("enc") or "")
        exam_enc = str(item.get("enc") or course_enc)

        start_url = self.course.exam_start_url(
            self.course_id, self.class_id, self.cpi, openc, course_enc,
            paper_id, relation_id, exam_enc=exam_enc,
            is_retest=bool(item.get("is_retest")),
        )
        limit_time = item.get("limit_time")
        if limit_time:
            self.log.info(f"  考试限时 {limit_time} 分钟，截止 {item.get('end_time') or '未知'}；"
                          f"进入后开始计时")

        self.log.info("  正在进入考试...")
        try:
            html = doGet(start_url, headers={"Referer": "https://mooc1.chaoxing.com/exam/test"})
        except Exception as e:
            self.log.error(f"  进入考试失败: {e}")
            return empty

        if not html:
            self.log.error("  进入考试后未返回页面内容")
            return empty
        blocked = self._blocked_reason(html)
        if blocked:
            self.log.error(f"  无法进入考试: {blocked}")
            return empty

        form = exam_form.parse_form(html)
        questions = exam_form.parse_questions(html)
        diagnostics = exam_form.describe_diagnostics(html, questions, form)
        self.log.debug(f"  考试页诊断: {json.dumps(diagnostics, ensure_ascii=False)}")

        if not questions:
            self.log.error("  未能从考试页面解析出题目；若浏览器里需要先点“开始考试”，"
                           "请先在网页端进入该考试后再试")
            return empty

        if exam_form.is_single_question_mode(html, len(questions)):
            self.log.error("  该考试为「一页一题」模式，当前版本不支持逐题提交，"
                           "已安全中止（不会提交任何答案）")
            return empty

        self.log.info(f"  已读取 {len(questions)} 道题"
                      + (f"（共 {diagnostics['total_questions']} 题）"
                         if diagnostics.get("total_questions") else ""))

        # 复用作业答题链路（AI + 缓存 + 兜底），但不走作业提交
        answers = []
        cache_hits = llm_calls = random_answers = 0
        for idx, question in enumerate(questions, 1):
            runtime.checkpoint()
            ans = self.exam._answer_question(question, idx, len(questions))
            if ans is not None:
                answers.append(ans)
                source = ans.get("source", "")
                if source == "cache":
                    cache_hits += 1
                elif source == "llm":
                    llm_calls += 1
                elif source == "random":
                    random_answers += 1
            self.exam._emit_answer_result(question, ans, idx, len(questions), title)
            runtime.emit("work_progress", "正在作答", stage="exam", payload={
                "id": exam_unit(item), "name": title, "current": idx, "total": len(questions)})
            runtime.emit("exam_stats", "答题进度", stage="exam", payload={
                "media": title, "current": idx, "total": len(questions),
                "cache_hits": cache_hits, "tiku_hits": 0,
                "llm_calls": llm_calls, "random_answers": random_answers,
            })

        stats = {"questions": len(questions), "cache_hits": cache_hits, "tiku_hits": 0,
                 "llm_calls": llm_calls, "random_answers": random_answers,
                 "submit_ok": 0, "submit_fail": 0}
        if not answers:
            self.log.warning("  没有生成任何答案，未提交")
            stats["submit_fail"] = len(questions)
            return stats

        if not self.exam.auto_submit:
            self.log.info("  auto_submit=false，仅生成答案，未提交")
            return stats

        ok, fail = self._submit_exam(item, html, form, answers)
        stats["submit_ok"] = ok
        stats["submit_fail"] = fail + (len(questions) - len(answers))
        if ok and not stats["submit_fail"]:
            self.log.success(f"  考试'{title}'提交被服务器接受")
        elif ok:
            self.log.warning(f"  考试'{title}'部分答案未提交：成功{ok}，失败{stats['submit_fail']}")
        else:
            self.log.error(f"  考试'{title}'提交失败")
        runtime.emit("exam_stats", "提交结果", stage="exam", payload={
            "media": title, "questions": len(questions),
            "submit_ok": ok, "submit_fail": stats["submit_fail"]})
        return stats

    # ------------------------------------------------------------------ 提交
    def _submit_exam(self, item: dict, html: str, form: dict, answers: list) -> tuple[int, int]:
        """按页面表单或探测到的接口提交考试答案；返回 (成功数, 失败数)"""
        from core import work_form

        total = len(answers)
        runtime.sleep(self.exam.submit_delay)

        endpoint = ""
        body: dict = {}
        source = ""
        if form.get("found") and form.get("controls") is not None:
            endpoint = form.get("action") or ""
            if endpoint:
                try:
                    _, body = work_form.build_submission(form, answers)
                except Exception as e:
                    self.log.warning(f"  按考试页面表单构造答案失败: {e}")
                    body = {}
                body = {**exam_form.parse_hidden_controls(html), **body}
                source = "考试页面表单"
        if not endpoint:
            candidates = exam_form.detect_submit_endpoints(html)
            if not candidates:
                self.log.error("  未找到可用的考试提交入口（页面没有提交表单，也没探测到提交接口）")
                return (0, total)
            endpoint = candidates[0]["url"]
            body = dict(exam_form.parse_hidden_controls(html))
            for ans in answers:
                qid = str(ans.get("question_id") or "")
                if not qid:
                    continue
                body[f"answer{qid}"] = str(ans.get("answer") or "")
                if ans.get("answer_type"):
                    body[f"answertype{qid}"] = str(ans["answer_type"])
            source = f"探测接口（{candidates[0]['token']}）"

        self.log.info(f"  正在提交考试答案（{source}）...")
        try:
            response = doPost(endpoint, headers={
                "Referer": "https://mooc1.chaoxing.com/exam/test",
                "X-Requested-With": "XMLHttpRequest",
            }, data=body)
        except Exception as e:
            self.log.error(f"  提交考试答案失败: {e}")
            return (0, total)

        if self._is_success(response):
            return (total, 0)
        detail = self._response_message(response)
        self.log.error(f"  提交失败! {detail}")
        return (0, total)

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _blocked_reason(html: str) -> str:
        for word in _BLOCKED_WORDS:
            if word in html:
                return word
        if len(html) < 600 and "考试" not in html:
            return "页面内容异常（可能无权限或登录已失效）"
        return ""

    @staticmethod
    def _is_success(response: str) -> bool:
        text = (response or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if any(word in lowered for word in _SUCCESS_WORDS):
            return True
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            status = data.get("status")
            if status in (True, 1, "true", "1", 200, "200"):
                return True
            if isinstance(status, str) and status.lower() in ("success", "ok"):
                return True
        return False

    @staticmethod
    def _response_message(response: str) -> str:
        text = (response or "").strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            for key in ("msg", "message", "errorMsg", "error"):
                if data.get(key):
                    return str(data[key])[:120]
        if "<" in text:
            return "服务器返回 HTML 页面（可能触发验证或提交被拒绝）"
        return text[:120] or "服务器未返回内容"

    def _apply_selection(self, pending: list, selection: dict | None) -> list:
        selection = selection or {}
        if str(selection.get("mode") or "all").lower() != "selected":
            return pending
        ids = {str(item) for item in (selection.get("ids") or []) if str(item)}
        if not ids:
            self.log.warning("已选择“指定考试”但未勾选任何考试，本次不处理")
            return []
        selected = [item for item in pending if exam_unit(item) in ids or str(item.get("exam_id")) in ids]
        self.log.info(f"按选择处理 {len(selected)} 场考试（共勾选 {len(ids)} 场）")
        return selected

    def _show_exams(self, all_exams: list, picked: list):
        picked_ids = {exam_unit(item) for item in picked}
        for i, item in enumerate(all_exams, 1):
            mark = "*" if exam_unit(item) in picked_ids else " "
            limit = item.get("limit_time")
            extra = f" | 限时{limit}分钟" if limit else ""
            window = ""
            if item.get("start_time") or item.get("end_time"):
                window = f" | {item.get('start_time') or '?'} ~ {item.get('end_time') or '?'}"
            self.log.info(f"  {mark} {i}. {item.get('title')}  [{item.get('status') or '未知'}"
                          f"{extra}{window}]")


def run(user, course, log, ui=None, selection=None):
    """考试功能入口（供 worker 调用）"""
    DealExamRoom(user, course, log, ui).do_finish(selection=selection)
