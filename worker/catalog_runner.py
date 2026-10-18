"""
课程目录 Worker（作业 / 考试列表）

Web 进程不持有超星 Session，因此「新建任务时列出可选作业/考试」也放到子进程：
1. 读取目录任务文件（账号凭据 + 课程标识 + kind=work|exam）
2. 登录并定位课程
3. 只读拉取作业或考试列表
4. 以 JSON Lines 事件写标准输出（catalog_result / catalog_failed / log）

本进程只发 GET 请求，不提交任何作业或考试。
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
    try:
        from app.log_redaction import patch_record
        logger.configure(patcher=patch_record)
    except Exception:
        pass

    def _loguru_sink(message):
        record = message.record
        sink.emit("log", record["message"], level=record["level"].name.lower(),
                  stage="log", payload={"module": f"{record['name']}:{record['line']}"})

    logger.add(_loguru_sink, level="INFO", format="{message}")


def build_config(job: dict) -> dict:
    advanced = job.get("advanced", {})
    return {
        "account": {"phone": job["username"], "password": job["password"]},
        "video": {"max_workers": 1, "mode": "instant", "random_progress": False},
        "answer": {"mode": "manual", "no_answer_action": "skip",
                   "submit_delay": 0, "auto_submit": False},
        "llm": {"base_url": "", "api_key": "", "model": "", "temperature": 0,
                "max_tokens": 0, "timeout": 30},
        "question_bank": {"enabled": False,
                          "db_path": job.get("question_bank_path", ""),
                          "auto_save": False},
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


def normalize_work_item(item: dict) -> dict:
    return {
        "id": str(item.get("work_id") or ""),
        "title": item.get("title") or "未命名作业",
        "status": item.get("status") or "",
        "time_left": item.get("time_left") or "",
        "valid": bool(item.get("valid", True)),
        "url": item.get("url") or "",
    }


def normalize_exam_item(item: dict) -> dict:
    return {
        "id": str(item.get("exam_id") or item.get("id") or ""),
        "title": item.get("title") or "未命名考试",
        "status": item.get("status") or "",
        "start_time": item.get("start_time") or "",
        "end_time": item.get("end_time") or "",
        "limit_time": item.get("limit_time"),
        "valid": bool(item.get("valid", True)),
        "relation_id": str(item.get("relation_id") or ""),
        "paper_id": str(item.get("paper_id") or ""),
        "enc": item.get("enc") or "",
    }


def find_course(user, job: dict):
    course_id = str(job.get("course_id") or "")
    class_id = str(job.get("class_id") or "")
    for course in user.course_list:
        if str(course.course_id) != course_id:
            continue
        if class_id and str(course.class_id) != class_id:
            continue
        return course
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: catalog_runner.py <job_file.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        job = json.load(f)

    account_id = str(job.get("account_id") or "")
    course_id = str(job.get("course_id") or "")
    kind = str(job.get("kind") or "work").lower()
    if kind not in ("work", "exam"):
        print("kind 必须是 work 或 exam", file=sys.stderr)
        return 2

    sink = runtime.EventSink(task_id=f"catalog-{account_id}-{course_id}-{kind}")
    runtime.set_sink(sink)
    setup_logging(sink)

    from core.config import Config
    from core.exceptions import AntispiderException, LoginException
    from core.request_client import init_client
    from models.user import User

    sink.emit("login_started", f"正在登录账号 {job.get('account_label') or job['username']}",
              stage="login")
    try:
        config = build_config(job)
        Config._data = config
        task_dir = job.get("task_dir") or os.path.join(WEBUI_ROOT, "data", "tasks")
        Config._config_path = os.path.join(task_dir, "catalog-config.json")
        init_client(config)

        user = User(job["username"], job["password"])
        user.get_courses()
        course = find_course(user, job)
        if course is None:
            sink.emit("catalog_failed", "课程未找到，请先同步该账号的课程列表",
                      level="error", stage="catalog")
            return 1

        sink.emit("log", f"正在读取课程「{course.course_name}」的"
                         f"{'作业' if kind == 'work' else '考试'}列表", stage="catalog")

        if kind == "work":
            raw = course.get_work_list()
            items = [normalize_work_item(item) for item in raw]
        else:
            raw = course.get_exam_list()
            items = [normalize_exam_item(item) for item in raw]

        label = "作业" if kind == "work" else "考试"
        sink.emit("catalog_result",
                  f"{label}列表读取完成，共 {len(items)} 项" if items
                  else f"该课程暂无可选的{label}",
                  stage="catalog",
                  payload={"account_id": account_id, "course_id": course_id,
                           "kind": kind, "items": items, "display_name": user.name})
        return 0

    except LoginException as exc:
        sink.emit("catalog_failed", f"登录失败: {exc}", level="error", stage="login")
        return 1
    except AntispiderException as exc:
        sink.emit("catalog_failed", f"触发反爬虫验证，请稍后重试: {exc}",
                  level="error", stage="login")
        return 1
    except Exception as exc:
        detail = traceback.format_exc()
        sink.emit("catalog_failed", f"读取列表失败: {exc}", level="error", stage="catalog",
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
