# 课舟 CourseArk v2.2.1 发布说明

> 本版修复三个真实使用问题：任务点进度一直显示 `0/0`、任务中断后重开直接显示「已完成」、
> 独立考试总是失败（现定位为平台安全验证）。此外补上了启动自动同步与「继续执行」。

## 一、问题与根因

### 1. 课程任务点全部显示 `0 / 0`

- 现象：桌面版「××的课程」弹窗里，每门课都是 `0 / 0 个任务点`，手动点同步也一样。
- 根因有两处：
  1. `worker/sync_runner.py` 在生成课程快照时把 `mission_fn` / `mission_all` 写死为 `0`，
     完全没有去读任务点进度——同步只同步了课程名与教师。
  2. `models/course.py::get_chapter()` 解析任务点只用
     `./div[1]/h2/span/text()`。现代课程页把「已完成任务点: 109/125」放在 `h2` 的文本节点里、
     只把 `109` 放进 `span`，因此即使读到了也得到 `109/0`。
- 修复：
  - 新增 `Course.parse_mission_progress()` / `Course.get_mission_progress()`：依次尝试
    「已完成任务点 N/M」标签、`chapter_head` 文本、整页文本兜底，要求文本含「任务点」才接受比例；
  - `sync_runner.py` 逐课读取任务点进度，边同步边发 `sync_progress`
    （`{done,total,course,mission_fn,mission_all}`），单课失败不中断整体同步，
    连续 5 门失败才中止；`sync_result` 增加 `course_errors`；
  - 启动时自动同步：`scheduler.sync_on_start`（默认 `true`）。只同步 `login_state=ok` 的账号，
    后台串行执行，失败写站内通知、不阻塞启动；设置页可关闭。

### 2. 任务点做到一半退出程序，重开后直接显示「已完成」

- 现象：任务执行中退出应用，重新打开再做，任务几秒就成功结束，不再继续处理。
- 根因有三层：
  1. 发现阶段一个任务点都没识别出来时，`CourseExecution.run()` 会静默 `succeeded`，
     事件流里只有空 `work_plan`，看不出「其实没做」；
  2. 旧任务点解析把 `109/125` 读成 `109/0`，丢失了「还有 16 个待完成」这一事实；
  3. 中断任务只能重新建任务，没有「按原参数继续」的入口。
- 修复：
  - `CourseExecution._finish_without_jobs()`：0 个任务点时按平台数字判断——
    还有未完成 → 抛 `RequestException`「平台显示还有 N 个任务点未完成（a/b），但未能识别具体任务」；
    确实全部完成 → 明确提示「平台显示课程任务点已完成（a/b），本次没有需要处理的任务」；
  - `POST /api/tasks/{id}/resume`：`interrupted` / `stopped` / `failed` 任务按原 `params_json`
    重新排队（返回 `resumed_from`、`new_task_id`），`paused/pausing` 仍走原「继续」语义；
  - 任务列表对上述状态显示「继续执行」；任务详情返回 `unfinished_units`
    （`running/failed/blocked/skipped` 的 work 单元数），便于判断上次做到哪。
  - 已完成的部分由平台状态自动跳过，不会重复提交作业答案。

### 3. 独立考试总是失败

- 现象：考试任务创建后立即 `blocked`，日志「无法进入考试: 无权限访问」。
- 根因：
  1. 进入考试的 URL 用错了参数：把 `paper_id` 当成 `tId`，实际 `tId` 必须是**考试 ID**，
     且新版考试入口在 `/exam-ans/...` 下、还带 `newMooc=true`；
  2. 学习通对进入考试有平台侧安全校验（考试说明页 `captchaCheck=1` / `examCheck=1`），
     必须先过人机验证；手机端接口同样要求（`captchaCheck=1` + `captchaCaptchaId`）。
