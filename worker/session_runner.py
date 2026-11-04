"""
会话获取 Worker

用账号密码登录一次学习通，把登录后的 Cookie 交给 Web 进程保存，
供"一键打开学习通课程页面"使用（浏览器带着这些 Cookie 直接进入已登录状态）。

输出事件：
- session_result: 成功，payload 含 cookies / display_name / uid
- session_failed: 失败，payload 含 message
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
from worker import common  # noqa: E402


def setup_logging(sink):
    # 统一日志桥（v2.4.0 T1）：DEBUG 级 + module:function:line payload，与任务 runner 口径一致
    common.setup_common_logging(sink, level="DEBUG")


def build_config(job: dict) -> dict:
    return common.build_base_config(job, profile="session")


def collect_cookies(cookie_jar) -> list:
    """把 requests 的 CookieJar 转成浏览器可注入的列表"""
    cookies = []
    for item in cookie_jar:
        domain = item.domain or ".chaoxing.com"
        if item.domain and not item.domain.startswith("."):
            # 浏览器要求 cookie 的 domain 与 Set-Cookie 语义一致：
            # 主机级 cookie 用 host-only 方式注入（domain 不带点）
            pass
        value = item.value
        if value is None:
            continue
        cookies.append({
            "name": item.name,
            "value": value,
            "domain": domain,
            "path": item.path or "/",
            "expires": int(item.expires) if item.expires else None,
        })
    return cookies


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: session_runner.py <job_file.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        job = json.load(f)

    sink = runtime.EventSink(task_id=f"session-{job.get('account_id', '')}")
    runtime.set_sink(sink)
    setup_logging(sink)

    from core.config import Config
    from core.exceptions import LoginException, AntispiderException
    from core.request_client import init_client, get_session
    from models.user import User

    sink.emit("login_started", f"正在为 {job.get('account_label') or job['username']} 登录学习通",
              stage="session")
    try:
        config = build_config(job)
        Config._data = config
        init_client(config)

        user = User(job["username"], job["password"])
        sink.emit("login_succeeded", f"登录成功：{user.name}", stage="session")

        cookies = collect_cookies(get_session().cookies)
        sink.emit("session_result", "会话已就绪", stage="session", payload={
            "cookies": cookies,
            "display_name": user.name,
            "uid": user.uid,
            "course_count": 0,
        })
        return 0

    except LoginException as exc:
        sink.emit("session_failed", f"登录失败：{exc}", level="error", stage="session",
                  payload={"message": str(exc)})
        return 1
    except AntispiderException as exc:
        sink.emit("session_failed", f"触发反爬虫验证，请稍后重试：{exc}", level="error",
                  stage="session", payload={"message": str(exc)})
        return 1
    except Exception as exc:
        detail = traceback.format_exc()
        sink.emit("session_failed", f"会话获取异常：{exc}", level="error", stage="session",
                  payload={"message": str(exc), "traceback": detail[-1200:]})
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
