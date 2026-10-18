"""
WebUI Worker 运行器

单个子任务一个进程：
1. 读取任务文件（任务快照：账号凭据、课程、功能、参数）
2. 把 cli_copy 加入 sys.path，初始化本进程独有的 RequestClient 与 Session
3. 登录并获取课程，校验课程 ID / 班级 ID / CPI
4. 调用无 TUI 处理器完成指定功能
5. 全过程把阶段、统计、日志以 JSON Lines 写到标准输出

控制：轮询控制文件，在章节/媒体/题目/提交/等待边界响应 pause / stop。
统计：复用 CLI 原有的 ui 钩子（record_exam_result / record_course_result），
      因此答题来源计数、提交结果等口径与 CLI 完全一致。
"""

import json
import os
import signal
import sys
import traceback

# ============================================================
# 路径与导入
# ============================================================

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (CLI_COPY, WEBUI_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime  # noqa: E402
from app import paths as webui_paths  # noqa: E402

FEATURE_LABELS = {
    "course_all": "一键完成课程任务",
    "chapter_exam": "章节测验答题",
    "independent_homework": "独立作业答题",
    "exam": "独立考试答题",
    "video": "刷取视频时长",
    "learn_count": "刷取学习次数",
    "download": "下载课程资源",
}


class TaskAborted(Exception):
    """任务主动中止（停止或严重错误）"""


# ============================================================
# 统计收集（实现 CLI 的 ui 接口）
# ============================================================

class TaskStatsUI:
    """把 CLI 的 ui 回调转换为任务统计与进度事件"""

    def __init__(self, sink: "runtime.EventSink"):
        self.sink = sink
        self.stats = {
            "success": 0, "failed": 0, "skipped": 0, "already_done": 0,
            "questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
            "random_answers": 0, "submit_ok": 0, "submit_fail": 0,
        }
        self._chapter_total = 0

    # --- 课程/章节进度 ---
    def start_course(self, course_name, index=1, total=1):
        self.sink.emit("course_started", f"[{index}/{total}] 处理课程: {course_name}",
                       stage="course", payload={"course_name": course_name})

    def start_section(self, section_name, index=1, total=1):
        self._chapter_total = max(self._chapter_total, int(total or 0))
        self.sink.emit("chapter_started", f"  [{index}/{total}] {section_name}",
                       stage="chapter", payload={"chapter": section_name,
                                                 "current": index, "total": total})
        self._flush_progress()

    def task_already_done(self, task_name, task_type=""):
        self.stats["already_done"] += 1
        self.stats["skipped"] += 0

    # --- 计数 ---
    def count_success(self, n=1):
        self.stats["success"] += n

    def count_failed(self, n=1):
        self.stats["failed"] += n

    def count_skipped(self, n=1):
        self.stats["skipped"] += n

    def record_course_result(self, success, failed, already_done=0):
        self.stats["success"] += int(success or 0)
        self.stats["failed"] += int(failed or 0)
        self.stats["already_done"] += int(already_done or 0)
        self._flush_progress()

    def record_exam_result(self, questions, cache, tiku, llm, random_answers,
                           submit_ok, submit_fail):
        self.stats["questions"] += int(questions or 0)
        self.stats["cache_hits"] += int(cache or 0)
        self.stats["tiku_hits"] += int(tiku or 0)
        self.stats["llm_calls"] += int(llm or 0)
        self.stats["random_answers"] += int(random_answers or 0)
        self.stats["submit_ok"] += int(submit_ok or 0)
        self.stats["submit_fail"] += int(submit_fail or 0)
        self._flush_progress()

    def _flush_progress(self):
        self.sink.emit("task_progress", "任务统计更新", stage="progress", payload=dict(self.stats))


# ============================================================
# 工具
# ============================================================

def load_task(task_path: str) -> dict:
    with open(task_path, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(sink: "runtime.EventSink"):
    """
    日志接管：
    - loguru 全部输出转为 log 事件（JSON Lines），由 Web 进程解析
    - 同时保留 WebUI 自己的日志文件（源 CLI 目录不写入）
    """
    from loguru import logger

    logger.remove()
    from app.log_redaction import patch_record
    logger.configure(patcher=patch_record)

    def _loguru_sink(message):
        record = message.record
        sink.emit(
            "log",
            record["message"],
            level=record["level"].name.lower(),
            stage="log",
            payload={
                "module": f"{record['name']}:{record['function']}:{record['line']}",
                "raw_level": record["level"].name,
            },
        )

    logger.add(_loguru_sink, level="DEBUG", format="{message}",
               filter=lambda record: not record['extra'].get('instant_probe'))


def add_file_logger(log_dir: str, task_id: str):
    """文件日志（仅 WebUI 数据目录）"""
    from loguru import logger

    try:
        os.makedirs(log_dir, exist_ok=True)
        logger.add(
            os.path.join(log_dir, f"{task_id}.log"),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            encoding="utf-8",
            filter=lambda record: not record['extra'].get('instant_probe'),
        )
    except Exception as exc:  # 日志文件失败不应影响任务
        logger.debug(f"创建任务日志文件失败: {exc}")


def build_config(task: dict) -> dict:
    """把任务快照转换为 CLI 副本使用的配置字典"""
    params = task.get("params", {})
    video = params.get("video", {})
    answer = params.get("answer", {})
    advanced = params.get("advanced", {})
    llm = task.get("llm", {})

    return {
        "account": {"phone": task["username"], "password": task["password"]},
        "video": {
            "max_workers": int(video.get("max_workers", 8)),
            "mode": video.get("mode", "hybrid"),
            "random_progress": bool(video.get("random_progress", True)),
        },
        "answer": {
            "mode": answer.get("mode", "ai"),
            "no_answer_action": answer.get("no_answer_action", "skip"),
            "submit_delay": float(answer.get("submit_delay", 2)),
            "auto_submit": bool(answer.get("auto_submit", True)),
        },
        "llm": {
            "base_url": llm.get("base_url", "https://api.deepseek.com/v1"),
            "api_key": llm.get("api_key", ""),
            "model": llm.get("model", "deepseek-chat"),
            "temperature": float(llm.get("temperature", 0.1)),
            "max_tokens": int(llm.get("max_tokens", 4096)),
            "timeout": int(llm.get("timeout", 180)),
        },
        "question_bank": {
            "enabled": True,
            "db_path": task["question_bank_path"],
            "auto_save": bool(task.get("question_bank_auto_save", True)),
        },
        "notification": {"enabled": False},
        "advanced": {
            "request_delay": float(advanced.get("request_delay", 1.0)),
            "request_delay_jitter": float(advanced.get("request_delay_jitter", 0.5)),
            "max_retries": int(advanced.get("max_retries", 3)),
            "retry_delay": float(advanced.get("retry_delay", 5)),
            "learn_count_dwell": float(advanced.get("learn_count_dwell", 30)),
            "rotate_ua": bool(advanced.get("rotate_ua", True)),
            "log_level": "INFO",
            "log_file": "",
        },
    }


# ============================================================
# 登录与课程
# ============================================================

def login_and_load(task: dict, sink: "runtime.EventSink"):
    from core.config import Config
    from core.request_client import init_client
    from models.user import User

    sink.emit("login_started", f"正在登录账号 {task.get('account_label') or task['username']}",
              stage="login")

    config = build_config(task)
    Config._data = config
    Config._config_path = os.path.join(task["task_dir"], f"{task['task_id']}-config.json")
    init_client(config)

    user = User(task["username"], task["password"])
    sink.emit("login_succeeded", f"登录成功: {user.name}", stage="login",
              payload={"display_name": user.name, "uid": user.uid})
    runtime.checkpoint()

    user.get_courses()
    sink.emit("courses_loaded", f"课程读取成功，共 {len(user.course_list)} 门",
              stage="course", payload={"courses": len(user.course_list)})
    return user


def locate_course(user, task: dict):
    """按课程 ID + 班级 ID 精确匹配，避免不同账号同名课程误匹配"""
    target_course_id = str(task.get("course_id", ""))
    target_class_id = str(task.get("class_id", ""))
    for course in user.course_list:
        if str(course.course_id) != target_course_id:
            continue
        if target_class_id and str(course.class_id) != target_class_id:
            continue
        return course
    return None


# ============================================================
# 功能分发
# ============================================================

def run_feature(user, course, task: dict, ui: TaskStatsUI, sink) -> dict:
    feature = task["feature"]
    params = task.get("params", {})

    if feature == "course_all":
        # 只完成章节任务点；独立作业是独立功能，需单独创建任务，
        # 避免一次点击同时提交作业（用户明确要求分开）
        from functions.deal_course import DealCourse
        DealCourse(user, course, sink, ui).do_finish()
        return {}

    if feature == "chapter_exam":
        from functions.deal_exam import DealExam
        DealExam(user, course, sink, ui).do_finish()
        return {}

    if feature == "independent_homework":
        from functions.deal_homework import DealHomework
        DealHomework(user, course, sink, ui).do_finish(selection=params.get("selection"))
        return {}

    if feature == "exam":
        exam_params = params.get("exam") or {}
        exam_url = str(exam_params.get("url") or "").strip()
        if exam_url:
            from functions.exam_room_url import ExamRoomByUrl
            ExamRoomByUrl(user, course, sink, ui).do_finish(exam_url)
        else:
            from functions.deal_exam_room import DealExamRoom
            DealExamRoom(user, course, sink, ui).do_finish(selection=params.get("selection"))
        return {}

    if feature == "video":
        from functions.deal_video import DealVideo
        dv = DealVideo(user, course, sink)
        videos = dv.get_videos()
        if not videos:
            sink.info(f"课程'{course.course_name}'没有待刷取的视频")
            return {}
        video_params = params.get("video", {})
        runtime.emit('work_plan', '视频范围已读取', stage='video', payload={
            'sealed': True})
        tasks = [{"video": v, "mode": video_params.get("mode", "hybrid")} for v in videos]
        result = dv.batch_run_videos(tasks, int(video_params.get("max_workers", 8)))
        ui.record_course_result(result["success"], result["failed"], 0)
        return {}

    if feature == "learn_count":
        from functions.deal_time import run as run_time
        learn = params.get("learn_count", {})
        wanted = int(learn.get('times', 10))
        runtime.emit('work_plan', '访问范围已确定', stage='progress', payload={
            'units': [{'id': 'visit:'+str(i), 'name': f'学习访问 {i+1}', 'kind': 'progress'} for i in range(wanted)], 'sealed': True})
        added = run_time(
            user, course, sink, ui,
            times=int(learn.get("times", 10)),
            params={
                "dwell": learn.get("dwell", 30),
                "request_delay": params.get("advanced", {}).get("request_delay", 1.0),
            },
        )
        ui.record_course_result(int(added or 0), 0, 0)
        for i in range(wanted):
            runtime.emit('work_result', '学习访问已记录' if i < int(added or 0) else '学习访问未完成', stage='progress',
                         payload={'id': 'visit:'+str(i), 'status': 'succeeded' if i < int(added or 0) else 'failed'})
        ui.stats['failed'] += max(0, wanted-int(added or 0))
        return {}

    if feature == "download":
        from functions.deal_media import MediaDownload
        download = params.get("download", {})
        if download.get("scope") == "chapters" and not download.get("chapters"):
            raise TaskAborted("指定章节下载时必须填写章节 ID，任务未执行")
        md = MediaDownload(user, course, sink)
        md.deal_course()
        if not md.chapter_all:
            return {}
        save_path = webui_paths.resolve_download_path(download.get("path"))
        if download.get("scope") == "chapters" and download.get("chapters"):
            from core.chapter_parser import work_id
            wanted = {str(item) for item in download["chapters"]}
            stats = {"ok": 0, "fail": 0, "skipped": 0}
            found = {str(c.get('knowledge_id')) for c in md.chapter_all}
            missing = wanted - found
            stats['fail'] += len(missing)
            queue = []
            seen = set()
            for chapter in md.chapter_all:
                if str(chapter.get("knowledge_id")) not in wanted:
                    continue
                runtime.checkpoint()
                for attach_item in md.deal_chapter(chapter):
                    for media in attach_item.get("attachments", []):
                        if not md._is_downloadable(media):
                            stats["skipped"] += 1
                            continue
                        key = 'download:'+work_id(media)
                        if key not in seen:
                            queue.append(media)
                            seen.add(key)
            runtime.emit('work_plan', '下载范围已读取', stage='download', payload={
                'units': [{'id': 'download:'+work_id(m), 'name': (m.get('property') or {}).get('name'), 'kind': 'download'} for m in queue]
                    + [{'id': 'missing:'+chapter, 'name': '章节 '+chapter, 'kind': 'chapter'} for chapter in sorted(missing)], 'sealed': True})
            for chapter in sorted(missing):
                runtime.emit('work_result', '指定章节不在课程中，请核对章节 ID', stage='chapter', level='warning',
                             payload={'id': 'missing:'+chapter, 'status': 'blocked', 'name': '章节 '+chapter})
            for media in queue:
                runtime.checkpoint()
                if md.do_download(save_path, media):
                    stats['ok'] += 1
                else:
                    stats['fail'] += 1
        else:
            stats = md.download_all(save_path)
        ui.stats["download_ok"] = stats["ok"]
        ui.stats["download_fail"] = stats["fail"]
        # 下载跳过的是“不可下载的附件”，与任务点“已完成”不是同一口径
        ui.stats["skipped"] += int(stats.get("skipped", 0) or 0)
        ui.record_course_result(stats["ok"], stats["fail"], 0)
        return {}

    raise TaskAborted(f"未知功能类型: {feature}")


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    if len(sys.argv) < 2:
        print("用法: runner.py <task_file.json>", file=sys.stderr)
        return 2

    task = load_task(sys.argv[1])
    sink = runtime.EventSink(task_id=task["task_id"])
    runtime.set_sink(sink)
    runtime.set_control(runtime.ControlState(task["control_path"], sink=sink))

    setup_logging(sink)
    add_file_logger(task.get("log_dir", ""), task["task_id"])

    ui = TaskStatsUI(sink)

    from loguru import logger
    from core.exceptions import AntispiderException, LoginException

    sink.emit("worker_started",
              f"Worker 启动 | 功能: {FEATURE_LABELS.get(task['feature'], task['feature'])}",
              stage="boot", payload={"pid": os.getpid(), "feature": task["feature"]})

    def _sigterm(_signum, _frame):
        runtime.emit("stop_requested", "收到系统终止信号", stage="control")
        raise TaskAborted("收到终止信号")

    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (ValueError, AttributeError, OSError):
        pass

    try:
        user = login_and_load(task, sink)
        runtime.checkpoint()

        sink.emit("stage_changed", "校验课程参数", stage="course")
        course = locate_course(user, task)
        if course is None:
            message = (f"账号 {task.get('account_label') or task['username']} 中未找到课程 "
                       f"{task.get('course_name') or task.get('course_id')}"
                       f" (classId={task.get('class_id')})")
            sink.emit("task_failed", message, level="error", stage="course")
            return 1

        sink.emit("course_started", f"开始处理课程: {course.course_name}", stage="course",
                  payload={"course_name": course.course_name})
        run_feature(user, course, task, ui, sink)
        runtime.checkpoint()
        if any(int(ui.stats.get(key, 0) or 0) > 0 for key in ('failed', 'submit_fail', 'download_fail')):
            sink.emit('task_failed', '部分内容未完成，请在任务详情查看具体问题', level='warning', stage='finish',
                      payload={'stats': dict(ui.stats)})
            return 1
        sink.emit("task_succeeded", "任务完成", stage="finish",
                  payload={"stats": dict(ui.stats)})
        return 0

    except runtime.StopRequested:
        sink.emit("task_stopped", "任务已按指令停止", level="warning", stage="finish",
                  payload={"stats": dict(ui.stats)})
        return 3
    except TaskAborted as exc:
        sink.emit("task_stopped", f"任务中止: {exc}", level="warning", stage="finish",
                  payload={"stats": dict(ui.stats)})
        return 3
    except AntispiderException as exc:
        sink.emit("task_failed", f"触发反爬虫验证: {exc}", level="error", stage="finish",
                  payload={"stats": dict(ui.stats)})
        return 1
    except LoginException as exc:
        sink.emit("login_failed", f"登录失败: {exc}", level="error", stage="login")
        sink.emit("task_failed", f"登录失败: {exc}", level="error", stage="finish")
        return 1
    except KeyboardInterrupt:
        sink.emit("task_stopped", "任务被中断", level="warning", stage="finish")
        return 3
    except Exception as exc:
        detail = traceback.format_exc()
        try:
            logger.error(f"任务异常退出: {exc}\n{detail}")
        except Exception:
            pass
        sink.emit("task_failed", f"任务异常: {exc}", level="error", stage="finish",
                  payload={"traceback": detail[-2000:]})
        return 1
    finally:
        try:
            from core.request_client import get_client
            client = get_client()
            if client is not None:
                client.session.close()
        except Exception:
            pass
        sink.emit("worker_exit", "Worker 进程退出", stage="finish")


if __name__ == "__main__":
    sys.exit(main())
