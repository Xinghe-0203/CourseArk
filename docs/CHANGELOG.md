# 课舟 CourseArk 变更日志

> 本文档是 **v2.1 起的完整变更历史**，按版本倒序排列（最新在最前）。
> 历史版本各自独立的 `release-*.md` 已全部合并至此并删除，内容未丢弃。
> 架构与实现说明见 [`docs/architecture.md`](architecture.md)；
> 协议调研见 [`docs/research-exam.md`](research-exam.md)、[`docs/research-github.md`](research-github.md)。
>
> 跨版本的通用约定（数据目录、安装方式、平台风控边界、验证环境）集中写在文末
> 「[跨版本通用说明](#跨版本通用说明)」，各版本中不再重复。

---

## 留白与行高修正（未发布）

> 承接「课程进度页与学习任务二级菜单（未发布）」。上一轮把信息压得太紧，实机截图（1919×913、
> 5 个真实账号 / 150 门课程）里左列账号菜单的「刘畅」与下一行「23 门 · 1071 / 1206 任务点」
> 字面直接压在一起，课程行的「待完成 19」也与「5 / 24」相撞。本轮只改 CSS：组件结构、类名、
> `aria-label`、`data` 与全部逻辑零改动，`tools/vue_check.py` 57 项断言一条未改。

### 一、重叠的总根因

- `frontend/src/styles/base.css` 的 `button, .button` 规则带 `line-height: 1`（为让 28px 定高按钮里的
  单行文字垂直居中）。这个行高会被按钮内部的多行文本继承：`.account-pick`（`height:auto`）里的
  `.pick-copy b`（13px 标题）+ `.pick-copy small`（11px 说明）都是 `display:block`，却共用 1em 行盒，
  而汉字字面高度约 1.15em ⇒ 两行的字身互相侵入。`.course-name b/small`、`.course-mission b/small`、
  `.account-name h2/small` 同理。
- 修法两层：
  1. 全局兜底 —— `button b, button strong, button small { line-height: 1.45; }`（插在
     `button:hover:not(:disabled), .button:hover` 之前，附注释说明原因）；
  2. 每处多行文本块显式行高 —— 标题 `line-height: 1.45`、说明 `line-height: 1.5`，
     上下再补 `margin-top: 2px` 与 `gap: 3~4px`。

### 二、留白与字号（按页面）

- **学习任务页**（`frontend/src/components/AccountWorkspace.vue`，35 处）：`.account-workspace` gap 10→14、
  `.workspace-toolbar` gap 6→8、`.workspace-scope` `gap:6px 12px`→`8px 14px` / padding `5px 10px`→`8px 12px`；
  账号竖列 `.account-menu-head` padding `6px 10px`→`9px 12px`、`.account-menu-item` gap 7→9 /
  padding `0 8px 0 10px`→`0 10px 0 12px`、`.account-pick` gap 7→9 / padding `7px 0`→`10px 0`
  （单行高度约 40→52px）；账号头 padding `8px 12px`→`12px 14px`、`.account-name h2` 13→13.5px、
  `.account-name small` 10.5→11px；五格数字 `.account-numbers > div` `gap:1px`→`3px` /
  padding `6px 10px`→`9px 12px`、`strong` 15→16px、`span` 10→10.5px；
  实时卡与最近结果 padding `8px 12px`→`12px 14px`；`.account-course-heading` padding
  `8px 12px 6px`→`13px 14px 9px`；课程表 `.course-row-head` 高 24→30px、`.workspace-course`
  上下 padding 6→11px、列 gap 12→16。
- **课程进度页**（`frontend/src/views/ProgressView.vue`，28 处）：`.progress-view` gap 12→16、
  `.progress-summary` `gap:8px 24px`→`14px 28px` / padding `12px 16px`→`16px 20px`、大号数字 24→26px、
  三格事实条 `gap:1px`→`4px` / padding `6px 9px`→`10px 12px`；`.progress-account-head` padding
  `8px 12px`→`12px 14px`；`.progress-course-head` 高 26→32px、`.progress-course` padding 7→12px。
- **其余五个行式表格页**（`TaskList.vue` 13 处 / `CompletedView.vue` 13 处 / `BankView.vue` 7 处 /
  `AccountsView.vue` 10 处 / `OverviewDashboard.vue` 13 处）：表头统一 28→34px；行内 padding
  由 7~11px 提到 11~15px；`.queue-row` min-height 40→46px、`.recent-row` 36→42px；
  `.execution-scroll` max-height 300→320px、padding 11→14px；`.bank-stats > div` 与 `.bank-item`
  padding `8px 11px`→`13px 14px`；`.account-row` padding `11px 12px`→`15px 14px`；
  `.completed-body` margin-top 2→7px。
- **设置页与新建任务弹窗**（`SettingsView.vue` 15 处 / `NewTask.vue` 35 处）：`.settings-layout`
  侧栏 168→180px、gap 12→16；`.settings-nav` button 高 28→32px；`.panel-head` padding
  `11px 14px`→`14px 16px`、`.panel-body` `12px 14px 14px`→`16px 16px 18px`、`.panel-foot`
  `9px 14px`→`12px 16px`。向导弹窗 `.wizard` gap 10→16、步骤条 padding `6px 10px`→`10px 12px`、
  序号圆 17→20px、`.wizard-accounts` 卡最小宽 210→220px、`.wizard-account` padding `7px 9px`→`11px 12px`、
  `.course-option` 与 `.catalog-item` padding `5px 8px`→`9px 10px`、`.feature-grid` button 高 30→32px。
- **任务详情抽屉与三个浮窗**（`TaskDrawer.vue` 41 处 / `ProgressWindow.vue` 17 处 /
  `styles/windows.css` 19 处）：抽屉 `.drawer` gap 9→14、四格指标 padding `6px 9px`→`10px 12px`、
  逐题卡 padding `7px 9px`→`11px 12px`、`.answer-question` 行高 1.55→1.65、事件行 padding
  `5px 9px`→`9px 12px`。进度小窗 268→**300px** 宽、body padding 8→12、已用时/预计剩余两格改
  `display:grid; gap:2px`。逐题与告警浮窗 320→**340px** 宽、max-height 340→380px、最小化态
  208→**220px**、`.feed-row` padding `6px 9px`→`10px 12px`、`.alert-list > li` `7px 9px`→`11px 12px`。

### 三、顺带修掉的两处排版缺陷

- **完成度末列贴边**：`.course-progress` 里 `progress-track` 用 `minmax(0,1fr)` 撑满，导致
  「21%」与「查看」被挤到右缘。改成 `grid-template-columns: minmax(0,1fr) 40px auto` + gap 12px、
  百分比 `text-align: right`；列宽 168→188px（进度页 128→152px）。
- **390px 下五格数字折成 3+2 留一格空白**：1080px 断点里 `.account-numbers > div:last-child
  { grid-column: span 2 }`，让末格跨两列铺满。
- **窄屏账号头挤成一团**：1080px 以下 `.workspace-account-head` 仍是
  `26px minmax(0,1fr) auto auto` 四列，头像、账号名、状态徽标与「创建任务 / 暂停 / 停止 /
  学习通」六个按钮被压到同一行。断点里改为两列 `26px minmax(0,1fr)`：状态徽标落到第二列
  `justify-self: start`，`.head-actions` 用 `grid-column: 1 / -1` 独占一行并左对齐。

### 四、弹窗底部按钮被裁（真实缺陷）

- 现象：新建学习任务弹窗（`ModalShell` + `.modal.wide`）底部「取消 / 上一步 / 创建 N 项任务」
  被弹窗下边缘切掉下半，按钮行下方还露出滚动内容的残影。
- 根因：`.modal` 是 `display:flex; flex-direction:column; max-height:min(88vh,900px); overflow:hidden`，
  但中间层 `.modal-body` 只有 `padding` + `overflow:auto`，没有 `flex:1 1 auto` 与 `min-height:0`，
  拿不到剩余高度；而 `.wizard-foot` 用 `position:sticky; bottom:0` 贴滚动视口底，正好落在
  `.modal-body` 的 16px padding-bottom 里被裁。
- 修法两步：`.modal-body` 补 `flex:1 1 auto; min-height:0`；`.wizard-foot` 改
  `margin-bottom:-16px; padding-bottom:16px; position:sticky; bottom:-16px`，让底栏自身铺满那段
  padding。未改 `ModalShell` 结构（它仍只有默认 slot），账号页、答题缓存页、任务抽屉五处调用不受影响。

### 五、验证

- `npx vue-tsc --noEmit` 无输出；`npm run build` 通过：`index.html` 0.49 kB、
  `index-*.css` 77.54 kB（gzip 12.30）、`index-*.js` 245.31 kB（gzip 86.45）、`MiniView-*.js` 1.71 kB。
- `python tools/vue_check.py` **57 项全过 / errors []**（断言与选择器一条未改）；`npm test` 7 files / 47 tests。
- 截图全部重跑（`docs/vue-validation/` 38 张）：左列账号菜单两行分离、课程行「5 / 24」与
  「待完成 19」分行、完成度列三元素不贴边、弹窗底部按钮完整且无残影。

### 改动文件（留白与行高修正，摘要）

| 领域 | 文件 |
|---|---|
| 根因兜底 | `frontend/src/styles/base.css`（按钮内多行文本行高 + `.modal-body` 弹性高度） |
| 学习任务页 | `frontend/src/components/AccountWorkspace.vue` |
| 课程进度页 | `frontend/src/views/ProgressView.vue` |
| 其余表格页 | `frontend/src/components/TaskList.vue`、`CompletedView.vue`、`BankView.vue`、`AccountsView.vue`、`OverviewDashboard.vue` |
| 设置与向导 | `frontend/src/components/SettingsView.vue`、`NewTask.vue` |
| 抽屉与浮窗 | `frontend/src/components/TaskDrawer.vue`、`frontend/src/components/ProgressWindow.vue`、`frontend/src/styles/windows.css` |

---

## 课程进度页与学习任务二级菜单（未发布）

> 承接上一轮「界面重做（未发布）」。本轮仍只动前端表现层与导航：后端接口、数据库 Schema、
> `store.ts` / `api.ts` / `types.ts` / `format.ts` / `mission.ts` / `live.ts` 的既有导出全部沿用，
> 旧数据无需迁移。改动动机来自实机截图：学习任务页把「5 格数字 + 实时任务 + 最近结果 + 课程网格」
> 塞进同一张 420px 宽的卡片，同一行里「已完成」既是任务状态又是任务点进度的开头，读起来是一团。

### 一、新增「课程进度」主页面

- **为什么单独成页**：用户关心的是「哪门课还有多少任务点没学」，这件事跨账号、跨课程、按任务点
  计数，和「这一轮任务跑得怎么样」是两个问题。混在任务卡里时只能看到当前展开的账号，
  需要滚动六个卡片逐个数。新页把「账号 × 课程 × 平台任务点」一次性摊平。
- 路由 `#/progress`（`frontend/src/views/ProgressView.vue` **新增**），导航放在「工作台」组
  「工作总览」与「学习任务」之间，图标 `ChartColumn`。
- **页头摘要**（`.progress-summary`）：左侧 `平台任务点进度` + 大号 `已完成 / 总数`
  （`94 / 432`）+ 一句 `N 个账号 · N 门课程 · N 个任务点待完成 · N 门正在执行`；
  中间整体完成度进度条 + 百分比；右侧三格事实条（正在执行 / 有未完成 / 剩余任务点）。
- **筛选**：关键词匹配账号标签、手机号、课程名；范围下拉「全部课程 / 执行中 / 有未完成 / 已完成」，
  右侧显示命中课程数。
- **按账号分组**：每个账号一段（`.progress-account`），段头是头像 + 账号名 + `手机号 · N 门课程`
  + 状态徽标（正在执行 / 已暂停 / 就绪 / 已停用 / 正在同步）+ 该账号的 `已完成 / 总数 百分比`；
  段内是四列表格「课程 / 平台任务点 / 本轮任务 / 完成度」，每门课一行。
- **课程行四列语义**（这是本轮修掉的核心问题）：
  - 第一列课程名 + `作者 · 缓存 MM/DD HH:mm`；
  - 第二列只放数字 `已完成 / 总数` 与一行 `待完成 N`，不再输出「已完成 5 / 24，待完成 19」整句——
    因为第三列状态徽标本身就写着「已完成」「进行中」，两句「已完成」并排必然误读；
  - 第三列本轮任务：状态徽标 + 功能名（课程任务点 / 独立作业 / 独立考试）+ `X / Y 项` + 「详情」，
    点击复用既有任务详情抽屉；没有任务时按课程开放状态说「还没有执行过」或「课程已关闭」；
  - 第四列任务点进度条 + 百分比。
- 新增 `frontend/src/course.ts`（**新增**，被进度页与学习任务页共用）：
  `courseKey(accountId, course)`（`[accountId, course_id, class_id, cpi].join(":")`，与 `store.ts`
  里 `selectedCourses` 的 key 口径一致）、`taskForCourse(workspace, course)`（先找执行中的任务，
  再找任意历史任务，最后回落到 `recent`，同 `course_id` + `class_id`）、
  `courseRows(workspaces)` 把工作区展平成 `CourseRow[]`。此前 `AccountWorkspace.vue` 里有一份
  同样的三级回退实现，两处口径容易分叉，现在只有一份。

### 二、学习任务页改为竖向二级菜单

- **左侧账号竖列**（`nav.account-menu`，`aria-label="账号列表"`）：每行是「勾选框 + 头像 + 账号名
  + `N 门 · fn / all 任务点` + 执行状态小圆点」，选中行 `.chosen` 加墨蓝底与左侧 2px 竖条；
  列宽 238px 并 `position: sticky` 跟随滚动。标题即各账号，用户不必再从卡片标题里找账号。
- **右侧只渲染选中账号的详情**：账号头（头像 / 账号名 / 手机号与登录状态 / 状态徽标 /
  创建任务·暂停·继续·停止·学习通·同步）+ 五格数字 + 实时任务卡 + 最近结果 + 课程表。
  一次只展开一个账号，纵向信息密度反而更高。
- **课程表从卡片网格改成行式表格**：`.course-row-head` 四列「课程 / 平台任务点 / 本轮任务 / 完成度」
  + `article.workspace-course` 四列 `minmax(0,1.5fr) 132px minmax(0,1.15fr) 168px`。
  同一门课以前是一小块卡片，里面并列「课程名 / 作者 / 状态 / 功能 / 本轮 X / Y 项 / 查看」六段，
  现在是四个对齐的列位。
- **「已完成」撞词修法**：新增 `missionNumbers(course)` 只返回 `{all, fn, pending, percent}`，
  模板里第二列显示 `fn / all` 与 `待完成 N`，状态文字只出现在第三列的状态徽标里。
- **删掉「紧凑展开 / 卡片展开」**：二级菜单已经固定为「竖列 + 单账号详情」，
  原来的 268px 紧凑布局没有对应形态，`compact` ref、`toggleLayout()` 与 localStorage 键
  `account-layout` 一并删除（旧键残留不会报错，只是不再读取）。
- 1080px 以下：`.account-workspaces` 转单列、`.account-menu` 变横向可滚动条、
  课程表隐藏表头并折成两行（课程名 + 完成度在上，任务点与任务在下）。

### 三、验证

- `npm run build` 通过：`index.html` 0.49 kB、`index-*.css` 76 kB（gzip 12 kB）、
  `index-*.js` 245 kB（gzip 86 kB）。`npm test` 7 files / 47 tests 通过（逻辑模块未改）。
- `tools/vue_check.py` 从 54 项扩到 **57 项全部通过**：
  - 三视口页面清单加「课程进度」（1920 / 1440 / 390 各一张截图 + 无横向溢出断言）；
  - 学习任务段落改写为二级菜单断言：`.account-menu-item` 6 个、`.workspace-account` 只 1 个、
    `.workspace-course` 随选中账号变 2 → 4 条、选中行 `.chosen .pick-copy b` 文本为「账号 03」、
    搜索「账号 02」后菜单只剩 1 项、切页往返后勾选数与选中行都保留；
  - 删掉旧的「紧凑展开」与 `.account-workspaces.compact` 断言，改断言 `.account-menu-item.chosen`
    只有 1 个，截图改名 `desktop-account-menu.png`。
- 截图产物：`docs/vue-validation/{wide,desktop,mobile}-课程进度.png`、`desktop-account-menu.png`。

### 改动文件（课程进度页与二级菜单，摘要）

| 领域 | 文件 |
|---|---|
| 新增页面 | `frontend/src/views/ProgressView.vue` **新增** |
| 共用口径 | `frontend/src/course.ts` **新增** |
| 学习任务页 | `frontend/src/components/AccountWorkspace.vue`（二级菜单重写） |
| 导航与骨架 | `frontend/src/router.ts`、`frontend/src/App.vue`、`frontend/src/types.ts`（`View` 加 `progress`） |
| 验收 | `tools/vue_check.py`（页面清单 + 学习任务段落断言改写） |

---


## 界面重做（未发布）

> 本轮只改前端表现层：数据层（`store.ts` / `api.ts` / `types.ts` / `format.ts` / `overview.ts` /
> `mission.ts` / `live.ts` / `windows/*`）与后端接口、数据库 Schema 全部未动，旧数据无需迁移。
> 目标是让界面承担「多账号 + 多任务 + 长时间运行」的实际信息密度，而不是把每块内容都做成等大的卡片。

### 一、视觉体系重建

- **样式拆成四层**：`frontend/src/style.css` 从 4698 行（v2.3 之后又叠了 T9/T14 若干段）收缩为
  四行 `@import`，实际样式落在 `frontend/src/styles/`：
  - `tokens.css`：冷灰纸面 `--paper #edf0f3` + 仪器墨蓝 `--navy #123a5e` + 交通灯语义色
    （`--ok #1a7a52` / `--warn #96620f` / `--danger #b23a2f` / `--info #2a5f9e`）；
    字体三个角色（正文 Microsoft YaHei UI、数字 Bahnschrift、等宽 Consolas）；
    并把 v2.3 的旧变量名（`--fg/--fg-muted/--bg/--card/--accent/--border` 等）映射到新 token，
    模板里的内联 SVG 因此不需要改。
  - `base.css`：按钮（28px 高、4px 圆角）、表单（30px 高、focus 环）、`.status/.pill/.tag` 胶囊
    （12 种任务状态映射到绿/蓝/黄/红/灰）、进度条、`.tabs`、`.filterbar`、`.pagination`、
    `.section-heading`、`.avatar`、`.metrics`、`.panel`、`.overlay/.modal`、`.toast`、`details.advanced`。
  - `shell.css`：`.shell` 网格（侧栏 216px + 内容）、白底侧栏、52px 顶栏、`.page-content`；
    断点 1080px（侧栏折成横向条）与 760px（隐藏计数、单列表单、全屏弹窗）。
  - `windows.css`：进度 / 逐题 / 告警三个浮层小窗的固定定位、最小化条与列表行。
- **顶栏承载页面身份**：删除「工作空间 / 页名」面包屑与 40px 巨标题，标题与一句说明移入顶栏
  `.top-title`（h1 15px），右侧依次是新建学习任务、账号/课程/运行中三项计数、浮层开关、刷新。
  页面层级改由「区块标题 + 行」承担，不再靠字号制造层级。

### 二、六个页面

- **工作总览**：删掉四张等大指标卡、环形仪表、三条阶段比例条与三段重复叙述（它们都在说同一件事），
  改为「续跑提示条 → 单块执行摘要（本轮已确认 / 总数 + 进度条 + 三枚阶段 chip）→ 调度队列表格
  （课程与任务 / 状态 / 说明 / 进度 / 创建，整行可点开任务）→ 正在执行的账号两卡（平台任务点缓存、
  已确认进度、媒体行、暂停/停止）→ 最近完成四行」。
- **学习任务**：六张账号卡两列（420px 起），卡内分四段：账号头（勾选 / 头像 / 名称 / 状态 / 同步）、
  四格数字（课程 / 平台任务点 / 执行排队 / 需处理）、绿色实时卡（进度、答题与提交、媒体行）、
  课程网格（勾选态整块变墨蓝淡底）与底部操作行（创建任务 / 暂停 / 继续 / 停止 / 学习通 / 缓存时间）。
  `.compact` 模式改为左 268px 头部（两行 grid）+ 右侧内容的左右分栏。
- **账号与课程**：从大卡片改为「账号 / 课程 / 登录 / 操作」四列行式表；同一事实只说一次
  （课程列只说同步结果，登录列只说登录缓存）；「登录状态与缓存」从大胶囊折叠改成一行细链接。
- **已完成**：五列表格（结果 / 课程与任务 / 逐题概要 / 耗时与时间 / 详情），逐题概要与考试信息
  作为展开行挂在第二列下方；窄屏时改为上下堆叠。
- **答题缓存**：三列统计（缓存题目 / 命中次数 / 命中率）+ 四列行（题型 / 题干 / 答案 / 删除）。
  `lookups = 0` 时命中率显示「—」而不是 0%——后端 `hit_rate = hits / lookups`，0 次查询必然算出 0%，
  显示 0% 会被误读成「缓存完全没用」。
- **偏好设置**：168px 侧栏 6 个分组 + 面板（参数两列网格、布尔项走开关行）+ 底部保存栏 +
  「配置备份与迁移」折叠。
- **新建任务向导 / 任务详情抽屉 / 三个浮层小窗 / 迷你监控**：步骤条、课程与考试列表、逐题卡、
  事件列表全部重排；逐题卡默认收起选项（`展开题干与选项`），避免一屏只看得到 4 题。

### 三、修掉的真实缺陷

- **`RouterView` 上的 `@select` 会透传**：`App.vue` 原来写 `<RouterView @select="selected = $event" />`，
  监听器被透传到页面组件，`$event` 是原生 `Event` 而不是 `Task`，任务抽屉会以空任务挂载；
  `ModalShell` 给 `.workspace/.sidebar` 加 `inert` 后子模板读 `task.course_name` 抛错，
  渲染不出 DOM 又不卸载，整页点击被拦截。改为 `v-slot="{ Component }"` + `<component :is>` 显式绑定，
  并加 `pick(task)` 守卫只接受带 `id` 的任务。
- **`ModalShell` 的 inert / overflow 锁改为引用计数**（模块级 `locks`），多弹窗叠加或任一实例异常卸载
  都不会把整页锁死；改用 `?.setAttribute` 避免 `.workspace` 缺失时抛错。
- **迷你窗**：`#/mini` 路由不再套侧栏与顶栏（Electron 以 340×220 无框窗加载，套壳会挤成残片）；
  已用时改用 `live.ts` 的 `elapsedSeconds`（会优先用 `task.live.elapsed_seconds`），
  修掉此前显示的 `497823:05:24`。
- **总览队列进度**：`/api/overview` 的 `stats.work` 只回传 `units` 与 `sealed`，不带汇总数字，
  `overview.ts` 的 `summarizeWork` 改为按 `units` 的 status 现算 completed/total/failed/blocked，
  队列不再显示 `0/—`。
- 390px 宽下导航条从三行收到两行（只留品牌图标 + 更紧凑的导航项）；`select` 不再在工具条里撑满整行；
  账号页/缓存页的图标按钮补齐描边，不再像空按钮。

### 四、验证

- `frontend`：`npm run build` 通过（`vue-tsc --noEmit` + `vite build`，产物约 236 kB JS / 70 kB CSS）；
  `npm test` 7 files / 47 tests 通过（逻辑模块未改，测试未动）。
- `tools/vue_check.py`：断言随新结构同步（`.execution-account` 由「固定 520px」改为「两卡等高且
  240–560px」、`.workspace-account` 由「等高」改为「等宽」），共 54 项全部通过，
  产物截图与报告写到 `docs/vue-validation/`（1920 / 1440 / 390 三视口 × 六页 + 向导、抽屉、
  考试、续跑、浮窗、迷你窗）。

### 改动文件（界面重做，摘要）

| 领域 | 文件 |
|---|---|
| 样式 | `frontend/src/style.css`（改为 `@import` 入口）、`frontend/src/styles/{tokens,base,shell,windows}.css` **新增** |
| 骨架 | `frontend/src/App.vue`（顶栏 / 迷你窗路由 / `pick` 守卫） |
| 页面 | `frontend/src/components/{OverviewDashboard,AccountWorkspace,AccountsView,TaskList,CompletedView,BankView,SettingsView}.vue` |
| 浮层与弹窗 | `frontend/src/components/{NewTask,TaskDrawer,ModalShell,ProgressWindow,AnswerFeedWindow,AlertWindow}.vue`、`frontend/src/views/MiniView.vue` |
| 逻辑 | `frontend/src/overview.ts`（`summarizeWork` 按 units 现算） |
| 验收 | `tools/vue_check.py`（两处断言按新布局改写，其余文案断言保持） |
| 文档 | `docs/architecture.md`「界面分区与布局」章节重写 |

---


## v2.4.0
> 本版是**工程质量版**：CLI 移植遗留清理（配置单源 / 状态机 / N+1 / 存储与日志通道）、
> 页面按实际信息重排（总览真值 + 调度队列 + 服务端筛选）、日志系统完善（单通道结构化）、
> Electron 桌面壳双端可用（多实例小窗注册表）。无破坏性 API 变更；数据库 Schema 不变，
> 旧数据全部兼容，无需迁移。

### 一、CLI 移植遗留重构（worker 公共基座 + 配置单源 + 状态机）

- **worker 公共基座**（`worker/common.py` 新增）：`build_base_config()` 统一四类 runner
  （视频 / 会话同步 / 目录 / 课程）的配置组装，`session.rotate_ua=False` 必须保留的隐式约定
  显式化；`terminate_gracefully()` 阶梯终止（taskkill 无 /F → CTRL_BREAK → kill）替代各处
  手写的进程收尾；`EventSink` 失败上限 3 次 → `StopRequested`，防止日志通道坏死后无限重试。
- **配置单源**（`cli_copy/core/config.py` 重写）：纯内存 schema，删除 `load()` / `save()` /
  `_config_path()` 与 YAML 依赖——CLI 不再读写磁盘配置文件，一切以 API 传入为准；
  `set_defaults` → `_normalize_config` 统一钳制与枚举校验；删除 `account.phone/password` 与
  `advanced.log_level/log_file` 死键；`video.max_workers` 默认 8。
- **状态机观察模式**（`app/task_model.py`）：`TRANSITIONS` 扩表覆盖中间态直达终态的合法迁移；
  `_EVENT_HANDLERS` 查表化 16 类事件；`_guard_status` 对非法迁移仅告警（
  `TASK_STATE_GUARD_STRICT=1` 可切严格模式，为后续收紧预留）；`_SLOT_EXEMPT_STATUSES`
  修复暂停任务占槽导致的调度饿死。
- **N+1 查询消灭**（`app/database.py` / `app/main.py`）：新增 `work_plans_batch` /
  `events_after_batch`（ROW_NUMBER 窗口取每任务最新）/ `answers_batch` 批量方法；任务列表、
  待续跑单元、逐题明细四处端点改批量预取——120 任务压测下列表页 SQL 从 142 条降到 4 条。
- **存储加固**（`app/database.py`）：`add_event` 缓冲（8 条或 2 秒）+ `executemany` 批量落库；
  超长 payload 截断（>4000 字符）；任务状态 CAS 更新（`COALESCE` 防覆盖）；仪表盘统计补齐
  12 种任务状态口径；设置深合并丢弃坏节点、导出脱敏（`REDACTED_PLACEHOLDER`）、
  `api_key: null` 显式清除；SSE 游标改为预分配 `_next_event_id()`（表 MAX 与缓冲尾取大 +1），
  消除并发下的事件 id 回退。
- **事件保留策略**（`tests/test_events_prune.py` 14 用例锁定）：任务事件按量保留清理；
  SSE 断线增量重连（`Last-Event-ID` 游标）；`worker_exit` / `worker_crash` 可见化。

### 二、页面按实际信息重排（前端接真值）

- **总览接 `/api/overview`**（新端点）：账号/任务计数、今日完成、调度队列（最多 60 条，
  含队列原因推断）、题库命中统计、最近事件一次取全；总览指标卡从「估算值」改为真实聚合，
  新增「调度队列」区块展示排队中的任务及原因。
- **已完成页服务端筛选**：状态筛选从客户端过滤改为 `GET /api/history?status=…`（上限 200），
  大任务量下不再整页拉取；行内备注提供回退展示。
- **答题缓存页接真值**：`/question-bank/stats?days=30` 三卡（总量 / 命中 / 命中率）替换静态
  占位；增删后自动刷新。
- **账号页补真实状态**：同步时间 `last_sync_at` 防字符串直显、会话最近结果、账号卡第 5 格
  成功计数；任务列表显示批次号（`run_id` 前 8 位短码）。
- **任务详情增强**：日志检索分页（关键词 / 级别 / 游标加载更多）、逐题明细补显（旧版本任务
  给出未记录说明）、参数结构化表格、续跑链 chips（断点续跑的来源/去向一目了然）。
- **vue-router@4 迁移**：手写 hash 路由改 `createWebHashHistory`（URL 形态不变，锚点零改动）；
  `/mini` 独立懒加载 chunk。

### 三、日志系统完善（单通道结构化）

- CLI 18 个文件的 `loguru` 直接调用全部改经 `core.runtime` 单通道：
  `_ModuleLogger` → `emit("log", …, stage="log")` 结构化事件，前端「诊断日志」按
  级别 / 关键词检索、分页加载。
- 死代码清理：`parse_index_list` / `clear_console` / `CookieExpiredException` /
  `VideoException` / `PauseAwareSleep` / 三处未用 `run()`；`tiku` 死分支全删
  （answer mode 只剩 `ai` / `manual`）；`TaskStatsUI.record_exam_result` 收敛为 6 参。
- 事件呈现重写（`app/presentation.py`）：`LOG_CATEGORIES`（关键词→分类）+
  `EVENT_CATEGORIES` + `HIDDEN_EVENTS`（`log` / `task_progress` / `media_progress` /
  `worker_exit` 不再进活动流），`describe()` 纯叙事驱动。

### 四、Electron 桌面壳：双端可用 + 多实例小窗

- **通用多窗注册表**（`desktop/src/main.cjs`）：`windows:open(route, preset)` /
  `windows:close(route)` IPC——渲染进程可按前端 hash 片段开通任意小窗；内置
  `WINDOW_PRESETS`（迷你监控保留 v2.2.4 形态）+ 未知 route 的 `FALLBACK_PRESET`；
  渲染端仅可覆盖白名单 8 字段（title / 宽高 / min / frame / alwaysOnTop / skipTaskbar），
  尺寸钳制下限防 0 尺寸窗口；同 route 单实例复用，关闭=隐藏（可随时复现）。
- **preload 桥扩展**：`coursearkDesktop.openWindow(route, preset)` / `closeWindow(route)`；
  前端 `desktop.ts` 对应封装，浏览器端静默降级（返回 false，不报错）。
- **迷你监控小窗**：`/#/mini` 紧凑视图（当前任务 / 进度 / 已用时，2.5s 自刷新），
  学习任务页「浮出迷你监控」按钮直达；无边框置顶、不占任务栏。
- **语义修正**：`window-all-closed` 仅主窗销毁才退出（子窗隐藏不算退出信号）；
  `before-quit` 连带销毁注册表全部子窗并停后端；`second-instance` 聚焦主窗与全部可见子窗。
- 推迟至 v2.4.1：dev 模式接 Vite dev server 热更新、托盘图标与崩溃自动恢复。

### 改动文件（v2.4.0，摘要）

| 领域 | 文件 |
|---|---|
| worker | `worker/common.py` **新增**（build_base_config / terminate_gracefully / EventSink）；四 runner 接入 |
| CLI | `cli_copy/core/config.py` 重写（纯内存 schema）；18 文件日志改单通道；死代码删除 |
| 后端 | `app/database.py`（批量方法 / 事件缓冲 / CAS / SSE 游标）、`app/main.py`（`/api/overview` 新端点 / 批量预取）、`app/task_model.py`（状态机查表）、`app/presentation.py`（呈现重写） |
| 前端 | `frontend/src/overview.ts` **新增**；store / App / 总览 / 已完成 / 题库 / 账号 / 任务列表 / 任务详情接真值；`frontend/src/router.ts` **新增**（vue-router@4）；`frontend/src/windows/manager.ts` **新增**（多实例小窗窗口管理）；`views/MiniView.vue` **新增** |
| 桌面 | `desktop/src/main.cjs`（多窗注册表 / IPC / 生命周期语义）、`preload.cjs`（openWindow / closeWindow） |
| 测试 | `tests/test_state_machine.py`(15) / `test_nplus1.py` / `test_database_extra.py`(22) / `test_events_prune.py`(14)；`frontend` vitest 47（含 window.test.ts 7）；全量 pytest 539 |

### 兼容性与迁移（v2.4.0）

- **无破坏性变更**：API 端点只增不改（`/api/overview` 新增；既有端点响应字段只增不减）；
  数据库 Schema 版本不变（`SCHEMA_VERSION = 1`），旧数据无需迁移。
- CLI 不再读写磁盘配置文件（`cli_copy` 删除 YAML 配置加载）——此前直接编辑 CLI 配置文件的
  用法失效，一切配置从应用「偏好设置」下发；`account.phone/password`、
  `advanced.log_level/log_file` 死键被忽略。
- Electron 小窗 API（`windows:open`）仅桌面端可用；网页端调用 `desktop.ts` 封装会静默降级，
  无需特性检测。
- 数据目录与安装方式见文末通用说明（仍适用）。

---

## v2.3.0

> 本版做两件事：**删掉一整套「通知」子系统**（它一直在重复任务事件里的信息，却要求用户再去一个
> 独立页面处理一遍），以及**按单一职责重做界面分区与布局**——总览只讲状态，学习任务只管课程与任务，
> 账号页只管账号与登录。这是一个**破坏性变更**：`/api/notifications*` 三个端点、`notifications`
> 数据表与 `notification` 设置组被移除，旧配置里该组会被自动丢弃（不影响其余设置）。

### 一、移除：通知子系统（站内问题中心 + 外部推送）

- 现象：同一个失败原因会同时出现在三处——任务详情的事件、总览的「待处理通知」、顶栏铃铛的
  未读计数。用户点进「问题中心」看到的是一条条已经读过的事件副本，还要手动「标记已处理」。
- 判断：这是**信息重复而不是功能**。失败与告警已经作为任务事件落库（`sync_failed` /
  `task_failed` / `login_failed` / `interrupted` …），`presentation.describe` 已能归类并给出
  处置建议，前端在任务详情「诊断日志」与总览指标里直接消费即可。
- 删除范围（后端）：`app/notifications.py` 整个文件（`classify()` 关键词表与
  `NotificationCenter`）；`app/database.py` 的 `notifications` 表、两个索引与 7 个方法
  （`repair_notification_labels` / `upsert_notification` / `list_notifications` /
  `count_notifications` / `notification_counts_by_level` / `mark_notifications_read` /
  `clear_notifications`）；`app/main.py` 的三个 `/api/notifications*` 端点、`_notification_view`
  与总览返回体的 `problems` 字段；`app/task_manager.py` 与 `app/sync_service.py` 里的
  `NotificationCenter` 引用；`app/settings.py` 的整个 `notification` 组
  （`enabled` / `server_chan` / `bark` / `telegram`）——`SECRET_PATHS` 现在只剩 `llm.api_key`。
- 删除范围（CLI 与 Worker）：`cli_copy/utils/notification.py`（ServerChan / Bark / Telegram
  推送）、`cli_copy/core/config.py` 的 `notification` 组、`worker/runner.py`、
  `worker/sync_runner.py`、`worker/session_runner.py`、`worker/catalog_runner.py` 里注入给 CLI
  的 `"notification": {"enabled": False}`。
- 删除范围（前端）：`NoticeBar.vue`（顶栏铃铛与站内通知栏）、`ProblemsView.vue`（问题中心页）、
  `store.ts` 的 `problems` / `unreadProblems` 与第四个 `GET /notifications` 请求（刷新从 4 个请求
  降到 3 个）、`types.ts` 的 `Problem` 接口与 `View` 的 `"problems"`、`SettingsView.vue` 的
  「通知提醒」页签与全部 `notification.*` 字段。
- 替代方案：`app/presentation.py` 重写——保留 `CATEGORIES` / `ACTIONS`，新增
  `LOG_CATEGORIES`（关键词→分类，先按关键词细化再回退事件映射，避免「登录凭据无效」被归成
  `task` 而不是 `login`）、`EVENT_CATEGORIES`、`HIDDEN_EVENTS`（`log` / `task_progress` /
  `media_progress` / `worker_exit`）与 `_categorize()`，`describe()` 的 `visible` 由事件类型与
  级别推导。总览第 4 张指标卡从「站内待处理通知」改为「待处理内容」，取
  `progress.failed + progress.blocked`。
- 迁移：无需迁移数据。旧 `settings` 里的 `notification` 组在读取时被 `normalize()` 丢弃；
  已存在的 `notifications` 表不会再被读写（新库不再创建它），不影响其它表。

### 二、重做：界面分区与布局（单一职责）

导航从 7 项减到 6 项，并按职责分成三组（工作台：工作总览 / 学习任务；档案：账号与课程 /
已完成 / 答题缓存；系统：偏好设置）。侧栏底部原「状态点 + 一句话」改为**引擎心跳**：后台服务
运行状态、运行中/暂停任务数、端口号，把原先藏在浮层里的信息变成常驻的一行。

- **统一口径**：新增 `frontend/src/stats.ts` 的 `workspaceStats(workspaces, tasks)`，顶栏
  `.top-stats`（账号 / 课程 / 运行中）、总览指标卡、学习任务页三处取同一份聚合数字。此前
  「总览说 2 门课程、学习任务页列出 18 门」的口径冲突由此消除——`courses` 现在按
  `workspaces.reduce((n, w) => n + w.courses.length, 0)` 计算，与学习任务页列出的课程条数一致。
- **学习任务页去掉卡内滚动**：`.workspace-account` 不再写死 `height:620px` / `overflow:hidden`，
  `.workspace-courses` 不再 `max-height:370px; overflow:auto`；改为 `.account-workspaces`
  的 `grid-auto-rows:1fr` 让同一行卡片等高、内容自然撑开。参考的三个同类项目里没有一个把
  滚动条塞进卡片内部。
- **进度小窗默认最小化**：`ProgressWindow.vue` 的 `minimized` 初值改为 `true`，任务开始时只留
  一条标题栏贴在右下角（任务结束后下一轮重新显示、仍是最小化），配合 `.page-content` 底部
  预留 `132px`，不再长期压住第二列卡片。展开仍可看到当前动作、已用时与预计剩余。
- **账号页只管账号**：账号卡只保留身份（头像 / 备注 / 学号 / 启用状态）、已同步课程数与
  「查看课程」（弹窗）、同步与打开学习通、编辑与删除、`<details>登录状态与缓存`。课程列表与
  任务列表不再在账号页重复出现（那是学习任务页的职责）。
- **总览补「最近完成」**：在运行中任务之外补一段 `.overview-recent`，按终态任务取最近 6 条，
  显示课程、结果与进度，点击直接打开任务详情；空态给出「去创建任务」。
- **空态成对化**：`AccountsView.vue` 的两处裸文案空态（无账号、账号无课程）改为标题 + 说明 +
  动作按钮。
- 清理通知遗留的死规则：`.notification-dot`、`.nav-count`、`.problem-card` / `.problem-icon` /
  `.problem-list` / `.problem-tags` / `.problem-actions` 全部删除（`Select-String` 复核 0 命中）。
- 验收锚点全部保留：`.execution-account`（含总览卡的 520px 等高约束）、`.execution-course`、
  `.media-live li`、`.execution-dashboard`、`.progress-window`、`.workspace-account`（同行等高）、
  `.workspace-course`（种子下 18 条）、`.resume-banner` / `.resume-action` / `.resume-dismiss`、
  `.completed-row`、`.task-row` 等类名与语义均未改动。

### 改动文件（v2.3.0）

| 文件 | 改动 |
|---|---|
| `app/notifications.py` | **删除**（关键词分类表与 `NotificationCenter` 整体移除） |
| `app/database.py` | 删 `notifications` 表、两个索引与 7 个通知方法 |
| `app/main.py` | 删 3 个 `/api/notifications*` 端点与 `_notification_view`；总览返回体去掉 `problems`；启动自动同步失败改为写 `sync_failed` 事件 |
| `app/presentation.py` | 全文重写：`LOG_CATEGORIES` / `EVENT_CATEGORIES` / `HIDDEN_EVENTS` / `_categorize()`，`describe()` 改为纯叙事驱动 |
| `app/settings.py` | 删 `notification` 组与对应 `_SOURCE_MAPPING`；`SECRET_PATHS` 只剩 `llm.api_key` |
| `app/task_manager.py`、`app/sync_service.py` | 去掉 `NotificationCenter` 引用，失败只写事件 |
| `cli_copy/utils/notification.py` | **删除**（外部推送整体移除） |
| `cli_copy/core/config.py` | 删 `notification` 配置组 |
| `worker/runner.py`、`worker/sync_runner.py`、`worker/session_runner.py`、`worker/catalog_runner.py` | 删注入的 `"notification": {"enabled": False}` |
| `frontend/src/components/NoticeBar.vue`、`ProblemsView.vue` | **删除** |
| `frontend/src/App.vue` | 导航 7→6 项并按三组分区；侧栏引擎心跳；顶栏 `.top-stats` 统一口径；删 `.eyebrow`；6 条页副标题按单一职责重写 |
| `frontend/src/stats.ts` | **新增** `workspaceStats()`，三处共用聚合数字 |
| `frontend/src/store.ts` | 删 `problems` / `unreadProblems` 与 `/notifications` 请求（刷新 4→3 个请求） |
| `frontend/src/types.ts` | 删 `Problem` 接口与 `View` 的 `"problems"` |
| `frontend/src/components/OverviewDashboard.vue` | 第 4 张指标卡改「待处理内容」；新增「最近完成」区块 |
| `frontend/src/components/AccountsView.vue` | 空态成对化；只保留账号职责 |
| `frontend/src/components/ProgressWindow.vue` | 默认最小化 |
| `frontend/src/components/SettingsView.vue` | 删「通知提醒」页签与全部 `notification.*` 字段 |
| `frontend/src/style.css` | `.nav-group` 分组、`.engine` 心跳、`.top-stats`、`.recent-row`；去掉账号卡死高度与卡内滚动；`.page-content` 底部预留 132px；删通知遗留死规则 |
| `tools/vue_check.py` | 删站内通知栏与问题中心分页验收；导航遍历列表改为 6 项；进度小窗验收改为「默认最小化 → 展开 → 收回」 |
| `tools/ui_check.py`、`tools/smoke_test.py` | 删通知种子与「8.6 问题中心」冒烟段 |
| `tests/` | 通知相关测试删除或改写为事件断言；新增 `tests/test_narrative_and_settings.py` |
| `docs/architecture.md`、`README.md`、`docs/layout-research.md` | 同步更新；新增布局调研文档 |

### 兼容性与迁移（v2.3.0）

- **破坏性**：`/api/notifications*` 三个端点与 `notification` 设置组已不存在，直接调用会 404；
  旧的 `notification` 配置在读取时被丢弃，其余设置不受影响。
- 数据库：新库不再创建 `notifications` 表；旧库里已存在的该表不再被读写，**不需要迁移**，
  也可手动 `DROP TABLE notifications` 释放空间。
- 任务数据、答题缓存、已完成记录、界面偏好（`ui.dismissed_resume_tasks` /
  `ui.completed_page_size`）均保持原格式，无需迁移。
- 数据目录与安装方式见文末通用说明（仍适用）。

---

## v2.2.4

> 相对 v2.2.3 的**纯前端修复版**：后端无任何改动，不新增端点、不改协议、不改数据格式。

本版修两处前端正确性问题，并把对应的浏览器验收补上：

### 一、修复：提示条（toast）计时器泄漏，新提示被提前清除

- 现象：连续出现两条提示时，**后出现的提示会被前一条的计时器提前清掉**，
  表现是提示一闪而过或干脆不显示。
- 根因：`frontend/src/App.vue` 的 `watch(() => state.toast)` 每次提示变更都新建一个
  **未登记**的 `setTimeout`，旧计时器到点后清掉的是**新**提示。
- 修复：改为 `let toastTimer`，重建前先 `clearTimeout(toastTimer)`，并在 `onUnmounted` 中清理。

### 二、修复：「已完成」页状态筛选的正确性与空状态

`frontend/src/components/CompletedView.vue`：

- 状态筛选时按接口上限 **100** 取最新一批，再在本地过滤
  （新增 `requestLimit` / `requestOffset` computed），避免「只过滤当前一页」造成的误导；
- 状态筛选时隐藏分页（`paginable`）；
- 结果被 100 条上限截断时给出 `.completed-scope` 提示条；
- 空状态按 `hasFilters` 区分两种语义：
  「筛选无结果」→ 按钮「清空筛选条件」；
  「确实还没有数据」→ 按钮「去新建学习任务」。

### 三、浏览器验收断言扩充

`tools/vue_check.py` 新增「不再提醒」持久化与「已完成」页筛选/分页/搜索断言，
浏览器验收从 **51 项增至 59 项**。

### 改动文件（v2.2.4）

| 文件 | 改动 |
|---|---|
| `frontend/src/App.vue` | 提示条计时器改为 `toastTimer` + `clearTimeout` 重建 + `onUnmounted` 清理 |
| `frontend/src/components/CompletedView.vue` | 状态筛选按 100 条上限取批后本地过滤、状态筛选隐藏分页、`.completed-scope` 截断提示、`hasFilters` 空状态分流 |
| `tools/vue_check.py` | 新增「不再提醒」持久化与「已完成」页筛选/分页/搜索断言（51 → 59 项） |

### 兼容性与迁移（v2.2.4）

- 纯前端修复，后端与数据格式不变；数据目录与安装方式见文末通用说明（仍适用）。
- 无需迁移任何配置或任务数据。

---

## v2.2.3

> 本版回答三件事：**「已完成」到底做了什么、要能看得见」**、**「完成的记录要有一个专门的地方集中看」**、
> **「不想再被同一条提醒打扰」**，并按「简约白黑大圆角」重做了整套界面。

### 一、修复：独立考试显示「已完成」，但看不到任何具体信息

#### 问题

任务列表显示该场考试「已完成」，但点进任务详情，逐题明细是空的、统计全是 0：

```text
questions: 0   llm_calls: 0   submit_ok: 0
work.units: { "exam:11021171": { status: "succeeded" } }
事件流: work_plan → work_result → task_progress → task_succeeded（没有一条 answer_result）
```

#### 根因

`cli_copy/functions/exam_room_url.py` 的「已交卷」分支：打开答题页时若平台已经显示交卷成功
（上一次运行已交、或用户自己在浏览器里交了），程序会**直接判定完成并返回**——
这是对的（不该重复交卷），但它只 emit 了一句「该场考试已交卷完成」+ `status=succeeded`，
既没有逐题明细，也没有说明「为什么没有明细」，于是用户看到的就是一个空洞的「已完成」。

#### 修复

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

### 二、新增：「已完成」专页

#### 后端 `GET /api/completed`

```text
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

#### 前端「已完成」页面

左侧导航新增「已完成」入口，页面提供：

- 关键词搜索（防抖）、账号筛选、功能筛选（课程任务点/独立作业/独立考试）、状态筛选、每页条数；
- 每行：状态徽标、课程与功能、账号、起止时间、耗时、逐题概要、结果说明（`outcome.reason`）；
- 考试行额外显示试卷名与「考后无逐题回顾」说明；
- 点「查看详情」复用任务详情抽屉（含「AI 做题」逐题卡片与 `answers_note` 提示条）；
- 分页与行动邀请式空状态。

### 三、新增：黄色续跑提示支持「不再提醒」

- 设置新增 `ui` 分组：`{dismissed_resume_tasks: string[], completed_page_size: int}`；
- `dismissed_resume_tasks` 归一为去重后的字符串列表（最多 100 条），
  `completed_page_size` 收敛到 10..100；
- 语义：**只对列表内的任务 id 隐藏黄色续跑提示**，出现新的中断任务仍会照常提醒
  （不做全局开关，避免用户错过真正的新问题）；
- 持久化复用既有 `PATCH /api/settings`，没有新增端点。

### 四、界面重做：简约白黑大圆角

- 页面底色纯白、次级面浅灰、1px hairline 分隔线；侧栏改为纯黑；
- 圆角统一走 token（`--r-sm 10px / --r-md 14px / --r-lg 20px / --r-xl 28px / --r-pill 999px`），
  卡片、弹窗、输入框、进度条一律大圆角；
- 强调色只用于状态语义（成功/警告/危险/信息），且只做小面积；主按钮改为近黑底白字；
- **移除所有纯装饰圆点/状态小点的可见图形**（`.dot` 置为透明，`.live-dot`、`.status i`、
  `.notification-dot` 置为 `display:none`）；选择器锚点保留以兼容既有 DOM，状态一律用文字表达；
- 阴影克制，hover/focus 只做轻微反馈，不加夸张动效。

### 五、改动文件（v2.2.3）

| 文件 | 改动 |
|---|---|
| `cli_copy/functions/exam_room_url.py` | 已交卷分支补充 `already_done`/`detail` 与考试统计说明 |
| `cli_copy/core/exam_answer_page.py` | `parse_answer_page` 尽力提取试卷标题（`.exam-title`/`h1`/`<title>`） |
| `app/main.py` | `GET /api/completed`、`_completed_view`、`_answers_note`、`answers_note` 字段 |
| `app/settings.py` | `ui` 分组（`dismissed_resume_tasks`、`completed_page_size`）与归一 |
| `app/presentation.py` | 「此前已完成」叙述与原因详情 |
| `frontend/src/style.css` | 全量重写为「简约白黑大圆角」设计语言 |
| `frontend/src/components/CompletedView.vue` | 新增「已完成」专页 |
| `frontend/src/App.vue`、`types.ts`、`store.ts`、`mission.ts`、`OverviewDashboard.vue`、`TaskList.vue`、`SettingsView.vue` | 新页面接线、不再提醒、设置项完善；收尾轮修正提示条（toast）计时器泄漏 |
| `frontend/src/components/*.vue` | 跟随 token 的视觉重做与装饰标记清除 |
| `tests/test_completed_and_ui_settings.py` | 新增 21 例（completed 契约、ui 设置、answers_note、叙述） |
| `tests/test_exam_answer_page.py` | 新增 4 例（交卷页标题提取） |
| `frontend/src/mission.test.ts` | 新增 4 例（不再提醒过滤、新任务仍提醒、损坏设置、去重与 100 条上限） |
| `tools/ui_seed.py` | 新增已完成考试任务种子，供「已完成」页文案验收 |
| `tools/vue_check.py` | 「已完成」页纳入三档视口无溢出断言，并新增「不再提醒」持久化与已完成页筛选/分页/搜索断言（51 → 59 项） |
| `tests/test_v223_audit.py` | 独立审计 22 例（不修改产品代码） |

### 六、兼容性与迁移（v2.2.3）

- 数据目录与安装方式不变（见文末通用说明，仍适用）；
- 新增的 `ui` 分组对旧设置文件是**向后兼容**的：缺失时按默认值补全，不会清空既有配置；
- 历史任务无需迁移：`/api/completed` 的解释逻辑对旧数据同样生效（见本节第一点第 3 条）；
- 考试作答协议未改动（v2.2.2 的「粘贴答题页地址」流程保持一致）。

### 七、验证（v2.2.3）

| 项目 | 结果 |
|---|---|
| `python -m pytest tests cli_copy/tests -q` | 453 passed（含独立审计 22 例；功能新增 28 例：completed 契约 21 + 交卷页标题 4 + 考试链路 3） |
| `python tools/smoke_test.py --mock` | 56 通过 / 0 失败 |
| `npm --prefix frontend test`（vitest） | 6 个文件 / 29 例通过（含「不再提醒」过滤 4 例） |
| `npm --prefix frontend run build` | `vue-tsc --noEmit` + vite 构建通过 |
| `python tools/vue_check.py` | 59 项通过 / 0 错误（含「已完成」页在 wide/desktop/mobile 三档无横向溢出；截图见 `docs/vue-validation/`） |
| `python tools/ui_check.py` | 51 项通过 / 0 错误 |
| `npm --prefix desktop run dist:win` | 产出 `CourseArk-2.2.3-Setup.exe` / `CourseArk-2.2.3-Portable.exe` |
| `npm --prefix desktop run smoke:packaged` | 解包版与便携版都能加载新界面并正常停掉 Python 后端（需先清掉环境变量 `ELECTRON_RUN_AS_NODE`） |
| 真实数据复核（只读） | 历史 3 条 succeeded 考试任务的 `outcome.reason` 均非空且说明「考后无逐题回顾」 |

> 独立验证任务（task-12）已完成：真实数据只读复核、`/api/completed` 契约与边界（limit 0/101/-1 → 422）、
> `settings.ui` 归一与持久化、「不再提醒」只隐藏列表内 id（新中断任务仍提醒）、4 个反例场景，
> 结论为**未发现需要修复的产品缺陷**。独立审计新增 `tests/test_v223_audit.py`（22 例）。
>
> 收尾轮修正：`vue_check.py` 曾出现的 locator 超时并非并发构建抖动，而是 `frontend/src/App.vue`
> 提示条（toast）计时器的真实缺陷——每次提示变更都新建一个未登记的 `setTimeout`，旧计时器会提前
> 清掉**新**提示。现改为在 `watch` 中 `clearTimeout` 后重建，并在 `onUnmounted` 清理，连续 3 次
> `vue_check.py` 均 59/59、0 错误。（该修复作为 v2.2.4 的前端修复正式发布，见本文 v2.2.4 第一节。）

---

## v2.2.2

> 本版把「独立考试」从「只能提示平台安全验证」变成**真正能交卷**：
> 在浏览器里进入考试后，把地址栏的答题页地址粘贴进来，程序即可逐题 AI 作答并自动交卷。
> 该流程已在真实考试中跑通并完成交卷（10/10 题，平台显示「已完成」）。

### 一、为什么需要粘贴地址

学习通进入考试前有一道**平台侧安全验证**（考试说明页 `examCheck=1` / `captchaCheck=1`，
需人机验证）。验证凭证绑定在浏览器会话上，程序的 HTTP 会话既拿不到、也不应尝试绕过，
因此 v2.2.1 只能安全中止并提示用户。

v2.2.2 改用「用户验证、程序作答」的分工：

1. 用户在浏览器里完成平台验证，正常进入考试答题页；
2. 复制地址栏里带 `enc=` 的答题页地址（`/exam-ans/exam/test/reVersionTestStartNew?...`）；
3. 在 CourseArk 新建「独立考试」任务时粘贴该地址，程序直接在该页面上作答。

带 `enc` 的地址本身就是平台发给本次考试的授权凭证，程序只做「打开已授权的答题页 → 读题 →
填答案 → 保存 → 下一题 → 交卷」，**不触碰验证码、不伪造验证结果、不重复开始考试**。

### 二、实现

#### 1. 新增纯解析模块 `cli_copy/core/exam_answer_page.py`

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

#### 2. 新增执行器 `cli_copy/functions/exam_room_url.py`

`ExamRoomByUrl(user, course, log, ui)` 复用 `DealExam` 的 LLM、答题缓存与逐题上报：

- 校验粘贴地址的 `courseId` 与任务课程一致，不一致直接给出可读错误；
- 逐题：AI 作答 → `tempSave=true` 保存 → 用响应前进到下一题；
- 最后一题保存后以 `tempSave=false` 交卷，响应 `status=submitted/forceSubmitted` 视为交卷成功；
- 每题 emit `answer_result`（题目/选项/AI 答案/来源）与 `work_progress`（当前/总数），
  进度小窗因此有真实进度与剩余时间预估；
- 安全护栏：同一题重复出现（页面没前进）→ 中止并提示刷新考试页后重新粘贴；
  最多 200 题；保存被拒/交卷被拒都抛出服务器原文；已交卷页面则记录「已完成」不再作答；
  **整卷交卷成功后才把 AI 答案写入答题缓存**（避免半途失败污染缓存）；
- `worker/runner.py`：`exam` 任务若带 `params.exam.url` 走本执行器，否则保持 v2.2.1 的
  「按考试列表处理」（仍会在平台验证处安全中止）。

#### 3. 参数与界面

- `app/task_model.py` 新增 `ExamParams{url}`，仅 `exam` 功能携带；URL 非空时校验必须是
  学习通答题页地址，否则提示「请粘贴学习通考试答题页地址（含 reVersionTestStartNew 与 enc 参数）」；
- 新建任务选「独立考试」时出现「考试答题页地址（推荐）」输入框，留空则仍按考试列表处理；
- 任务详情沿用 v2.2.1 的「AI 做题」逐题卡片，考试同样适用。

#### 4. 自检工具

`tools/check_work_page.py --exam-url "<答题页地址>"`：只读打开该页并打印题目、选项、
表单字段与提交 URL，不发答案、不提交，用于排查「粘贴后没反应」。

### 三、改动文件（v2.2.2）

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

### 四、兼容性与迁移（v2.2.2）

- 数据目录与安装方式不变（见文末通用说明，仍适用）；
- 旧考试任务（不带 URL）行为与 v2.2.1 一致：仍会在平台安全验证处中止并提示，不会自动开始考试；
- 粘贴地址带有时效（`enc` 由平台按考试会话签发）；过期后重新进入考试再复制一次即可。

### 五、验证（v2.2.2）

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

本版特有未验证项：不同题型的考试（多选、填空、简答）已按页面协议实现并有单测，
但尚未在真实考试中逐类验证。

### 六、使用与边界（v2.2.2）

- 平台安全验证、考试码仍需用户在浏览器完成；本工具不会绕过，也不会代为开始考试
  （通用边界见文末通用说明）；
- 考试是有时限、可能影响成绩的操作：请确认允许 AI 作答后使用；程序在交卷前会逐题保存，
  中途退出可在考试页面继续（平台已保存的临时答案仍在）；
- 若粘贴后提示「答题页没有前进」：刷新考试页重新复制地址，通常是页面已过期或平台限制了并发作答。

---

## v2.2.1

> 本版修复三个真实使用问题：任务点进度一直显示 `0/0`、任务中断后重开直接显示「已完成」、
> 独立考试总是失败（现定位为平台安全验证）。此外补上了启动自动同步与「继续执行」。

### 一、问题与根因

#### 1. 课程任务点全部显示 `0 / 0`

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

#### 2. 任务点做到一半退出程序，重开后直接显示「已完成」

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

#### 3. 独立考试总是失败

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

> **后续版本已解决（v2.2.2）**：本版对考试只能「安全中止并提示」；v2.2.2 新增「粘贴考试答题页
> 地址」直连作答，已在真实考试中完成交卷（10/10 题）。见本文 v2.2.2 节。

### 二、改动文件（v2.2.1）

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

### 三、兼容性与迁移（v2.2.1）

- 数据目录与安装方式不变（见文末通用说明，仍适用）；
- 旧任务（含 `interrupted` / `failed`）在任务列表可直接「继续执行」；
- 新增设置项 `scheduler.sync_on_start` 默认开启；可用环境变量
  `AUTOCXWEBUI_DISABLE_AUTO_SYNC=1` 临时关闭（测试/自动化场景）。

### 四、验证（v2.2.1）

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

本版特有未验证项：真实考试交卷流程未执行（该考试被平台安全验证拦截，属已知限制，
已由 v2.2.2 解决）。

---

## v2.2.0

> 本轮目标：让 AI 答得更准、把「考试」接进同一条答题链路、让作业/考试可以挑着做、
> 运行中能看见「正在做什么、还要多久」。

### 一、AI 做题正确率：提示词 v2

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

### 二、独立考试（新功能）

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
本版本会识别出来并**安全中止**（不提交半份答案）；已验证的手机端协议
（`reVersionSubmitTestNew` + 签名参数）只做了调研记录，见
[`docs/research-exam.md`](research-exam.md)，尚未实现。因此在浏览器里只能一页一题作答的考试，
本版本会提示你在网页端手动完成。

> **后续版本已解决（v2.2.2）**：上面这条限制不再成立。v2.2.2 新增「粘贴考试答题页地址」直连：
> 用户在浏览器里进入答题页后把带 `enc=` 的地址交给程序，程序按 `reVersionSubmitTestNew`
> 逐题 `tempSave=true` 保存、末题 `tempSave=false` 交卷，并已用真实考试验证（10 题全部作答并成功交卷）。
> 实现与验证数据见本文 v2.2.2 节。
> 另：本节第 2 条「开始考试」写的 `tId=paperId` 是当时的错误猜测，v2.2.1 起已修正为 `tId=考试ID`。

### 三、挑选作业/考试

- 新增课程目录接口 `GET /api/accounts/{id}/courses/{course_id}/catalog?kind=work|exam&refresh=false`：
  由 `app/catalog_service.py` 拉起 `worker/catalog_runner.py` 子进程登录并只读拉取列表，
  结果写入 SQLite 表 `course_catalog` 缓存 600 秒；失败时有旧缓存则降级返回并带 `error`。
- 新建任务时，选好课程后可「加载列表」，勾选要处理的作业/考试（默认全选，可全选/取消全选），
  提交为 `params.selection = {mode: "selected", ids: [...]}`；不勾选任何项时为 `mode: "all"`。
- 任务执行端（`worker/runner.py`）按 `selection.ids` 过滤；`deal_homework` / `deal_exam_room`
  会把「勾选的项不在待处理范围」等原因为写进日志，避免出现「0 个待处理」而无解释。

### 四、运行中的进度小窗

- `GET /api/tasks/{id}` 新增 `live` 快照：当前动作、动作时间、已用时、
  当前处理项的 `current/total`，以及预计剩余 `eta_seconds` + `eta_source`。
  预计剩余优先用「当前项速率」推算（视频/下载这类有明确总量的项更准），
  其次退化为「任务级速率」，老任务返回 null。
- 前端右下角浮动小窗显示「正在做什么 / 已用时 / 预计剩余 / 当前项百分比」，
  可最小化或关闭；任务列表里运行中的行也显示一行摘要。

### 五、改动文件（v2.2.0）

后端与答题链路：

- 新增 `cli_copy/core/exam_form.py`、`cli_copy/functions/deal_exam_room.py`、`worker/catalog_runner.py`；
- `cli_copy/models/course.py`（`get_exam_list` / `exam_start_url`）、
  `cli_copy/utils/llm_client.py`（提示词 v2 / context / strict / `_clean_value`）、
  `cli_copy/functions/deal_exam.py`（上下文注入 + 严格重试）、
  `cli_copy/functions/deal_homework.py`（selection 过滤）、`worker/runner.py`（exam 分发）；
- 新增 `tests/test_exam_form.py`；扩充 `cli_copy/tests/test_core_behaviors.py`、`tests/test_worker_features.py`；
- `tools/check_work_page.py` 支持 `--kind exam`（默认只读列出考试，不发起「开始考试」）。

服务端：`app/task_model.py`、`app/database.py`、`app/catalog_service.py`（新）、
`app/main.py`、`app/narrative.py`、`app/presentation.py`、`tests/test_catalog_and_live.py`（新）等。

前端：新增 `frontend/src/catalog.ts`、`live.ts`、`components/ProgressWindow.vue` 及测试；
`NewTask.vue`（独立考试 + 列表勾选）、`TaskList.vue`（运行摘要）、`TaskDrawer.vue`（考试文案）等。

### 六、验证（v2.2.0）

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

本版特有边界：考试链路**没有**用真实考试验证（开始考试会占用考试机会且不可逆），
只做了只读列表核对与合成页面单测。

### 七、升级说明（v2.2.0）

- 直接覆盖安装即可，数据目录与安装方式见文末通用说明（仍适用）；
- 旧配置自动兼容：`tiku` 组与 `answer.fallback_to_tiku` 在读取时丢弃，
  `answer.mode: tiku` 归一为 `ai`；
- 关闭程序后安装新版；安装包与便携版文件名带版本号，便于回滚。

---

## v2.1

> v2.1 的主线是**把「独立作业」修到真的能交上**，并按需求**删除在线题库，只保留 AI 做题**，
> 同时把「AI 在做什么题」实时呈现在界面上。本文记录根因、改动与验证口径，便于以后回归。

### 1. 事故复盘：独立作业为什么失败

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

### 2. 改动

#### 2.1 新增 `cli_copy/core/work_form.py`

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

> 提交参数细节：`token` 来自 `enc_work`，与 `standardEnc`、列表页 `enc` 三者不同，不可互替；
> `totalQuestionNum` 是平台下发的 32 位十六进制令牌，**不是题目数量**；
> 字体解密覆盖 `font-cxsecret` 加密文字（`cli_copy/core/font_decoder.py`），
> 用「字形特征哈希 → 汉字」离线反查（参考数据 `cli_copy/resource/font_ref_cx.bin`），
> 未解码时不下发乱码，直接标记 `unreadable`。

#### 2.2 `cli_copy/functions/deal_exam.py`

- 解析：优先新解析器，旧 `TiMu`/正则路径仅作兜底；`_extract_independent_page` 与 API 兜底路径统一返回
  `(题目, 隐藏字段, 表单)` 三元组。
- 提交：有页面表单时 `work_form.build_submission` 回放；无表单时走 `_legacy_submission` 兼容旧页面。
  新增 `_check_submit_ready()`：POST 前 GET `work/validate`，`1`（状态异常）与 `2`（需要验证码）直接拦截并写明原因。
- 缓存：只有 `source == "llm"` 的答案写入缓存，随机答案不落库。
- 逐题事件：新增 `_emit_answer_result()`，每题 emit `answer_result`（题干/选项/答案/来源/状态/原因）。
- 在线题库：删除 `TikuProvider` 依赖与分支，历史配置 `answer.mode == "tiku"` 归一为 `ai`。

#### 2.3 删除在线题库

- 删除 `cli_copy/utils/tiku_provider.py`；`core/config.py` 引入 `REMOVED_KEYS`，读写两侧丢弃 `tiku` 组与
  `answer.fallback_to_tiku`；`answer.mode` 只允许 `ai` / `manual`。
- `app/settings.py`（掩码、默认值、导入映射）、`app/task_model.py`、`app/task_manager.py` 同步删除；
  旧配置/旧预设里的相关字段在读取时忽略、写回时不带（不会报错）。
- 前端删除「题库来源」设置组、`fallback_to_tiku`、`tiku_hits` 展示；「我的题库」改为「答题缓存」。
- `exam_stats` 保留 `tiku_hits` 键（恒 0）以兼容旧事件与旧前端，不再解释为在线题库。

#### 2.4 答题缓存与「AI 做题」页签

- `DELETE /api/question-bank` 新增，用于一键清空缓存（界面二次确认）。
- `GET /api/tasks/{id}` 新增 `answers[]` 与 `answers_summary`；答案按 `(media,index)` 去重取最新，
  经 `redact_data` 脱敏，旧任务的这两个字段为空数组/零值。
- 任务详情新增「AI 做题」页签：按作业分组、逐题卡片（题干、选项、答案、来源、失败原因），
  运行中 1.5s 轮询 + SSE 300ms 防抖；摘要展示 AI / 缓存 / 随机 / 未识别分布。
- 侧栏、任务列表、总览里的「题库」字样统一改为「答题缓存」；任务列表去掉 `feature` 过滤，
  所有任务都能在历史里看到。

#### 2.5 只读自检工具

`tools/check_work_page.py`：按数据目录读账号，登录后只发 GET，打印解析到的题目、提交 URL、将提交的
全部表单字段，以及 `work/validate` 的提交前置校验结果。用于平台再次改版时快速定位是解析问题还是提交问题。

### 3. 兼容性与迁移（v2.1）

- 设置：旧 `tiku` 组、`fallback_to_tiku`、`mode: tiku` 在读取/导入时被丢弃或归一为 `ai`，不报错。
- 任务：旧任务的 `params_json` 里残留字段在生成任务参数时被忽略；旧事件流仍可展示。
- 数据目录与安装方式见文末通用说明（这是该说明首次出现的版本）。
- 旧版 `question_bank.db` 直接作为答题缓存使用，无需迁移。

### 4. 验证（v2.1）

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

### 5. 尚未验证与已知风险（v2.1）

- **真实提交**：自动测试与自检脚本都不会提交答案，`addStudentWorkNewWeb` 的成功响应只在浏览器里验证过
  协议一致。请用桌面版跑一次真实独立作业确认；若仍失败，任务详情「AI 做题」和诊断日志会给出提交 URL 与响应。
- **验证码**：`work/validate` 返回「需要验证码」时会中止并提示，目前不自动识别验证码。
- **页面变体**：已覆盖现行内嵌题目页与导出页两代结构；其它课程若出现第三种结构，先跑自检脚本再补选择器。
- **简答题**：现行页面把部分判断题以「简答题（answertype=4）」形式下发，AI 返回的「正确/错误」会按文本写入，
  答案质量依赖模型；如需更严格，可在此处加题型启发式（见 [`docs/research-github.md`](research-github.md)）。

### 6. 下一版候选（来自 GitHub 调研）

[`docs/research-github.md`](research-github.md) 汇总了同类项目的做法与 14 项功能候选。与本项目方向最贴近的顺序建议：

1. 失败题汇总与「异常率阈值中止」（参考 uh 的 `cover_rate`），避免大面积随机作答；
2. 任务断点续跑（保存已完成题目索引，重跑只补未完成部分）；
3. 图片题干 OCR / 多模态答题（仅允许 `chaoxing.com` HTTPS 图片）；
4. 答案校验更严（简答题关键词、判断题启发式），并允许用户自定义兜底策略；
5. 桌面端打包流程固化（本地已验证的构建/冒烟命令写进 CI）。

---

## 跨版本通用说明

以下约定自首次出现的版本起**持续适用**，各版本小节不再重复：

### 数据目录与安装（首次出现于 v2.1）

- 数据目录不变：网页版为项目 `data/`，桌面版为 `%APPDATA%\AutoCxWebUI`（该目录名为兼容既有安装而保留）。
- 升级方式：直接**覆盖安装**即可，无需迁移；关闭程序后再安装新版。
- 安装包与便携版文件名带版本号，便于回滚。

### 平台风控边界（首次出现于 v2.2.0）

- 平台安全验证（`captchaCheck` / `examCheck`）、考试码、验证码与人脸识别均需用户自行在浏览器完成；
  本工具**不会尝试绕过**，命中即记录原因并安全中止（不启动考试计时、不提交任何答案）。
- v2.2.2 起的分工是「用户验证、程序作答」：用户在浏览器完成验证后，把带 `enc=` 的授权答题页地址
  粘贴给程序；`enc` 由平台按考试会话签发，带时效，过期后重新进入考试再复制一次即可。

### 验证环境（首次出现于 v2.1）

- 自动化会话**没有可交互桌面**：Electron 安装包可以构建，但窗口无法在该环境手动确认，
  `smoke:packaged` 需在真实桌面会话运行；各版本验证表中的「未验证项」按当时口径记录。
- 在 Electron 相关终端运行打包烟测前，先清掉 `ELECTRON_RUN_AS_NODE` 环境变量
  （`Remove-Item Env:ELECTRON_RUN_AS_NODE`），否则打包应用会被当成纯 Node 进程启动并立刻退出。
- 打包烟测用独立的 `--user-data-dir` 启动打包应用，因此**已打开的 CourseArk（安装版/便携版）不会
  干扰烟测**，无需先退出。若仍出现 `READY http://127.0.0.1:<port>` 断言失败
  （`The input did not match the regular expression /^READY http:\/\/127\.0\.0\.1:\d+\s*$/`），
  先确认 `ELECTRON_RUN_AS_NODE` 已清掉，再用 `Get-Process CourseArk -ErrorAction SilentlyContinue`
  检查残留进程后重跑。
