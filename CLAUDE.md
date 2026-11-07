# CLAUDE.md

This file provides guidance to [CC] () when working with code in this repository.

## 项目概览

课舟 CourseArk：超星学习通多账号本机学习工作台。Vue 3 + TypeScript 前端、FastAPI 本机服务、独立 Worker 子进程，以及复用 AutoChaoxingCLI 业务代码的 `cli_copy/`。网页版与 Electron 桌面版共用同一套前端与后端。

## 常用命令

```bash
# 网页版（自动建虚拟环境、装依赖、必要时重建前端）
./start.bat                 # 或 .\start.bat --port 8850 / --check
python -m pip install -r requirements.txt && python run.py

# 前端
npm --prefix frontend ci
npm --prefix frontend run dev        # Vite 127.0.0.1，/api 代理到 8848
npm --prefix frontend run build      # 先 vue-tsc --noEmit，再 vite build → webui_static/vue
npm --prefix frontend test           # vitest run
cd frontend && npx vitest run src/answers.test.ts   # 单文件

# Python 测试（两套，均使用临时数据目录，不连接学习通）
python -m pip install -r requirements-dev.txt   # 开发依赖（含运行依赖 + pytest/httpx/playwright）
python -m pytest tests -q            # WebUI 后端
python -m pytest cli_copy/tests -q   # CLI 副本
python -m pytest tests/test_api.py::test_xxx -q      # 单条

# 端到端 / 界面验收
python tools/smoke_test.py --mock    # 真启服务与 Worker，--mock 不访问超星
python tools/vue_check.py            # Playwright 断言 + 截图到 docs/vue-validation/
python tools/ui_check.py --serve --port 8899   # 保留隔离预览服务

# 桌面版
npm --prefix desktop ci
npm --prefix desktop test            # node --test test/*.test.cjs
npm --prefix desktop run dev         # 先构建前端再启动 Electron
npm --prefix desktop run dist:win
npm --prefix desktop run smoke:runtime / smoke:packaged
```

没有 lint 脚本；类型检查由 `frontend run build` 里的 `vue-tsc --noEmit` 承担。`smoke:packaged` 需先 `dist:win`，且运行前清掉 `ELECTRON_RUN_AS_NODE`（否则打包应用被当成纯 Node 进程立刻退出）。构建环境要求 Windows x64、Node.js ≥22.12、CPython 3.13 x64。

## 架构

```text
Vue 3 / TS ──HTTP + SSE── FastAPI (app/)
                             ├─ SQLite（data/webui.db）
                             └─ 子进程 worker/*.py ── cli_copy/（业务实现）
Electron (desktop/) ── 启动随包 Python ── 加载同一套 Vue 页面
```

**进程与职责边界**：`app/main.py` 只做参数校验、持久化、调度与事件推送，**不持有超星 Session，不在请求线程里跑长任务**。真正的登录、抓课、答题都在子进程：

- `worker/runner.py`：单个子任务一个进程。读 `data/tasks/<id>.json` 快照，登录后按 `feature` 分发到 `cli_copy/functions/*`。
- `worker/session_runner.py`、`sync_runner.py`、`catalog_runner.py`：会话缓存、课程同步、作业/考试目录拉取。
- `worker/common.py`：四类 runner 的公共基座——`build_base_config(job, profile)`（`task|session|sync|catalog` 预设，含 `rotate_ua` 等差异）、`terminate_gracefully()` 的 Windows 阶梯终止、`EventSink` 写失败上限。
- `app/subprocess_runner.py`：Web 侧四处子进程样板的单一出口（`worker_env`/`spawn`/`iter_lines`/`parse_record`/`write_json_atomic`/`wait_exit`/`stop_process`）；行为差异保留在调用方（sync 非 JSON 行记 log、session 超时强杀）。

**路由拆分（v2.4.x 重构）**：50 个路由按域放在 `app/routes/`（system/overview/accounts/workspace/tasks/settings/bank），每个模块 `from .. import main` 后在**调用时**动态取 `main.db/hub/manager/sessions`——conftest 会逐测试整体替换这些单例，路由模块里**严禁** `from ..main import db` 式的顶层绑定。视图序列化辅助（`_task_view`/`_event_view`/`_completed_view`/`_live_view`/`_sse` 等）留在 `app/main.py`：tests 直接引用这些名字，路由与测试都动态经 `main.` 取用。`_register_routes` 把各 router 的 APIRoute 直接并入 `app.router.routes`（本机 FastAPI 的 `include_router` 包惰性 `_IncludedRouter` 无 `.path`，tests/test_reliability.py 按 path 找 SSE endpoint）。

