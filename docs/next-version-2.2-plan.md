# 课舟 CourseArk v2.2 实施方案（团队契约）

> 状态：**已实施完成（2026-10-18）**，交付说明见 [`docs/release-2.2.md`](release-2.2.md)。
> 本文件保留为当时的团队口径记录；如与代码不一致，以 `release-2.2.md` 与代码为准。
>
> 原状态：进行中（2026-10-18 起）。本文件是 Lead / backend-api / frontend-ui / gh-research 的共同口径，
> 任何偏离本契约的改动必须先在本文件更新后再实施。

## 1. 本轮目标（来自用户第二轮需求）

1. **提升 AI 答题正确率**：提示词带上课程/作业/考试上下文与作答规则，并对失败解析做一次严格重试。
2. **新增「独立考试」功能**：列出课程考试 → 选择 → 进入考试 → AI 作答 → 提交（与独立作业同模式）。
3. **独立作业支持选择**：新建任务时勾选要做哪些作业（单选 / 全选），不再只能"全部待做"。
4. **课程任务点小窗**：任务运行中显示"正在做什么 + 已用时 + 预计还需多久"。

## 2. 后端契约（backend-api 实施 `app/**`）

### 2.1 新功能类型

- `app/task_model.py`：`FEATURES` 追加 `"exam"`；`FEATURE_LABELS["exam"] = "独立考试"`。
- 新增参数模型：

```python
class SelectionParams(BaseModel):
    mode: str = "all"          # all | selected
    ids: List[str] = []        # work_id / exam_id（按课程过滤）
```

校验：`mode` 只能是 `all`/`selected`；`mode=="selected"` 时 `ids` 不能为空，报错文案「选择模式下至少选择一项」；`ids` 去重去空白。
- `TaskParams` 增加 `selection: SelectionParams = Field(default_factory=SelectionParams)`；
  `from_settings()` 允许 `overrides["selection"]` 覆盖（dict 合并已通用，注意 ids 是列表要整体替换）；
  `for_feature()`：
  - `independent_homework` → `("answer", "advanced", "selection")`
  - `exam` → `("answer", "advanced", "selection")`
  - 其它不变。

### 2.2 课程目录 API（用于选择作业/考试）

```
GET /api/accounts/{account_id}/courses/{course_id}/catalog?kind=work|exam&refresh=false
```

- 数据来源：启动子进程 `worker/catalog_runner.py`（Lead 负责实现），job 文件内容：
  ```json
  {"account_id":"...","account_label":"...","username":"...","password":"...",
   "course_id":"...","class_id":"...","cpi":"...","kind":"work","task_dir":"..."}
  ```
  用法参照 `app/sync_service.py`：写 `paths.TASK_DIR/catalog-<account>-<course>-<kind>.json`，
  `subprocess.Popen([sys.executable, worker/catalog_runner.py, job_path], cwd=ROOT_DIR, stdout=PIPE, stderr=STDOUT, env=...PYTHONIOENCODING/PYTHONUNBUFFERED/AUTOCXWEBUI_DATA_DIR)`。
  stdout 每行一个 JSON：`{"event":"log"|"catalog_result"|"catalog_failed","message":...,"level":...,"payload":{...}}`。
  - `catalog_result` payload：`{"account_id","course_id","kind","items":[...],"display_name":""}`
  - `catalog_failed` 时 message 为可直接展示的中文原因。
- 缓存：SQLite 新表 `course_catalog(account_id, course_id, kind, items_json, fetched_at)`；
  TTL 600 秒；`refresh=true` 强制重取。缓存命中返回 `from_cache: true`。
- 响应（200）：
  ```json
  {"account_id":"...","course_id":"...","kind":"work","items":[...],
   "fetched_at":1760000000.0,"from_cache":true,"error":""}
  ```
  无缓存且取数失败 → 502 `{"detail":"<中文原因>"}`（前端提示可重试）。
- `items` 结构（由 catalog_runner 产出，后端原样透传）：
  - `kind=work`：`{"id","title","status","time_left","valid","url"}`
  - `kind=exam`：`{"id","title","status","start_time","end_time","limit_time","valid","relation_id","paper_id"}`
  - `valid` 含义：当前可作答（未提交且未过期）。

### 2.3 任务详情增加「运行中快照」`live`

`GET /api/tasks/{id}` 响应新增：

```json
"live": {
  "activity": "正在播放「1.1 Vue 基础」",
  "activity_at": 1760000000.0,
  "elapsed_seconds": 754,
  "unit": {"label":"1.1 Vue 基础","current":120,"total":600},
  "eta_seconds": 380,
  "eta_source": "unit"
}
```

