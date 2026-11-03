# CourseArk 布局与信息架构研究笔记

> **调研对象**：三个已下载到本机的开源「学习通 / 网课自动化」项目。
> **调研目的**：为 CourseArk（Vue 3 + TS 本地 Web 控制台）提炼可复用的布局骨架、信息层级与状态表达做法。
> **调研方式**：只读阅读三个项目的源码（`read` / `glob` / `grep`，不用 `Get-Content` 避免中文乱码），并与本仓库 `frontend/src` 现状对照。
> **约束**：本文件是研究笔记，**未修改参考项目的任何文件，也未修改 CourseArk 的任何源码**。
> **调研时间**：2026-11-03。
>
> **现状快照的时点说明**：本文对 CourseArk 的描述取自调研开始时的 `frontend/src`。调研过程中该工作区被并行修改过（`ProblemsView.vue`、`NoticeBar.vue` 被删除，`store.ts` 移除 `state.problems` / `state.unreadProblems`，`types.ts` 的 `View` 去掉 `"problems"`），因此文中「导航 7 项」「问题中心」「顶栏铃铛」等描述指的是**改动前**的基线，用于和用户提出的 4 个已知问题对齐。第 3、4 节的建议按「问题中心/通知这套信息该怎么收」来写，无论最终保留还是移除该页都成立。

## 参考项目实际路径

三个仓库在 `%TEMP%\courseref\` 下都多套了一层随机 sha 目录：

| 简称 | 实际路径 | 技术栈 | 规模 |
| --- | --- | --- | --- |
| **pang-qin**（题库后台，Star 62） | `C:\Users\Zora\AppData\Local\Temp\courseref\pang-qin__chaoxing-toolkit\pang-qin-chaoxing-toolkit-5b3b503\tiku\frontend` | Vue 3 + Element Plus + vue-router | 14 个源文件 |
| **checkin**（签到助手，Star 12） | `C:\Users\Zora\AppData\Local\Temp\courseref\liixnglinb__Superstar-checkin\liixnglinb-Superstar-checkin-4818448` | Electron + TypeScript，服务端拼 HTML 字符串 | `console-ui.ts` 2848 行 / 207 KB |
| **vibe-GIF**（桌面版，Star 13） | `C:\Users\Zora\AppData\Local\Temp\courseref\vibe-GIF__chaoxing\vibe-GIF-chaoxing-a1c02cf` | Tkinter（`ui.py`）+ 命令行菜单（`main.py`） | `ui.py` 193 行 |

---

## 0. 结论先行

1. **三个项目的信息组织都是「对象 → 动作 → 结果」三段式**，差别只在「对象」是一级容器（账号）还是平铺列表（题目）。CourseArk 天然是账号容器型，应该照 checkin 的分组表 + vibe-GIF 的账号上下文条来做，而不是 pang-qin 的一视同仁卡片流。
2. **状态必须收在一套四色语义里（ok / warn / err / idle）**，checkin 的 `.status-pill` 把「已手动暂停 / 未配置账号 / 登录需核验 / 扫描异常 (N) / 监控中」全部推导成同一套胶囊，这是三家里唯一做到「状态文案随条件变、视觉不变」的实现。
3. **列表页不做卡片内滚动**。checkin 用「表格行 + 详情抽屉/弹窗」，pang-qin 用「等高卡片流 + 分页」，都没有把滚动条塞进卡片里；CourseArk 的 `height: 620px` 写死高度是自找的。
4. **全局计数放顶栏，页面内只放该页该管的东西**（pang-qin 的做法），是解决 CourseArk「三页重复展示同一批账号+课程+进度」最直接的一刀。
5. **空态要成对设计**：一个图形/单字 + 一句主文案 + 一句引导，且「有筛选无结果」和「确实没数据」必须是两套文案两个按钮（CourseArk 的 `CompletedView.vue` 已经做对了，其他页没做）。

---

## 1. 逐项目分析

### 1.1 pang-qin / chaoxing-toolkit —— Vue 3 题库管理后台

**实读文件**：`index.html`、`src\App.vue`、`src\main.js`、`src\api\index.js`、`src\router\index.js`、`src\styles\theme.css`、`src\views\Layout.vue`、`src\views\Login.vue`、`src\views\Questions.vue`、`src\views\Pending.vue`、`src\components\QuestionCard.vue`、`src\components\QuestionForm.vue`、`src\components\PendingCard.vue`、`src\components\ImportModal.vue`。

#### 布局骨架：无侧栏的「顶栏 + 标签页」双层结构

```
.app-layout（display:flex; flex-direction:column; height:100vh）
├── header（固定 64px，横向 flex，两侧对齐）
│   ├── .header-left：logo「題庫」26px 毛笔字体 + 1px×24px 竖分隔线 +「管理面板」12px/字距 2px
│   └── .header-right：两个 .stat-item（可点击跳转）+ 退出按钮
└── main（flex:1; overflow:auto; padding:28px 32px）
    ├── .tab-bar（下划线 tab，padding:10px 24px，13px，active 用 2px 金色下边框）
    │   └── .tab-badge（min-width:18px; height:18px; font:10px; radius:9px; 危险色底）
    └── 页面内容：toolbar（单行）+ 卡片流 + 分页
```

- **没有侧栏**。导航信息量只有 2 项（题库 / 待处理），用顶栏 tab 就够了；多出的一条侧栏只会稀释内容宽度。
- **顶栏右侧的 `.stat-item` 是「全局计数 + 快捷入口」合体**：`padding:5px 14px`、`border:1px solid var(--border-light)`、`font-size:13px`，数字用 `600` 字重 + 金色 `--gold-text #8b7355`，点击直接进对应页。它承担了「我现在有多少活要干」这个最高频问题。

#### 信息层级顺序（页面内）

`tab-bar`（我在哪、有几件事） → `toolbar`（搜索 + 排序 + 主操作，一行 38px 高） → `卡片流`（主体，每卡自洽） → `分页`（`margin-top:24px`，每页 20 条）。

卡片内部固定四段：**头部元信息行 → 题干 → 选项 → 答案块 → 操作行**。以 `QuestionCard.vue` 为例：

