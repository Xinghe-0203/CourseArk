# 课舟 CourseArk v2.2.2 发布说明

> 本版把「独立考试」从「只能提示平台安全验证」变成**真正能交卷**：
> 在浏览器里进入考试后，把地址栏的答题页地址粘贴进来，程序即可逐题 AI 作答并自动交卷。
> 该流程已在真实考试中跑通并完成交卷（10/10 题，平台显示「已完成」）。

## 一、为什么需要粘贴地址

学习通进入考试前有一道**平台侧安全验证**（考试说明页 `examCheck=1` / `captchaCheck=1`，
需人机验证）。验证凭证绑定在浏览器会话上，程序的 HTTP 会话既拿不到、也不应尝试绕过，
因此 v2.2.1 只能安全中止并提示用户。

v2.2.2 改用「用户验证、程序作答」的分工：

1. 用户在浏览器里完成平台验证，正常进入考试答题页；
2. 复制地址栏里带 `enc=` 的答题页地址（`/exam-ans/exam/test/reVersionTestStartNew?...`）；
3. 在 CourseArk 新建「独立考试」任务时粘贴该地址，程序直接在该页面上作答。

带 `enc` 的地址本身就是平台发给本次考试的授权凭证，程序只做「打开已授权的答题页 → 读题 →
填答案 → 保存 → 下一题 → 交卷」，**不触碰验证码、不伪造验证结果、不重复开始考试**。

## 二、实现

### 1. 新增纯解析模块 `cli_copy/core/exam_answer_page.py`

无网络请求、可单测，负责把答题页 HTML 转成结构化数据，并构造提交报文：

- `parse_exam_url(url)`：校验并解析粘贴地址（`courseId/classId/tId/id/enc/cpi/openc`），
  非答题页地址给出中文可操作提示；
- `parse_answer_page(html)`：解析当前题（`qid`、题型、题干、选项、第几题/总题数、剩余时间、
  试卷名、`#submitTest` 隐藏字段、表单 action），并识别「已交卷」「被平台拦截」页面；
- `question_from_page(page)`：转成 `LLMClient.answer_single` 需要的题目结构；
- `submit_query/submit_url/build_submit_data`：按真实页面协议构造提交请求。关键细节：
  - 提交 query 只保留 `classId/courseId/testPaperId/testUserRelationId`，
    再补 `cpi`、`tempSave`、`version=1`；**多带 `keyboardDisplayRequiresUserAction=1`
    会被服务端判「提交失败：无效操作」**；
  - 表单 action 里的 `&amp;` 必须 `html.unescape`，否则 query 键会变成 `amp;classId`；
  - 答案写入隐藏字段 `answer<qid>`（选择题写字母、判断题写 `true`/`false`），
    并设 `isAnswered=true`；
  - 服务端接受**不带 `pos` 签名**的提交（`pos` 来自平台混淆脚本，普通浏览器同样不签）。
- `build_next_url(entry, data, start)`：用提交响应里的
  `data="lastUpdateTime|remainTime|enc"` 拼「下一题」地址（与页面 `getTheNextQuestion` 一致）；
- `normalize_answer(type_code, answer)`：单选/多选规范化字母、判断题映射 true/false、
  其它题型清理「答案：」前缀。

### 2. 新增执行器 `cli_copy/functions/exam_room_url.py`

`ExamRoomByUrl(user, course, log, ui)` 复用 `DealExam` 的 LLM、答题缓存与逐题上报：

- 校验粘贴地址的 `courseId` 与任务课程一致，不一致直接给出可读错误；
- 逐题：AI 作答 → `tempSave=true` 保存 → 用响应前进到下一题；
- 最后一题保存后以 `tempSave=false` 交卷，响应 `status=submitted/forceSubmitted` 视为交卷成功；
- 每题 emit `answer_result`（题目/选项/AI 答案/来源）与 `work_progress`（当前/总数），
  进度小窗因此有真实进度与剩余时间预估；
- 安全护栏：同一题重复出现（页面没前进）→ 中止并提示刷新考试页后重新粘贴；
  最多 200 题；保存被拒/交卷被拒都抛出服务器原文；已交卷页面则记录「已完成」不再作答；
  整卷交卷成功后才把 AI 答案写入答题缓存（避免半途失败污染缓存）；
