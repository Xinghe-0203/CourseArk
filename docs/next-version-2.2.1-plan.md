# CourseArk 2.2.1 计划：任务点同步 + 中断后续跑

> 状态：**已实施完成**（2026-10-18，v2.2.1）。发布说明与验证数据见 docs/release-2.2.1.md。
> 用户反馈两条 bug（m01742 / m01770），本文件为当时的实施契约。

## 用户反馈与根因

1. **「每门课都是 0 / 0 个任务点」**（m01742，附桌面截图）：`worker/sync_runner.py` 把每门课的
   `mission_fn` / `mission_all` 写死为 0，从未读取平台进度；`app/main.py` 的 lifespan 也没有启动同步，
   于是课程列表永远显示 0/0。
2. **「任务点执行中退出程序，重开后直接显示已完成，不做了」**（m01770）：
   - 中断任务确实被标记为 `interrupted`，但用户看不到「未完成 N 项 / 继续执行」入口；
   - 更关键的是 `course_all` 在 `discover()` 得到 0 个任务点时**静默成功**（DB 里 3 次 4 秒
     succeeded、`work.units={}`），因为 `Course.get_chapter()` 的任务点进度解析失效
     （新页面 `h2` 里只有一个 `<span>109</span>`，`/125` 在文本里），`mission_all` 变成 0，
     平台明明还有 16 个待完成任务点，程序却宣称任务完成。

真实页面证据（只读 GET，`%TEMP%\courseark-probe-mission\report.txt`）：

- 「人工智能应用项目综合实训」`h2` 文本 = `已完成任务点: 109/125`，但 `h2/span/text()` 只有 `109`；
  章节解析正常（11 组 / 63 章，16 个待完成任务点，discover 得到 39 个作业单元）。
- 「HTML5 APP应用开发（vue3）」= `已完成任务点: 27/27`（确实全部完成），所以对它跑 course_all
  秒完成是**正确结果**，但缺少「平台显示 27/27，已全部完成」的明确提示，用户误以为程序跳过了工作。

## 修复项

### A. 任务点进度（cli_copy + worker）

- `cli_copy/models/course.py`
  - 新增 `parse_mission_progress(html) -> (fn, all)`（staticmethod）：
    优先正则 `已完成任务点\s*[:：]?\s*(\d+)\s*/\s*(\d+)`，其次 `fanyaChapterWhite` 前三层文本里
    搜 `(\d+)\s*/\s*(\d+)`，最后退回旧的 `h2/span` 拆分；全失败返回 `(0, 0)`。
  - `get_chapter()` 改用上述解析。
  - 新增 `get_mission_progress() -> (fn, all)`：只 GET `studentcourse` 页解析进度（不解析章节），
    反爬/空页/登录失效抛 `RequestException`，供同步进程使用。
- `worker/sync_runner.py`：`user.get_courses()` 之后逐课调用 `get_mission_progress()`（每门课之间
  `threading.Event().wait(0.2)` 级别的小延迟），写入 `mission_fn/mission_all`；单课失败记入
  `course_errors`（`{course_id,name,error}`）不中断整体；连续失败 ≥5 门则提前结束并整体告警；
  每门课 emit `sync_progress`（payload `{done,total,course,mission_fn,mission_all}`）。
- `cli_copy/functions/course_execution.py`：`run()` 在 `discover()`+过滤后若 `self.jobs` 为空：
  - `mission_all > 0 and mission_fn < mission_all` → 抛 `RequestException`：
    「平台显示还有 {pending} 个任务点未完成（{fn}/{all}），但未能识别具体任务；请更新到最新版本或查看诊断日志」
    → 任务失败，**绝不静默成功**；
  - 否则 log「平台显示课程任务点已完成（{fn}/{all}），本次没有需要处理的任务」并在 stats 里加
    `no_pending=True`，事件 `work_plan(units=[])` 保持现有契约。

### B. 启动自动同步 + 中断续跑（app）

- `app/settings.py`：`scheduler.sync_on_start`（bool，默认 `True`），PATCH 可改；`/api/settings`
  的 `scheduler` 组加中文 label「启动时自动同步课程」。
- `app/main.py` lifespan：`manager.start()` 之后若 `sync_on_start` 为真，用后台线程（不阻塞启动、
  不阻塞事件循环）对 `accounts` 里 `login_state == "ok"` 的账号逐个 `sync_service.sync_account(...)`，
  已同步中的跳过；异常只记日志。进程退出时随 `sync_service.shutdown()` 一并收尾。
- 新增 `POST /api/tasks/{task_id}/resume`：仅允许 `interrupted|stopped|failed` → 复用
  `manager.retry_task()`（同参数快照新建 pending 任务，Worker 会重新按平台状态发现未完成任务点），
  返回 `_task_view`；其他状态返回 409。
- `_task_view` 新增 `unfinished_units`：从 `stats.work.units` 里统计 `status in
  ("running","failed","blocked","skipped")` 的数量，供前端显示「未完成 N 项」。

### C. 界面（frontend）

- `AccountWorkspace.vue`：课程行任务点显示「已完成 x / y」+ 待完成高亮；`mission_all == 0 &&
  synced_at` 时显示「任务点未同步」，`syncing` 时显示「同步中…」；同步完成事件后自动刷新。
- 任务列表/总览：`interrupted|stopped|failed` 任务显示「继续执行」按钮（POST resume）；
  存在未完成任务时在总览顶部显示一条提示条（「上次任务未完成，共 N 项」）。
- `SettingsView.vue`：新增「启动时自动同步课程」开关（`scheduler.sync_on_start`）。
- `tools/vue_check.py` / `tools/ui_seed.py`：种子数据补一个 interrupted 任务；断言「继续执行」
  按钮与自动同步开关；截图 `docs/vue-validation/desktop-resume.png`。

## 写作用域

| 成员 | 范围 |
| --- | --- |
| lead | `cli_copy/**`、`worker/sync_runner.py`、`tests/test_mission_progress.py`、`tests/test_course_execution.py`、`tools/check_work_page.py`、`docs/**` |
| backend-api | `app/**`、`tests/test_auto_sync_and_resume.py` |
| frontend-ui | `frontend/**`、`tools/vue_check.py`、`tools/ui_seed.py` |

## 验收

- `python -m pytest tests cli_copy/tests -q` 全绿；`npm --prefix frontend test` 与 build 通过；
  `python tools/vue_check.py`、`python tools/ui_check.py`、`python tools/smoke_test.py --mock` 全绿。
- 真实账号只读核对：23 门课全部拿到 `mission_fn/mission_all`（人工智能 109/125、HTML5 27/27）。
- 版本号 2.2.0 → **2.2.1**，重新构建桌面安装包；文档补 `docs/release-2.2.1.md`。

## 安全边界

- 探针只允许 GET；不启动考试、不提交作业、不跑真实任务。
- 不在日志/文档/提交里出现账号密码、手机号、真实姓名、页面原文。