| 区块 | 关键数值 | 作用 |
| --- | --- | --- |
| `.q-head` | `gap:12px; margin-bottom:10px` | ID `11px` + 题型标签 + 其余元信息，一行放完 |
| `.q-type` | `font:10px; padding:2px 10px` | 题型色：0/1 金色、2 紫 `#8e44ad`、3 橙 `#d68910`、4–7 绿 |
| `.q-text` | `15px; line-height:1.8` | 题干，全卡唯一大字号 |
| `.q-opt` | `12px; padding:4px 12px; gap:8px` | 选项，弱化 |
| `.q-answer` | `13px; padding:8px 14px; 左侧 3px 绿色实边` | 答案块用「左边框」而不是背景色区分，省一层视觉噪音 |
| `.q-actions` | `margin-top:12px`，按钮 `12px; padding:5px 14px` | 编辑 / 删除 |

#### 一屏信息量

`.q-card` `padding:20px 24px` + `.card-list gap:12px`，1440px 宽下 3 列时一屏约 6–9 张；单列时约 4–5 张。**这个密度适合「每条都需要通读」的内容**（题目），不适合「每条只需要看状态」的内容（账号/任务）。

#### 列表与详情

**列表页不做内联展开**。所有编辑、导入、详情一律走 Element Plus 对话框（`QuestionForm.vue`、`ImportModal.vue`），`PendingCard` 转正时把内容预填进 `QuestionForm` 并带 `_pendingId`。好处是列表页的 DOM 复杂度恒定，滚动性能可预期。

#### 空状态

`.empty`：纵向居中、`padding:80px 20px`、一个 `48px` 毛笔字图标 `opacity:.4` + `14px` 文案。最有辨识度的一点是**每个页面给一个不同的单字**：题库页用「空」，待处理页用「净」。成本极低但页面之间不会「看起来一样」。

无选项时不写「暂无选项数据」留白，而是 `.p-empty` 斜体 `12px` 灰字 —— **用文字占位而不是用空白占位**。

#### 状态徽章与进度条

- 徽章只有一种用途：`.tab-badge` 表示待处理条数（`min-width:18px; height:18px; font:10px; radius:9px; 危险色底`）。
- **没有进度条**。这个项目没有长任务，所以不做 —— 反过来说明：进度条只应该出现在真的有长任务的地方。

#### 字号与间距规律

字号阶梯：`26px`（logo）/ `15px`（题干）/ `13px`（正文、tab、stat-item、答案）/ `12px`（按钮、次要元信息）/ `11px`（ID）/ `10px`（题型标签、时间）。
间距阶梯：`4 / 8 / 10 / 12 / 20 / 24 / 28 / 32 px`，最常用 `12px`（卡内块间距、卡片间距、元信息行内间距）。
圆角：**全站 `border-radius:0`**，刻意直角。卡片只有 `1px` 发丝线 + 极轻阴影 `0 1px 4px rgba(0,0,0,.02)`，hover 升到 `0 2px 12px rgba(0,0,0,.05)`。
滚动条：`6px` 宽，thumb 用 `--border`，hover 变金色。

#### 可复用 / 不可复用

- ✅ 顶栏全局计数 + 下划线 tab + 单行 toolbar + 分页这套骨架，在「列表型页面」几乎零成本。
- ✅ 空态单字 + 一句文案的组合，成本极低、辨识度高。
- ❌ **无多账号 / 多课程维度**，所有卡片一视同仁平铺，不适合 CourseArk 的分层数据。

---

### 1.2 liixnglinb / Superstar-checkin —— Electron 单页控制台（本笔记的主要参照）

**实读文件**：`src\server\console-ui.ts`（2848 行，全量结构 + 样式段）、`src\server\voyra-ui.ts`（13285 B，设计 token 全集）、`src\server\components.ts`（286 行，全部渲染函数）。

#### 布局骨架：三栏 + 单视图切换

```
.app-shell（100vw/100vh; flex column; overflow:hidden）
├── .app-titlebar（38px，自绘无边框标题栏，-webkit-app-region:drag）
│   └── 品牌 + 版本 + 状态芯片条 + 窗口按钮
└── .app-body（flex:1）
    ├── .app-sidebar（232px，三段式）
    │   ├── .sidebar-brand（44px：22px logo + 名称 + 版本）
    │   ├── .nav-groups（flex:1; overflow-y:auto; 隐藏滚动条）
    │   │   └── 三个带组标签的组：工作台（总览/课程清单/课表扫描）
    │   │       · 档案（历史记录/实时日志）· 系统（运行设置）
    │   └── .sidebar-foot（「引擎心跳」：状态点 + 状态文字
    │       + N 账号 / :端口 / 轮询秒数 三个 meta + 主题切换）
    └── .app-main（flex:1; overflow-y:auto; padding: var(--sp-5) var(--sp-6)）
        └── 一次只显示一个 .view（display:none 切换）
```

**关键 IA 决策**：

1. **单视图切换，不是路由多页**。`.view` 用 `display:none` 互斥，页头标题/副标题/面包屑随页面更新。好处是「同时只有一个页面存在于视觉里」，不会出现 CourseArk 那种三页同时挂着账号卡的情况。
2. **侧栏三段式（品牌 / 导航 / 心跳）**。底部 `.sidebar-foot` 常驻「引擎心跳」块：状态点 + 「N 账号 / :端口 / 轮询秒数」三个 meta。**运行态是常驻可见的，但它待在侧栏底部，不侵占内容区** —— 这正好是 CourseArk 右下角浮层该学的反面。
3. **导航分组 + 组标签**。9 项导航分成「工作台 / 档案 / 系统」三组，`.nav-item` `min-height:44px`、`padding:10px 12px`、`font-size:13px`，active 用 `background:hover + font-weight:600`（**不用左侧竖条、不用彩色块**）。移动端断点下侧栏变底部 tab 栏（`.nav-item flex:1`，竖排 `icon 20px` + `10px` 文字）。

#### 页头结构（每个页面统一）

`.page-head`：`display:flex; align-items:flex-end; margin-bottom:20px`，左侧三行 ——

| 元素 | 字号 / 字重 | 内容 |
| --- | --- | --- |
| `.page-crumb` | `12px` 弱色 | 面包屑 |
| `.page-title` | `20px` / `600` / `letter-spacing:-0.02em` | 页面标题 |
| `.page-sub` | `13px` 弱色 | **一句话说明这页做什么** |

右侧 `.top-actions` 放该页主按钮。**页头只有 20px 标题，不是 32px** —— 页头不该抢内容区的高度。