- `worker/runner.py`：`exam` 任务若带 `params.exam.url` 走本执行器，否则保持 v2.2.1 的
  「按考试列表处理」（仍会在平台验证处安全中止）。

### 3. 参数与界面

- `app/task_model.py` 新增 `ExamParams{url}`，仅 `exam` 功能携带；URL 非空时校验必须是
  学习通答题页地址，否则提示「请粘贴学习通考试答题页地址（含 reVersionTestStartNew 与 enc 参数）」；
- 新建任务选「独立考试」时出现「考试答题页地址（推荐）」输入框，留空则仍按考试列表处理；
- 任务详情沿用 v2.2.1 的「AI 做题」逐题卡片，考试同样适用。

### 4. 自检工具

`tools/check_work_page.py --exam-url "<答题页地址>"`：只读打开该页并打印题目、选项、
表单字段与提交 URL，不发答案、不提交，用于排查「粘贴后没反应」。

## 三、改动文件

| 文件 | 改动 |
|---|---|
| `cli_copy/core/exam_answer_page.py` | 新增：答题页解析、提交报文与下一题地址构造 |
| `cli_copy/functions/exam_room_url.py` | 新增：URL 直连逐题作答与交卷 |
| `worker/runner.py` | `exam` 任务分发到 URL 执行器 |
| `app/task_model.py` | `ExamParams.url`、URL 校验、exam 参数快照 |
| `frontend/src/components/NewTask.vue` | 考试答题页地址输入框与校验 |
| `tools/check_work_page.py` | `--exam-url` 只读自检；修复 `--help` 中 `%APPDATA%` 转义 |
| `tests/test_exam_answer_page.py` | 新增 31 例（URL/页面/提交报文/答案规范化） |
| `tests/test_exam_room_url.py` | 新增 11 例（完整两题作答交卷、各类中止路径、无答案/越界答案/手动模式拦截） |
| `tests/test_storage_and_model.py`、`tests/test_catalog_and_live.py` | 参数快照与校验用例更新 |

## 四、兼容性与迁移

- 数据目录不变（`%APPDATA%\AutoCxWebUI`），覆盖安装即可。
- 旧考试任务（不带 URL）行为与 v2.2.1 一致：仍会在平台安全验证处中止并提示，不会自动开始考试。
- 粘贴地址带有时效（`enc` 由平台按考试会话签发）；过期后重新进入考试再复制一次即可。

## 五、验证

| 项目 | 结果 |
|---|---|
| `python -m pytest tests cli_copy/tests -q` | 406 passed |
| `python tools/smoke_test.py --mock` | 56 通过 / 0 失败 |
| `python tools/vue_check.py` | 48/48 通过（含考试地址输入与提交参数） |
| `python tools/ui_check.py` | 47/47 通过（浏览器错误 0） |
| `npm --prefix frontend run build` | 通过（`vue-tsc` + vite） |
| `npm --prefix frontend test` | 25 passed |
| `npm --prefix desktop test` | 8 passed |
| 真实考试（`vue3第一章测试题`，10 题） | 粘地址 → 逐题作答 → 自动交卷：`{"msg":"提交成功","status":"success"}`，平台考试状态「已完成」，用时 21 分钟 |
| `npm --prefix desktop run dist:win` | 产出 `CourseArk-2.2.2-Setup.exe` / `-Portable.exe` |

未验证项：本会话环境没有可交互桌面，Electron 窗口需在本机手动确认；
不同题型的考试（多选、填空、简答）已按页面协议实现并有单测，但尚未在真实考试中逐类验证。

## 六、使用与边界

- 平台安全验证、考试码仍需用户在浏览器完成；本工具不会绕过，也不会代为开始考试。
- 考试是有时限、可能影响成绩的操作：请确认允许 AI 作答后使用；程序在交卷前会逐题保存，
  中途退出可在考试页面继续（平台已保存的临时答案仍在）。
- 若粘贴后提示「答题页没有前进」：刷新考试页重新复制地址，通常是页面已过期或平台限制了并发作答。
