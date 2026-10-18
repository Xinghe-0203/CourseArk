"""
TaskManager：批次与子任务调度

职责：
- 维护任务状态机，展开批次为子任务并落库
- 按全局活动 Worker 上限调度 pending 任务（同账号并行由用户明确允许）
- 为每个子任务拉起一个 Worker 子进程，读取其 JSON Lines 事件
- 事件先校验任务 ID，再写 task_events/tasks，最后推送 SSE
- 暂停/继续/停止通过控制文件下达，停止优先等待协作退出，超时才强制终止
- WebUI 重启后把找不到 Worker 的非终态任务标记为 interrupted

并发精度：进程级由全局 Worker 上限控制，线程级由任务自身的视频线程数控制。
"""

import json
import os
import subprocess
import sys
import threading
import time

from . import control, events, narrative, paths, settings
from .database import Database
from .notifications import NotificationCenter
from .log_redaction import redact, redact_data

# 事件到状态/阶段的映射
STAGE_EVENTS = {
    "login_started": "logging_in",
    "login_succeeded": "loading_courses",
    "courses_loaded": "loading_courses",
    "course_started": "running",
    "stage_changed": "running",
}


class RunningTask:
    """运行期任务句柄"""

    def __init__(self, task_id: str, process: subprocess.Popen, monitor: threading.Thread):
        self.task_id = task_id
        self.process = process
        self.monitor = monitor
        self.stop_requested_at = None
        self.force_stopped = False


