"""
Worker 公共基座（v2.4.0 T1）

四个 Worker（任务 / 会话 / 同步 / 目录）此前各自复制一份 build_config 与
setup_logging，参数已漂移（request_delay 0.5/1.0、max_retries 1/2/3、
rotate_ua False/True、loguru 桥 INFO/DEBUG 不一）。本模块合并为单一实现：

- build_base_config(job, profile): 四份 build_config 的并集，profile 决定预设；
  默认值取 WebUI app settings（video.max_workers=8，修正 CLI 默认 20 的漂移）。
- setup_common_logging(sink, level, task_id): loguru 统一桥接（DEBUG + module
  payload，与任务 runner 口径一致），保持 log_redaction patcher。
- graceful_exit: 协作退出信号。EventSink 写失败不再静默吞——连续失败即置位，
  父进程死亡后 Worker 不再傻跑（T1.5）。
- terminate_gracefully(proc, timeout_s): Windows 优雅终止阶梯。此前
  Popen.terminate() 在 Windows 上等价 TerminateProcess，runner 的 SIGTERM
  处理器从不执行（无 session.close、无 worker_exit 事件、文件日志不落盘）；
  现按 taskkill(无 /F) → 等待退出 → CTRL_BREAK → TerminateProcess 兜底。

设计约束：不引入 cli_copy 之外的依赖；纯 CLI 场景（无 Web 父进程）下全部函数
可用且行为不回退。
"""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time

# ============================================================
# 协作退出信号
# ============================================================

graceful_exit = threading.Event()


# ============================================================
# 配置预设（build_config 四份合一）
# ============================================================

# profile → (request_delay, request_delay_jitter, max_retries, retry_delay, rotate_ua)
# rotate_ua=False 是会话 Runner 的有意设计：Cookie 与 UA 保持稳定避免会话判异常。
_ADVANCED_PRESETS = {
    "session": (0.5, 0.2, 1, 2, False),
    "sync": (1.0, 0.5, 2, 3, True),
    "catalog": (1.0, 0.5, 2, 3, True),
    "task": (1.0, 0.5, 3, 5, True),
}

# 修正 CLI 漂移：video.max_workers 默认取 app settings（settings.py:42 = 8），
# 而非 cli_copy/core/config.py:215 的 20。
TASK_VIDEO_DEFAULT_MAX_WORKERS = 8


def build_base_config(job: dict, profile: str = "task") -> dict:
    """
    合并四份 build_config 为单一实现。

    Args:
        job: 任务/作业文件内容。task profile 读 job["params"]/job["llm"]，
            其余 profile 读 job["advanced"]（app 侧 resolve 后的 advanced 节）。
        profile: task | session | sync | catalog

    Returns:
        dict: CLI Config 兼容的完整配置字典（account/video/answer/llm/
        question_bank/advanced 六节）。
    """
    if profile not in _ADVANCED_PRESETS:
        raise ValueError(f"未知 profile: {profile}（可选 task/session/sync/catalog）")

    advanced = job.get("advanced", {}) or {}
    request_delay, jitter, max_retries, retry_delay, rotate_ua = _ADVANCED_PRESETS[profile]

    if profile == "task":
        params = job.get("params", {}) or {}
        video = params.get("video", {}) or {}
        answer = params.get("answer", {}) or {}
        llm = job.get("llm", {}) or {}
        advanced = params.get("advanced", {}) or advanced
        video_section = {
            "max_workers": int(video.get("max_workers", TASK_VIDEO_DEFAULT_MAX_WORKERS)),
            "mode": video.get("mode", "hybrid"),
            "random_progress": bool(video.get("random_progress", True)),
        }
        answer_section = {
            "mode": answer.get("mode", "ai"),
            "no_answer_action": answer.get("no_answer_action", "skip"),
            "submit_delay": float(answer.get("submit_delay", 2)),
            "auto_submit": bool(answer.get("auto_submit", True)),
        }
        llm_section = {
            "base_url": llm.get("base_url", "https://api.deepseek.com/v1"),
            "api_key": llm.get("api_key", ""),
            "model": llm.get("model", "deepseek-chat"),
            "temperature": float(llm.get("temperature", 0.1)),
            "max_tokens": int(llm.get("max_tokens", 4096)),
            "timeout": int(llm.get("timeout", 180)),
        }
        question_bank_section = {
            "enabled": True,
            "db_path": job["question_bank_path"],
            "auto_save": bool(job.get("question_bank_auto_save", True)),
        }
        learn_count_dwell = float(advanced.get("learn_count_dwell", 30))
    else:
        # session/sync/catalog：无 LLM、无答题提交，纯只读预设
        video_section = {"max_workers": 1, "mode": "instant", "random_progress": False}
        answer_section = {
            "mode": "manual", "no_answer_action": "skip",
            "submit_delay": 0, "auto_submit": False,
        }
        llm_section = {
            "base_url": "", "api_key": "", "model": "",
            "temperature": 0, "max_tokens": 0, "timeout": 30,
        }
        question_bank_section = {
            "enabled": False,
            "db_path": job.get("question_bank_path", ""),
            "auto_save": False,
        }
        learn_count_dwell = 0

    return {
        "account": {"phone": job["username"], "password": job["password"]},
        "video": video_section,
        "answer": answer_section,
        "llm": llm_section,
        "question_bank": question_bank_section,
        "advanced": {
            "request_delay": float(advanced.get("request_delay", request_delay)),
            "request_delay_jitter": float(advanced.get("request_delay_jitter", jitter)),
            "max_retries": int(advanced.get("max_retries", max_retries)),
            "retry_delay": float(advanced.get("retry_delay", retry_delay)),
            "learn_count_dwell": learn_count_dwell,
            "rotate_ua": bool(advanced.get("rotate_ua", rotate_ua)),
            "log_level": str(advanced.get("log_level", "INFO")),
            "log_file": str(advanced.get("log_file", "")),
        },
    }


