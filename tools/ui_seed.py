"""
UI 验收用种子服务

在独立数据目录（data/uitest）里准备真实感的数据：
- 6 个账号（含登录成功/失败/未验证状态）
- 每个账号各自隔离的课程缓存
- 覆盖各种状态的任务与事件（运行中/暂停/成功/失败/被打断）
- 一批题库题目

仅用于界面验收，不影响正式 data/。
"""

import json
import os
import sys
import time

WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEBUI_ROOT)

SANDBOX = os.environ.get("UI_SEED_DIR") or os.path.join(WEBUI_ROOT, "data", "uitest")
os.environ['AUTOCXWEBUI_DATA_DIR'] = SANDBOX
os.makedirs(SANDBOX, exist_ok=True)

from app import paths  # noqa: E402

paths.DATA_DIR = SANDBOX
paths.CONTROL_DIR = os.path.join(SANDBOX, "control")
paths.TASK_DIR = os.path.join(SANDBOX, "tasks")
paths.LOG_DIR = os.path.join(SANDBOX, "logs")
paths.EXPORT_DIR = os.path.join(SANDBOX, "exports")
paths.DOWNLOAD_DIR = os.path.join(SANDBOX, "downloads")
paths.ACCOUNTS_FILE = os.path.join(SANDBOX, "accounts.json")
paths.SETTINGS_FILE = os.path.join(SANDBOX, "settings.json")
paths.SETTINGS_BACKUP_FILE = os.path.join(SANDBOX, "settings.backup.json")
paths.DATABASE_FILE = os.path.join(SANDBOX, "webui.db")
paths.QUESTION_BANK_FILE = os.path.join(SANDBOX, "question_bank.db")
# prepare() 会覆盖源路径，演示数据不会读取正式配置与题库。
paths.ensure_dirs()


