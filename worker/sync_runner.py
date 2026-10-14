"""
账号同步 Worker

单独进程执行登录 + 课程列表拉取，避免 Web 进程持有超星 Session：
1. 读取同步任务文件（账号凭据 + 外部服务配置）
2. 登录并获取课程列表
3. 把课程列表以 JSON Lines 事件写到标准输出
4. 同时刷新章节进度快照（失败不影响课程列表返回）
"""

import json
import os
import sys
import traceback

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_COPY = os.path.join(WEBUI_ROOT, "cli_copy")
for path in (CLI_COPY, WEBUI_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import runtime  # noqa: E402


def setup_logging(sink):
    from loguru import logger

    logger.remove()
    from app.log_redaction import patch_record
    logger.configure(patcher=patch_record)

    def _loguru_sink(message):
        record = message.record
        sink.emit("log", record["message"], level=record["level"].name.lower(),
                  stage="log", payload={"module": f"{record['name']}:{record['line']}"})

    logger.add(_loguru_sink, level="DEBUG", format="{message}")


def build_config(job: dict) -> dict:
    advanced = job.get("advanced", {})
    return {
        "account": {"phone": job["username"], "password": job["password"]},
        "video": {"max_workers": 1, "mode": "instant", "random_progress": False},
        "answer": {"mode": "manual", "fallback_to_tiku": False, "no_answer_action": "skip",
                   "submit_delay": 0, "auto_submit": False},
        "llm": {"base_url": "", "api_key": "", "model": "", "temperature": 0, "max_tokens": 0,
                "timeout": 30},
        "tiku": {"enabled": False, "timeout": 5},
        "question_bank": {"enabled": False, "db_path": job["question_bank_path"], "auto_save": False},
        "notification": {"enabled": False},
        "advanced": {
            "request_delay": float(advanced.get("request_delay", 1.0)),
            "request_delay_jitter": float(advanced.get("request_delay_jitter", 0.5)),
            "max_retries": int(advanced.get("max_retries", 2)),
            "retry_delay": float(advanced.get("retry_delay", 3)),
            "learn_count_dwell": 0,
            "rotate_ua": True,
            "log_level": "INFO",
            "log_file": "",
        },
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: sync_runner.py <job_file.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        job = json.load(f)

    sink = runtime.EventSink(task_id=f"sync-{job.get('account_id', '')}")
    runtime.set_sink(sink)
    setup_logging(sink)

    from core.config import Config
    from core.exceptions import LoginException, AntispiderException
    from core.request_client import init_client
    from models.user import User

    sink.emit("login_started", f"正在登录账号 {job.get('account_label') or job['username']}",
              stage="login")
    try:
        config = build_config(job)
        Config._data = config
        task_dir = job.get("task_dir") or os.path.join(WEBUI_ROOT, "data", "tasks")
        Config._config_path = os.path.join(task_dir, "sync-config.json")
        init_client(config)

        user = User(job["username"], job["password"])
        sink.emit("login_succeeded", f"登录成功: {user.name}", stage="login",
                  payload={"display_name": user.name, "uid": user.uid})

        user.get_courses()
        sink.emit("courses_loaded", f"课程读取成功，共 {len(user.course_list)} 门",
                  stage="course", payload={"courses": len(user.course_list)})

        courses = []
        with_progress = []
        for course in user.course_list:
            courses.append({
                "course_id": str(course.course_id),
                "class_id": str(course.class_id),
                "cpi": str(course.cpi),
                "name": course.course_name,
                "author": course.course_author,
                "if_open": bool(course.if_open),
                "mission_fn": 0,
                "mission_all": 0,
            })
        sink.emit("sync_result", f"同步完成，共 {len(courses)} 门课程", stage="finish",
                  payload={"courses": courses, "display_name": user.name, "uid": user.uid,
                           "course_errors": with_progress})
        return 0

    except LoginException as exc:
        sink.emit("sync_failed", f"登录失败: {exc}", level="error", stage="login")
        return 1
    except AntispiderException as exc:
        sink.emit("sync_failed", f"触发反爬虫验证，请稍后重试: {exc}", level="error", stage="login")
        return 1
    except Exception as exc:
        detail = traceback.format_exc()
        sink.emit("sync_failed", f"同步异常: {exc}", level="error", stage="finish",
                  payload={"traceback": detail[-1500:]})
        return 1
    finally:
        try:
            from core.request_client import get_client
            client = get_client()
            if client is not None:
                client.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
