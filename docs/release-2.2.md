# 课舟 CourseArk 2.2.0 版本说明

> 本轮目标：让 AI 答得更准、把「考试」接进同一条答题链路、让作业/考试可以挑着做、运行中能看见「正在做什么、还要多久」。

## 一、AI 做题正确率：提示词 v2

改动集中在 `cli_copy/utils/llm_client.py`：

- **上下文注入**：请求里带上「课程：<课程名>」与「作答内容：独立作业/考试《<标题>》」，
  并要求模型「结合该课程的知识范围作答」。此前 prompt 里只有题干，模型不知道这是哪门课。
- **不允许空答**：v1 提示词允许「信息不足时返回空字符串」，结果是模型大量返回空答案，
  再被兜底成随机选项。v2 改为「即使不确定也必须给出最可能答案」，空串会被判为无效并
  **用严格模式重试一次**（`STRICT_PROMPT`：只输出 JSON、不要思考过程、答案非空）。
- **答案清洗**：新增 `_clean_value`，把 `答案：B.`、`(B)`、`**D**`、反引号等常见装饰
  统一清洗成纯字母/文本，减少「模型答对了但解析不出来」的浪费。
- **解析忽略 `reason`**：新提示词要求模型额外给一句依据（`reason`），用于让模型自我核对，
  解析层丢弃该字段，不影响兼容性。
- **校验不变**：答案仍要过 `core/answer_validation.py`（判断题归一 true/false；
  选择题必须落在选项字母集内，多选按序拼接）。

已知边界：正确率天花板由模型本身决定，提示词只能消除「空答/格式错」这类浪费，
不能保证知识性题目答对；需要更高正确率时，请在设置里换成更强的模型。

## 二、独立考试（新功能）

新增任务类型「独立考试」（`feature=exam`），与独立作业同一套作答链路：

1. **列出考试**：`GET https://mooc1.chaoxing.com/exam/test?courseId&classId&ut=s&cpi&openc&enc`，
   解析 `goTest(courseId, examId, relationId, endTime, paperId, isRetest, examEnc)` 七个参数，
   以及状态、考试窗口、`TestRelationInfo[examId].limitTime` 限时。
2. **开始考试**：`GET /exam/test/reVersionTestStartNew?courseId&classId&tId=paperId&id=relationId&p=1&tag=1&enc&examsystem=0&cpi&openc`。
3. **作答**：`core/exam_form.py` 解析答题页（与作业页同构时复用 `work_form`），
   逐题走「答题缓存 → AI → 兜底」链路，并逐题发 `answer_result` 事件，
   任务详情「AI 做题」页签实时可见。
4. **交卷**：优先回放页面里的真实 `<form>`；没有表单时只从页面内联脚本探测提交端点；
   探测不到就中止并记录原因（**不猜端点**）。
5. **安全中止**（命中任一即不提交）：
   - 识别为「一页一题」考试（页面出现「下一题」/逐题保存脚本）；
   - 页面里出现「无权限访问 / 长时间没有操作 / 请重新登录 / 验证码 / 人脸识别 /
     不在考试时间 / 考试已结束」等拦截文案；
   - 解析出的题目数为 0。

**已知限制（重要）**：PC 端考试的交卷端点没有公开可靠证据，且多数 PC 考试是「一页一题」，
当前版本会识别出来并**安全中止**（不提交半份答案）；已验证的手机端协议
（`reVersionSubmitTestNew` + 签名参数）只做了调研记录，见
[`docs/research-exam.md`](research-exam.md)，尚未实现。因此在浏览器里只能一页一题作答的考试，
本版本会提示你在网页端手动完成。

## 三、挑选作业/考试

- 新增课程目录接口 `GET /api/accounts/{id}/courses/{course_id}/catalog?kind=work|exam&refresh=false`：
  由 `app/catalog_service.py` 拉起 `worker/catalog_runner.py` 子进程登录并只读拉取列表，
  结果写入 SQLite 表 `course_catalog` 缓存 600 秒；失败时有旧缓存则降级返回并带 `error`。
- 新建任务时，选好课程后可「加载列表」，勾选要处理的作业/考试（默认全选，可全选/取消全选），
  提交为 `params.selection = {mode: "selected", ids: [...]}`；不勾选任何项时为 `mode: "all"`。