#### 总览页的信息顺序（最重要参照）

```
① .stats-grid：4 列等高统计卡
② .trend-card：14 天双柱 SVG（空态一句话兜底）
③ .overview-lower-grid：两列 grid-template-columns:340px 1fr
   ├── 左：账号列表卡片
   └── 右：最近活动表格
④ 全宽「各账号签到统计」卡片
@media (max-width:1120px) 两列塌成 1 列
```

`.stat-box` 细节：`padding:16px`、`radius:12px`、label `12px` 弱色 + 右上 `26px` 图标块、数值 `24px`/`600` 等宽 `tabular-nums`、**`margin-top:auto` 把数值贴底**、sub `11px` 最弱。等宽数字（`tabular-nums`）是关键 —— 数字跳动时不抖。

**「4 个数字 → 1 张趋势 → 左账号右活动 → 全宽汇总」这个顺序，是「先给我全局体检，再给我今天的流水，再给我可下钻的对象」的标准排法**。CourseArk 总览现在是「续跑条 → 4 指标 → 环形仪表 → 账号卡网格」，缺的正是「最近活动」这一层（它被放到了「已完成」页）。

#### 列表与详情的组织方式：**表格行 + 开关 + 详情按钮**

课程行 `.course-row` 是**表格**（不是卡片）：

| 列 | 内容 | 字号 |
| --- | --- | --- |
| 课程名列 | 课程名 `14px/600` + 副行「可复制的 CID / 班级」`mono 11px` 弱色 | 主视线给课程名 |
| 签到时段列 | `.window-pill`（`icon` + 时段文字） | |
| 状态列 | `.status-pill` 四色胶囊 | |
| 操作列 | `switch` 开关 + 详情 icon | |

**「技术 ID 降级为可点击复制的次要标签，主视线让给时段/状态」** —— 这是 CourseArk 账号卡里「平台任务点 fn/all」这类数字最该学的处理方式。

账号行 `.acct-row`：`34px` 方形头像（`brand-100` 底 / `brand-700` 字）+ 名字 `13px/600` + 主账号 pill + 副行 `12px` 弱色「学校 · 用户名」。

#### 空状态与错误态

- `.empty`：`padding:36px 20px`、居中、一行主文案 + `.empty-sub` `12px` 弱色 + 可选引导按钮（「去配置账号」直接锚到 `#settings`）。
- 表格空态 `.cell-empty`：`colspan` 全表、居中、`padding:32px 0`。
- grid 空态 `.grid-empty`：`grid-column:1/-1`（**保证空态不被挤成半格**）。
- 趋势图空态：一句话「暂无签到数据，产生签到记录后自动生成趋势图」，**图位保留、不塌陷**。
- 所有空态都是「说清楚 + 给下一步」，没有一处是纯图标。

#### 状态徽章与进度条

`.status-pill is-ok / is-warn / is-err / is-idle`：`6px` 圆点 + 文字，`padding:3px 8px`、`font:11px`、pill 圆角。课程行按条件**推导文案**，视觉恒定：

| 条件 | 文案 |
| --- | --- |
| `!watching` | 「已手动暂停」（idle）/「已结课停用」 |
| `!runtimeReady` | 「未配置账号」/「登录需核验」/「已暂停监听」（warn） |
| `fails >= 3` | 「扫描异常 (N)」（err，`title` 里写明「已自动重试；持续异常可点击重新拉取」） |
| 正常 | 「监控中」（ok） |

`.status-chip` 顶栏芯片：`height:22px`、`padding:0 9px`、`font:11px/600`、`flex-shrink:0`。

**进度条在 checkin 里几乎不出现** —— 因为它的任务是「轮询签到」，没有连续百分比。它把「进展」表达为**统计卡 + 趋势图 + 活动表**，而不是进度条。CourseArk 有真实的连续任务，进度条该留，但应该收进「运行中」这一个分区，而不是三页各画一次。

#### 字号与间距规律（`voyra-ui.ts` 设计 token 全集）

字号阶梯（`--text-*`）：

| token | 值 | 用途 |
| --- | --- | --- |
| `2xs` | `11px` | 元信息 |
| `xs` | `12px` | 卡标题辅助 / 标签 |
| `sm` | `13px` | 正文 |
| `base` | `14px` | 卡标题 |
| `md` | `16px` | |
| `lg` | `20px` | 页标题 |
| `xl` | `24px` | 统计数字 |
| `2xl` | `28px` | |

间距阶梯（`--sp-*`）：`4 / 8 / 12 / 16 / 20 / 24 / 32 / 40`。
圆角（`--r-*`）：控件 `8px`、卡片 `12px`、**浮层 `16px`**、胶囊 `999px`。
阴影：三档 `sm/md/lg` + `shadow-modal`。**注释明写「卡片无阴影；阴影只归浮层」** —— 卡片只有 `1px` 发丝线。这是三家里最克制的一套层级语言。

配色（浅色）：`--bg-canvas #F3F5F6`、`--bg-surface #FFFFFF`、`--bg-surface-sub #EDF1F3`、`--bg-surface-hover #E6EBEE`；文字 `#18181B / #55565C / #676C73`（注释写明「弱文字档是核算后刚好过线的值，不许再降」）；线 `--line-dim #E3E3E7` / `--line-strong #D4D4D9`；brand `#426987 / #355B7D / #284C6B`；status 四色各四值（bg/line/ink/dot），如 ok `#EDFDF5/#A7F3D0/#065F46/#10B981`、err `#FEF2F2/#FECACA/#991B1B/#EF4444`。深色主题整套覆盖同名变量（`--bg-canvas #10151B` 等）。

#### 复用函数：同一数据在多页只写一次

`components.ts` 导出 `renderStatCard({label,value,sub,icon,tone})`、`renderStatusPill(type,text,title)`、`renderTrendSvg(trend)`（纯函数手绘 `640×150` SVG）、`renderRecentRows(recent)`（**总览页与历史页共用同一行渲染**，空态 `<td colspan="4">还没有签到记录`）、`renderCourseRow`、`renderAccountRow`。这是「总览里的最近活动和历史页的第一屏是同一个组件」的工程化保证 —— **重复展示不是靠自觉避免的，是靠共用 renderer 避免的**。

---

