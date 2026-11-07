# 架构概览

CourseArk 由网页前端、本机 API 服务和独立 Worker 组成。网页端与 Electron 桌面端共用 Vue 页面和 FastAPI 后端；桌面端负责启动随包 Python 服务，并通过回环地址加载本机页面。

```text
Vue 3 / TypeScript ── HTTP + SSE ── FastAPI
                                      ├─ SQLite：设置、账号、任务、课程缓存、事件和答题缓存
                                      ├─ Worker：任务执行及课程/会话同步
                                      └─ 控制状态：运行、暂停和停止

Electron ── Python runtime ── FastAPI ── Vue 页面
```

## 组件

- `frontend/`：Vue 组件、类型、请求和状态管理。
- `webui_static/vue/`：由前端生产构建生成，随服务提供。
- `app/`：FastAPI 路由、持久化、任务调度、会话、课程同步。
  路由按域拆在 `app/routes/`（`system` / `overview` / `accounts` / `workspace` /
  `tasks` / `settings` / `bank`），`app/main.py` 保留惰性资源单例、请求模型、
  视图序列化辅助与鉴权守卫；路由模块经 `from .. import main` 在调用时动态取
  `db/hub/manager/sessions`（测试会整体替换这些单例，禁止 import 时绑定）。
  四处 Worker 子进程的启动/读取/终止样板在 `app/subprocess_runner.py`。
- `worker/`：任务、同步与会话子进程入口。
- `cli_copy/`：复用的 AutoChaoxingCLI 业务代码及 WebUI 适配；资源来源与许可见其 `resource/`。
- `desktop/`：Electron 桌面壳、Windows 构建和打包冒烟检查。
- `tools/check_work_page.py`：只读自检脚本，核对作业/考试页面解析与提交报文（不提交、不调用 AI）。
- `app/catalog_service.py` + `worker/catalog_runner.py`：新建任务时按需读取课程作业/考试列表（子进程登录、只读 GET、SQLite 缓存 600 秒）。

每项任务按账号、课程和模块隔离执行；数据库保存任务状态、事件、设置和答题缓存。Worker 通过本机数据目录与服务共享运行状态。桌面版的 FastAPI 仅监听 `127.0.0.1`。

## 答题链路（v2.1）

```text
作业/测验页面 GET（带登录态）
   └─ cli_copy/core/work_form.py
        ├─ parse_questions：div.singleQuesId[data] 等容器 → 题干/选项/题型/题号/填空数
        └─ parse_form：<form action=…addStudentWorkNewWeb?token=…&totalQuestionNum=…> 及全部具名控件
   └─ functions/deal_exam.py
        ├─ _answer_question：本地答题缓存 → AI（llm_client）→ 兜底（跳过/随机）
        ├─ answer_validation.normalize_answer：题型归一与选项字母校验
        ├─ 逐题 emit answer_result 事件（题干、选项、答案、来源、失败原因）
        └─ _submit_answers：work_form.build_submission 回放页面表单
             ├─ build_submit_url：按页面 version() 追加 ua/formType/saveStatus/version
             ├─ _check_submit_ready：GET work/validate，拦截验证码/异常状态
             └─ POST 表单（Referer 为作业页面）
```

关键约束（与浏览器行为对齐，改动前请先跑 `tools/check_work_page.py` 对照）：

- 提交端点是表单 `action` 里的 `addStudentWorkNewWeb` 且 **token/totalQuestionNum 在查询串**；
  `token` 来自 `enc_work`，与 `standardEnc`、列表页 `enc` 三者不同，不可互替。
- `totalQuestionNum` 是平台下发的 32 位十六进制令牌，**不是题目数量**，缺失时不能自行填题数。
- `answerwqbid` 由页面脚本在提交前填成「全部题号 + 尾部逗号」。
- 题目容器不能用 `div.TiMu`（命中的是整页外壳，会把「举报」和课程标题当成题干）。
- 题干兼容两代结构：`h3.mark_name` 与 `.Zy_TItle > .fontLabel`，需剥离题号与题型标记。

## 考试链路（v2.2）

