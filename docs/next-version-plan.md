# 课舟 CourseArk v2.1 改造方案（团队协作基线）

> **状态：已实施完成（2026-10-18）。** 落地方案、根因复盘与验证结果见
> [`docs/release-2.1.md`](release-2.1.md)；本文件保留为当时的实施口径，便于追溯。
>
> 本文件是 v2.1 迭代的唯一口径来源。所有成员在改动前先读本文件；实现与本文件冲突时先告知 Lead，不要各自发挥。

## 0. 本轮目标

1. **修好「独立作业 / 章节测验」的 AI 作答与提交**：题目解析正确、AI 答案不被静默丢弃、提交不再报「无效的参数：code-2」。
2. **只保留 AI 做题**：删除在线题库（enncy / icodef / datam）全部功能与配置。
3. **页面能实时看到 AI 做题**：逐题作答明细（题干、题型、AI 答案、来源、状态）随任务实时更新。
4. **优化页面**：删除冗余入口、统一视觉、补齐空状态与运行中反馈。
5. 参考 GitHub 同类项目完善下一版（见 `docs/research-github.md`）。

## 1. 产品口径

- 作答方式只剩两种：`ai`（默认）与 `manual`（只抓题不答）。
- 本地答题缓存保留，用于同题复用（省 token），UI 名称统一为 **「答题缓存」**，不再叫「题库」。
- 删除的概念：在线题库、题库 token、`fallback_to_tiku`、`answer.mode == "tiku"`、叙事里的「在线题库」字样。
- 保留：`no_answer_action`（`random` / `skip`）、`submit_delay`、`auto_submit`、`question_bank.auto_save`。

## 2. 逐题 AI 明细：事件契约（Lead 在 worker 侧产出，后端/前端照此消费）

每作答一题，worker 通过 `runtime.emit` 发一条事件（新增，不影响现有 `exam_stats`）：

- `event`: `answer_result`
- `stage`: `work`（独立作业 / 章节任务点作业）或 `exam`（章节测验）
- `level`: `info`（已作答）或 `warning`（跳过 / 无法识别）
- `message`: 一行人类可读摘要，例如 `第 2 题 单选题 -> C（AI）`
- `payload`:

```json
{
  "index": 2,            // 本份作业内第几题（1 基）
  "total": 4,            // 本份作业题目总数
  "media": "第4章组件",   // 作业/测验名称
  "question_type": "单选题",
  "question": "下列关于组件通信的说法……",   // 题干，截断到 160 字以内
  "options": ["A. props", "B. emit"],      // 可选，最多 6 项，每项截断 60 字
  "answer": "C",          // 规范化后的答案；无答案时为空串
  "source": "ai",         // ai | cache | random | failed
  "status": "answered",   // answered | skipped | unreadable
  "note": ""              // 可选：失败原因（如「题面未识别」）
}
```

约定：
- `source=failed` 时 `status` 必为 `skipped`/`unreadable`，`answer` 为空串。
- 同一题可能因重试发多条；**消费端按 (media, index) 取最后一条**。
- 事件必须逐题实时发出（题目答完即发，不要等整份作业结束）。

## 3. 后端 API 契约

### 3.1 任务详情新增字段（`GET /api/tasks/{id}`）

```json
{
  "answers": [
    {
      "key": "第4章组件#2",
      "index": 2, "total": 4, "media": "第4章组件",
      "question_type": "单选题", "question": "……", "options": ["A. …"],
      "answer": "C", "source": "ai", "status": "answered", "note": "",
      "ts": 1760790000.0, "time": "2026-10-18T20:03:00"
    }
  ],
  "answers_summary": {
    "answered": 3, "skipped": 1, "total": 4,
    "ai": 2, "cache": 1, "random": 0, "failed": 1,
    "submit_ok": 1, "submit_fail": 0
  }
}
```

- 只从 `event='answer_result'` 的事件派生，最多回放 500 条，按 `(media, index)` 去重取最新，按 media 分组但返回平铺数组（前端自行分组）。
- 复用 `_event_view` 的脱敏（`redact_data` / `redact`）。
- 任务不存在仍返回 404。

### 3.2 答题缓存接口（保留并改名）

- `GET /api/question-bank/stats`、`/search`、`/export`、`/import`、`/import-db`、`DELETE /api/question-bank/{hash}`：**保留**，响应字段不变。
- 新增 `DELETE /api/question-bank`：清空全部缓存，返回 `{"deleted": n}`。

### 3.3 设置项变更

- 删除 `tiku` 整组（`enabled/timeout/order/*-token`）。
- 删除 `defaults.answer.fallback_to_tiku`。
- `defaults.answer.mode` 允许值只剩 `ai` / `manual`；传入 `tiku` 时回落为 `ai` 并在响应中忽略（不报错，避免旧配置导入失败）。
- 旧 settings 里残留的 `tiku` 键在读取/保存时被丢弃（迁移：读取时忽略，写回时不带）。
- `GET /api/settings` 的 `features` 不变。

## 4. 前端契约

- 侧栏导航：`工作总览 / 账号与课程 / 学习任务 / 答题缓存 / 问题中心 / 偏好设置`（「我的题库」改「答题缓存」）。
- `store.refresh()` 获取任务列表时**不再按 feature 过滤**（当前只取 course_all 与 independent_homework，导致其它任务不可见）。
- 任务详情抽屉新增「AI 做题」页签：读 `detail.answers`，按 `media` 分组，逐题卡片展示题型、题干、选项、答案、来源徽章、状态；运行中每 1.5s 轮询一次，任务进入终态后停止轮询。
- 运行中反馈：SSE 事件到达即刷新任务列表与当前打开的任务详情（沿用现有 debounce，≤600ms）。
- 删除前端所有在线题库字段与「题库来源」文案；`NewTask` 作答方式只剩「AI 作答 / 手动」。
- 视觉优化不得更换技术栈，不得引入新的 UI 框架；沿用 `style.css` 的变量体系，重点：信息层级、卡片间距、空状态、加载态、长文本换行、窄屏可用。

## 5. 文件写作用域（避免并行冲突）

| 成员 | 独占写作用域 |
| --- | --- |
| lead | `cli_copy/**`、`worker/runner.py`、`tests/test_exam_*.py`、`tests/test_llm_*.py`、`tools/**`、`docs/architecture.md`、`README.md` |
| backend-api | `app/**`、`tests/test_api.py`、`tests/test_settings_*.py`、`tests/test_modernization.py`、`tests/test_import_and_config.py` |
| frontend-ui | `frontend/**` |
| gh-research | `docs/research-github.md` |

> 注意：`app/presentation.py`、`app/narrative.py` 属 backend-api；`answer_result` 的 presentation 处理由 backend-api 负责（category 用 `exam`，标题「AI 作答」）。`worker/runner.py` 属 lead，因为要配合事件契约与 tiku 配置清理，改完立刻告知。

## 6. 验证口径（每人都要自己跑）

- 后端/核心：`python -m pytest tests -q` 与 `python -m pytest cli_copy/tests -q` 全绿。
- 前端：`npm --prefix frontend test`、`npm --prefix frontend run build`（或仓库现有构建命令）。
- 集成：`python tools/smoke_test.py --mock`、`python tools/ui_check.py --serve --port 8899`。
- 不允许用 `pytest -k` 只跑自己关心的子集就宣称完成。