### 1.3 vibe-GIF / chaoxing —— Tkinter 桌面版

**实读文件**：`ui.py`（193 行，全量）、`main.py`（菜单 / 打印片段）、`README.md`（含命令行菜单截图）。

#### 布局骨架

```
App（900×650，minsize 800×500）
├── top 标题条（「超星学习通刷课工具」14px bold，padx:10 pady:5）
├── tk.PanedWindow（横向可拖）
│   ├── left（width:280，minsize:200）
│   │   ├── 「账号列表」11px bold 标题
│   │   └── 账号卡纵列（每卡两行：10px bold 姓名 + 9px 灰用户名）
│   └── right
│       ├── .func_frame 功能区
│       └── 「日志」11px 标题 + ScrolledText（height:15 行，Consolas 10px）
└── bottom 退出按钮
```

#### 信息层级顺序（这是它唯一但很有价值的贡献）

**左侧「对象列表」→ 右侧「该对象可做的动作」→ 底部「动作输出日志」**，全局唯一选中对象。

- 未选中账号时，功能区显示灰字「**请选择一个账号**」—— 空态就是引导语，不用另做空态设计。
- 选中后功能区顶部出现**上下文条**「当前: 姓名 (账号)」，下面一排等宽 `12` 的按钮：查看课程 / 开始刷课 / 签到监控 / 导出题目 / 爬取题库。
- 账号卡：白底、选中 `#e3f2fd`、`1px ridge` 边框、`cursor:hand2`、**整卡可点**。
- 动作结果全部进底部日志（`StdoutRedirector` 把 `stdout` 重定向到 `ScrolledText`，`see(tk.END)` 自动滚到底）。

#### 命令行菜单版本的信息顺序（`main.py`）

一级：账号表（`编号 / 姓名 / 账号` 三列）+ `[T] 题库管理` + `[0] 退出`。
二级：**当前账号上下文条**「`> 已选择: 张三 (13800138001)`」+ 动作编号列表 + `[0] 返回上级`。
课程选择用多选弹窗（「点击切换勾选，回车=全部/确认，Esc 取消」）。
题库管理是独立二级菜单（总题目数 + 按题型计数 + 导出/导入 JSON）。

**结论**：vibe-GIF 的信息组织 = 「先选账号 → 再看该账号的课程 → 再执行动作 → 动作结果进日志」，是「**账号为一级容器**」的最朴素实现。**视觉层不可参考**（无进度条、无状态徽章、无空态设计，错误只有红色提示字），但它的**顺序是对的**，而且证明了「上下文条」这个元素在多账号场景下是必需的。

---

## 2. 横向对比表：四类信息的呈现方式

| 维度 | pang-qin（题库后台） | checkin（Electron 控制台） | vibe-GIF（Tkinter 桌面版） | CourseArk 现状 |
| --- | --- | --- | --- | --- |
| **多账号** | 不支持（无账号维度） | 侧栏无账号入口；总览左栏 `.acct-row` 列表（`34px` 头像 + 名字 + 主账号 pill + 学校·用户名）；课程清单按账号分组 | 左侧 280px 账号卡纵列，全局唯一选中，选中态 `#e3f2fd`；二级菜单用「已选择: 姓名 (账号)」上下文条 | 账号卡网格（`repeat(2,1fr)` gap `16px`），每卡 `padding:24px` + 4 个操作按钮 + 折叠「登录状态与缓存」；**同一批账号在总览 / 学习任务 / 账号与课程三页各画一次** |
| **多课程** | 不支持（题目平铺） | 课程清单页用**表格行**：课程名 `14px/600` + 副行可复制 CID/班级 `mono 11px` + 时段 pill + 状态 pill + 开关；另有 `.course-grid` 卡片模式 `minmax(260px,1fr)` gap `12px`，`.course-card padding:16px` | 课程是「查看课程」动作的输出，只在日志里逐行 `[i] 标题`；选择课程走多选弹窗 | 账号卡内嵌课程 article 列表，**卡内滚动条**（`flex:1; min-height:0; overflow:auto; scrollbar-gutter:stable`），卡高写死 `620px`（compact `430px`）；账号与课程页则把课程塞进 `ModalShell` 宽弹窗 |
| **运行中任务** | 无长任务；只有 `.tab-badge` 待处理条数 | 无进度条概念；进展 = 统计卡 + 14 天趋势 + 最近活动表 + 各账号统计卡；顶栏 `.status-chip` 常驻运行态，侧栏底部「引擎心跳」常驻 | 无进度、无状态；动作输出全进日志，`see(tk.END)` 自动滚底 | **三处同时表达**：① 总览 4 指标 + 环形仪表 + 阶段三行 + 账号卡内 `.live-progress`；② 学习任务页 `.task-row` 进度条 + 状态 + 操作；③ 右下角 `ProgressWindow` 浮层（`328px`，`fixed right:22px bottom:22px`，2s 轮询） |
| **历史结果** | 无历史（题目只有增删） | `.history-row` 表格（时间 / 课程 / 类型 / 结果 pill），**总览与历史页共用 `renderRecentRows`**；空态 `colspan=4` 一句「还没有签到记录」 | 无历史（只有当次日志） | 独立「已完成」页：5 控件 filterbar + 竖排 `.completed-row`（状态徽章 + 标题 + 开始/结束/耗时 + 结果说明 + 考试块 + 逐题概要 + 查看详情）+ 可配置每页条数 + 双语义空态。**做得最好的一个页，但总览里没有它的摘要** |
| **导航形态** | 顶栏 tab（2 项）+ 顶栏 stat 快捷入口 | 侧栏 232px，9 项分 3 组带组标签，`min-height:44px`；移动端变底部 tab | 无导航（左侧列表即导航） | 侧栏 236px，7 项平铺，**无分组**；「问题中心」与顶栏铃铛浮层是同一份数据的两个入口（调研期间两者已被并行移除，基线见文首说明） |
| **详情在哪看** | Element Plus 对话框（列表不内联展开） | 详情按钮 → 弹窗/抽屉；表格行本身只放状态与开关 | 无详情，全在日志 | `TaskDrawer` 抽屉（任务）+ `ModalShell` 弹窗（课程）+ `ProgressWindow` 浮层（实时进度）；**三种容器并存** |
| **空态** | 每页一个 `48px` 毛笔单字 + 一句文案 | 主文案 + `.empty-sub` + 引导按钮；表格/grid 各有专用空态类 | 只有灰字「请选择一个账号」和红字错误 | `CompletedView` 有双语义空态（已做对）；`OverviewDashboard` / `ProblemsView` / `BankView` / `TaskList` 有 `icon + h3 + p` 结构但缺双语义分支；`AccountsView` 两处仍是裸文案 |
| **状态色语义** | 题型色（金/紫/橙/绿），非状态 | **ok/warn/err/idle 四色 × 四值（bg/line/ink/dot），文案随条件推导** | 无 | `.status` 按 task.status 上色（running / paused / succeeded / failed…），但缺「idle」这一档；指标卡 attention 态只把图标染 `--warn` |
| **圆角 / 阴影** | 全站 `0`，卡片 `1px` 线 + 极轻阴影 | 卡片 `12px` + `1px` 线无阴影；**阴影只归浮层**（`16px`） | Tk 默认 | `r-sm 10 / md 14 / lg 20 / xl 28 / pill 999`（**比两家都大**），卡片带 `shadow-sm` |

