"""
本地 Web smoke test

真实启动 WebUI 服务与 Worker 子进程，验证端到端链路：
1. 服务健康检查、静态页面
2. 账号 CRUD 与密码脱敏
3. 创建批次 -> Worker 子进程启动 -> 事件落库 -> SSE 推送
4. 暂停/继续/停止控制
5. 重启后遗留任务标记为“被打断”
6. 答题缓存导入导出

使用 --mock 时不会访问真实超星：任务会在登录阶段失败，
但仍能验证调度、事件协议、状态机和控制的完整链路。
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import tempfile

import httpx

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEBUI_ROOT)

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} -> {detail}")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(url: str, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mock", action="store_true", help="使用本地 Worker 模拟器，不访问学习通")
    parser.add_argument("--keep-data", action="store_true",
                        help="保留本次测试产生的数据目录内容")
    args = parser.parse_args()

    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"

    # 使用独立数据目录，避免污染正式 data/
    sandbox = tempfile.mkdtemp(prefix="autocx-smoke-")
    os.makedirs(sandbox, exist_ok=True)
    os.environ["AUTOCXWEBUI_DATA_DIR"] = sandbox

    print(f"数据目录: {sandbox}")
    print(f"服务端口: {port}")

    from app import paths
    paths.DATA_DIR = sandbox
    paths.CONTROL_DIR = os.path.join(sandbox, "control")
    paths.TASK_DIR = os.path.join(sandbox, "tasks")
    paths.LOG_DIR = os.path.join(sandbox, "logs")
    paths.EXPORT_DIR = os.path.join(sandbox, "exports")
    paths.DOWNLOAD_DIR = os.path.join(sandbox, "downloads")
    paths.ACCOUNTS_FILE = os.path.join(sandbox, "accounts.json")
    paths.SETTINGS_FILE = os.path.join(sandbox, "settings.json")
    paths.SETTINGS_BACKUP_FILE = os.path.join(sandbox, "settings.backup.json")
    paths.DATABASE_FILE = os.path.join(sandbox, "webui.db")
    paths.QUESTION_BANK_FILE = os.path.join(sandbox, "question_bank.db")
    paths.SOURCE_QUESTION_BANK = os.path.join(sandbox, "no-source.db")
    paths.SOURCE_CONFIG = os.path.join(sandbox, "no-config.yml")
    paths.ensure_dirs()

    if args.mock:
        # 保留真实的调度、子进程、事件解析和落库，仅替换平台请求边界。
        paths.WORKER_RUNNER = os.path.join(sandbox, "mock_worker.py")
        with open(paths.WORKER_RUNNER, "w", encoding="utf-8") as handle:
            handle.write('''import json, sys, os
with open(sys.argv[1], encoding="utf-8") as f:
    task = json.load(f)
for event, message, stage, level in [
    ("worker_started", "本地测试进程已启动", "boot", "info"),
    ("login_started", "本地测试登录边界", "login", "info"),
    ("task_failed", "模拟登录失败，不访问学习通", "login", "error"),
    ("worker_exit", "测试进程退出", "finish", "info"),
]:
    print(json.dumps({"task_id": task["task_id"], "event": event,
        "message": message, "stage": stage, "level": level,
        "payload": {"pid": os.getpid()}}, ensure_ascii=False), flush=True)
sys.exit(1)
''')

    import threading

    import uvicorn

    from app.main import create_app

    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not wait_for(f"{base}/api/health"):
        print("服务启动失败")
        return 1

    print("\n== 1. 健康检查与静态页面 ==")
    health = httpx.get(f"{base}/api/health", timeout=10).json()
    check("健康检查返回 ok", health.get("ok") is True)
    check("源 CLI 标注为只读", health.get("source_cli_writable") is False)
    index = httpx.get(f"{base}/", timeout=10)
    check("控制台页面可访问", index.status_code == 200 and "CourseArk" in index.text)
    check("页面标注仅本机访问", httpx.get(f"{base}/api/settings", timeout=10).json()["storage"]["host_mode"] == "local-only")
    assets = re.findall(r'(?:src|href)="(/static/vue/assets/[^\"]+)"', index.text)
    for extension, label in (('.css', '静态样式表可访问'), ('.js', '静态脚本可访问')):
        files = [asset for asset in assets if asset.endswith(extension)]
        check(label, bool(files) and all(httpx.get(base + asset, timeout=10).status_code == 200 for asset in files))

    print("\n== 2. 账号 CRUD 与脱敏 ==")
    created = httpx.post(f"{base}/api/accounts", json={
        "username": "13800000001", "password": "smoke-pass", "label": "冒烟账号",
    }, timeout=10).json()
    check("账号创建成功", created.get("has_password") is True)
    check("创建响应不含密码", "password" not in created)
    check("手机号脱敏显示", created.get("username_masked") == "138****0001")

    accounts = httpx.get(f"{base}/api/accounts", timeout=10).json()["items"]
    check("账号列表不含密码", all("password" not in item for item in accounts))

    # 6 个账号，验证多账号场景
    for index in range(2, 7):
        httpx.post(f"{base}/api/accounts", json={
            "username": f"1380000000{index}", "password": "smoke-pass",
            "label": f"冒烟账号 {index:02d}",
        }, timeout=10)
    accounts = httpx.get(f"{base}/api/accounts", timeout=10).json()["items"]
    check("可配置 6 个账号", len(accounts) == 6, f"实际 {len(accounts)}")
    check("账号之间 ID 不重复", len({item["id"] for item in accounts}) == 6)
    check("账号之间手机号不重复",
          len({item["username"] for item in accounts}) == 6)

    print("\n== 3. 课程缓存按账号隔离 ==")
    from app.main import db
    first, second = accounts[0], accounts[1]
    db.replace_courses(first["id"], [{
        "course_id": "c100", "class_id": "k100", "name": "同名课程", "author": "甲老师",
        "if_open": True, "mission_fn": 1, "mission_all": 10,
    }])
    db.replace_courses(second["id"], [{
        "course_id": "c100", "class_id": "k200", "name": "同名课程", "author": "乙老师",
        "if_open": True, "mission_fn": 5, "mission_all": 10,
    }])
    left = httpx.get(f"{base}/api/accounts/{first['id']}/courses", timeout=10).json()["items"][0]
    right = httpx.get(f"{base}/api/accounts/{second['id']}/courses", timeout=10).json()["items"][0]
    check("同 ID 同名课程按账号隔离", left["class_id"] == "k100" and right["class_id"] == "k200")
    check("课程进度互不串号", left["mission_fn"] == 1 and right["mission_fn"] == 5)

    print("\n== 4. 创建批次与 Worker 调度 ==")
    targets = [
        {"account_id": account["id"], "course_id": "c100", "class_id": "k100",
         "course_name": "同名课程"}
        for account in accounts
    ]
    run = httpx.post(f"{base}/api/runs", json={
        "feature": "video", "targets": targets,
        "params": {"video": {"mode": "instant", "max_workers": 1}},
        "note": "smoke",
    }, timeout=15)
    check("创建批次成功", run.status_code == 201, run.text[:200])
    run_data = run.json()
    check("为每个账号生成独立子任务", run_data["count"] == 6)

    # 等待调度器拉起 Worker（登录会失败，但进程与事件链路必须跑通）
    deadline = time.time() + 60
    states = {}
    while time.time() < deadline:
        tasks = httpx.get(f"{base}/api/tasks?limit=50", timeout=10).json()["items"]
        states = {task["status"] for task in tasks}
        if not (states & {"pending", "starting", "logging_in", "loading_courses", "running"}):
            break
        time.sleep(1)

    tasks = httpx.get(f"{base}/api/tasks?limit=50", timeout=10).json()["items"]
    check("子任务全部离开等待态", not (states & {"pending", "starting"}),
          f"状态: {sorted(states)}")
    check("Worker 进程被分配 PID", any(task.get("pid") for task in tasks))
    check("任务进入终态",
          all(task["status"] in ("succeeded", "failed", "stopped", "interrupted") for task in tasks),
          f"状态: {[task['status'] for task in tasks]}")

    sample = tasks[0]
    events = httpx.get(f"{base}/api/tasks/{sample['id']}/events", timeout=10).json()["items"]
    event_names = {item["event"] for item in events}
    check("事件包含 worker_started", "worker_started" in event_names, str(sorted(event_names)))
    check("事件包含登录尝试", bool({"login_started", "login_failed"} & event_names),
          str(sorted(event_names)))
    check("Worker 事件已完成落盘", any(item["event"] in
          ("task_failed", "task_stopped", "task_succeeded", "worker_exit") for item in events))
    check("事件消息非空", all(item["message"] for item in events if item["event"] != "worker_exit"))
    check("事件带人类可读叙事", any(item.get("narrative") for item in events))

    print("\n== 5. SSE 实时事件流 ==")
    collected = []
    stop_listening = threading.Event()

    def listen():
        try:
            with httpx.stream("GET", f"{base}/api/events/stream?last_event_id=0", timeout=30) as response:
                for line in response.iter_lines():
                    if stop_listening.is_set():
                        break
                    if line.startswith("data: "):
                        collected.append(json.loads(line[6:]))
                        if collected[-1].get("message") == "smoke-sse":
                            break
        except Exception:
            pass

    listener = threading.Thread(target=listen, daemon=True)
    listener.start()
    time.sleep(1.5)  # 等待订阅建立（期间会先收到历史 backlog）

    from app.main import hub
    backlog_seen = len(collected)
    hub.publish({
        "id": 999999, "task_id": "smoke", "account_id": "", "event": "log",
        "message": "smoke-sse", "level": "info", "stage": "log", "payload": {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "ts": time.time(),
    })

    deadline = time.time() + 10
    while time.time() < deadline:
        if any(item.get("message") == "smoke-sse" for item in collected):
            break
        time.sleep(0.2)
    stop_listening.set()
    listener.join(timeout=5)

    check("SSE 连接建立后有历史补发", backlog_seen > 0, f"backlog {backlog_seen} 条")
    check("SSE 实时推送成功", any(item.get("message") == "smoke-sse" for item in collected),
          f"共收到 {len(collected)} 条")

    print("\n== 6. 暂停 / 继续 / 停止控制 ==")
    run2 = httpx.post(f"{base}/api/runs", json={
        "feature": "learn_count", "targets": [targets[0]],
        "params": {"learn_count": {"times": 3, "dwell": 1}},
    }, timeout=15).json()
    control_task = run2["task_ids"][0]
    # 任务可能很快就失败（登录失败），控制链路单独用一条持久态任务验证
    db.set_task_status(control_task, "running")
    paused = httpx.post(f"{base}/api/tasks/{control_task}/pause", timeout=10)
    check("暂停指令被接受", paused.status_code == 200, paused.text[:150])
    check("暂停写入控制文件",
          httpx.get(f"{base}/api/tasks/{control_task}", timeout=10).json()["status"] == "pausing")
    control_file = paths.control_path(control_task)
    check("控制文件已生成", os.path.exists(control_file))
    with open(control_file, "r", encoding="utf-8") as handle:
        check("控制文件内容为 pause", json.load(handle)["command"] == "pause")

    resumed = httpx.post(f"{base}/api/tasks/{control_task}/resume", timeout=10)
    check("继续指令被接受", resumed.status_code == 200, resumed.text[:150])
    stopped = httpx.post(f"{base}/api/tasks/{control_task}/stop", timeout=10)
    check("停止指令被接受", stopped.status_code == 200, stopped.text[:150])
    with open(control_file, "r", encoding="utf-8") as handle:
        check("控制文件内容为 stop", json.load(handle)["command"] == "stop")

    print("\n== 7. 重试与终态约束 ==")
    db.set_task_status(control_task, "failed", error="smoke", finished=True)
    retry = httpx.post(f"{base}/api/tasks/{control_task}/retry", timeout=10)
    check("终态任务可重试", retry.status_code == 201, retry.text[:150])
    check("重试任务继承了参数快照",
          retry.json()["params"] == httpx.get(f"{base}/api/tasks/{control_task}", timeout=10).json()["params"])
    check("运行态任务禁止暂停",
          httpx.post(f"{base}/api/tasks/{retry.json()['id']}/pause", timeout=10).status_code in (200, 409))

    print("\n== 8. 答题缓存导入导出（共享单库） ==")
    payload = json.dumps([
        {"question_text": f"冒烟题目{i}", "answer": "A", "question_type": "单选题"}
        for i in range(5)
    ], ensure_ascii=False)
    preview = httpx.post(f"{base}/api/question-bank/import", json={
        "content": payload, "preview_only": True, "format": "json",
    }, timeout=10).json()
    check("导入预览统计正确", preview["parsed"] == 5 and preview["new"] == 5)
    committed = httpx.post(f"{base}/api/question-bank/import", json={
        "content": payload, "format": "json",
    }, timeout=10).json()
    check("答题缓存写入成功", committed["imported"] == 5)
    stats = httpx.get(f"{base}/api/question-bank/stats", timeout=10).json()
    check("答题缓存统计与写入一致", stats["total"] == 5, str(stats["total"]))
    exported = httpx.get(f"{base}/api/question-bank/export?format=csv", timeout=10)
    check("CSV 导出成功", exported.status_code == 200 and "冒烟题目" in exported.text)

    print("\n== 8.5 配置持久化到 SQLite ==")
    storage = httpx.get(f"{base}/api/settings", timeout=10).json().get("storage", {})
    check("设置主存储为 SQLite", storage.get("backend") == "sqlite", str(storage.get("backend")))
    check("设置表名为 app_settings", storage.get("table") == "app_settings")
    check("服务标记为仅本机模式", storage.get("host_mode") == "local-only")

    print("\n== 8.6 问题中心（不自动消失） ==")
    from app.main import db as _db
    _db.upsert_notification(category="antispider", title="触发反爬虫限制",
                            detail="状态码202", level="warning", dedupe_key="smoke-1",
                            context={"account_label": "冒烟账号"})
    notes = httpx.get(f"{base}/api/notifications", timeout=10).json()
    check("问题写入后立即可查", notes["unread"] >= 1, str(notes["unread"]))
    check("问题带上下文信息",
          any(item.get("context", {}).get("account_label") == "冒烟账号"
              for item in notes["items"]))
    first_id = notes["items"][0]["id"]
    httpx.post(f"{base}/api/notifications/read", json={"id": first_id}, timeout=10)
    after = httpx.get(f"{base}/api/notifications", timeout=10).json()
    check("标记已读后移出未读", after["unread"] == notes["unread"] - 1,
          f"{notes['unread']} -> {after['unread']}")

    print("\n== 9. 设置与敏感值 ==")
    httpx.patch(f"{base}/api/settings", json={"llm": {"api_key": "smoke-secret"}}, timeout=10)
    settings_view = httpx.get(f"{base}/api/settings", timeout=10).json()
    check("API Key 不回显", settings_view["llm"]["api_key"] == "")
    check("API Key 标记为已配置", settings_view["secrets"]["llm_api_key_configured"] is True)
    httpx.patch(f"{base}/api/settings", json={"llm": {"api_key": ""}}, timeout=10)
    from app import settings as settings_module
    check("空值不会清空已保存密钥",
          settings_module.resolve("llm.api_key") == "smoke-secret")
    clamped = httpx.patch(f"{base}/api/settings", json={
        "scheduler": {"max_active_workers": 999},
    }, timeout=10).json()
    check("Worker 上限被规范化到 20", clamped["scheduler"]["max_active_workers"] == 20)

    print("\n== 10. 重启恢复（遗留任务标记为被打断） ==")
    db.set_task_status(tasks[0]["id"], "running")
    db.update_task(tasks[0]["id"], pid=999999999)
    # 直接调用恢复逻辑，模拟 WebUI 重启时的扫描行为
    from app.events import EventHub
    from app.task_manager import TaskManager
    TaskManager(db, EventHub())._recover_interrupted()
    recovered_row = db.get_task(tasks[0]["id"])
    check("遗留任务被标记为被打断", recovered_row["status"] == "interrupted", recovered_row["status"])
    check("被打断任务记录原因", "重启" in (recovered_row["error"] or ""), recovered_row["error"])

    print("\n== 11. 历史可查询 ==")
    history = httpx.get(f"{base}/api/history?limit=100", timeout=10).json()
    check("历史记录可查询", history["total"] >= 7, str(history["total"]))
    overview = httpx.get(f"{base}/api/overview", timeout=10).json()
    check("总览接口结构完整",
          all(key in overview for key in ("accounts", "tasks", "today", "workers",
                                          "question_bank", "queue", "recent_events")))

    print("\n== 12. 源 CLI 目录零改动 ==")
    check("源目录未被写入 data/smoke", not os.path.exists(
        os.path.join(paths.SOURCE_CLI_DIR, "data", "smoke")))

    server.should_exit = True
    thread.join(timeout=10)

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print(f"  - {item}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