```text
考试列表 GET /exam/test?courseId&classId&ut=s&cpi&openc&enc
   └─ models/course.py::get_exam_list：解析 goTest(courseId, examId, relationId, endTime, paperId, isRetest, examEnc)
   └─ models/course.py::exam_notes_url：GET /exam/test/examcode/examnotes?courseId&classId&examId&cpi
        └─ parse_exam_notes：取 #startBtn[data] 的真实入口 + examCheck/captchaCheck/needCode
             ├─ needCode=1 → 提示需要考试码，中止（不启动考试）
             ├─ captchaCheck=1 或 examCheck=1 → 提示需要平台安全验证，中止（不启动考试）
             └─ 无风控 → 请求 #startBtn[data]（/exam-ans…&newMooc=true）
   └─ models/course.py::exam_start_url（回退）：tId=考试ID、id=relationId、newMooc=true；重考才走 /exam 旧路径
   └─ functions/deal_exam_room.py
        ├─ exam_form.parse_questions / parse_form / detect_submit_endpoints
        ├─ 一页一题（is_single_question_mode）→ 安全中止，不提交任何答案
        └─ 整卷页面 → 复用 deal_exam 的作答链路 → 表单回放交卷
```

- 考试列表里的 `examEnc` 是「这场考试」自己的 enc，与课程 `enc`、作业 `enc_work` 均不可互换。
- `tId` 必须是**考试 ID**（列表页 `goTest` 的第 2 个参数），不是 `paperId`；新版入口主机是
  `mooc1.chaoxing.com/exam-ans/...`，且带 `newMooc=true`。
- 学习通对进入考试有人机校验（`captchaCheck` / `examCheck`，手机端同样如此）。这是账号级的平台策略，
  程序不尝试绕过：命中即记录原因并中止，**不会开始考试计时**，也不会替用户交白卷。
  浏览器验证完成后可用下面的「答题页直连」继续（v2.2.2）。

## 考试答题页直连（v2.2.2）

```text
用户浏览器完成平台验证 → 复制带 enc 的答题页地址
   └─ app/task_model.py::ExamParams.url（校验 reVersionTestStartNew + chaoxing.com）
        └─ worker/runner.py：exam 且 url 非空 → functions/exam_room_url.py::ExamRoomByUrl
             ├─ core/exam_answer_page.parse_exam_url：courseId/classId/tId/id/enc/cpi/openc
             ├─ GET 该答题页（Referer=考试列表）
             │    ├─ finished（交卷成功页）→ emit work_result{already_done,detail}
             │    │     + exam_stats{already_done,note}，不再作答（v2.2.3 起带原因）
             │    └─ blocked（无权限/已结束/需验证）→ 中止，不绕过
             ├─ 循环：parse_answer_page（当前题/题型/选项/题量/剩余时间/隐藏字段）
             │    ├─ DealExam._answer_question（AI/缓存，复用作业链路）→ normalize_answer
             │    ├─ POST reVersionSubmitTestNew（tempSave=true，answer<qid>=答案）
             │    ├─ 响应 data=lastUpdateTime|remainTime|enc → build_next_url 取下一题
             │    └─ 末题（index>=total-1）→ 再 POST tempSave=false 交卷
             └─ 交卷成功后写答题缓存 + emit answer_result/work_progress/exam_stats
```

- 提交 query 只保留 `classId/courseId/testPaperId/testUserRelationId` + `cpi/tempSave/version=1`；
  多带 `keyboardDisplayRequiresUserAction=1` 会被服务端判「无效操作」。表单 action 的 `&amp;`
  必须 `html.unescape`。服务端接受不带 `pos` 签名的提交。
- 进度与统计沿用作业事件：每题 `answer_result` + `work_progress{current,total}`，
  整卷成功才有 `work_result`，失败抛出服务器原文，不伪造成功。
- 旧路径（不带 URL）保持不变：仍按考试列表处理，在平台验证处安全中止。
- 协议调研（逐题提交、`data` 滚动令牌、`tempSave`、超时自动交卷、`pos` 签名）见
  [`docs/research-exam.md`](research-exam.md)，本版本按真实 PC 页面行为实现并已真机验证。

## 课程同步与续跑（v2.2.1）

```text
启动 → app/main.py lifespan
   └─ scheduler.sync_on_start（默认 true）→ sync_service.sync_account(blocking=True)
        └─ worker/sync_runner.py（子进程）
             ├─ User.get_courses()
             ├─ 逐课 Course.get_mission_progress()：平台「已完成任务点 N/M」
             ├─ 逐课 emit sync_progress {done,total,course,mission_fn,mission_all}
             └─ emit sync_result {courses[...], course_errors[...]} → app 写 courses 表
```

