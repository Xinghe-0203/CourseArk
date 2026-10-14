"""
AutoChaoxingCLI - 课程独立作业处理器

重要区分：
- 章节测验（章节任务点内的作业）：作为章节任务点存在，完成计入任务点进度，
  由 DealCourse / DealExam.answer_work() 处理。
- 独立作业（本模块）：位于课程"作业"标签页，有独立截止时间与提交入口，
  不属于章节任务点，需通过 workId + workAnswerId 单独作答提交。

本模块负责：获取课程独立作业列表 -> 展示 -> 逐个自动答题提交。
"""

from functions.deal_exam import DealExam


class DealHomework:
    """
    独立作业处理器

    Attributes:
        user: 用户对象
        course: 课程对象
        log: 日志对象
        ui: TUI界面（可选）
    """

    def __init__(self, user, course, log, ui=None):
        self.user = user
        self.course = course
        self.log = log
        self.ui = ui
        self.course_name = course.course_name

    def do_finish(self, only_pending: bool = True):
        """
        执行独立作业的获取与自动答题

        Args:
            only_pending: 仅处理未完成/未过期的作业
        """
        if not self.course.if_open:
            self.log.warning("本课程已结课或锁定，将自动跳过")
            if self.ui:
                self.ui.record_course_result(0, 1, 0)
            return

        self.log.info(f"正在获取'{self.course_name}'的独立作业列表...")
        try:
            works = self.course.get_work_list()
        except Exception as e:
            self.log.error(f"获取独立作业列表失败: {e}")
            raise

        if not works:
            self.log.info(f"'{self.course_name}' 没有独立作业")
            return

        # 状态过滤：已完成/已过期的作业按需跳过
        picked = []
        skipped_done = 0
        skipped_expired = 0
        for w in works:
            status = w.get("status", "")
            if only_pending and ("已完成" in status or "已提交" in status or "已批阅" in status):
                skipped_done += 1
                continue
            if only_pending and not w.get("valid", True):
                skipped_expired += 1
                self.log.info(f"  作业'{w.get('title')}'已过期，跳过")
                continue
            picked.append(w)
        self.log.info(f"独立作业筛选：共 {len(works)} 个，已完成 {skipped_done} 个，"
                      f"已过期 {skipped_expired} 个，待处理 {len(picked)} 个")

        self._show_works(works, picked)
        from core import runtime
        unit = lambda work: 'homework:' + str(work.get('work_id') or work.get('workId') or work.get('title'))
        runtime.emit('work_plan', '作业范围已读取', stage='homework', payload={
            'units': [{'id': unit(w), 'name': w.get('title', '独立作业'), 'kind': 'homework'} for w in picked], 'sealed': True})
        if not picked:
            # 明确说明为什么没有待处理项，避免只看到“0 个待处理”却不知原因
            reasons = []
            if skipped_done:
                reasons.append(f"{skipped_done} 个已完成")
            if skipped_expired:
                reasons.append(f"{skipped_expired} 个已过期")
            detail = f"（{'、'.join(reasons)}）" if reasons else ""
            self.log.info(f"没有需要处理的独立作业{detail}")
            return

        exam = DealExam(self.user, self.course, self.log, self.ui)
        total_q = total_cache = total_tiku = total_llm = total_random = 0
        submit_ok_total = submit_fail_total = 0
        success = failed = 0

        for i, work in enumerate(picked, 1):
            runtime.checkpoint()
            exam.active_unit_id = unit(work)
            runtime.emit('work_started', '开始处理独立作业', stage='homework', payload={
                'id': unit(work), 'name': work.get('title'), 'kind': 'homework', 'status': 'running'})
            self.log.info(f"[独立作业] [{i}/{len(picked)}] {work.get('title')}")
            try:
                stats = exam.answer_independent_work(work)
            except Exception as e:
                self.log.error(f"  独立作业'{work.get('title')}'处理异常: {e}")
                failed += 1
                runtime.emit('work_result', f'独立作业读取或处理失败: {e}', level='warning', stage='homework',
                             payload={'id': unit(work), 'name': work.get('title'), 'kind': 'homework', 'status': 'failed'})
                continue

            if not stats:
                failed += 1
                runtime.emit('work_result', '未能读取独立作业题目与提交结果', level='warning', stage='homework',
                             payload={'id': unit(work), 'name': work.get('title'), 'kind': 'homework', 'status': 'failed'})
                continue

            total_q += stats.get("questions", 0)
            total_cache += stats.get("cache_hits", 0)
            total_tiku += stats.get("tiku_hits", 0)
            total_llm += stats.get("llm_calls", 0)
            total_random += stats.get("random_answers", 0)
            submit_ok_total += stats.get("submit_ok", 0)
            submit_fail_total += stats.get("submit_fail", 0)

            ok = stats.get('questions', 0) > 0 and stats.get('submit_ok') == stats.get('questions') and not stats.get('submit_fail')
            runtime.emit('work_result', '作业提交已接受' if ok else '作业仍有未完成内容', stage='homework',
                         level='info' if ok else 'warning', payload={'id': unit(work), 'name': work.get('title'),
                                                                   'kind': 'homework', 'status': 'succeeded' if ok else 'blocked'})
            if ok:
                success += 1
            elif stats.get("questions", 0) == 0:
                self.log.info(f"  作业'{work.get('title')}'无题目，跳过")
                failed += 1
            else:
                failed += 1

        # 汇总
        if total_q > 0:
            parts = [f"缓存={total_cache}"]
            if total_tiku > 0:
                parts.append(f"题库={total_tiku}")
            parts.append(f"LLM={total_llm}")
            if total_random > 0:
                parts.append(f"随机={total_random}")
            self.log.success(
                f"[独立作业汇总] 共{total_q}题 | {' | '.join(parts)} | "
                f"提交成功={submit_ok_total}"
                + (f" | 失败={submit_fail_total}" if submit_fail_total else "")
            )
        self.log.info(
            f"'{self.course_name}'独立作业处理完毕: 成功{success}个 | 失败{failed}个"
        )
        from core import runtime
        runtime.emit("task_progress", "独立作业统计", stage="homework", payload={
            "course_name": self.course_name,
            "success": success,
            "failed": failed,
            "total": len(picked),
        })
        if self.ui:
            self.ui.record_exam_result(
                total_q, total_cache, total_tiku, total_llm, total_random,
                submit_ok_total, submit_fail_total,
            )
            self.ui.record_course_result(success, failed, 0)

    def _show_works(self, all_works: list, picked: list):
        """展示独立作业列表"""
        self.log.info(f"共 {len(all_works)} 个独立作业，其中 {len(picked)} 个待处理")
        picked_ids = {id(w) for w in picked}
        for i, w in enumerate(all_works, 1):
            mark = "*" if id(w) in picked_ids else " "
            status = w.get("status") or "未知"
            time_left = w.get("time_left") or ""
            extra = f" | {time_left}" if time_left else ""
            self.log.info(f"  {mark} {i}. {w.get('title')}  [{status}{extra}]")


def run(user, course, log, ui=None):
    """独立作业功能入口（供 main.py 调用）"""
    DealHomework(user, course, log, ui).do_finish()
