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
- `app/`：FastAPI 路由、持久化、任务调度、会话、课程同步和通知。
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
- 考试**没有**可靠的整卷临时保存语义，因此本版本不会「先保存再补交」；识别不了页面就中止。
- PC 端交卷端点无公开可靠证据，优先回放页面表单；没有表单时只从页面内联脚本探测候选，
  探测不到即中止（不猜测端点）。手机协议（`reVersionSubmitTestNew` + 签名）调研结果见
  [`docs/research-exam.md`](research-exam.md)，尚未实现。

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

## 本机数据

网页版默认在项目 `data/` 中保存账号、配置、SQLite 数据库、日志和任务数据。桌面版使用 `%APPDATA%\AutoCxWebUI`，该目录名为兼容既有安装而保留。运行数据不随源码或安装包分发。

服务仅监听 `127.0.0.1`，并校验写请求来源；跨站网页无法调用本机接口。
