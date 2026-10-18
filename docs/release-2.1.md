# CourseArk v2.1 变更与修复说明

v2.1 的主线是**把「独立作业」修到真的能交上**，并按需求**删除在线题库，只保留 AI 做题**，
同时把「AI 在做什么题」实时呈现在界面上。本文记录根因、改动与验证口径，便于以后回归。

## 1. 事故复盘：独立作业为什么失败

2026-10-18 桌面版一次独立作业任务的状态是 `failed`，统计为「共 2 题 | 缓存=0 | 在线题库=0 |
LLM=0 | 随机=1 | 提交成功=0 | 失败=2」。日志显示两道题的 LLM 输入只有约 180 字符、输出 13 tokens，
结果落到「随机 C」，随后提交返回 `无效的参数：code-2！`。

四个根因（都已修复）：

1. **题目容器选择器完全过时**。旧代码用 `div.TiMu` 找题，而在现行作业页里 `TiMu` 命中的是整页外壳
   `div.fanyaMarking.TiMu#fanyaMarking`，于是「举报」链接和课程标题被当成了题干，10 道题被解析成 1 道，
   LLM 拿到的是一个没有题目信息的 prompt，按提示词返回空答案字符串，代码再退回随机作答。
2. **提交端点与参数和浏览器不一致**。页面真实表单是
   `<form action="/mooc-ans/work/addStudentWorkNewWeb?_classId=…&courseid=…&token=<enc_work>&totalQuestionNum=<令牌>">`，
   提交前 JS 还会追加 `ua/formType/saveStatus/version`，并把 `answerwqbid` 填成「全部题号 + 尾逗号」。
   旧实现改打无查询串的 `addStudentWorkNew`、把参数全塞进表单体，服务端因此返回 `code-2`。
3. **本地缓存永远为空**。保存逻辑只在 `item.get("verified_correct")` 为真时才落库，而答题流程从不设置该键，
   于是缓存命中率恒为 0，每题都要重新问 AI。
4. **界面看不到 AI 在做什么**。答题过程只上报聚合统计（`exam_stats`），没有逐题事件；任务列表接口还按
   `feature` 过滤，部分任务根本不在列表里，用户看到的是「做题失效、页面不更新」。

## 2. 改动

### 2.1 新增 `cli_copy/core/work_form.py`

作业页面解析与提交报文构造集中到一处，`deal_exam` 不再手工拼表单：

- `parse_questions(html)`：容器 `div.singleQuesId[data]`（回退 `.questionLi` / `.mark_item`），
  题号 `data` → `id` 数字 → 题内控件名 `answertype<qid>`；题型取 `input[name=answertype<qid>]`；
  题干兼容 `h3.mark_name` 与 `.Zy_TItle > .fontLabel` 两代结构，剥离题号与「（单选题）」标记；
  选项支持 `.answerBg` 与 `ul.Zy_ulTop > li`；填空数取 `tiankongsize<qid>` 或 `answerEditor<qid>N` 数量；
  字体未解码或选择题缺选项时标记 `unreadable` 并给原因。
- `parse_form(html)`：提取 `action`、`method` 与全部具名控件（跳过 disabled，选中的 radio/checkbox 才收）。
- `build_submit_url(action)`：按页面 `version()` 语义追加 `va/formType/saveStatus/version`。
- `build_submission(form, answered)`：页面隐藏域打底，写 `answer<qid>` / `answerEditor<qid>N` / `answertype<qid>`，
  `answerwqbid` 为「逗号拼接 + 尾逗号」，保留页面下发的 `totalQuestionNum` 令牌。
- `split_blanks`：填空按 `;；` 优先、再 `,，、` 拆分并补齐空位。

### 2.2 `cli_copy/functions/deal_exam.py`

- 解析：优先新解析器，旧 `TiMu`/正则路径仅作兜底；`_extract_independent_page` 与 API 兜底路径统一返回
  `(题目, 隐藏字段, 表单)` 三元组。
- 提交：有页面表单时 `work_form.build_submission` 回放；无表单时走 `_legacy_submission` 兼容旧页面。
  新增 `_check_submit_ready()`：POST 前 GET `work/validate`，`1`（状态异常）与 `2`（需要验证码）直接拦截并写明原因。
- 缓存：只有 `source == "llm"` 的答案写入缓存，随机答案不落库。
- 逐题事件：新增 `_emit_answer_result()`，每题 emit `answer_result`（题干/选项/答案/来源/状态/原因）。
- 在线题库：删除 `TikuProvider` 依赖与分支，历史配置 `answer.mode == "tiku"` 归一为 `ai`。

### 2.3 删除在线题库

- 删除 `cli_copy/utils/tiku_provider.py`；`core/config.py` 引入 `REMOVED_KEYS`，读写两侧丢弃 `tiku` 组与
  `answer.fallback_to_tiku`；`answer.mode` 只允许 `ai` / `manual`。
- `app/settings.py`（掩码、默认值、导入映射）、`app/task_model.py`、`app/task_manager.py` 同步删除；
  旧配置/旧预设里的相关字段在读取时忽略、写回时不带（不会报错）。