- 任务点数量只能来自平台页面；解析失败不编造数字，宁可保留旧快照并写 `course_errors`。
- 发现阶段 0 个任务点时，`CourseExecution._finish_without_jobs()` 用 `mission_fn/mission_all`
  判断：还有未完成 → 直接失败并说明；确实全完成 → 明确成功并说明「没有需要处理的任务」。
- 续跑：`POST /api/tasks/{id}/resume` 对 `interrupted/stopped/failed` 用原 `params_json`
  重新排队（`retry_task` 语义），已完成部分由平台状态跳过；`paused/pausing` 仍是暂停恢复。


## 已完成记录与界面偏好（v2.2.3）

```text
GET /api/completed?feature&account_id&q&since&until&limit&offset
   └─ db.list_tasks(status=succeeded,failed,stopped,interrupted)
        └─ _completed_view = _task_view + answers_summary + answers_count
             + duration_seconds + outcome{status,reason} + exam{...}|null
             └─ reason 回退链：task.error → 考试已交卷说明 → _answers_note
```

- `_task_answers` 每任务查一次 `answer_result`（`latest=True`、按 `(media,index)` 去重），
  `_completed_view` 在循环里复用同一结果，**不再逐任务拉全量事件**。
- `GET /api/tasks/{id}` 的 `answers_note`：明细为空时给出可读解释（旧版本任务 / 考试考后无回顾 /
  纯视频任务），有明细时为 `""`；「AI 做题」页签据此显示提示条。
- 设置 `ui = {dismissed_resume_tasks: [...], completed_page_size: 30}`：
  前者是「不再提醒」的任务 id（去重、最多 100 条），**只隐藏列表内的任务**，
  新的中断任务仍会提醒；后者是「已完成」专页每页条数（10..100）。
  两者都通过既有 `PATCH /api/settings` 持久化，没有新增端点。

## 事件与前端

Worker 通过 `runtime.emit` 写事件，`app/database.py` 落库，`app/narrative.py` /
`app/presentation.py` 生成人话叙述与处置建议，前端经 SSE（`/api/events/stream`）收到后刷新。

- `answer_result`（逐题）：`index/total/media/question_type/question/options/answer/source/status/note`；
  `source` 为 `ai|cache|random|failed`，`status` 为 `answered|skipped|unreadable`。
- `GET /api/tasks/{id}` 返回 `answers[]`（按 `(media,index)` 去重取最新）与 `answers_summary`
  （answered/skipped/total/ai/cache/random/failed/submit_ok/submit_fail），任务详情「AI 做题」页签消费该结构。
- `exam_stats` 仍兼容旧字段 `tiku_hits`（v2.1 起恒为 0），不再展示「在线题库」。
- `GET /api/tasks/{id}` 另有 `live`：`activity/activity_at/elapsed_seconds/unit/eta_seconds/eta_source`。
  `eta` 优先用当前项速率推算（`(total-current)/(current/age)`），退化为任务级速率，老任务返回 null；
  前端浮动进度小窗与任务列表摘要消费该结构。
- 带 `already_done` 的 `work_result` 由 `presentation` 输出为「此前已完成」+ 原因详情，
  避免「已完成」看起来像是程序真的作答过。
- v2.3.0 起不再有通知子系统：失败与告警只作为任务事件落库（`sync_failed` / `task_failed` /
  `login_failed` 等），由 `presentation.describe` 归类（`login/llm/antispider/network/media/...`）
  并给出处置建议，前端在任务详情「诊断日志」与总览指标里消费，不再有独立的站内问题中心。

## 界面分区与布局（界面重做 v3）

前端按**单一职责**分区，导航分三组：

| 组 | 页面 | 职责 |
|---|---|---|
| 工作台 | 工作总览 | 只讲状态摘要与正在运行的任务；不提供课程/任务的增删改 |
| 工作台 | 课程进度 | 只看平台任务点进度：按账号分组，逐门课列「已完成 / 总数」与待完成，跨账号比较 |
| 工作台 | 学习任务 | 左侧账号竖列 + 右侧选中账号详情：选课、创建任务、暂停/继续/停止、看逐题明细 |
| 档案 | 账号与课程 | 只管账号身份、登录缓存与课程同步；课程详情走弹窗，不重复列任务 |
| 档案 | 已完成 | 汇总每次跑完的任务：课程、起止时间、耗时、逐题概要、结果说明 |
| 档案 | 答题缓存 | 搜索、导入、导出、删除本机记住的答案 |
| 系统 | 偏好设置 | 默认学习方式、并发、AI 服务、存储与备份 |