def seed():
    from app import accounts, question_bank_manager as bank
    from app.database import Database
    from app.task_model import FEATURE_LABELS

    db = Database()
    now = time.time()

    # 账号：2 个登录正常、1 个失败、3 个未验证
    specs = [
        ("13800000001", "账号 01 · 主号", "ok"),
        ("13800000002", "账号 02", "ok"),
        ("13800000003", "账号 03", "failed"),
        ("13800000004", "账号 04", ""),
        ("13800000005", "账号 05", ""),
        ("13800000006", "账号 06", ""),
    ]
    account_ids = []
    for username, label, login_state in specs:
        existing = accounts.get_account_by_username(username)
        record = existing or accounts.create_account(username, "demo-password", label=label)
        accounts._mark(record["id"], {
            "login_state": login_state,
            "last_login_at": accounts._now(),
            "last_sync_at": accounts._now(),
            "last_sync_status": "ok" if login_state == "ok" else ("failed" if login_state == "failed" else ""),
            "last_error": "登录失败: 密码错误" if login_state == "failed" else "",
            "display_name": label if login_state == "ok" else "",
        })
        account_ids.append(record["id"])

    # 课程：每个账号各自的课程（课程 ID 故意重名，验证隔离）
    course_names = ["高等数学（上）", "大学英语综合", "数据结构与算法", "中国近现代史纲要"]
    for index, account_id in enumerate(account_ids):
        courses = []
        for offset, name in enumerate(course_names[: 2 + index % 3]):
            courses.append({
                "course_id": f"c{offset + 100}",
                "class_id": f"k{index + 1}{offset}",
                "cpi": f"cpi-{index}-{offset}",
                "name": name,
                "author": ["张明", "李慧", "王强", "陈静"][offset % 4],
                "if_open": offset != 2,
                "mission_fn": 3 + offset * 2,
                "mission_all": 24,
            })
        db.replace_courses(account_id, courses)

    # 任务与事件：覆盖所有状态
    db.create_run("run-ui-1", 3, note="早间批次")
    db.create_run("run-ui-2", 3, note="午间批次")

    task_specs = [
        ("task-ui-1", "run-ui-1", 0, 0, "course_all", "running", "chapter",
         {"success": 8, "failed": 1, "already_done": 5}),
        ("task-ui-2", "run-ui-1", 1, 1, "course_all", "running", "video",
         {"current": 12, "total": 20, "success": 10, "failed": 1}),
        ("task-ui-3", "run-ui-1", 2, 2, "independent_homework", "paused", "exam",
         {"questions": 40, "cache_hits": 18, "tiku_hits": 6, "llm_calls": 14,
          "random_answers": 2, "submit_ok": 36, "submit_fail": 4}),
        ("task-ui-4", "run-ui-2", 3, 3, "independent_homework", "succeeded", "finish",
         {"questions": 22, "cache_hits": 12, "tiku_hits": 4, "llm_calls": 5,
          "random_answers": 1, "submit_ok": 22, "submit_fail": 0}),
        ("task-ui-5", "run-ui-2", 4, 2, "course_all", "failed", "finish",
         {"success": 6, "failed": 4}),
        ("task-ui-6", "run-ui-2", 5, 3, "independent_homework", "interrupted", "homework",
         {"success": 14, "failed": 2, "skipped": 5, "download_ok": 14, "download_fail": 2}),
    ]

    for task_id, run_id, account_index, course_index, feature, status, stage, stats in task_specs:
        account = accounts.get_account(account_ids[account_index])
        course_row = db.list_courses(account_ids[account_index])[min(course_index, 1)]
        from app.work_progress import reduce_progress
        units = [{'id': f'{task_id}-u{n}', 'kind': 'video' if n%2 else 'work',
                  'name': ['第一章 · 函数与极限', '第二讲 · 连续与导数', '章节测验', '第三讲 · 微积分'][n%4]} for n in range(8)]
        work = reduce_progress({}, 'work_plan', {'units': units, 'sealed': True})
        confirmed = 8 if status=='succeeded' else 4
        for unit in units[:confirmed]:
            work = reduce_progress(work, 'work_result', {'id':unit['id'], 'status':'succeeded'})
        if status in ('running','paused'):
            for unit in units[confirmed:confirmed+2]:
                work=reduce_progress(work,'work_progress',{'id':unit['id'],'current':240,'total':480})
            stats.update({'questions': 12, 'cache_hits': 6, 'tiku_hits': 2, 'llm_calls': 4, 'submit_ok': 1,
                          'activity': {'name': '第二章 · 连续与导数'}})
        elif status in ('failed','interrupted'):
            work=reduce_progress(work,'work_result',{'id':units[confirmed]['id'],'status':'blocked'})
        stats['work'] = work
        db.create_task({
            "id": task_id,
            "run_id": run_id,
            "account_id": account["id"],
            "account_label": account["label"],
            "course_id": course_row["course_id"],
            "class_id": course_row["class_id"],
            "cpi": course_row["cpi"],
            "course_name": course_row["name"],
            "feature": feature,
            "status": status,
            "params": {
                "video": {"mode": "hybrid", "max_workers": 8, "random_progress": True},
                "answer": {"mode": "ai", "fallback_to_tiku": True,
                           "no_answer_action": "skip", "submit_delay": 2, "auto_submit": True},
            },
            "created_at": now - 1800 + account_index * 120,
        })
        db.update_task(task_id,
                       stage=stage,
                       stats_json=json.dumps(stats, ensure_ascii=False),
                       pid=20000 + account_index,
                       started_at=now - 1500 + account_index * 100,
                       finished_at=None if status in ("running", "paused") else now - 300)

    # 事件：运行中任务写一批日志，供详情抽屉展示
    log_lines = [
        ("login_started", "正在登录账号", "info", "login"),
        ("login_succeeded", "登录成功: 学员", "info", "login"),
        ("courses_loaded", "课程读取成功，共 3 门", "info", "course"),
        ("course_started", "开始处理课程: 高等数学（上）", "info", "course"),
        ("chapter_started", "  [1/12] 第一章 函数与极限", "info", "chapter"),
        ("log", "[OK] 1.1 函数的概念 -- 视频任务点", "success", "log"),
        ("log", "  [2/12] 第二章 导数与微分", "info", "log"),
        ("log", "'1.2 极限的运算' 当前刷取时长3分钟, 总时长12分钟", "info", "log"),
        ("log", "任务点'1.3 习题课'触发反爬虫: 状态码202，触发反爬虫验证", "warning", "log"),
        ("log", "反爬虫冷却中，等待 96+7 秒", "warning", "log"),
        ("exam_stats", "答题进度", "info", "exam"),
        ("log", "  单选 不定积分的定义是.. -> B (缓存)", "info", "log"),
        ("log", "  多选 下列哪些是连续函数.. -> ABD (题库)", "info", "log"),
        ("log", "  判断 可导必连续 -> true (LLM)", "info", "log"),
        ("task_progress", "任务统计更新", "info", "progress"),
        ("log", "  提交 12 道题的答案...", "info", "log"),
        ("log", "  提交成功!", "success", "log"),
    ]
    for index, (event, message, level, stage) in enumerate(log_lines):
        db.add_event("task-ui-1", account_ids[0], event, message, level=level, stage=stage,
                     payload={"module": "functions/deal_course.py:120"} if event == "log" else {},
                     ts=now - 900 + index * 20)

    db.add_event("task-ui-1", account_ids[0], "task_failed", "登录失败: 密码错误", level="error", stage="login")
    db.add_event("task-ui-5", account_ids[4], "task_failed",
                 "任务异常: 连续失败10次，终止刷取", level="error", stage="finish")
    db.add_event("task-ui-6", account_ids[5], "interrupted",
                 "WebUI 重启，未找到对应的 Worker 进程", level="warning", stage="recovery")

    # 题库
    bank._connect().close()
    questions = [
        ("设函数 f(x) 在区间 [a,b] 上连续，则 f(x) 在该区间上一定", "B", "单选题"),
        ("下列哪些属于导数的几何意义", "ACD", "多选题"),
        ("可导函数一定是连续函数", "true", "判断题"),
        ("不定积分的定义为", "A", "单选题"),
        ("求极限 lim(x→0) sinx/x 的值", "1", "填空题"),
        ("简述拉格朗日中值定理的条件与结论", "函数在闭区间连续、开区间可导", "简答题"),
        ("矩阵可逆的充要条件是", "D", "单选题"),
        ("向量组线性无关的判定方法是", "ABC", "多选题"),
        ("期权的内在价值一定大于等于零", "true", "判断题"),
        ("函数在某点可微则一定可导", "true", "判断题"),
    ]
    conn = bank._connect()
    for question, answer, qtype in questions:
        options = json.dumps(["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
                              ensure_ascii=False, sort_keys=True)
        conn.execute(
            """INSERT OR REPLACE INTO question_cache
               (hash, question_text, question_type, options, answer, course_id, chapter_id,
                created_at, hit_count) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)""",
            (bank.make_hash(question, options), question, qtype, options, answer,
             "c100", now - 86400 * 2, 3),
        )
    conn.commit()
    conn.close()
    db.close()
    print("种子数据准备完成")