---

## 3. 针对 CourseArk 的建议清单

> 每条格式：**现状问题 → 建议做法 → 为什么（参考哪个项目）**。

### 建议 1：把「账号 + 课程 + 进度」的全局计数收进顶栏，三页不再各画一遍

- **现状问题**：工作总览 / 学习任务 / 账号与课程 三页都在重复展示账号 + 课程 + 进度卡片，且**数字口径不一致**（总览说 2 门课程，学习任务说 6 个账号 18 门课程）。用户无法判断哪个是真的。
- **建议做法**：
  1. 在 `.topbar` 右侧加两个 `.stat-item`（可点击）：`N 个账号 / M 门课程`、`K 项运行中`，与现有刷新按钮并排。样式参考 pang-qin：`padding:5px 14px`、`1px` 边框、`13px` 字，数字 `600` 字重。
  2. 数字口径**只在一处定义**：账号数 = `state.accounts.length`（已启用账号），课程数 = 各账号已同步课程的并集，运行中 = `state.tasks` 里 `active()` 的条数。三页所有「N 门课程」都从这一个 selector 取。
  3. 页面内只保留「该页该管的东西」，不再出现「全局有多少账号」这种跨页计数。
- **为什么**：pang-qin 的 `.stat-item` 证明「全局计数放顶栏 + 点击跳转」是零成本方案；checkin 的 `renderRecentRows` 共用 renderer 证明「同一数据在多页只写一次」要靠工程手段而不是靠自觉。

### 建议 2：账号卡不再写死高度，课程列表移出卡片内滚动

- **现状问题**：账号卡片内课程列表有内部滚动条，卡片高度不统一（`.workspace-account { height:620px }`、compact `430px`、`.workspace-account-scroll { flex:1; min-height:0; overflow:auto }`）。结果是「有的卡空着一大片，有的卡要滚才能看全」。
- **建议做法**（三选一，推荐 B）：
  - **A（对齐 pang-qin）**：卡片高度 `auto`，课程全部展开，外层 `.account-workspaces` 用 `align-items:start`，靠页面滚动而不是卡片滚动。
  - **B（对齐 checkin，推荐）**：**把课程从卡片里拿出来，改成表格行**。账号 = 一个 `.account-group` 分组标题（头像 + 名字 + 「N 门课程 · M 项运行中」+ 横线），课程 = 表格行（课程名 / 时段或任务点 / 状态 / 开关）。彻底消灭卡内滚动。
  - **C（折中）**：卡片内只展示前 3 门课程 + 「查看全部 N 门」按钮 → `ModalShell`（账号与课程页已经是这个做法，统一过去即可）。
- **为什么**：checkin 的课程清单用表格行而不是卡内列表，`renderCourseRow` 把「课程名（主）/ CID·班级（可复制次要）/ 时段 pill / 状态 pill / 开关」压进一行；pang-qin 的卡片全部等高、靠分页而不是卡内滚动。**三家里没有一家把滚动条塞进卡片里**。

### 建议 3：右下角运行进度浮层改成「侧栏底部心跳 + 内容区占位」

- **现状问题**：`ProgressWindow` `position:fixed; right:22px; bottom:22px; width:328px; z-index:45`，常驻右下角且**没有为它预留布局空间**，直接遮挡卡片内容（尤其是两列账号卡的第二列右下）。
- **建议做法**：
  1. **主方案**：把「当前运行」收成**页面内的固定区域**（总览的「正在执行」区块已有），浮层只在用户离开总览页时出现，且出现时给 `.page-content` 加 `padding-bottom: 260px` 或 `scroll-padding-bottom`，保证任何卡片都能滚到浮层之上。
  2. **副方案（更贴 checkin）**：在 `.sidebar-bottom`（现在只放连接状态）扩成「引擎心跳」块：状态点 + 状态文字 + 「N 运行中 / 端口 / 并发数」三个 meta，浮层改为**默认最小化**（`248px` 的 pill 条），只有点击才展开。
  3. 浮层位置从 `right:22px` 改到 `right:22px; bottom:22px` 时同时把 `.page-content` 的 `padding-bottom` 从 `24px` 提到 `96px`。
- **为什么**：checkin 的 `.sidebar-foot` 把运行态常驻在侧栏底部，**不侵占内容区**；它的日志页「滚动至最新」按钮才用浮出（`.log-pin` `position:absolute`、`32px` 高、pill），且浮在日志容器内部而不是全屏。浮层只应该解决「我暂时看不见」的问题，不应该长期压住内容。

### 建议 4：「问题中心」与顶栏通知二选一，保留一个入口

- **现状问题**：导航 7 项里有「问题中心」，与总览的「站内待处理通知」指标卡 + 顶栏 `NoticeBar` 铃铛浮层**是同一份数据的三个入口**，且导航项本身没有未读角标，用户得先点进去才知道有没有事。（注：调研期间该页与铃铛已被并行移除，见文首「现状快照的时点说明」；此条建议按「若保留该能力」写。）
- **建议做法**：
  1. **保留顶栏铃铛浮层作为「快速处理」入口**（它已经能单条标记处理 + 「查看全部通知与分类」跳转）。
  2. **导航里把「问题中心」从主列表移出**，改为：铃铛角标显示未读数；若仍要独立页，收进侧栏「档案」分组里（见建议 6 的分组方案）。
  3. 总览的「站内待处理通知」指标卡**保留**（它是全局体检的一部分），但点击行为统一为「打开铃铛浮层」，不再跳独立页。