- `activity`：最近一条业务事件的 `presentation.title`（缺 detail 时拼上），没有则为 `stage` 中文或「准备中」。
- `activity_at`：该事件 `ts`。
- `elapsed_seconds`：`now - started_at`（终态用 `finished_at - started_at`）。
- `unit`：最近 `work_progress`/`media_progress` 事件的 `{name|media, current, total}`（数字型），没有则 `null`。
- `eta_seconds`：优先「当前项速率」= `(total-current) / (current/age)`，其中 `age = now - activity_at`
  （`current`/`total` 是秒或字节都适用，要求 `current>0 && total>current && age>1`）；
  否则用任务级 `剩余项/已完成项 * 已用时`（`completed>0`）；都不满足为 `null`，`eta_source` 为 `unit|task|null`。
- 老任务/无数据时 `live` 可为 `null`，前端必须容错。

## 3. 前端契约（frontend-ui 实施 `frontend/**`）

1. **新建任务**：功能选项新增「独立考试」。选择作业/考试课程后显示「加载列表」按钮 →
   `GET .../catalog?kind=work|exam`；列表项带状态徽标与时间；顶部「全选/取消全选」；默认全选；
   提交任务时写入 `params.selection = {mode:"selected", ids:[...]}`（未改动则 `{"mode":"all","ids":[]}`）。
2. **运行中进度小窗**：存在运行中任务时，右下角浮动小窗（可关闭/最小化）：当前动作、已用时、
   预计剩余（`eta_seconds`，用 `hh:mm:ss`，缺失显示「计算中」）、当前项 `current/total`
   （视频/下载显示百分比或秒）。数据来自 `task_view.live` + 现有轮询；不新增轮询频率超过 2 秒。
3. **任务列表**：运行中行显示一行摘要「正在… · 预计剩余 …」，来源同上。
4. **考试任务详情**：与作业共用「AI 做题」页签；`stage=exam` 的事件文案为「AI 正在作答考试」等。
5. 保留 v2.1 的视觉风格，新增组件沿用现有 design token；更新 `tools/vue_check.py` 断言（导航/新弹窗/小窗）。

## 4. 答题链路（Lead 实施 `cli_copy/**` + `worker/**`）

1. `cli_copy/models/course.py::get_exam_list()`：`GET https://mooc1.chaoxing.com/exam/test?courseId&classId&ut=s&cpi&openc&enc`
   （`enc/openc` 来自 `_get_work_enc_params()`），解析 `a[onclick^=goTest]` 的 7 个参数
   `(courseId, examId, examRelationId, endTime, paperId, isRetest, examEnc)`、标题、状态、考试时间、
   `TestRelationInfo[examId].limitTime`；返回与 work 对齐的 item（`id`=examId，`valid`=状态含「待做」或时间窗内且未完成）。
2. `cli_copy/core/exam_form.py`：考试答题页解析（与 work_form 同构 + 考试特有：逐题模式检测、提交表单/接口探测）。
3. `cli_copy/functions/deal_exam_room.py`：进考试（`reVersionTestStartNew`）→ AI 作答（每题 emit `answer_result`）
   → 提交（页面表单回放优先）。检测到逐题/单题限时 → 安全中止并给出明确原因，不提交半份答案。
4. `worker/runner.py`：`feature=="exam"` → `DealExamRoom`；`independent_homework` 传 `selection.ids` 过滤；
   未知/缺失 id 计入失败并给出原因。
5. `cli_copy/utils/llm_client.py`：提示词 v2（课程/任务上下文、必须给最可能答案、题型规则、JSON 输出），
   `answer_single(question, context=None, strict=False)`；调用方传入 `{"course":course_name,"media":title,"kind":"作业"|"考试"}`。
6. `worker/catalog_runner.py`：登录后只读拉取 `kind=work|exam` 列表并 emit `catalog_result`（见 2.2）。

## 5. 写作用域（避免冲突，禁止越界）

| 成员 | 写作用域 |
| --- | --- |
| lead | `cli_copy/**`、`worker/**`、`tests/test_exam_*`、`tests/test_llm_*`、`tools/check_*`、`docs/**` |
| backend-api | `app/**`、`tests/test_api.py`、`tests/test_modernization.py`、`tests/test_storage_and_model.py`、`tests/test_ai_only_backend.py` 新文件 `tests/test_catalog_and_live.py` |
| frontend-ui | `frontend/**`、`tools/vue_check.py`、`tools/ui_seed.py` |
| gh-research | `docs/research-exam.md`（只新增该文件） |

## 6. 验收标准

- `python -m pytest tests cli_copy/tests -q` 全绿；`python -m pytest frontend?` 不适用。
- `npm --prefix frontend test`、`npm --prefix frontend run build` 成功。
- `python tools/vue_check.py` 全绿（含新增考试/选择/小窗断言）。
- `python tools/smoke_test.py --mock` 全绿。
- 真实账号只读核对：`python tools/check_work_page.py` 解析正常；考试列表能列出（不启动考试）。
- 文档：README、architecture、release-2.2.md 更新。

## 7. 安全边界

- 任何真实提交/启动考试都必须由用户在自己的任务里触发；自动化测试与探针脚本只允许 GET。
- 日志与文档不得出现密码、api_key、cookie、学号姓名等；`tools/check_*` 不打印密钥。