- 修复：
  - `Course.exam_notes_url()` / `Course.parse_exam_notes()`：先读考试说明页，取真实入口
    （`#startBtn[data]`、`enc=?` 占位）与风控开关；`Course.exam_start_url()` 改为 `tId=<考试ID>`、
    `newMooc=true`、`/exam-ans` 主机，重考才用旧 `/exam` 路径；
  - `DealExamRoom.answer_exam()`：`needCode` → 明确提示需要考试码；`captchaCheck`/`examCheck`
    → 先调用只读的 `examcheck` 查询验证状态：已通过则用返回的 `enc` 补齐入口地址继续；
    仍未通过则明确提示需要平台安全验证，并在**启动考试之前**中止（不开始计时、不提交答案）；
  - 手动验证后的复跑：在浏览器里完成验证后重新执行同一考试任务，`examcheck` 若返回
    `status=true`+`enc` 即自动继续（这一步只发 GET，不会重复开始考试）；
  - `tools/check_work_page.py --kind exam` 同时打印入口页、风控开关与构造地址，便于只读核对。
- 边界：平台人机验证/考试码无法自动通过，本工具不会尝试绕过。可在考试列表点
  「在浏览器中打开」手动完成验证；验证后平台可能仍要求逐题进入，属平台策略限制。

## 二、改动文件

| 文件 | 改动 |
|---|---|
| `cli_copy/models/course.py` | 任务点进度解析、考试说明页解析、进入考试 URL 修正 |
| `cli_copy/functions/course_execution.py` | 0 任务点时的显式失败/成功语义 |
| `cli_copy/functions/deal_exam_room.py` | 考试入口改用说明页，命中风控时安全中止 |
| `worker/sync_runner.py` | 逐课任务点进度、`sync_progress`、错误容忍 |
| `app/settings.py` | `scheduler.sync_on_start` |
| `app/main.py` | 启动自动同步、`POST /api/tasks/{id}/resume`、`unfinished_units` |
| `frontend/**` | 任务点进度与未同步提示、继续执行、自动同步开关、考试「在浏览器中打开」、页面细节 |
| `tools/check_work_page.py` | 考试只读核对扩展 |
| `tests/` | `test_mission_progress.py`、`test_course_execution.py`、`test_exam_notes.py`、`test_auto_sync_and_resume.py` 等 |

## 三、兼容性与迁移

- 数据目录不变（`%APPDATA%\AutoCxWebUI`），直接覆盖安装即可，无需迁移。
- 旧任务（含 `interrupted` / `failed`）在任务列表可直接「继续执行」。
- 新增设置项 `scheduler.sync_on_start` 默认开启；可用环境变量
  `AUTOCXWEBUI_DISABLE_AUTO_SYNC=1` 临时关闭（测试/自动化场景）。

## 四、验证

| 项目 | 结果 |
|---|---|
| `python -m pytest tests cli_copy/tests -q` | 362 passed |
| `python tools/smoke_test.py --mock` | 56 通过 / 0 失败 |
| 真实账号只读同步（23 门课） | 9 门读到任务点进度，如 `109/125`、`27/27`、`148/149`、`248/248`；无 course_errors |
| 真实账号只读考试核对 | 入口页 `examCheck=1`、`captchaCheck=1`，程序按设计安全中止并给出提示 |
| `python tools/vue_check.py` | 47/47 通过，浏览器错误 0（含任务点、续跑提示条、自动同步开关、考试验证入口） |
| `python tools/ui_check.py` | 47/47 通过 |
| `npm --prefix frontend test` | 25 passed |
| `npm --prefix desktop test` | 8 passed |
| `npm --prefix desktop run dist:win` | 产出 `CourseArk-2.2.1-Setup.exe` / `-Portable.exe` |

未验证项：本会话环境没有可交互桌面，Electron 窗口无法在此环境手动确认；真实考试交卷流程
未执行（该考试被平台安全验证拦截，属于已知限制）。

> **后续版本已解决（v2.2.2）**：本版对考试只能「安全中止并提示」；v2.2.2 新增「粘贴考试答题页
> 地址」直连作答，已在真实考试中完成交卷（10/10 题）。见 [`docs/release-2.2.2.md`](release-2.2.2.md)。