**事件链路**：Worker 通过 `cli_copy/core/runtime.py` 的 `runtime.emit()` 把事件以 JSON Lines 写到 stdout；`TaskManager._monitor` 逐行解析 → 校验任务 ID → `app/database.py` 落 `task_events`/`tasks` → `app/events.py` 的 EventHub → SSE `/api/events/stream` → 前端 `store.ts` 刷新。事件在 `app/narrative.py` / `app/presentation.py` 被翻译成人话并分类；`HIDDEN_EVENTS` 不进活动流。

**任务状态机**：`app/task_model.py` 的 `TRANSITIONS` 是唯一状态迁移表，`TaskManager._apply_event` 用 `_EVENT_HANDLERS` 查表分发。默认观察模式只告警；`TASK_STATE_GUARD_STRICT=1` 才拒绝非法迁移。`paused/pausing` 不占并发槽（`_SLOT_EXEMPT_STATUSES`）。中断/停止/失败的任务 `resume` 会用原 `params_json` 新建任务（`retry_task`），已完成部分由平台状态跳过。

**控制通道**：`app/control.py` 写 `data/control/<task_id>.json`（`run|pause|stop` + 单调递增 `version`）；Worker 在 `runtime.checkpoint()` / `sleep()` 等安全边界轮询。停止先协作退出，超过 `scheduler.stop_grace_seconds` 才强杀。

**配置单源**：设置只存在 SQLite（`app/settings.py`，键 `global`），API 下发；`cli_copy/core/config.py` 的 `Config` 已退化为纯内存 schema，不再读写 YAML。`TaskParams` 提交时冻结为快照（`for_feature` 只保留该功能相关字段），之后改全局设置不影响历史任务。

**持久化**：`app/database.py` 单连接 + 线程锁 + WAL，表为 `courses` / `course_catalog` / `runs` / `tasks` / `task_events` / `presets` / `settings_meta`。事件写入有批量缓冲（8 条或 2 秒），payload 超长截断，SSE 游标预分配以支持 `Last-Event-ID` 增量重连。

**前端**：`frontend/src/router.ts` 是 vue-router hash 路由（`#/overview`、`#/progress`、`#/tasks`、`#/accounts`、`#/completed`、`#/bank`、`#/settings`、`#/mini`）。`App.vue` 是侧栏 + 顶栏外壳（`#/mini` 例外）。`store.ts` 的 `state` 是唯一共享状态；`overview.ts` / `course.ts` / `mission.ts` / `answers.ts` / `catalog.ts` / `live.ts` 是纯计算模块（都有对应 `*.test.ts`）。样式在 `frontend/src/styles/` 的 tokens / base / shell / windows 四层，`style.css` 只做 `@import`。

**浮层与弹窗层叠**：右上角两个浮窗由 `App.vue` 的 `.float-stack` 容器承载（不要给单个浮窗写 `position: fixed` 坐标，否则会重叠）；进度小窗的开合/最小化必须走 `windows/manager.ts`，不要用组件局部 ref；`ModalShell` 有模块级弹窗栈，只有最顶层响应 Escape 与 Tab 陷阱，新增叠层弹窗不需要额外处理。层级用 `--z-sticky/--z-overlay/--z-float/--z-toast`。

**桌面壳**：`desktop/src/main.cjs` 用注册表管理子窗（`windows:open(route, preset)` / `windows:close`），preload 暴露 `coursearkDesktop.openWindow/closeWindow`，浏览器端由 `frontend/src/desktop.ts` 静默降级。桌面数据目录是 `%APPDATA%\AutoCxWebUI`（为兼容旧安装而保留该名字）。**T16 应用内验证窗**：IPC `verify:open(payload)` 开 `persist:cx-<accountId>` 分区窗口注入 Cookie（`GET /accounts/{id}/session/cookies`），用户手动完成平台人机验证后 `webRequest` 被动捕获带 `enc=` 的答题页 URL，经 `verify:captured` 发主窗——主窗渲染端回写 `POST /accounts/{id}/session/cookies` 并预填 NewTask 的考试地址（`state.capturedExamUrl` 一次性消费）。验证窗**不挂 preload、不注脚本、不碰考试页 DOM**（风控红线）；捕获正则与 Cookie 白名单见 `desktop/src/main.cjs` 的 `ANSWER_URL_RE` 与 `app/routes/accounts.py` 的 `_COOKIE_FIELDS`。