- **为什么**：checkin 的导航把 9 项分成「工作台 / 档案 / 系统」三组，**同一份数据的入口不重复出现**；顶栏 `.status-chip` 承担常驻状态，不需要另开一页。pang-qin 则用顶栏 `.stat-item` + tab 的关系证明「快捷入口在顶栏、完整页在导航」是清晰的分工。

### 建议 5：状态统一成四色语义胶囊，文案随条件推导

- **现状问题**：状态表达分散在 `.status`（按 `task.status` 上色）、指标卡 `.attention`（只染图标）、账号卡 status 徽章（已启用/已停用）、课程副行「开放/关闭」文字。**同一件事有四种视觉**，且缺「idle（未配置/未登录）」这一档。
- **建议做法**：
  1. 定义一组 `.status-pill is-ok / is-warn / is-err / is-idle`：`6px` 圆点 + 文字，`padding:3px 8px`、`font:11px`、pill 圆角；四色取 checkin 的值（ok `#065F46` on `#EDFDF5`、warn `#92400E` on `#FFFBEB`、err `#991B1B` on `#FEF2F2`、idle `#69635E` on `#F5F5F4`）。
  2. 把状态**推导成文案**而不是直接显示枚举：`running → 执行中`、`paused → 已手动暂停`、`pending → 等待调度`、未登录 → `登录需核验`、未同步课程 → `未同步课程`、无账号 → `未配置账号`、`fails>=3 → 需处理 (N)`。
  3. 给 `title` 属性写清「为什么 + 怎么办」（如「近期多次失败，已自动重试；持续异常可重新拉取」）。
- **为什么**：checkin 的 `renderStatusPill` + `renderCourseRow` 是唯一做到「条件 → 文案 → 固定视觉」的实现，用户不需要记住颜色含义，读文字即可；`title` 兜住了解释成本。

### 建议 6：侧栏导航改成分组，并把导航项数量压到 5 项以内

- **现状问题**：7 项平铺无分组（工作总览 / 账号与课程 / 学习任务 / 已完成 / 答题缓存 / 问题中心 / 偏好设置），视觉上「任务类」和「配置类」混在一起；`问题中心` 与通知重复（建议 4）。**即使已移除「问题中心」（当前为 6 项），仍是平铺无分组**，且「账号与课程」夹在「学习任务」和「已完成」之间，读不出「对象 / 任务 / 档案」的层次。
- **建议做法**：分三组 + 组标签（`.nav-caption` 已有样式，现在是单个「工作空间」）：

| 分组 | 项 |
| --- | --- |
| **工作台** | 工作总览 / 学习任务 |
| **档案** | 账号与课程 / 已完成 / 答题缓存 |
| **系统** | 偏好设置 |

- **为什么**：checkin 的 9 项分 3 组带组标签，`.nav-item min-height:44px` + active 只改背景与字重（不用左竖条），侧栏信息密度高但不乱；`.nav-caption` 已经是 CourseArk 现成的样式，改文案成本几乎为零。

### 建议 7：总览补一层「最近活动」，并把「已完成」的摘要搬上来

- **现状问题**：总览的顺序是「续跑条 → 4 指标 → 环形仪表 + 阶段 → 账号卡网格」，**没有「最近发生了什么」**。用户想看「刚才那次跑得怎么样」必须跳到「已完成」页。
- **建议做法**：在指标卡之后、账号卡网格之前插入一行两列（`grid-template-columns: 340px 1fr`，`@media(max-width:1120px)` 塌成 1 列）：
  - 左：**账号列表**（`34px` 头像 + 名字 + 主账号 pill + 「学校 · 用户名」副行）—— 只读，点击进账号与课程页。
  - 右：**最近活动表格**（时间 / 课程 / 类型 / 结果 pill，8–10 行），底部「查看全部 →」跳「已完成」。
  - **这张表和「已完成」页的第一屏共用同一个渲染函数/组件**。
- **为什么**：checkin 的 `.overview-lower-grid` 就是 `340px 1fr` 两列（左账号右活动），且 `renderRecentRows` 被总览与历史页共用 —— 这是「总览不缺摘要、历史页不重复实现」的唯一可靠做法。

### 建议 8：空态成对设计，区分「筛选无结果」与「确实没数据」

- **现状问题**：只有 `CompletedView.vue:284-305` 做了双语义空态（有筛选 → 「当前筛选条件下没有…」+「清空筛选条件」；无筛选 → 「还没有…」+「去新建学习任务」）。其余页的空态结构已成型（`OverviewDashboard.vue:334-339`、`ProblemsView.vue:132-136`（基线版本，该文件调研期间被并行删除）、`BankView.vue:190/225`、`TaskList.vue:259-263` 都是 `icon + h3 + p`），但**普遍缺「有筛选 vs 无筛选」的双语义分支**（`BankView.vue:225` 只在标题上换了文案，没有换按钮）；`AccountsView.vue:176-178` 与 `:236-237` 两处空态更是**只有一句裸文案，没有图标、标题和下一步按钮**。
- **建议做法**：
  1. 统一一个 `.empty` 组件：`icon 30px` + `h3` 主文案 + `p` 引导 + 可选按钮，`padding:36px 20px`。
  2. 每个页面在无数据时给**一句具体的下一步**，而不是「暂无数据」。
  3. 有筛选时必须有「清空筛选条件」按钮。
  4. 表格/grid 内嵌空态用 `colspan` / `grid-column:1/-1` 兜底，不要留半格空白。
- **为什么**：checkin 的 `.empty`（主文案 + `.empty-sub` + 引导按钮）、`.cell-empty`（`colspan` + `padding:32px 0`）、`.grid-empty`（`grid-column:1/-1`）是三种容器的三套兜底；pang-qin 的「每页一个单字 + 一句文案」证明空态可以很便宜但很有辨识度。

### 建议 9：详情容器收敛成一种（抽屉），别三种并存

