"""
学习通会话服务

两条能力：
1. 用账号密码换取登录 Cookie 并保存在数据库里（会话缓存）
2. 把缓存或新取的 Cookie 注入真实浏览器，打开学习通课程页面，
   实现"一键登录已登录状态的学习通"

Cookie 只保存在本机数据库里，接口只返回数量与时间，不回传 Cookie 内容。
"""

import json
import os
import subprocess
import sys
import threading
import time

from . import accounts, paths, settings
from .store import SettingsStore

SESSION_KEY = "chaoxing_sessions"

# 学习通入口：i.chaoxing.com 是个人主页，登录态下直接展示自己的课程
CHAOXING_HOME = "https://i.chaoxing.com/"
CHAOXING_COURSES = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courses/list"

_lock = threading.RLock()
_running = {}  # account_id -> {"process": Popen, "started_at": float}


class SessionService:
    """
    会话缓存与会话获取

    store 惰性创建：数据库路径由 paths.DATABASE_FILE 决定，
    不能在导入时绑定（那时路径可能还没被配置好，测试也会隔离失败）。
    """

    def __init__(self, store=None):
        self._store = store
        self._last_result = {}
        self._browser_states = {}
        self._browser_stop_events = {}
        self._browser_threads = {}
        self._shutting_down = False

    @property
    def store(self) -> SettingsStore:
        if self._store is None:
            self._store = SettingsStore()
        return self._store

    # --------------------------------------------------------
    # 会话缓存
    # --------------------------------------------------------

    def _all(self) -> dict:
        data = self.store.get(SESSION_KEY, {})
        return data if isinstance(data, dict) else {}

    def get(self, account_id: str) -> dict:
        entry = self._all().get(account_id) or {}
        return entry

    def save(self, account_id: str, cookies: list, display_name: str = "", uid: str = ""):
        with _lock:
            data = self._all()
            data[account_id] = {
                "cookies": cookies,
                "count": len(cookies),
                "display_name": display_name,
                "uid": uid,
                "saved_at": time.time(),
            }
            self.store.set(SESSION_KEY, data)

    def drop(self, account_id: str):
        with _lock:
            data = self._all()
            if account_id in data:
                data.pop(account_id)
                self.store.set(SESSION_KEY, data)

    def status(self, account_id: str) -> dict:
        """对外状态：只暴露是否存在、时间与数量，不泄露 Cookie 内容"""
        entry = self.get(account_id)
        if not entry:
            return {"has_session": False, "browser": self._browser_states.get(account_id, {})}
        return {
            "has_session": bool(entry.get("cookies")),
            "cookie_count": entry.get("count", 0),
            "saved_at": entry.get("saved_at"),
            "display_name": entry.get("display_name", ""),
            "fresh": (time.time() - float(entry.get("saved_at") or 0)) < 6 * 3600,
            "browser": self._browser_states.get(account_id, {}),
        }

    def is_fetching(self, account_id: str) -> bool:
        with _lock:
            return account_id in _running

    def shutdown(self, grace: float = 3.0) -> None:
        """Close Playwright browsers and stop session subprocesses before API exit."""
        deadline = time.monotonic() + max(0.0, grace)
        with _lock:
            self._shutting_down = True
            browser_events = list(self._browser_stop_events.items())
            browser_threads = list(self._browser_threads.items())
            for _, stop_event in browser_events:
                stop_event.set()
        for _, thread in browser_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

        with _lock:
            running = list(_running.items())
        for account_id, reservation in running:
            process = reservation.get("process")
            if process is not None:
                self._stop_process(process, max(0.1, deadline - time.monotonic()))
            with _lock:
                if _running.get(account_id) is reservation:
                    _running.pop(account_id, None)

    @staticmethod
    def _stop_process(process, grace: float) -> None:
        try:
            if process.poll() is not None:
                return
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=max(0.1, grace))
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        try:
            process.kill()
            process.wait(timeout=max(1.0, grace))
        except Exception:
            pass

    # --------------------------------------------------------
    # 获取会话（子进程登录）
    # --------------------------------------------------------

    def fetch(self, account_id: str, blocking: bool = False) -> dict:
        account = accounts.get_account(account_id, public=False)
        if not account:
            raise KeyError("账号不存在")
        with _lock:
            if self._shutting_down:
                raise RuntimeError("本机服务正在关闭")
            if self.is_fetching(account_id):
                return {"started": False, "reason": "该账号正在获取会话"}
            # 先预留账号，包含创建进程和读取结果期间，避免重复请求覆盖任务文件。
            _running[account_id] = {"process": None, "started_at": time.time()}
            self._last_result.pop(account_id, None)

        job = {
            "account_id": account["id"],
            "account_label": account.get("label", ""),
            "username": account["username"],
            "password": account["password"],
            "question_bank_path": paths.QUESTION_BANK_FILE,
            "task_dir": paths.TASK_DIR,
            "advanced": settings.resolve("advanced", {}),
        }
        try:
            job_path = os.path.join(paths.TASK_DIR, f"session-{account['id']}.json")
            os.makedirs(os.path.dirname(job_path), exist_ok=True)
            tmp = job_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(job, f, ensure_ascii=False, indent=2)
            os.replace(tmp, job_path)

            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env["AUTOCXWEBUI_DATA_DIR"] = paths.DATA_DIR

            process = subprocess.Popen(
                [sys.executable, os.path.join(paths.ROOT_DIR, "worker", "session_runner.py"), job_path],
                cwd=paths.ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception as exc:
            with _lock:
                _running.pop(account_id, None)
            raise RuntimeError("无法启动会话获取进程") from exc
        with _lock:
            shutting_down = self._shutting_down
            if shutting_down:
                _running.pop(account_id, None)
            else:
                _running[account_id] = {"process": process, "started_at": time.time()}
        if shutting_down:
            self._stop_process(process, 1.0)
            raise RuntimeError("本机服务正在关闭")

        def _consume():
            failure = None
            result = None
            code = -1
            try:
                for raw in iter(process.stdout.readline, b""):
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    event = record.get("event", "")
                    payload = record.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue
                    if event == "session_result":
                        result = payload
                    elif event == "session_failed":
                        failure = record.get("message", "会话获取失败")
            except Exception:
                failure = "读取会话结果失败，请重试"
            finally:
                try:
                    process.stdout.close()
                except Exception:
                    pass
                try:
                    code = process.wait(timeout=10)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception:
                        pass
                try:
                    cookies = self._browser_cookies((result or {}).get("cookies") or [])
                    if not failure and (code != 0 or not cookies):
                        failure = "会话获取未返回有效登录信息，请检查账号密码后重试"
                    if failure:
                        accounts.mark_login(account_id, False, error=failure)
                    else:
                        self.save(account_id, cookies, result.get("display_name", ""), result.get("uid", ""))
                        accounts.mark_login(account_id, True, display_name=result.get("display_name", ""))
                except Exception:
                    failure = "保存登录会话失败，请重试"
                finally:
                    with _lock:
                        self._last_result[account_id] = {
                            "ok": not bool(failure), "message": failure or "会话已保存", "at": time.time(),
                        }
                        _running.pop(account_id, None)

        if blocking:
            _consume()
        else:
            threading.Thread(target=_consume, name=f"session-{account_id[:8]}", daemon=True).start()
        return {"started": True, "reason": ""}

    def last_result(self, account_id: str) -> dict:
        return getattr(self, "_last_result", {}).get(account_id, {})

    # --------------------------------------------------------
    # 用会话打开浏览器
    # --------------------------------------------------------

    def open_browser(self, account_id: str, url: str = "") -> dict:
        """
        带着已保存的 Cookie 打开真实浏览器

        使用 Playwright 启动独立浏览器上下文，把 Cookie 注入后再跳转，
        因此打开时就已经是登录状态，不需要再次输入账号密码。
        """
        entry = self.get(account_id)
        if not entry or not entry.get("cookies"):
            raise ValueError("该账号还没有可用会话，请先获取会话")
        with _lock:
            if self._shutting_down:
                raise RuntimeError("本机服务正在关闭")

        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            raise RuntimeError("未安装 Playwright，无法打开浏览器。请执行 pip install playwright")

        target = url or CHAOXING_HOME
        cookies = self._browser_cookies(entry["cookies"])
        ready = threading.Event()
        stop_event = threading.Event()
        outcome = {}
        self._browser_states[account_id] = {"state": "starting", "message": "正在打开浏览器"}

        def _launch():
            browser = None
            try:
                with sync_playwright() as playwright:
                    try:
                        browser = self._launch_browser(playwright)
                        context = browser.new_context(locale="zh-CN")
                        try:
                            context.add_cookies(cookies)
                        except Error:
                            for cookie in cookies:
                                try:
                                    context.add_cookies([cookie])
                                except Error:
                                    continue
                        page = context.new_page()
                        page.goto(target, wait_until="domcontentloaded", timeout=30000)
                        outcome["opened"] = True
                        with _lock:
                            if self._browser_stop_events.get(account_id) is stop_event:
                                self._browser_states[account_id] = {
                                    "state": "opened", "message": "学习通已打开",
                                }
                        ready.set()
                        # 轮询只发生在创建 Playwright 的同一线程；退出时关闭 browser 以结束其 Node/Chromium 子进程。
                        while not stop_event.wait(0.25):
                            try:
                                if not browser.is_connected():
                                    break
                            except Error:
                                break
                    finally:
                        if browser is not None:
                            try:
                                browser.close()
                            except Error:
                                pass
            except Exception as exc:
                outcome["error"] = str(exc)
                with _lock:
                    if self._browser_stop_events.get(account_id) is stop_event:
                        self._browser_states[account_id] = {
                            "state": "failed", "message": "浏览器启动失败，请重试",
                        }
            finally:
                ready.set()
                with _lock:
                    if (outcome.get("opened")
                            and self._browser_stop_events.get(account_id) is stop_event):
                        self._browser_states[account_id] = {
                            "state": "closed", "message": "浏览器已关闭",
                        }
                    if self._browser_stop_events.get(account_id) is stop_event:
                        self._browser_stop_events.pop(account_id, None)
                    if self._browser_threads.get(account_id) is threading.current_thread():
                        self._browser_threads.pop(account_id, None)

        thread = threading.Thread(target=_launch, name=f"browser-{account_id[:8]}", daemon=True)
        with _lock:
            if self._shutting_down:
                raise RuntimeError("本机服务正在关闭")
            previous_event = self._browser_stop_events.get(account_id)
            previous_thread = self._browser_threads.get(account_id)
            if previous_event is not None:
                previous_event.set()
            self._browser_stop_events[account_id] = stop_event
            self._browser_threads[account_id] = thread
            thread.start()
        if previous_thread and previous_thread is not threading.current_thread():
            previous_thread.join(timeout=1.0)
        if not ready.wait(timeout=40):
            stop_event.set()
            thread.join(timeout=1.0)
            raise RuntimeError("打开浏览器超时，请检查网络或本机浏览器")
        if not outcome.get("opened"):
            raise RuntimeError(outcome.get("error") or "打开浏览器失败")
        return {
            "opened": True,
            "url": target,
            "cookie_count": len(cookies),
            "note": "已在本机浏览器中打开学习通（登录态）。关闭该浏览器窗口即可退出。",
        }

    @staticmethod
    def _browser_cookies(raw_cookies: list) -> list:
        """把保存的 Cookie 转成 Playwright 需要的格式"""
        cookies = []
        for item in raw_cookies or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if not name or value is None:
                continue
            domain = item.get("domain") or ".chaoxing.com"
            cookie = {
                "name": name,
                "value": str(value),
                "domain": domain,
                "path": item.get("path") or "/",
            }
            expires = item.get("expires")
            if expires:
                cookie["expires"] = int(expires)
            cookies.append(cookie)
        return cookies

    @staticmethod
    def _launch_browser(playwright):
        """
        启动浏览器

        优先使用 Playwright 自带 Chromium；本机未下载时回退到系统安装的
        Chrome / Edge（channel 方式），避免因缺少浏览器而完全不可用。
        """
        errors = []
        try:
            return playwright.chromium.launch(headless=False)
        except Exception as exc:
            errors.append(f"chromium: {exc}")
        for channel in ("chrome", "msedge"):
            try:
                return playwright.chromium.launch(headless=False, channel=channel)
            except Exception as exc:
                errors.append(f"{channel}: {exc}")
        raise RuntimeError("无法启动浏览器（已尝试 Chromium/Chrome/Edge）：" + "; ".join(errors))