- **视觉基底**：`frontend/src/style.css` 只做四行 `@import`，实际样式在 `frontend/src/styles/`。
  `tokens.css` 定义冷灰纸面（`--paper #edf0f3`）+ 仪器墨蓝（`--navy #123a5e`）+ 交通灯语义色
  （`--ok/--warn/--danger/--info`）与字体角色（正文 Microsoft YaHei、数字 Bahnschrift、等宽 Consolas），
  并把旧变量名（`--fg/--bg/--line/--accent` 等）映射到新 token，供模板内联 SVG 继续使用；
  `base.css` 是按钮、表单、状态胶囊、进度条、标签页、筛选条、分页、面板、弹窗与空态的公共件；
  `shell.css` 是侧栏 `--rail:208px` + 顶栏 `--topbar:54px` 的骨架与 1080 / 760 两档断点；
  `windows.css` 是进度、逐题、告警三个浮层小窗。
- **顶栏承载页面身份**：标题与一句说明放在 `.top-title`（h1 15px），不再有 40px 巨标题和
  「工作空间 / 页名」面包屑；右侧依次是新建任务、账号/课程/运行中三项计数、浮层开关、刷新。
- **统一口径**：`frontend/src/overview.ts` 的 `overviewCounts()` / `engineTotals()` 是唯一聚合来源，
  顶栏 `.top-stats`（账号 / 课程 / 运行中）与总览共用它；`courses` 按 `sum(w.courses.length)` 计算。
- **总览只讲一次**：续跑条 → 单块执行摘要（`.execution-dashboard`：本轮已确认 / 总数 + 进度条 +
  三枚阶段 chip）→ 调度队列表格（课程与任务 / 状态 / 说明 / 进度 / 创建）→ 正在执行的账号卡 →
  最近完成。原先四张等大指标卡、环形仪表与三条阶段比例条都在重复同一件事，已删除。
- **列表用行式表格**：账号与课程、已完成、答题缓存、任务记录都是「34px 表头 + 行」，不再用大卡片；
  行内多行信息用 `small` 与 `.num` 分层次，状态统一 `.status` 胶囊。
- **学习任务用竖向二级菜单**：`.account-workspaces` 是 `238px + minmax(0,1fr)` 的两列网格，
  左列 `nav.account-menu` 每个账号一行（勾选框、头像、账号名、`N 门 · fn / all 任务点`、执行状态点），
  `position: sticky` 跟随滚动；右列只渲染选中账号（`.workspace-account`），一次一个。
  课程区从卡片网格改为四列表格 `.course-row-head`（课程 / 平台任务点 / 本轮任务 / 完成度），
  行高由内容决定，不再有卡内滚动。1080px 以下左列转横向可滚动条、课程表折成两行。
- **进度口径只出现一次**：`frontend/src/course.ts` 提供 `courseKey` / `taskForCourse` / `courseRows`，
  进度页与学习任务页共用同一份「账号 × 课程 × 本轮任务」映射；任务点进度在表格里只显示数字
  （`fn / all` + `待完成 N`），不输出「已完成 x / y，待完成 z」整句——状态徽标已经写着「已完成」。
- **课程进度页**（`#/progress`）：页头 `.progress-summary` 三段（总任务点 + 整体完成度条 + 三格事实条），
  下面是 `.filterbar`（搜索 + 范围下拉 + 命中课程数）与按账号分组的 `.progress-account` 段，
  每段四列课程行；数据全部来自 `state.workspaces`，不发额外请求。
- **浮层让位**：`ProgressWindow` 默认 `minimized=true`，只留贴边标题栏；`.page-content` 不再预留
  固定底部空间。侧栏底部 `.engine` 常驻心跳（服务状态、运行中/暂停数、端口）。
- **留白与行高**：按钮基类 `button, .button` 带 `line-height: 1`（28px 定高单行文字居中），
  会被按钮内部的多行文本继承，导致 `.account-pick`（`height:auto`）里 13px 标题与 11px 说明
  共用 1em 行盒而字身相撞。`base.css` 因此补一条全局兜底
  `button b, button strong, button small { line-height: 1.45 }`，各页多行文本块再显式写
  标题 `line-height:1.45` / 说明 `line-height:1.5` 并加 `margin-top:2px`。
  留白基线：行式表格表头 34px、行 padding 11~15px；账号竖列每项约 52px；卡片块内边距 12~14px；
  浮窗宽 340px（进度小窗 300px、最小化 220px）。