- **现状问题**：`TaskDrawer`（任务详情抽屉）、`ModalShell`（课程弹窗）、`ProgressWindow`（实时进度浮层）三种容器并存，用户不知道「点哪里会出什么」。
- **建议做法**：**任务详情统一走 `TaskDrawer`**；课程列表统一走表格行（建议 2-B）或 `ModalShell`（二选一，不要两套）；`ProgressWindow` 按建议 3 处理。列表页本身**不做内联展开**。
- **为什么**：pang-qin 所有详情/编辑一律走 Element Plus 对话框，列表页 DOM 复杂度恒定；checkin 的表格行只放「状态 + 开关 + 详情按钮」，详情另开。

### 建议 10：圆角与阴影往回收一档，卡片只留发丝线

- **现状问题**：CourseArk 圆角 `r-sm 10 / md 14 / lg 20 / xl 28 / pill 999`，卡片还带 `shadow-sm`。对比 checkin（卡片 `12px` 无阴影、浮层 `16px` 才有阴影）和 pang-qin（全站 `0` 直角、卡片只有极轻阴影），CourseArk 的层级语言偏「软」。
- **建议做法**：卡片 `12px`、控件 `8px`、浮层 `16px`、pill `999px`；**卡片去掉 `box-shadow`，只留 `1px solid var(--line)`**；`--shadow-lg` 只给浮层/抽屉/进度窗。
- **为什么**：checkin 的 `voyra-ui.ts` 注释明写「卡片无阴影；阴影只归浮层」，这是让「浮层 = 浮层」这件事在视觉上成立的前提；否则卡片和浮层同阴影，用户分不清层级。

### 建议 11：字号阶梯与数字等宽

- **现状问题**：`h1 32px` 偏大（页头抢了内容高度），指标数字 `34px` 与 `h1 32px` 几乎同权；数字未用 `tabular-nums`，轮询刷新时会抖动。
- **建议做法**：页标题 `20px`（对齐 checkin 的 `.page-title`），页副标题 `13px`；指标数字 `24px`；所有数字加 `font-variant-numeric: tabular-nums`；正文 `13px`、元信息 `11px`、标签 `10–11px`。
- **为什么**：checkin 的 `--text-lg 20px` 专给页标题、`--text-xl 24px` 专给统计数字，两档分开；`renderStatCard` 注释明写「数值用等宽数字」；`tabular-nums` 是数字跳动不抖的唯一低成本解。

---

## 4. 单一职责分区建议

> 原则：**每一页只回答一个问题**；跨页重复的只有「全局计数」（顶栏）和「最近活动行」（共用组件）。

### 4.1 工作总览（`overview`）—— 回答「现在整体怎么样？」

**只放全局体检与下钻入口，不放可操作的长列表。**

首屏信息顺序（自上而下）：

1. **续跑提示条** `.resume-banner`（有未完成任务时才出现；主按钮「继续执行」+ 两个 text-link）。保留现状。
2. **4 个指标卡**（`repeat(4,1fr)` gap `14px`，`padding:22px`，label `12px` / 数字 `24px` tabular-nums / 说明 `11px`）：
   - 执行中的账号（`activeAccounts` 数）
   - 执行中的课程（`activeCourses` 数）
   - 本轮已确认（`completed / total`，未完整时显示「正在读取完整任务范围」）
   - 站内待处理通知（`unreadProblems`，点击开铃铛浮层）；若按当前代码已移除通知能力，这一格改为「需处理任务」（`fails` 或需人工介入的任务数），点击跳学习任务页并按「需处理」筛选。
   - **口径唯一来源**：全部取自同一个 selector，与顶栏 `.stat-item` 同源。
3. **两列区块**（`grid-template-columns: 340px 1fr`，≤1120px 塌成 1 列）：
   - 左：**账号列表**（只读：头像 + 名字 + 主账号 pill + 「学校 · 用户名」），点击进「账号与课程」。
   - 右：**最近活动表格**（时间 / 课程 / 类型 / 结果 pill，8–10 行 + 「查看全部」），与「已完成」页共用渲染组件。
4. **「正在执行」区块**（现有 `.execution-dashboard` 的环形仪表 + 阶段三行可以保留，但**收缩成一行高**）：只显示有运行中任务的账号，每账号**最多 2 门课程摘要**，其余走「查看全部任务 →」跳学习任务页。**不做卡片内滚动，不写死高度。**
5. 底部：无。

**总览不该出现**：完整账号卡网格（含 4 个操作按钮）、课程全量列表、任务历史全量、可勾选批量操作的控件。

### 4.2 学习任务（`tasks`）—— 回答「有哪些任务在跑 / 跑得怎么样 / 我该干预哪个？」

**这里是唯一允许出现「进度条 + 暂停/继续/停止」的地方。**

首屏信息顺序：

1. **页头 + 主按钮**「新建学习任务」（`primary`，`v-if` 仅 overview/tasks 出现 —— 保留）。
2. **二级 tab**（下划线样式，对齐 checkin 的 `.filter-pills`：`min-height:44px`、`12px/600`、active `2px` 下边框 + `margin-bottom:-1px`）：`按账号展开` / `任务记录与历史`。**保留现有 `App.vue:207-230` 的结构。**
3. **filterbar**（一行）：搜索 `260px` + 账号 select + 状态 select（当前任务 / 全部与历史 / 已完成 / 需处理 / 已暂停 / 已停止）。
4. **`workspace-scope` 一行统计**（`11.5px` 弱色）：「N 个账号同时展开 · N 项正在执行 · N 项排队」。保留。
5. **任务列表**：按账号分组的 `.account-group`（头像 + 名字 + 「N 项任务 · M 项进行中」+ 横线）→ 四列表格「课程与任务 / 实际进度 / 状态 / 操作」。每行：课程名 `13.5px/500` + 副行「功能 · 时间」`11px` + 进度条 + 状态 pill + 操作 icon。
6. 空态 + 分页。

**学习任务不该出现**：账号的启用/停用/同步课程按钮、账号的 4 个小指标（课程数 / 平台任务点 / 执行·排队 / 需处理任务）—— 这些属于账号页；也不该出现「已完成」的逐题明细（跳详情抽屉）。

### 4.3 账号与课程（`accounts`）—— 回答「我有哪些账号、它们能不能跑、能跑哪些课？」

**这里是账号作为「配置对象」的页面，不是运行监控页。**

首屏信息顺序：