# ============================================================
# 日志统一（loguru → EventSink 单通道桥接）
# ============================================================

def setup_common_logging(sink, level: str = "DEBUG", task_id: str = "",
                         extra_filter=None) -> None:
    """
    四个 Runner 共用的日志接管。

    - loguru 全部输出转为 log 事件（JSON Lines），由 Web 进程解析；
    - payload 带 module:function:line（与任务 runner 口径一致，废弃
      session/catalog 的 INFO 级无 payload 漂移）；
    - 保持 log_redaction patcher；可选 extra_filter（如任务 runner 的
      instant_probe 过滤）。
    """
    from loguru import logger

    logger.remove()
    try:
        from app.log_redaction import patch_record
        logger.configure(patcher=patch_record)
    except Exception:
        pass  # 纯 CLI 场景可能没有 app 包

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

    logger.add(_loguru_sink, level=level, format="{message}", filter=extra_filter)


# ============================================================
# 进程优雅终止阶梯（Windows 不再裸 TerminateProcess）
# ============================================================

def _windows_send_ctrl(proc, event: int) -> bool:
    """向进程组发 CTRL 事件；返回是否发送成功"""
    k32 = ctypes.windll.kernel32
    try:
        k32.SetConsoleCtrlHandler(None, True)  # 本进程忽略 CTRL_C/CTRL_BREAK
        k32.GenerateConsoleCtrlEvent(event, proc.pid)
        return True
    except Exception:
        return False


def terminate_gracefully(proc, timeout_s: float = 5.0) -> None:
    """
    优雅终止阶梯（替代裸 terminate/kill）：

    1. taskkill（无 /F）：向进程发 WM_CLOSE，子进程 SIGTERM 处理器经
       Windows 消息循环触发优雅路径（session.close / worker_exit / 日志落盘）；
    2. 等待 timeout_s 秒内退出（轮询 poll，间隔 0.1s）；
    3. CTRL_BREAK 到同组进程；再等待最长 3s；
    4. 兜底 TerminateProcess（kill），不再等待。

    非 Windows 平台退化为 terminate() → wait → kill()。
    """
    if proc is None or proc.poll() is not None:
        return

    if os.name != "nt":
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=max(0.1, timeout_s))
            return
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return

    # Windows 阶梯
    # 阶段 1：taskkill 无 /F（请求关闭）
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid)],
            check=False, capture_output=True, creationflags=_no_window(),
        )
    except Exception:
        pass

    if _wait_exit(proc, timeout_s):
        return

    # 阶段 2：CTRL_BREAK（进程组；仅对共享控制台的子进程有效）
    if _windows_send_ctrl(proc, 1):  # CTRL_BREAK_EVENT = 1
        if _wait_exit(proc, min(3.0, max(0.5, timeout_s))):
            return

    # 阶段 3：兜底强杀
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _wait_exit(proc, timeout_s: float) -> bool:
    """轮询等待进程退出（避免 wait() 阻塞在已死的管道读上）"""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.1)
    return proc.poll() is not None


def _no_window() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def write_json_atomic(path: str, data) -> None:
    """临时文件 + os.replace 原子写 JSON（四个 Runner 的 job 文件写入统一）"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