- **弹窗高度链**：`.modal` 是 `flex` 列 + `max-height:min(88vh,900px)`，`.modal-body` 必须有
  `flex:1 1 auto; min-height:0` 才能拿到剩余高度，否则子级的 `position:sticky; bottom:0` 底栏
  （如 `NewTask.vue` 的 `.wizard-foot`）会被 `overflow:hidden` 裁掉下半。
- 验收锚点（`tools/vue_check.py` 断言）不可重命名：`.execution-account`（总览两卡等高，240–560px）、
  `.execution-course`、`.media-live li`、`.execution-dashboard`、`.progress-window`、
  `.account-menu-item`（左侧账号竖列）、`.workspace-account`（右侧单账号详情）、`.workspace-course`、
  `.progress-account`、`.progress-course`、`.completed-row`。

## 浮层与弹窗的层叠规则（v2.5）

三类浮层各自只负责自己的一层，定位与叠放交给容器：

- **右上角浮窗列**：`App.vue` 用一个 `.float-stack`（`position: fixed`，纵向 flex）承载
  逐题小窗与告警小窗。此前两个小窗各自 fixed 到同一坐标，同时打开时完全重叠。
- **进度小窗**：开合、最小化统一由 `windows/manager.ts` 的 `ensureWindow/openWindow/closeWindow/
  toggleMinimized` 管理。顶栏开关、小窗标题栏与关闭按钮操作同一份状态——此前顶栏切换的是
  `windows.map.progress`，而组件用自己的局部 `closed/minimized`，按钮亮了小窗却不动。
- **弹窗栈**：`ModalShell` 维护一个模块级栈，只有最顶层响应 Escape 与 Tab 焦点陷阱
  （否则任务抽屉上再开确认框时，一次 Esc 会把两层都关掉）；`inert` 作用于整个 `.shell`，
  浮窗在弹窗后面也不可聚焦；焦点落在第一个可操作控件上。
- 层级统一用 `tokens.css` 的 `--z-sticky / --z-overlay / --z-float / --z-toast`，不再写字面量。

## 「已完成」筛选（v2.5）

`GET /api/completed` 新增 `status` 参数（`succeeded,failed,stopped,interrupted`，逗号分隔），
筛选在 SQL 侧完成，返回的仍是带 `answers_summary` / `outcome` / `duration_seconds` / `exam`
的完整视图，`total` 与 `offset` 分页语义同时成立。

此前前端在状态筛选时改打 `/api/history` 取前 200 条本地过滤：分页被隐藏、逐题汇总与结果说明
也不在该接口的返回结构里，筛选后的行只能提示「点详情补齐」。`/api/history` 仍保留给
`tools/smoke_test.py` 与测试使用，职责是轻量列表。

## Worker 公共基座与进程治理（v2.4.0）

`worker/common.py` 是四类 runner（视频 / 会话同步 / 目录 / 课程）的公共基座：

- `build_base_config()` 统一配置组装——`session.rotate_ua=False`（会话同步不轮换 UA 的风控
  约定）在此显式化，runner 不再各自手写 dict。
- `terminate_gracefully()` 阶梯终止子进程：`taskkill`（无 /F，请求体面退出）→
  `CTRL_BREAK` 信号 → 强杀；替代各 runner 手写的收尾逻辑。
- `EventSink` 包装 stdout 事件通道：写入失败计满 3 次抛 `StopRequested`，防止主进程日志
  通道坏死后 worker 无限重试空转。

CLI 配置单源（`cli_copy/core/config.py`）：纯内存 schema，`_normalize_config` 统一钳制与
枚举校验；不再读写磁盘 YAML——一切配置由 API 从「偏好设置」下发。任务状态迁移由
`app/task_model.py` 的 `TRANSITIONS` 表驱动（`_EVENT_HANDLERS` 查表 16 类事件），
`_guard_status` 观察模式下非法迁移仅告警（`TASK_STATE_GUARD_STRICT=1` 切严格）。

## 日志系统（v2.4.0）

