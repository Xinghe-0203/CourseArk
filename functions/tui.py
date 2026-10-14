"""
AutoChaoxingCLI - Rich TUI 界面

基于 Rich 库的终端用户界面，提供：
- 彩色 Banner 和菜单
- 进度条
- 课程选择
- 任务统计和运行报告
- 表格展示
"""

import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt, IntPrompt
from rich.text import Text
from rich import box

console = Console()


class TUI:
    """Rich TUI 界面管理器"""

    def __init__(self):
        self.start_time = time.time()
        self.stats = {
            'courses_total': 0, 'courses_processed': 0,
            'tasks_success': 0, 'tasks_failed': 0,
            'tasks_skipped': 0, 'tasks_already_done': 0,
            'exam_total': 0, 'exam_cache': 0, 'exam_llm': 0,
            'exam_tiku': 0, 'exam_random': 0, 'exam_submit_ok': 0, 'exam_submit_fail': 0,
        }

    def banner(self, version: str = "3.0"):
        """显示 Banner"""
        banner_text = Text()
        banner_text.append("  ╔═══════════════════════════════════════════╗\n", style="bold cyan")
        banner_text.append("  ║                                           ║\n", style="bold cyan")
        banner_text.append("  ║     ", style="bold cyan")
        banner_text.append("AutoChaoxingCLI", style="bold green")
        banner_text.append("  v" + version, style="dim")
        banner_text.append("       ║\n", style="bold cyan")
        banner_text.append("  ║     ", style="bold cyan")
        banner_text.append("超星学习通自动学习工具", style="bold white")
        banner_text.append("       ║\n", style="bold cyan")
        banner_text.append("  ║                                           ║\n", style="bold cyan")
        banner_text.append("  ╚═══════════════════════════════════════════╝\n", style="bold cyan")
        console.print(banner_text)

    def main_menu(self) -> int:
        """显示主菜单并获取选择"""
        table = Table(title="功能菜单", box=box.ROUNDED, show_header=False, border_style="cyan")
        table.add_column("序号", style="bold yellow", width=6)
        table.add_column("功能", style="bold white", min_width=20)
        table.add_column("说明", style="dim", min_width=30)

        table.add_row("1", "一键完成课程任务", "自动完成视频/阅读/文档/作业等任务点")
        table.add_row("2", "AI答题/作业", "自动回答章节任务点内的测验/作业")
        table.add_row("3", "刷取视频时长", "并发刷取视频观看时长(支持0-200线程)")
        table.add_row("4", "刷取学习次数", "刷取课程学习访问次数")
        table.add_row("5", "下载课程资源", "下载视频/文档等课程资源文件")
        table.add_row("6", "切换账号", "切换或管理已保存账号，无需重复登录")
        table.add_row("7", "AI答独立作业", "处理课程作业页中的独立作业")
        table.add_row("0", "退出程序", "")

        console.print(table)
        try:
            choice = IntPrompt.ask("\n请选择功能", default=0)
        except (ValueError, KeyboardInterrupt):
            return 0
        return choice

    def select_courses(self, course_list) -> list:
        """选择课程"""
        if not course_list:
            console.print("[red]没有可用的课程[/red]")
            return []

        table = Table(title="课程列表", box=box.ROUNDED, show_header=True, border_style="green")
        table.add_column("序号", style="bold yellow", width=6)
        table.add_column("课程名称", style="white", min_width=25)
        table.add_column("教师", style="dim", min_width=15)
        table.add_column("状态", width=8)

        for i, course in enumerate(course_list):
            status = "[green]开放[/green]" if course.if_open else "[red]锁定[/red]"
            table.add_row(str(i + 1), course.course_name, course.course_author or "未知", status)

        console.print(table)

        choice = Prompt.ask("\n请输入课程序号(多个用逗号分隔, 回车刷取全部, q退出)", default="")
        if choice.strip().lower() == 'q':
            return []

        try:
            from core.selection import parse_selection
            indices = parse_selection(choice, len(course_list))
            selected = [course_list[i] for i in indices if course_list[i].if_open]
            if len(selected) != len(indices):
                console.print('[yellow]未开放课程已排除[/yellow]')
            return selected
        except (ValueError, IndexError):
            console.print("[red]无效的序号[/red]")
            return []

    def show_accounts(self, accounts, selected):
        table = Table(title="账号列表", box=box.ROUNDED, show_header=True, border_style="green")
        table.add_column("序号", style="bold yellow", width=6)
        table.add_column("账号备注", style="white", min_width=18)
        table.add_column("手机号", style="dim", min_width=14)
        table.add_column("登录状态", width=10)
        table.add_column("已选", width=6)
        for i, a in enumerate(accounts, 1):
            session = Text("已保存", style="green") if a["has_session"] else Text("自动登录", style="yellow")
            chosen = Text("✓", style="green") if a["id"] in selected else ""
            table.add_row(str(i), a["label"], a["username"], session, chosen)
        console.print(table, markup=False)

    def account_heading(self, label):
        console.print(f"\n[bold green]账号: {label}[/bold green]")
        console.print("─" * 50)

    def batch_table(self, rows):
        table = Table(title="多账号任务进度", box=box.ROUNDED, show_header=True,
                      border_style="cyan", expand=True)
        table.add_column("账号", style="bold white", min_width=14)
        table.add_column("状态 / 课程", style="dim", min_width=24)
        table.add_column("成功", style="green", justify="right", width=8)
        table.add_column("失败", style="red", justify="right", width=8)
        table.add_column("答题 / 提交", style="white", justify="right", width=12)
        for row in rows.values():
            stats = row.get('stats', {})
            table.add_row(row['label'], row['message'], str(stats.get('tasks_success', 0)),
                          str(stats.get('tasks_failed', 0)),
                          f"{stats.get('exam_total', 0)} / {stats.get('exam_submit_ok', 0)}")
        return table

    def select_course(self, course_list):
        """选择单个课程"""
        result = self.select_courses(course_list)
        return result[:1] if result else []

    def video_config(self) -> dict:
        """配置视频刷取参数"""
        from core.config import Config

        console.print("\n[bold cyan]视频刷取配置[/bold cyan]")
        console.print("─" * 40)

        # 模式选择菜单
        mode_table = Table(box=box.ROUNDED, show_header=False, border_style="dim")
        mode_table.add_column("序号", style="bold yellow", width=4)
        mode_table.add_column("模式", style="white", min_width=12)
        mode_table.add_column("说明", style="dim", min_width=30)
        mode_table.add_row("1", "instant", "尝试立即完成，未确认时自动真实播放")
        mode_table.add_row("2", "real_time", "等时长刷取（按视频时长逐步上报）")
        mode_table.add_row("3", "混合模式", "先尝试立即完成，再静默转为真实播放（推荐）")
        console.print(mode_table)

        default_mode = Config.get("video.mode", "hybrid")
        # 映射旧配置值到新序号
        default_num = {"instant": "1", "real_time": "2", "hybrid": "3"}.get(default_mode, "3")

        mode_choice = Prompt.ask("请选择刷取模式", choices=["1", "2", "3"], default=default_num)
        mode_map = {"1": "instant", "2": "real_time", "3": "hybrid"}
        mode = mode_map[mode_choice]

        max_workers = IntPrompt.ask(
            "并发线程数 (0=不限制, 1-200)",
            default=Config.get("video.max_workers", 20)
        )
        max_workers = max(0, min(max_workers, 200))

        return {"mode": mode, "max_workers": max_workers}

    def start_course(self, course_name: str, index: int, total: int):
        """显示开始处理课程"""
        console.print(f"\n[bold green][{index}/{total}] 处理课程: {course_name}[/bold green]")
        console.print("─" * 50)

    def start_section(self, section_name: str, index: int, total: int):
        """显示章节信息"""
        console.print(f"  [dim][{index}/{total}] {section_name}[/dim]")

    def task_already_done(self, task_name: str, task_type: str = ""):
        """显示已完成任务"""
        icon = self._task_type_icon(task_type)
        console.print(f"    [dim][OK] {icon}{task_name} -- 已完成[/dim]")

    def task_result(self, task_name: str, result: str, detail: str = ""):
        """显示任务结果"""
        if result == 'success':
            msg = f"    [green]  [OK] {task_name}[/green]"
        elif result == 'failed':
            msg = f"    [red]  [FAIL] {task_name}[/red]"
        elif result == 'skipped':
            msg = f"    [yellow]  [SKIP] {task_name}[/yellow]"
        else:
            msg = f"    {task_name}"
        if detail:
            msg += f" -- {detail}"
        console.print(msg)

    def course_summary(self, chapter_count: int, task_stats: dict = None):
        """显示课程汇总"""
        console.print("─" * 50)
        s = task_stats or {}
        parts = []
        if s.get('already_done', 0) > 0:
            parts.append(f"[dim]已完成 {s['already_done']}个[/dim]")
        if s.get('success', 0) > 0:
            parts.append(f"[green]成功 {s['success']}个[/green]")
        if s.get('failed', 0) > 0:
            parts.append(f"[red]失败 {s['failed']}个[/red]")
        if s.get('skipped', 0) > 0:
            parts.append(f"[yellow]跳过 {s['skipped']}个[/yellow]")
        detail = " | ".join(parts) if parts else "无任务"
        console.print(f"  汇总: {chapter_count} 个章节 | {detail}")

    def run_report(self):
        """显示运行报告"""
        elapsed = time.time() - self.start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"

        report = Table(title=f"运行报告 (耗时: {time_str})", box=box.ROUNDED, border_style="cyan",
                       show_header=False)
        report.add_column("项目", style="bold")
        report.add_column("结果")

        if self.stats['courses_processed'] > 0:
            report.add_row("处理课程", f"{self.stats['courses_processed']} 门")

        t_s = self.stats['tasks_success']
        t_f = self.stats['tasks_failed']
        t_d = self.stats['tasks_already_done']
        if t_s + t_f + t_d > 0:
            report.add_row("任务点", f"成功 {t_s} | 失败 {t_f} | 已完成 {t_d}")

        e_t = self.stats['exam_total']
        if e_t > 0:
            report.add_row("答题", f"共 {e_t} 题 | 缓存 {self.stats['exam_cache']} | "
                           f"题库 {self.stats['exam_tiku']} | LLM {self.stats['exam_llm']} | "
                           f"随机 {self.stats['exam_random']}")
            report.add_row("提交", f"成功 {self.stats['exam_submit_ok']} | 失败 {self.stats['exam_submit_fail']}")

        console.print()
        console.print(report)
        console.print()

    @staticmethod
    def _task_type_icon(task_type: str) -> str:
        icons = {
            'video': '[视频]', 'insertaudio': '[音频]', 'read': '[阅读]',
            'document': '[文档]', 'live': '[直播]', 'work': '[作业]',
            'workid': '[作业]', 'book': '[图书]', 'vote': '[投票]',
            'insertvote': '[投票]', 'insertbbs': '[讨论]', 'unknown': '[其他]',
        }
        return icons.get(task_type, '[?]')

    def count_success(self, n=1):
        self.stats['tasks_success'] += n

    def count_failed(self, n=1):
        self.stats['tasks_failed'] += n

    def count_skipped(self, n=1):
        self.stats['tasks_skipped'] += n

    def record_course_result(self, success: int, failed: int, already_done: int = 0):
        """记录一门课程或一次独立任务的处理结果。"""
        self.stats['courses_processed'] += 1
        self.stats['tasks_success'] += success
        self.stats['tasks_failed'] += failed
        self.stats['tasks_already_done'] += already_done

    def record_exam_result(self, questions: int, cache: int, tiku: int,
                           llm: int, random_answers: int,
                           submit_ok: int, submit_fail: int):
        """记录答题统计。"""
        self.stats['exam_total'] += questions
        self.stats['exam_cache'] += cache
        self.stats['exam_tiku'] += tiku
        self.stats['exam_llm'] += llm
        self.stats['exam_random'] += random_answers
        self.stats['exam_submit_ok'] += submit_ok
        self.stats['exam_submit_fail'] += submit_fail