- 任务执行端（`worker/runner.py`）按 `selection.ids` 过滤；`deal_homework` / `deal_exam_room`
  会把「勾选的项不在待处理范围」等原因为写进日志，避免出现「0 个待处理」而无解释。

## 四、运行中的进度小窗

- `GET /api/tasks/{id}` 新增 `live` 快照：当前动作、动作时间、已用时、
  当前处理项的 `current/total`，以及预计剩余 `eta_seconds` + `eta_source`。
  预计剩余优先用「当前项速率」推算（视频/下载这类有明确总量的项更准），
  其次退化为「任务级速率」，老任务返回 null。
- 前端右下角浮动小窗显示「正在做什么 / 已用时 / 预计剩余 / 当前项百分比」，
  可最小化或关闭；任务列表里运行中的行也显示一行摘要。

## 五、变更文件

后端与答题链路（Lead）：

- 新增 `cli_copy/core/exam_form.py`、`cli_copy/functions/deal_exam_room.py`、`worker/catalog_runner.py`；
- `cli_copy/models/course.py`（`get_exam_list` / `exam_start_url`）、
  `cli_copy/utils/llm_client.py`（提示词 v2 / context / strict / `_clean_value`）、
  `cli_copy/functions/deal_exam.py`（上下文注入 + 严格重试）、
  `cli_copy/functions/deal_homework.py`（selection 过滤）、`worker/runner.py`（exam 分发）；
- 新增 `tests/test_exam_form.py`；扩充 `cli_copy/tests/test_core_behaviors.py`、`tests/test_worker_features.py`；
- `tools/check_work_page.py` 支持 `--kind exam`（默认只读列出考试，不发起「开始考试」）。

服务端（backend-api）：`app/task_model.py`、`app/database.py`、`app/catalog_service.py`（新）、
`app/main.py`、`app/narrative.py`、`app/presentation.py`、`tests/test_catalog_and_live.py`（新）等。

前端（frontend-ui）：新增 `frontend/src/catalog.ts`、`live.ts`、`components/ProgressWindow.vue` 及测试；
`NewTask.vue`（独立考试 + 列表勾选）、`TaskList.vue`（运行摘要）、`TaskDrawer.vue`（考试文案）等。

## 六、验证

| 项目 | 结果 |
| --- | --- |
| `python -m pytest tests cli_copy/tests -q` | **324 passed** |
| `npm --prefix frontend test` | **18 passed**（7 文件） |
| `npm --prefix frontend run build` | 成功（`index-CWgiPDO_.js` 174.6kB / `index-BtSmST93.css` 46.7kB） |
| `python tools/smoke_test.py --mock` | **56 通过 / 0 失败** |
| `python tools/vue_check.py` | **40/40 通过**，0 浏览器错误 |
| `python tools/ui_check.py` | **40/40 通过** |
| `npm --prefix desktop test` | 8 passed |
| `npm --prefix desktop run dist:win` | 成功产出 `CourseArk-2.2.0-Setup.exe` / `-Portable.exe` |
| 真实账号只读核对（作业） | 第4章组件 10 题解析正确；`work/validate` 可提交 |
| 真实账号只读核对（考试） | 列出「vue3第一章测试题」（状态待做、限时 100 分钟、考试窗口 2026-10-18 20:00 至 10-31 20:00） |
| 真实账号只读核对（目录接口） | `catalog?kind=work` 3 项、`kind=exam` 1 项，字段与前端契约一致 |

边界：本会话没有交互式桌面，Electron 安装包只能构建、不能在这里验证窗口
（`smoke:packaged` 需要真实桌面会话）；考试链路**没有**用真实考试验证
（开始考试会占用考试机会且不可逆），只做了只读列表核对与合成页面单测。

## 七、升级说明

- 直接覆盖安装即可，数据目录不变（桌面版 `%APPDATA%\AutoCxWebUI`）。
- 旧配置自动兼容：`tiku` 组与 `answer.fallback_to_tiku` 在读取时丢弃，
  `answer.mode: tiku` 归一为 `ai`。
- 关闭程序后安装新版；安装包与便携版文件名带版本号，便于回滚。