单通道结构化：CLI 侧 18 个文件的 `loguru` 直接调用全部收敛到 `core.runtime` 的
`_ModuleLogger`，以 `emit("log", …, stage="log")` 落为任务事件；前端任务详情「诊断日志」
按级别 / 关键词检索、游标分页。事件呈现由 `app/presentation.py` 集中分类：
`LOG_CATEGORIES`（关键词→分类）→ `EVENT_CATEGORIES`（事件映射兜底），
`HIDDEN_EVENTS`（`log` / `task_progress` / `media_progress`）不进活动流；`worker_exit` /
`worker_crash` 自 v2.4.0 T10 起可见。

存储侧配套：`add_event` 缓冲（8 条或 2 秒）+ `executemany` 批量落库；超长 payload 截断；
SSE 游标预分配 `_next_event_id()`（表 MAX 与缓冲尾取大 +1），断线用 `Last-Event-ID`
增量重连不丢事件；任务事件按量保留清理（`tests/test_events_prune.py`）。

## 桌面壳与多窗（v2.4.0）

`desktop/src/main.cjs` 以**注册表模式**管理子窗：`childWindows: Map<route, BrowserWindow>`，
同 route 单实例复用、关闭=隐藏（可复现）。

- IPC：`windows:open(route, preset)` / `windows:close(route)`；`mini:open` / `mini:close`
  保留为迷你监控的语义别名。内置 `WINDOW_PRESETS`（迷你监控 340×220 无边框置顶）+
  未知 route 的 `FALLBACK_PRESET`（360×420）；渲染端仅可覆盖白名单 8 字段
  （title / width / height / minWidth / minHeight / frame / alwaysOnTop / skipTaskbar），
  其余 BrowserWindow 选项不透传；尺寸钳制下限（width≥200 / height≥140 /
  minWidth≥120 / minHeight≥100）。
- preload 桥：`coursearkDesktop.openWindow(route, preset)` / `closeWindow(route)`；
  前端 `frontend/src/desktop.ts` 封装并在浏览器端静默降级（返回 false）。
- 子窗加载 `${baseUrl}/#/${route}`（如 `/#/mini` 紧凑监控视图，2.5s 自刷新），
  与主窗共用同一后端与 `configureNavigation` 导航策略（内部放行、外链交系统浏览器）。
- 生命周期：`window-all-closed` 仅主窗销毁才退出（子窗隐藏不算退出信号）；`before-quit`
  连带销毁注册表全部子窗并 `stopBackend`；`second-instance` 聚焦主窗与全部可见子窗。
- 推迟 v2.4.1：dev 模式接 Vite dev server、托盘图标、崩溃自动恢复。

## 应用内安全验证窗（T16）

学习通对进入考试/作业有平台侧人机验证（滑块、考试码、人脸）。程序不绕过这些校验；
桌面端提供一条「验证在应用内完成、地址自动带回」的流程，替代 v2.2.2 的纯手动粘贴：

1. **导出登录态**：`GET /api/accounts/{id}/session/cookies` 返回已保存会话的 Cookie
   （无会话 409）。服务只监听回环，Cookie 不出本机。
2. **验证窗**：桌面壳新 IPC `verify:open`——按账号开 `persist:cx-<id>` 持久分区
   `BrowserWindow`，`session.setCookie` 注入登录态，UA 与 Worker 对齐；窗口不挂
   preload、不注脚本（验证由用户手动完成）；学习通域名留在窗内，其余链接交系统浏览器。
3. **被动捕获**：`webRequest.onBeforeRedirect/onCompleted`（filter `*://*.chaoxing.com/*`）
   监听带 `enc=` 的 `reVersionTestStartNew` / `doHomeWorkNew` / `selectWorkQuestion`
   与考试 start 跳转；命中后把地址 + 窗口 Cookie 经 `verify:captured` 发给主窗。
4. **回写与预填**：主窗渲染端 `POST /api/accounts/{id}/session/cookies` 把窗口会话
   Cookie 写回会话缓存（白名单字段 name/value/domain/path/expires/secure/httpOnly/
   sameSite），并把地址预填进新建考试任务的「考试答题页地址」（一次性消费）。
5. **防串扰**：验证窗期间不要对同账号并发创建任务——考试 `enc` 是滚动令牌，
   双端并发会互相作废（同类项目踩过的坑，见 research-github 调研增量）。

## 本机数据

网页版默认在项目 `data/` 中保存账号、配置、SQLite 数据库、日志和任务数据。桌面版使用 `%APPDATA%\AutoCxWebUI`，该目录名为兼容既有安装而保留。运行数据不随源码或安装包分发。

服务仅监听 `127.0.0.1`，并校验写请求来源；跨站网页无法调用本机接口。
