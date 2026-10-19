# 课舟 CourseArk v2.2.3 发布说明

> 本版回答三件事：**「已完成」到底做了什么、要能看得见」**、**「完成的记录要有一个专门的地方集中看」**、
> **「不想再被同一条提醒打扰」**，并按「简约白黑大圆角」重做了整套界面。

## 一、修复：独立考试显示「已完成」，但看不到任何具体信息

### 问题

任务列表显示该场考试「已完成」，但点进任务详情，逐题明细是空的、统计全是 0：

```
questions: 0   llm_calls: 0   submit_ok: 0
work.units: { "exam:11021171": { status: "succeeded" } }
事件流: work_plan → work_result → task_progress → task_succeeded（没有一条 answer_result）
```

### 根因

`cli_copy/functions/exam_room_url.py` 的「已交卷」分支：打开答题页时若平台已经显示交卷成功
（上一次运行已交、或用户自己在浏览器里交了），程序会**直接判定完成并返回**——
这是对的（不该重复交卷），但它只 emit 了一句「该场考试已交卷完成」+ `status=succeeded`，
既没有逐题明细，也没有说明「为什么没有明细」，于是用户看到的就是一个空洞的「已完成」。

### 修复

1. **把原因写进事件**：该分支现在 emit `work_result`（带 `already_done: true` 与
   `detail`）与 `exam_stats{already_done:1, questions:0, note}`，
   文案是「平台显示该场考试已交卷（可能由上一次运行或你在浏览器里手动交卷完成）；
   考试结束后平台不再提供逐题回顾，因此这场考试没有可展示的逐题明细。」
2. **事件叙述可读**：`app/presentation.py` 对带 `already_done` 的 `work_result`
   输出标题「此前已完成」+ 原因详情，不再只显示一句「已确认完成」。
3. **历史任务同样可解释**（关键）：早于本次修复完成的考试任务没有 `already_done` 标记，
   因此 `GET /api/completed` 的 `outcome.reason` 增加了回退链：
   `task.error` → 考试已交卷说明 → `_answers_note` 的逐题解释。
   用真实数据目录复核，三条历史「已完成」考试任务的 reason 现在都是
   「考试已交卷，但平台在考后不提供逐题回顾，本场考试没有可展示的逐题明细。」
4. **`GET /api/tasks/{id}` 新增 `answers_note`**：明细为空时给出可读解释，覆盖三种情况——
   旧版本任务（`stats.questions>0` 但无事件）、考试任务（考后无逐题回顾）、
   纯视频任务（完成时没有产生逐题作答）。有明细时为 `""`。

> 诚实性说明：考后平台不提供逐题回顾是平台行为，不是程序缺陷；本版做的是
> **把这件事明确写出来**，而不是继续显示一个没有解释的「已完成」。

## 二、新增：「已完成」专页

### 后端 `GET /api/completed`

```
GET /api/completed?feature=&account_id=&q=&since=&until=&limit=30&offset=0
→ { "total": int, "items": [CompletedTask] }
```

- `status` 固定为 `succeeded,failed,stopped,interrupted`（已结束的任务）；
- 每条任务在既有任务视图之上追加：
  - `answers_summary`：逐题汇总（answered/skipped/total/ai/cache/random/failed/submit_ok/submit_fail）；
  - `answers_count`：实际记录的逐题条数；
  - `duration_seconds`：`finished_at - started_at`（缺一为 `null`）；
  - `outcome{status, reason}`：结果与**可读原因**（见上一节的回退链）；
  - `exam{title, exam_id, url, already_done, detail} | null`：考试任务才有，
    `url` 可能为空串（列表入口任务没有答题页地址）。
- 明细按任务各查一次 `answer_result`（`latest=True`），**不在循环里拉全量事件**。

### 前端「已完成」页面

左侧导航新增「已完成」入口，页面提供：

- 关键词搜索（防抖）、账号筛选、功能筛选（课程任务点/独立作业/独立考试）、状态筛选、每页条数；
- 每行：状态徽标、课程与功能、账号、起止时间、耗时、逐题概要、结果说明（`outcome.reason`）；
- 考试行额外显示试卷名与「考后无逐题回顾」说明；
- 点「查看详情」复用任务详情抽屉（含「AI 做题」逐题卡片与 `answers_note` 提示条）；
- 分页与行动邀请式空状态。

## 三、新增：黄色续跑提示支持「不再提醒」

- 设置新增 `ui` 分组：`{dismissed_resume_tasks: string[], completed_page_size: int}`；
- `dismissed_resume_tasks` 归一为去重后的字符串列表（最多 100 条），
  `completed_page_size` 收敛到 10..100；
- 语义：**只对列表内的任务 id 隐藏黄色续跑提示**，出现新的中断任务仍会照常提醒
  （不做全局开关，避免用户错过真正的新问题）；
