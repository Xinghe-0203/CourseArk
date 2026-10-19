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
         {"questions": 40, "cache_hits": 18, "tiku_hits": 0, "llm_calls": 20,
          "random_answers": 2, "submit_ok": 36, "submit_fail": 4}),
        ("task-ui-4", "run-ui-2", 3, 3, "independent_homework", "succeeded", "finish",
         {"questions": 22, "cache_hits": 12, "tiku_hits": 0, "llm_calls": 9,
          "random_answers": 1, "submit_ok": 22, "submit_fail": 0}),
        ("task-ui-5", "run-ui-2", 4, 2, "course_all", "failed", "finish",
         {"success": 6, "failed": 4}),
        ("task-ui-6", "run-ui-2", 5, 3, "independent_homework", "interrupted", "homework",
         {"success": 14, "failed": 2, "skipped": 5, "download_ok": 14, "download_fail": 2}),
        # 独立考试：暂停态、带选择范围参数、无业务事件，用于详情 stage=exam 文案验收
        ("task-ui-7", "run-ui-2", 2, 0, "exam", "paused", "exam",
         {"questions": 0, "llm_calls": 0, "submit_ok": 0, "submit_fail": 0}),
        # v2.2.3：考试「已交卷」分支不产生逐题明细，需要一条真实形态的已完成考试任务，
        # 供「已完成」页的 exam 信息与 outcome.reason 文案验收。
        ("task-ui-8", "run-ui-2", 2, 0, "exam", "succeeded", "finish",
         {"questions": 0, "cache_hits": 0, "tiku_hits": 0, "llm_calls": 0,
          "random_answers": 0, "submit_ok": 0, "submit_fail": 0}),
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
            stats.update({'questions': 12, 'cache_hits': 6, 'tiku_hits': 0, 'llm_calls': 5, 'submit_ok': 1,
                          'activity': {'name': '第二章 · 连续与导数'}})
        elif status in ('failed','interrupted'):
            # 2.2.1：中断/失败任务保留未完成单元（blocked + failed + running），
            # 供后端 unfinished_units 与前端「继续执行」提示验收。
            work=reduce_progress(work,'work_result',{'id':units[confirmed]['id'],'status':'blocked'})
            work=reduce_progress(work,'work_result',{'id':units[confirmed+1]['id'],'status':'failed'})
            for unit in units[confirmed+2:confirmed+4]:
                work=reduce_progress(work,'work_progress',{'id':unit['id'],'current':240,'total':480})
        stats['work'] = work
        # v2.2.3：已完成的独立考试任务用真实形态落库——工作单元只有 exam:<id>、
        # 参数里带答题页地址、逐题明细为空（平台考后不提供回顾），
        # 供「已完成」页的 exam 信息与 outcome.reason 文案验收。
        if feature == "exam" and status == "succeeded":
            exam_unit = {'id': 'exam:11021171', 'kind': 'exam', 'name': '期中考试',
                         'status': 'succeeded', 'already_done': True,
                         'detail': '平台显示该场考试已交卷；考试结束后平台不再提供逐题回顾。'}
            work = reduce_progress({}, 'work_plan', {'units': [exam_unit], 'sealed': True})
            work = reduce_progress(work, 'work_result', exam_unit)
            stats['work'] = work
            exam_params = {"exam": {"url": "https://mooc1.chaoxing.com/exam-ans/mooc2/exam/preview?examId=11021171&enc=seed"}}
        else:
            exam_params = {}
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
                "answer": {"mode": "ai", "no_answer_action": "skip",
                           "submit_delay": 2, "auto_submit": True},
                **({"selection": {"mode": "selected",
                                  "ids": ["exam-1001", "exam-1002"]}}
                   if feature == "exam" else {}),
                **exam_params,
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
        ("log", "  多选 下列哪些是连续函数.. -> ABD (AI)", "info", "log"),
        ("log", "  判断 可导必连续 -> true (AI)", "info", "log"),
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
    # 2.2.1：考试说明页触发平台安全验证而安全中止，供详情提示条验收。
    # 用 info 级 log 事件：不会顶掉 live 的 stage 兜底文案，但可被提示条与诊断日志读到。
    db.add_event("task-ui-7", account_ids[2], "log",
                 "考试说明页需要平台安全验证（captchaCheck=1），已安全中止，未启动考试计时",
                 level="info", stage="exam")

    # 2.2.1：失败/中断任务的未完成工作单元（work_plan + 部分 work_result），
    # 供后端 unfinished_units 推导「继续执行」入口与总览提示条验收。
    for task_id, account_id in (("task-ui-5", account_ids[4]),
                                ("task-ui-6", account_ids[5])):
        unit_ids = [f"{task_id}-u{n + 1}" for n in range(8)]
        db.add_event(task_id, account_id, "work_plan", "任务点计划", level="info", stage="plan",
                     payload={"units": [{"id": uid, "name": f"任务点 {n + 1}", "kind": "video"}
                                        for n, uid in enumerate(unit_ids)], "sealed": True},
                     ts=now - 1500)
        for n, uid in enumerate(unit_ids[:4]):
            db.add_event(task_id, account_id, "work_result", f"任务点 {n + 1} 已完成",
                         level="success", stage="video",
                         payload={"id": uid, "status": "succeeded"}, ts=now - 1400 + n * 20)

    # 运行中任务的实时进度事件：供「运行进度小窗」与任务行摘要验收
    for offset, (name, current, total) in enumerate([
        ("第二讲 · 连续与导数", 240, 480),
        ("第二讲 · 连续与导数", 360, 480),
    ]):
        db.add_event(
            "task-ui-2", account_ids[1], "work_progress", f"正在学习 {name}",
            level="info", stage="video",
            payload={"id": "task-ui-2-u1", "kind": "video", "name": name,
                     "current": current, "total": total},
            ts=now - 120 + offset * 45,
        )

    # 逐题作答明细：供任务详情「AI 做题」页签验收
    answer_seed = [
        ("第4章组件", 1, 10, "单选题",
         "组件的生命周期钩子函数中，在组件挂载完成后调用的是哪个?",
         ["A. created", "B. mounted", "C. updated", "D. destroyed"],
         "B", "ai", "answered", ""),
        ("第4章组件", 2, 10, "简答题", "在 Vue 组件中，data 必须是一个函数。",
         [], "正确", "ai", "answered", ""),
        ("第4章组件", 3, 10, "单选题", "下列哪个指令用于条件渲染?",
         ["A. v-for", "B. v-if", "C. v-bind", "D. v-on"], "B", "cache", "answered", ""),
        ("第4章组件", 4, 10, "单选题", "v-model 默认在哪个事件上同步输入值?",
         ["A. change", "B. input", "C. blur", "D. keyup"], "B", "random", "answered",
         "AI 未返回可用答案，按兜底策略随机选择"),
        ("第4章组件", 5, 10, "填空题", "Vue 3 中创建响应式对象的函数是 ____。",
         [], "", "failed", "unreadable", "题面字体未能解码，已跳过"),
    ]
    for index, (media, seq, total, qtype, question, options,
                answer, source, status, note) in enumerate(answer_seed):
        db.add_event("task-ui-3", account_ids[2], "answer_result", "答题结果",
                     level="warning" if status != "answered" else "info", stage="exam",
                     payload={"index": seq, "total": total, "media": media,
                              "question_id": f"seed{index + 1}",
                              "question_type": qtype, "question": question,
                              "options": options, "answer": answer,
                              "source": source, "status": status, "note": note},
                     ts=now - 620 + index * 15)

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