1. **页头 + 主按钮**「添加账号」（`primary`）。
2. **filterbar**：搜索 + 状态 select（已启用 / 已停用 / 登录需核验 / 未同步课程）。
3. **账号表格或等高卡片**（推荐表格，对齐 checkin `.course-row`）：
   - 账号名列：`34px` 头像 + 名字 `13.5px/600` + 副行「学校 · 用户名」`11px` 弱色。
   - 登录状态列：状态 pill（`已登录` / `登录需核验` / `已停用`）。
   - 课程列：`N 门课程` + 「查看课程」→ `ModalShell`（**沿用现有做法**）。
   - 同步列：「上次同步时间」`11px` + 「同步课程」按钮。
   - 操作列：启用/停用 switch + 更多 icon（编辑 / 删除 / 查看登录状态与缓存）。
   - **课程列表不进卡片内联**，走弹窗；卡片高度全部 `auto`。
4. **空态**：「还没有账号」+「添加账号」按钮 / 「没有符合条件的账号」+「清空筛选条件」。

**账号与课程不该出现**：进度条、运行中任务、暂停/停止按钮、逐题明细。

### 4.4 已完成（`completed`）—— 回答「过去每一次跑成什么样？」

**现状基本正确**，只需两处调整：

1. **与总览共用「最近活动行」组件**，避免两套渲染。
2. **筛选语义说明保留**（`completed-scope` 说明「正在最近 100 条中筛选，命中 N 条」）—— 这是三家里唯一的诚实做法。

### 4.5 答题缓存 / 偏好设置

- **答题缓存**：统计（总数 / 按题型）+ 搜索 + 列表 + 导入/导出/清理。参考 vibe-GIF 的题库管理二级菜单（总题目数 + 按题型计数 + 导出/导入 JSON）即可，不需要进度条。
- **偏好设置**：参考 checkin 的设置页结构 —— 顶部下划线 tab（学习与并发 / 通知 / 数据与维护 / 关于）+ 每个 pane 里若干 `.card`；每卡 = `.card-head`（标题 `14px/600` + 描述 `12px` 弱色 + 右侧状态芯片）+ `.card-body`（`grid-template-columns:repeat(auto-fit,minmax(280px,1fr))`、`gap:16px 20px`；每项 = label `12px/600` + 控件 `36px` 高 + help `12px` 弱色）+ `.card-foot`（保存按钮 + 提示）。危险区只改 `border-color` 为 err 色，不刷背景。

### 4.6 分区责任总表

| 信息 | 总览 | 学习任务 | 账号与课程 | 已完成 | 顶栏 |
| --- | --- | --- | --- | --- | --- |
| 全局账号数 / 课程数 / 运行中数 | ✅ 指标卡 | — | — | — | ✅ `.stat-item`（唯一口径） |
| 账号头像 + 名字 + 登录状态 | ✅ 只读列表 | ✅ 分组标题 | ✅ 完整 + 操作 | — | — |
| 课程全量列表 | — | — | ✅ 弹窗 | — | — |
| 进度条 / 暂停 / 停止 | 仅摘要，最多 2 门 | ✅ 完整 | — | — | — |
| 最近活动流水 | ✅ 8–10 行 | — | — | ✅ 完整 | — |
| 逐题明细 / 结果说明 | — | 抽屉 | — | ✅ 列表内 + 抽屉 | — |
| 站内通知 / 问题 | ✅ 指标卡（开浮层 / 或改为「需处理任务」） | — | — | — | ✅ 铃铛角标 |
| 账号配置（启用/停用/同步） | — | — | ✅ | — | — |
| 空态 | 每块各自兜底 | 双语义 | 双语义 | 双语义 | — |

---

## 附录：参考项目实读文件清单

### pang-qin / chaoxing-toolkit（`tiku\frontend`）

- `index.html`
- `src\App.vue`、`src\main.js`、`src\router\index.js`、`src\api\index.js`
- `src\styles\theme.css`（设计 token 与全部组件样式）
- `src\views\Layout.vue`、`src\views\Login.vue`、`src\views\Questions.vue`、`src\views\Pending.vue`
- `src\components\QuestionCard.vue`、`src\components\QuestionForm.vue`、`src\components\PendingCard.vue`、`src\components\ImportModal.vue`

### liixnglinb / Superstar-checkin

- `src\server\console-ui.ts`（2848 行，页面结构与全部样式段）
- `src\server\voyra-ui.ts`（13285 B，浅色/深色设计 token 全集）
- `src\server\components.ts`（286 行，全部渲染函数：`renderStatCard` / `renderStatusPill` / `renderTrendSvg` / `renderRecentRows` / `renderCourseRow` / `renderAccountRow`）
- 目录清单核对：`electron\main.js`、`docs\ARCHITECTURE.md`、`tests\timetable-ui.test.js` 等（仅确认结构，未深读）

### vibe-GIF / chaoxing

- `ui.py`（193 行，全量）
- `main.py`（一级/二级菜单、题库管理菜单、打印片段）
- `README.md`（含命令行菜单截图）
- 目录清单核对：`api\`（`answer.py`、`base.py`、`decode.py` 等）、`resource\font_map_table.json`（仅确认存在）

### CourseArk 现状（`D:\CODE\AutoChaoxingCLI\AutoCxUI\frontend\src`，只读）

- `App.vue`（导航 7 项基线、shell 骨架、topbar、page-heading、页面映射）
- `components\OverviewDashboard.vue`、`components\AccountWorkspace.vue`（`App.vue:207-230` 的 `tasks` 页在「按账号展开 / 任务记录与历史」两个二级 tab 下分别挂 `AccountWorkspace` 与 `TaskList`）
- `components\TaskList.vue`、`components\CompletedView.vue`、`components\AccountsView.vue`、`components\BankView.vue`
- `components\NoticeBar.vue`、`components\ProblemsView.vue`（基线版本，调研期间被并行删除）、`components\ProgressWindow.vue`、`components\SettingsView.vue`
- `style.css`（设计 token 段 `:5-61`、`.sidebar` `:481`、`.topbar` `:616`、`.page-content` `:657`、`.metrics` `:679`、`.accounts-grid` `:1049`、`.workspace-account` `:2003`、`.account-workspaces` `:1997-2014`、`.compact` `:2356-2399`、`.execution-grid` `:2543`、`.progress-window` `:4005`）

> 本次调研**未修改**上述任何文件。本文件是唯一产出。