- 持久化复用既有 `PATCH /api/settings`，没有新增端点。

## 四、界面重做：简约白黑大圆角

- 页面底色纯白、次级面浅灰、1px hairline 分隔线；侧栏改为纯黑；
- 圆角统一走 token（`--r-sm 10px / --r-md 14px / --r-lg 20px / --r-xl 28px / --r-pill 999px`），
  卡片、弹窗、输入框、进度条一律大圆角；
- 强调色只用于状态语义（成功/警告/危险/信息），且只做小面积；主按钮改为近黑底白字；
- **删除所有纯装饰圆点/状态小点**（`.dot`、`.live-dot`、`.status i`、`.notification-dot` 等图形），
  状态一律用文字表达；
- 阴影克制，hover/focus 只做轻微反馈，不加夸张动效。

## 五、改动文件

| 文件 | 改动 |
|---|---|
| `cli_copy/functions/exam_room_url.py` | 已交卷分支补充 `already_done`/`detail` 与考试统计说明 |
| `cli_copy/core/exam_answer_page.py` | `parse_answer_page` 尽力提取试卷标题（`.exam-title`/`h1`/`<title>`） |
| `app/main.py` | `GET /api/completed`、`_completed_view`、`_answers_note`、`answers_note` 字段 |
| `app/settings.py` | `ui` 分组（`dismissed_resume_tasks`、`completed_page_size`）与归一 |
| `app/presentation.py` | 「此前已完成」叙述与原因详情 |
| `frontend/src/style.css` | 全量重写为「简约白黑大圆角」设计语言 |
| `frontend/src/components/CompletedView.vue` | 新增「已完成」专页 |
| `frontend/src/App.vue`、`types.ts`、`store.ts`、`mission.ts`、`OverviewDashboard.vue`、`TaskList.vue`、`SettingsView.vue` | 新页面接线、不再提醒、设置项完善 |
| `frontend/src/components/*.vue` | 跟随 token 的视觉重做与装饰标记清除 |
| `tests/test_completed_and_ui_settings.py` | 新增 21 例（completed 契约、ui 设置、answers_note、叙述） |
| `tests/test_exam_answer_page.py` | 新增 4 例（交卷页标题提取） |
| `frontend/src/mission.test.ts` | 新增 4 例（不再提醒过滤、新任务仍提醒、损坏设置、去重与 100 条上限） |
| `tools/ui_seed.py` | 新增已完成考试任务种子，供「已完成」页文案验收 |
| `tools/vue_check.py` | 「已完成」页纳入三档视口无溢出断言 |
| `tests/test_v223_audit.py` | 独立审计 22 例（不修改产品代码） |

## 六、兼容性与迁移

- 数据目录不变（`%APPDATA%\AutoCxWebUI`），覆盖安装即可；
- 新增的 `ui` 分组对旧设置文件是**向后兼容**的：缺失时按默认值补全，不会清空既有配置；
- 历史任务无需迁移：`/api/completed` 的解释逻辑对旧数据同样生效（见第一节第 3 点）；
- 考试作答协议未改动（v2.2.2 的「粘贴答题页地址」流程保持一致）。

## 七、验证

| 项目 | 结果 |
|---|---|
| `python -m pytest tests cli_copy/tests -q` | 453 passed（含独立审计 22 例；功能新增 28 例：completed 契约 21 + 交卷页标题 4 + 考试链路 3） |
| `python tools/smoke_test.py --mock` | 56 通过 / 0 失败 |
| `npm --prefix frontend test`（vitest） | 6 个文件 / 29 例通过（含「不再提醒」过滤 4 例） |
| `npm --prefix frontend run build` | `vue-tsc --noEmit` + vite 构建通过 |
| `python tools/vue_check.py` | 51 项通过 / 0 错误（含「已完成」页在 wide/desktop/mobile 三档无横向溢出；截图见 `docs/vue-validation/`） |
| `python tools/ui_check.py` | 51 项通过 / 0 错误 |
| `npm --prefix desktop run dist:win` | 产出 `CourseArk-2.2.3-Setup.exe` / `CourseArk-2.2.3-Portable.exe` |
| 真实数据复核（只读） | 历史 3 条 succeeded 考试任务的 `outcome.reason` 均非空且说明「考后无逐题回顾」 |

> 独立验证任务（task-12）已完成：真实数据只读复核、`/api/completed` 契约与边界（limit 0/101/-1 → 422）、
> `settings.ui` 归一与持久化、「不再提醒」只隐藏列表内 id（新中断任务仍提醒）、4 个反例场景，
> 结论为**未发现需要修复的产品缺陷**。唯一异常是 `vue_check.py` 在前端构建期间的首次运行出现过 locator 超时，
> 之后同命令稳定通过，属并发构建引起的时序抖动；构建期间不要并行跑 `vue_check.py`。
> 独立审计新增 `tests/test_v223_audit.py`（22 例）。