## 改代码时的关键约定

- **前端构建产物入库**：`webui_static/vue/` 已纳入 Git。改完 `frontend/src` 必须 `npm --prefix frontend run build` 并提交生成的文件，否则 `start.bat`/桌面版仍跑旧页面。`start.bat` 也会在检测到源码更新时自动重建。
- **验收锚点类名不可重命名**：`tools/vue_check.py` 断言依赖 `.execution-account`、`.execution-course`、`.media-live li`、`.execution-dashboard`、`.progress-window`、`.account-menu-item`、`.workspace-account`、`.workspace-course`、`.progress-account`、`.progress-course`、`.completed-row`。改布局先跑 `python tools/vue_check.py`。
- **CSS 陷阱**：`button, .button` 带 `line-height:1`（28px 定高按钮），按钮内多行文本会继承导致汉字重叠，已有兜底 `button b/strong/small { line-height:1.45 }`；新增按钮内多行文本要显式写行高。弹窗高度链要求 `.modal-body` 保持 `flex:1 1 auto; min-height:0`，否则 sticky 底栏被裁。
- **测试隔离**：`tests/conftest.py` 的 `sandbox` fixture 会重定向 `app.paths` 全部路径并重建 `main.db/hub/manager/sessions` 等惰性单例；新增全局资源必须同样可重置，否则测试间会串库。`cli_copy/tests/conftest.py` 重置 `Config._data`。测试与子进程都不得在 `cli_copy/` 里生成 `config.yml`/日志（`AUTOCXWEBUI_DATA_DIR` 已重定向）。
- **破坏性操作要确认**：停止任务/停止账号/清空缓存/清除登录缓存统一用 `components/ConfirmDialog.vue`（`title/message/hint/confirmText/busy` + `confirm`/`cancel`）；暂停、继续可逆，保持直接执行。
- **`/api/completed` 支持 `status`**：终态过滤在 SQL 侧完成，返回完整视图（`answers_summary`/`outcome`/`duration_seconds`/`exam`），分页语义成立。不要退回「先取 200 条再本地筛」的写法。
- **平台风控边界**：验证码、`captchaCheck`/`examCheck`、考试码一律不绕过，命中即记录原因并中止，不启动考试计时、不提交答案。核对作业/考试页面解析用只读脚本 `python tools/check_work_page.py ...`（不提交、不调 AI）。
- **协议细节易错**：作业提交的 `token`/`totalQuestionNum` 在查询串里，`totalQuestionNum` 是 32 位十六进制令牌而非题数；考试列表的 `examEnc` 与课程 `enc`、作业 `enc_work` 不可互换；`tId` 是考试 ID 不是 `paperId`。详见 `docs/architecture.md` 的答题/考试链路。
- **文档同步**：本仓库习惯是功能变更同时更新 `docs/CHANGELOG.md`（v2.1 起完整历史，含根因与验证数字）、`docs/architecture.md`、必要时 `README.md`。提交信息用中文 Conventional Commits（`feat(ui):`、`fix(api):` 等），正文列出根因、改动与验收结果。
- **运行数据不入库**：`data/`、`*.db`、日志、`desktop/build/`、`desktop/dist/`、`desktop/.cache/`、`docs/vue-validation/`、`.tmp-*/` 均被忽略。
- **测试 patch 面**：tests/test_desktop_paths.py、test_reliability.py 等会 `monkeypatch.setattr(sync_service.subprocess, "Popen", …)` / `session_service.subprocess` / `catalog_service.subprocess`——这三个服务模块必须保留 `import subprocess`（子进程统一走 `app/subprocess_runner.spawn`，但模块级 `subprocess` 名字是测试的替换锚点）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| `docs/architecture.md` | 组件划分、答题/考试/同步链路、事件、前端布局与进程治理 |
| `docs/CHANGELOG.md` | v2.1 起完整变更历史与跨版本约定（数据目录、风控边界、验证环境） |
| `docs/research-exam.md` | 考试协议调研（逐题提交、滚动令牌、风控） |
| `docs/research-github.md` | 同类项目调研与作业协议结论 |