class TaskManager:
    def __init__(self, db: Database, hub: events.EventHub):
        self.db = db
        self.hub = hub
        self.notifications = NotificationCenter(db)
        self._lock = threading.RLock()
        self._running = {}
        self._thread = None
        self._stopping = threading.Event()
        self._cancels = {}  # task_id -> 阻止继续调度的标记

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stopping.clear()
            self._recover_interrupted()
            self._thread = threading.Thread(target=self._scheduler_loop, name="task-scheduler", daemon=True)
            self._thread.start()

    def shutdown(self, grace: float = 5.0):
        """WebUI 退出：请求所有 Worker 停止，短暂等待后强制终止"""
        self._stopping.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(grace, 2))
        with self._lock:
            task_ids = list(self._running.keys())
        for task_id in task_ids:
            try:
                control.write_command(task_id, control.STOP, reason="webui_shutdown")
            except Exception:
                pass
        deadline = time.time() + grace
        with self._lock:
            running = list(self._running.values())
        for handle in running:
            remaining = deadline - time.time()
            if remaining > 0:
                try:
                    handle.process.wait(timeout=remaining)
                except Exception:
                    pass
            if handle.process.poll() is None:
                self._terminate(handle)
            if handle.monitor is not threading.current_thread():
                handle.monitor.join(timeout=2)

    def _recover_interrupted(self):
        """重启后清点非终态任务：标记 interrupted，并清理可能残留的孤儿进程"""
        for task_id in self.db.active_task_ids():
            row = self.db.get_task(task_id)
            message = "WebUI 重启，未找到对应的 Worker 进程"
            if row and row.get("pid"):
                alive = _pid_alive(row["pid"])
                if alive:
                    message = f"WebUI 重启，检测到残留 Worker (pid={row['pid']})，已标记为被打断"
                    try:
                        control.write_command(task_id, control.STOP, reason="orphan_cleanup")
                    except Exception:
                        pass
                    time.sleep(0.2)
                    _terminate_pid(row["pid"])
            status = "interrupted"
            self.db.set_task_status(task_id, status, error=message, finished=True)
            self._record_event(task_id, row.get("account_id", "") if row else "", "interrupted",
                               message, level="warning", stage="recovery")
            if row and row.get("run_id"):
                self.db.refresh_run_status(row["run_id"])
            control.clear(task_id)

    # --------------------------------------------------------
    # 批次与子任务
    # --------------------------------------------------------

    def create_run(self, tasks: list, run_id: str, note: str = "") -> dict:
        self.db.create_run(run_id, len(tasks), source="web", note=note)
        for task in tasks:
            self.db.create_task(task)
            self.db.add_event(task["id"], task["account_id"], "task_created",
                              f"任务已创建: {task['course_name'] or task['course_id']}",
                              level="info", stage="queue",
                              payload={"feature": task["feature"], "run_id": run_id})
        return self.db.get_run(run_id)

    def retry_task(self, task_id: str) -> dict:
        """用原参数快照创建重试任务（终态任务不可直接继续）"""
        from .task_model import new_task_id

        row = self.db.get_task(task_id)
        if not row:
            raise KeyError("任务不存在")
        account = self.db.get_account_snapshot(row["account_id"]) if hasattr(self.db, "get_account_snapshot") else None
        new_id = new_task_id()
        snapshot = self._load_params(row)
        run_id = self.db.get_task(task_id)["run_id"]
        self.db.create_task({
            "id": new_id,
            "run_id": run_id,
            "account_id": row["account_id"],
            "account_label": row["account_label"],
            "course_id": row["course_id"],
            "class_id": row["class_id"],
            "cpi": row["cpi"],
            "course_name": row["course_name"],
            "feature": row["feature"],
            "status": "pending",
            "params": snapshot,
            "created_at": time.time(),
        })
        self.db.add_event(new_id, row["account_id"], "task_created",
                          f"重试任务已创建（来源 {task_id[:8]}）", level="info", stage="queue")
        if row.get("run_id"):
            self.db.refresh_run_status(row["run_id"])
        del account
        return self.db.get_task(new_id)

    @staticmethod
    def _load_params(row: dict) -> dict:
        try:
            return json.loads(row.get("params_json") or "{}")
        except ValueError:
            return {}

    # --------------------------------------------------------
    # 调度循环
    # --------------------------------------------------------

    def _scheduler_loop(self):
        while not self._stopping.is_set():
            try:
                self._tick()
            except Exception as exc:  # 调度器不允许因单次异常退出
                print(f"[scheduler] 调度异常: {exc}", file=sys.stderr)
            self._stopping.wait(1.0)

    def _tick(self):
        with self._lock:
            self._prune_finished()
            limit = int(settings.resolve("scheduler.max_active_workers", 8))
            active = len(self._running)
        if active >= limit:
            return
        for row in self.db.pending_tasks(limit=limit - active):
            with self._lock:
                if row["id"] in self._running:
                    continue
                if len(self._running) >= limit:
                    break
            self._launch(row)

    def _prune_finished(self):
        for task_id, handle in list(self._running.items()):
            if handle.process.poll() is None:
                # 停止请求超时 → 强制终止
                if handle.stop_requested_at and not handle.force_stopped:
                    grace = float(settings.resolve("scheduler.stop_grace_seconds", 25))
                    if time.time() - handle.stop_requested_at > grace:
                        self._force_stop(handle)
                continue
            if handle.monitor.is_alive():
                handle.monitor.join(timeout=2.0)
            self._running.pop(task_id, None)

    # --------------------------------------------------------
    # Worker 进程
    # --------------------------------------------------------

    def _launch(self, row: dict):
        # 排队快照可能已经过期；停止与启动共用锁，防止已停止任务被重新拉起。
        with self._lock:
            current = self.db.get_task(row["id"])
            if not current or current["status"] != "pending" or self._stopping.is_set():
                return
            self._launch_pending(current)

    def _launch_pending(self, row: dict):
        from . import accounts

        task_id = row["id"]
        account = accounts.get_account(row["account_id"], public=False)
        if not account:
            self.db.set_task_status(task_id, "failed", error="账号已被删除", finished=True)
            self.db.add_event(task_id, row["account_id"], "task_failed",
                              "账号已被删除，无法执行", level="error", stage="queue")
            if row.get("run_id"):
                self.db.refresh_run_status(row["run_id"])
            return

        task_payload = self._build_task_file(row, account)
        path = paths.task_file_path(task_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(task_payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

        control.ensure_run(task_id)
        self.db.set_task_status(task_id, "starting")
        self.db.add_event(task_id, row["account_id"], "worker_starting",
                          "正在启动 Worker 进程", level="info", stage="boot")

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["WEBUI_TASK_ID"] = task_id
        # 副本内的默认用户数据路径重定向到 WebUI 数据目录，
        # 避免 Worker 在 cli_copy 里生成 config.yml / logs 等文件
        env["AUTOCXWEBUI_DATA_DIR"] = paths.DATA_DIR

        try:
            process = subprocess.Popen(
                [sys.executable, paths.WORKER_RUNNER, path],
                cwd=paths.ROOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=0,
                universal_newlines=False,
                creationflags=_creationflags(),
            )
        except Exception as exc:
            self.db.set_task_status(task_id, "failed", error=f"Worker 启动失败: {exc}", finished=True)
            self.db.add_event(task_id, row["account_id"], "task_failed",
                              f"Worker 启动失败: {exc}", level="error", stage="boot")
            if row.get("run_id"):
                self.db.refresh_run_status(row["run_id"])
            return

        self.db.update_task(task_id, pid=process.pid)
        monitor = threading.Thread(target=self._monitor, args=(task_id, process),
                                   name=f"monitor-{task_id[:8]}", daemon=True)
        with self._lock:
            self._running[task_id] = RunningTask(task_id, process, monitor)
        monitor.start()

    def _build_task_file(self, row: dict, account: dict) -> dict:
        """组装任务文件：账号凭据 + 课程 + 功能 + 参数快照 + 外部服务配置"""
        config = settings.load()
        question_bank = config.get("question_bank", {})
        return {
            "task_id": row["id"],
            "run_id": row.get("run_id"),
            "feature": row["feature"],
            "username": account["username"],
            "password": account["password"],
            "account_id": account["id"],
            "account_label": account.get("label", ""),
            "course_id": row.get("course_id", ""),
            "class_id": row.get("class_id", ""),
            "cpi": row.get("cpi", ""),
            "course_name": row.get("course_name", ""),
            "params": self._load_params(row),
            "llm": config.get("llm", {}),
            "notification": config.get("notification", {}),
            "question_bank_path": paths.QUESTION_BANK_FILE,
            "question_bank_auto_save": bool(question_bank.get("auto_save", True)),
            "control_path": paths.control_path(row["id"]),
            "task_dir": paths.TASK_DIR,
            "log_dir": paths.LOG_DIR,
        }

    def _monitor(self, task_id: str, process: subprocess.Popen):
        """读取 Worker 的 JSON Lines 输出，解析事件并落库/推送"""
        row = self.db.get_task(task_id)
        account_id = row.get("account_id", "") if row else ""
        stream = process.stdout
        try:
            for raw in iter(stream.readline, b""):
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                self._handle_line(task_id, account_id, text)
        except Exception as exc:
            self.db.add_event(task_id, account_id, "log",
                              f"读取 Worker 输出失败: {exc}", level="error", stage="monitor")
        finally:
            try:
                stream.close()
            except Exception:
                pass

        exit_code = process.poll()
        if exit_code is None:
            try:
                exit_code = process.wait(timeout=10)
            except Exception:
                exit_code = -1

        current = self.db.get_task(task_id)
        status = current.get("status") if current else None
        keep_terminal = status in ("succeeded", "failed", "stopped", "interrupted")
        with self._lock:
            handle = self._running.get(task_id)
            forced = handle.force_stopped if handle else False

        if not keep_terminal:
            if exit_code == 0:
                final, level, message = "succeeded", "success", "任务完成"
            elif exit_code == 3:
                final, level, message = "stopped", "warning", "任务已停止"
            else:
                final, level, message = "failed", "error", f"Worker 异常退出 (exit={exit_code})"
            self.db.set_task_status(task_id, final, finished=True,
                                    error="" if final == "succeeded" else message)
            self._record_event(task_id, account_id, final, message, level=level, stage="finish")
        elif forced:
            self.db.set_task_status(task_id, "stopped", error="超过宽限时间，已强制终止", finished=True)

        if row and row.get("run_id"):
            self.db.refresh_run_status(row["run_id"])
        control.clear(task_id)

    def _handle_line(self, task_id: str, account_id: str, text: str):
        """解析单行输出：JSON 事件按协议处理，非 JSON 作为普通日志"""
        text = (text or "").strip()
        if not text:
            return
        try:
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError("非对象")
        except ValueError:
            self._record_event(task_id, account_id, "log", text[:2000], level="info", stage="raw")
            return

        # 校验任务 ID，避免串号
        if record.get("task_id") and record["task_id"] != task_id:
            self._record_event(task_id, account_id, "log",
                               f"忽略来自其它任务的事件: {record.get('task_id')}",
                               level="warning", stage="monitor")
            return

        event = record.get("event", "log")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        level = record.get("level", "info")
        stage = record.get("stage", "")
        message = redact(record.get("message", ""))
        payload = redact_data(payload)

        self._record_event(task_id, account_id, event, message, level=level, stage=stage,
                           payload=payload)
        self._apply_event(task_id, event, stage, payload, message=message)

    def _apply_event(self, task_id: str, event: str, stage: str, payload: dict, message: str = ""):
        """把事件映射为任务状态/阶段/统计的变更"""
        current = self.db.get_task(task_id)
        if not current:
            return
        status = current.get("status")
        if status in ("succeeded", "failed", "stopped", "interrupted"):
            return

        fields = {}
        if stage:
            fields["stage"] = stage

        if event in ("work_plan", "work_started", "work_progress", "work_result"):
            from .work_progress import reduce_progress
            stats = self._load_json(current.get("stats_json"))
            stats["work"] = reduce_progress(stats.get("work", {}), event, payload)
            fields["stats_json"] = json.dumps(stats, ensure_ascii=False)
        elif event == "task_progress" and payload:
            stats = self._load_json(current.get("stats_json"))
            stats.update(payload)
            fields["stats_json"] = json.dumps(stats, ensure_ascii=False)
        elif event == "exam_stats":
            stats = self._load_json(current.get("stats_json"))
            for key in ("cache_hits", "tiku_hits", "llm_calls", "random_answers"):
                if key in payload:
                    stats[key] = max(int(payload.get(key, 0) or 0), int(stats.get(key, 0) or 0))
            if payload.get("submit_ok") is not None:
                stats["submit_ok"] = int(stats.get("submit_ok", 0) or 0) + int(payload.get("submit_ok", 0) or 0)
                stats["submit_fail"] = int(stats.get("submit_fail", 0) or 0) + int(payload.get("submit_fail", 0) or 0)
            if payload.get("questions"):
                stats["questions"] = int(stats.get("questions", 0) or 0) + int(payload.get("questions", 0) or 0)
            fields["stats_json"] = json.dumps(stats, ensure_ascii=False)
        elif event == 'chapter_started':
            stats = self._load_json(current.get('stats_json'))
            stats['activity'] = {'kind': 'chapter', 'name': payload.get('chapter', ''),
                                 'current': payload.get('current'), 'total': payload.get('total')}
            fields['stats_json'] = json.dumps(stats, ensure_ascii=False)
        elif event == "task_succeeded":
            stats = self._load_json(current.get("stats_json"))
            stats.update(payload.get("stats") or {})
            if fields:
                self.db.update_task(task_id, **fields)
            self.db.update_task(task_id, stats_json=json.dumps(stats, ensure_ascii=False))
            self._finish(task_id, "succeeded", "")
            return
        elif event == "task_failed":
            if payload.get("stats"):
                stats = self._load_json(current.get('stats_json'))
                stats.update(payload['stats'])
                self.db.update_task(task_id, stats_json=json.dumps(stats, ensure_ascii=False))
            self._finish(task_id, "failed", payload.get("message") or message or "任务执行失败")
            return
        elif event == "task_stopped":
            if payload.get("stats"):
                stats = self._load_json(current.get('stats_json'))
                stats.update(payload['stats'])
                self.db.update_task(task_id, stats_json=json.dumps(stats, ensure_ascii=False))
            self._finish(task_id, "stopped", "")
            return
        elif event == "paused":
            if status in ("running", "pausing", "logging_in", "loading_courses", "starting"):
                fields["status"] = "paused"
        elif event == "resumed":
            if status in ("paused", "pausing"):
                fields["status"] = "running"
        elif event == "login_failed":
            if fields:
                self.db.update_task(task_id, **fields)
            self._finish(task_id, "failed", payload.get("message") or message or "学习通登录失败")
            return
        elif event == "media_progress":
            stats = self._load_json(current.get("stats_json"))
            stats["progress"] = payload
            fields["stats_json"] = json.dumps(stats, ensure_ascii=False)
        elif event == "stop_requested":
            if status != "stopping":
                fields["status"] = "stopping"
        elif event == "worker_exit":
            return

        if event in STAGE_EVENTS and status in ("starting", "logging_in", "loading_courses", "pending"):
            fields.setdefault("status", STAGE_EVENTS[event])

        if fields:
            self.db.update_task(task_id, **fields)

    def _finish(self, task_id: str, status: str, error: str):
        row = self.db.get_task(task_id)
        if not row:
            return
        self.db.set_task_status(task_id, status, error=redact(error), finished=True)
        if row.get("run_id"):
            self.db.refresh_run_status(row["run_id"])

    @staticmethod
    def _load_json(text) -> dict:
        try:
            data = json.loads(text or "{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def _record_event(self, task_id: str, account_id: str, event: str, message: str,
                      level: str = "info", stage: str = "", payload: dict = None):
        """落库事件 -> 生成叙事 -> 更新通知中心 -> 推送 SSE"""
        message = redact(message)
        payload = redact_data(payload)
        event_id = self.db.add_event(task_id, account_id, event, message,
                                     level=level, stage=stage, payload=payload)

        task = self.db.get_task(task_id) or {}
        feature = task.get("feature", "")
        narrative_item = narrative.describe(event, message, level=level, stage=stage,
                                           payload=payload, feature=feature)

        record = events.make_record(
            event_id, task_id, account_id, event, message,
            level=level, stage=stage, payload=payload,
            narrative=narrative_item,
            context={
                "account_label": task.get("account_label", ""),
                "course_name": task.get("course_name", ""),
                "feature_label": narrative.feature_label(feature) if feature else "",
            },
        )
        self.hub.publish(record)

        # 需要人处理的问题进入持久化通知中心（不自动消失）
        try:
            self.notifications.record(
                event=event, level=level, message=message, task_id=task_id,
                account_id=account_id,
                account_label=task.get("account_label", ""),
                course_name=task.get("course_name", ""),
                feature_label=narrative.feature_label(feature) if feature else "",
                stage=stage,
            )
        except Exception:
            pass  # 通知写入失败不应影响任务事件流
        return record

    # --------------------------------------------------------
    # 控制命令
    # --------------------------------------------------------

    def pause(self, task_id: str) -> dict:
        return self._command(task_id, "pause", allowed=("running", "starting", "logging_in", "loading_courses"))

    def resume(self, task_id: str) -> dict:
        return self._command(task_id, "resume", allowed=("paused", "pausing"))

    def stop(self, task_id: str) -> dict:
        with self._lock:
            return self._stop(task_id)

    def _stop(self, task_id: str) -> dict:
        row = self.db.get_task(task_id)
        if not row:
            raise KeyError("任务不存在")
        status = row.get("status")
        if status in ("succeeded", "failed", "stopped", "interrupted"):
            raise ValueError("终态任务不可停止，可用重试创建新任务")
        control.write_command(task_id, control.STOP, reason="user")
        self.db.set_task_status(task_id, "stopping")
        self._record_event(task_id, row["account_id"], "stop_requested",
                           "用户请求停止任务", level="warning", stage="control")
        with self._lock:
            handle = self._running.get(task_id)
            if handle and handle.stop_requested_at is None:
                handle.stop_requested_at = time.time()
            if handle is None and status == "pending":
                self.db.set_task_status(task_id, "stopped", error="任务在开始前被停止", finished=True)
                if row.get("run_id"):
                    self.db.refresh_run_status(row["run_id"])
        return self.db.get_task(task_id)

    def _command(self, task_id: str, command: str, allowed: tuple) -> dict:
        with self._lock:
            return self._command_locked(task_id, command, allowed)

    def _command_locked(self, task_id: str, command: str, allowed: tuple) -> dict:
        row = self.db.get_task(task_id)
        if not row:
            raise KeyError("任务不存在")
        status = row.get("status")
        if status in ("succeeded", "failed", "stopped", "interrupted"):
            raise ValueError("终态任务不可控制")
        if status not in allowed:
            raise ValueError(f"当前状态({status})不允许该操作")

        if command == "pause":
            control.write_command(task_id, control.PAUSE, reason="user")
            self.db.set_task_status(task_id, "pausing")
            self._record_event(task_id, row["account_id"], "pause_requested",
                               "用户请求暂停任务", level="info", stage="control")
        else:
            control.write_command(task_id, control.RUN, reason="user")
            self.db.set_task_status(task_id, "running")
            self._record_event(task_id, row["account_id"], "resume_requested",
                               "用户请求继续任务", level="info", stage="control")
        return self.db.get_task(task_id)

    def _force_stop(self, handle: RunningTask):
        handle.force_stopped = True
        row = self.db.get_task(handle.task_id)
        self._record_event(handle.task_id, row["account_id"] if row else "",
                           "force_stop", "Worker 未在宽限时间内退出，已强制终止",
                           level="warning", stage="control")
        self._terminate(handle)
        self.db.set_task_status(handle.task_id, "stopped",
                                error="超过宽限时间，已强制终止", finished=True)
        if row and row.get("run_id"):
            self.db.refresh_run_status(row["run_id"])

    @staticmethod
    def _terminate(handle: RunningTask):
        try:
            if handle.process.poll() is None:
                handle.process.terminate()
                try:
                    handle.process.wait(timeout=5)
                except Exception:
                    handle.process.kill()
        except Exception:
            pass

    # --------------------------------------------------------
    # 查询
    # --------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            running = len(self._running)
        return {
            "running": running,
            "limit": int(settings.resolve("scheduler.max_active_workers", 8)),
            "busy": running,
        }


# ============================================================
# 平台工具
# ============================================================

def _creationflags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:
            return False
    return False


def _terminate_pid(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           check=False, capture_output=True)
        else:
            os.kill(pid, 15)
    except Exception:
        pass