- 前端删除「题库来源」设置组、`fallback_to_tiku`、`tiku_hits` 展示；「我的题库」改为「答题缓存」。
- `exam_stats` 保留 `tiku_hits` 键（恒 0）以兼容旧事件与旧前端，不再解释为在线题库。

### 2.4 答题缓存与「AI 做题」页签

- `DELETE /api/question-bank` 新增，用于一键清空缓存（界面二次确认）。
- `GET /api/tasks/{id}` 新增 `answers[]` 与 `answers_summary`；答案按 `(media,index)` 去重取最新，
  经 `redact_data` 脱敏，旧任务的这两个字段为空数组/零值。
- 任务详情新增「AI 做题」页签：按作业分组、逐题卡片（题干、选项、答案、来源、失败原因），
  运行中 1.5s 轮询 + SSE 300ms 防抖；摘要展示 AI / 缓存 / 随机 / 未识别分布。
- 侧栏、任务列表、总览里的「题库」字样统一改为「答题缓存」；任务列表去掉 `feature` 过滤，
  所有任务都能在历史里看到。

### 2.5 只读自检工具

`tools/check_work_page.py`：按数据目录读账号，登录后只发 GET，打印解析到的题目、提交 URL、将提交的
全部表单字段，以及 `work/validate` 的提交前置校验结果。用于平台再次改版时快速定位是解析问题还是提交问题。

## 3. 兼容性与迁移

- 设置：旧 `tiku` 组、`fallback_to_tiku`、`mode: tiku` 在读取/导入时被丢弃或归一为 `ai`，不报错。
- 任务：旧任务的 `params_json` 里残留字段在生成任务参数时被忽略；旧事件流仍可展示。
- 数据目录不变（网页版 `data/`，桌面版 `%APPDATA%\AutoCxWebUI`）。
- 旧版 `question_bank.db` 直接作为答题缓存使用，无需迁移。

## 4. 验证

| 项目 | 结果 |
| --- | --- |
| `python -m pytest tests -q` | 271 passed |
| `python -m pytest cli_copy/tests -q` | 24 passed |
| `python tools/smoke_test.py --mock` | 56 项通过 |
| `npm --prefix frontend test` | 8 passed |
| `npm --prefix frontend run build` | 成功，产物已更新 `webui_static/vue` |
| `npm --prefix desktop test` | 8 passed |
| `npm --prefix desktop run dist:win` | 成功，生成 `desktop/dist/CourseArk-2.1.0-Setup.exe` 与 `CourseArk-2.1.0-Portable.exe` |
| `npm --prefix desktop run smoke:packaged` | 当前自动化会话无交互桌面，Electron 无法创建窗口（已安装的 2.0.0 表现相同），需在真实桌面会话手动确认 |
| `python tools/vue_check.py` | 35/35 通过，无浏览器错误 |
| `python tools/ui_check.py` | 35/35 通过 |
| 真实账号只读核对（`tools/check_work_page.py`） | 「第4章组件」解析出 10 题（5 单选 + 5 简答）、题干与选项正确、表单 action 带 `token`/`totalQuestionNum`、35 个提交字段、`work/validate` 返回可提交 |

新增/更新的单测：`tests/test_work_form.py`（12 例：两代页面结构、整页外壳不误判、表单解析、
URL 版本参数、填空拆分、报文构造、旧版兜底）、`cli_copy/tests/test_core_behaviors.py`
（提交回放页面表单 / 无表单时回退旧端点）、`tests/test_ai_only_backend.py`（AI-only 后端行为）。

## 5. 尚未验证与已知风险

- **真实提交**：自动测试与自检脚本都不会提交答案，`addStudentWorkNewWeb` 的成功响应只在浏览器里验证过
  协议一致。请用桌面版跑一次真实独立作业确认；若仍失败，任务详情「AI 做题」和诊断日志会给出提交 URL 与响应。
- **验证码**：`work/validate` 返回「需要验证码」时会中止并提示，目前不自动识别验证码。
- **页面变体**：已覆盖现行内嵌题目页与导出页两代结构；其它课程若出现第三种结构，先跑自检脚本再补选择器。
- **简答题**：现行页面把部分判断题以「简答题（answertype=4）」形式下发，AI 返回的「正确/错误」会按文本写入，
  答案质量依赖模型；如需更严格，可在此处加题型启发式（见 `docs/research-github.md`）。

## 6. 下一版候选（来自 GitHub 调研）

`docs/research-github.md` 汇总了同类项目的做法与 14 项功能候选。与本项目方向最贴近的顺序建议：

1. 失败题汇总与「异常率阈值中止」（参考 uh 的 `cover_rate`），避免大面积随机作答；
2. 任务断点续跑（保存已完成题目索引，重跑只补未完成部分）；
3. 图片题干 OCR / 多模态答题（仅允许 `chaoxing.com` HTTPS 图片）；
4. 答案校验更严（简答题关键词、判断题启发式），并允许用户自定义兜底策略；
5. 桌面端打包流程固化（本地已验证的构建/冒烟命令写进 CI）。
