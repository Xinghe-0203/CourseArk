# 课舟 CourseArk

> 超星学习通多账号本机学习工作台

课舟集中管理多个学习通账号的课程和学习任务。网页端与 Windows 桌面端共用本机 FastAPI 服务；独立 Worker 执行任务，并在工作台展示进度、近期结果和需要处理的问题。

## 功能

- 多账号课程工作台：查看账号状态、课程、执行中的任务和最近结果。
- 课程任务点：处理章节内的视频、音频、阅读、文档、图书、测验，以及平台已有的投票和讨论任务点。
  任务点进度来自平台「已完成任务点 N/M」，每次打开程序会自动同步各账号课程；平台显示还有
  未完成任务点、但页面里识别不到具体任务时，任务会明确失败并写清原因，不再静默显示「已完成」。
- 中断续跑：中断、停止或失败的任务可在任务记录里点「继续执行」，按原参数重新排队（已完成的部分
  会按平台状态自动跳过，不会重复提交）。
- 独立作业：单独创建并处理课程“作业”页中待处理且未过期的作业；按作业页面里真实的
  `<form>` 回放提交（token、`totalQuestionNum`、`answerwqbid` 等字段与浏览器 `serialize()` 一致），
  提交前先调用平台的 `work/validate` 校验作业是否可提交。新建任务时可先「加载列表」，
  勾选要处理的作业（默认全选）。
- 独立考试（v2.2）：读取课程的考试列表（状态、考试窗口、限时），可勾选要作答的考试；
  进入考试页后用同一套 AI 作答链路逐题作答，并优先按页面真实表单回放交卷。
  「一页一题」的考试会被识别并安全中止（不会提交半份答案）。若平台要求在进入考试前完成
  人机校验（验证码）或输入考试码，程序会明确提示并**不会启动考试、也不会尝试绕过**；
  可在考试列表点「在浏览器中打开」手动完成验证。
  **v2.2.2 起推荐「粘贴答题页地址」**：在浏览器里进入考试后，把地址栏里带 `enc=` 的答题页
  地址粘贴到新建考试任务里，程序即可逐题 AI 作答、自动下一题并交卷（真实考试验证可用）。
  说明见 [`docs/release-2.2.md`](docs/release-2.2.md)、
  [`docs/release-2.2.1.md`](docs/release-2.2.1.md)、
  [`docs/release-2.2.2.md`](docs/release-2.2.2.md)。
- AI 做题：只保留 AI 作答链路，逐题实时展示题干、选项、答案与来源（AI / 答题缓存 / 随机 / 未识别），
  答案先过题型校验（判断题归一为 true/false，选择题必须落在选项字母内）；无法可靠作答时按策略跳过。
  提示词会带上课程与作答内容（作业/考试名称）的上下文，并要求模型给出最可能答案而不是留空。
- 进度小窗：任务运行时右下角浮动小窗显示「正在做什么、已用时、预计剩余」，任务列表同步显示一行摘要。
- 答题缓存：AI 答对的题会存进本机 SQLite 缓存，下次遇到相同题目直接复用，不再重复调用 AI；
  缓存可在「答题缓存」页搜索、导入、导出、单条删除或一键清空。
- 任务控制：按账号或跨账号暂停、继续、停止；查看任务进度、历史和问题通知。
- 诊断日志和站内通知便于定位问题；默认不启用外部推送。

> v2.1 起**移除了在线题库**（enncy / icodef / datam 及其 token 配置），旧配置里的 `tiku` 组
> 与 `answer.fallback_to_tiku` 会在读取时自动丢弃，旧 `answer.mode: tiku` 归一化为 `ai`。
> 变更与根因说明见 [`docs/release-2.1.md`](docs/release-2.1.md)。

## 使用

### 网页版

Windows 双击 `start.bat`，或在项目目录执行：

```powershell
.\start.bat
.\start.bat --port 8850
.\start.bat --check
```

默认地址为 <http://127.0.0.1:8848>。需要 Python 3.10 或更新版本；启动器会在用户目录建立独立虚拟环境并准备依赖。服务仅监听本机回环地址。

也可手动运行：

```powershell
python -m pip install -r requirements.txt
python run.py
```

### Windows 桌面版

在 [GitHub Releases](https://github.com/Xinghe-0203/CourseArk/releases) 下载：

- `CourseArk-2.2.3-Setup.exe`：Windows x64 安装版。
- `CourseArk-2.2.3-Portable.exe`：Windows x64 便携版。

桌面版内置 Python 运行时，不要求最终用户安装 Python 或 Node.js。关闭应用时会停止本机服务和 Worker。为兼容现有安装，桌面数据目录继续使用 `%APPDATA%\AutoCxWebUI`；安装包不包含账号、配置、答题缓存或任务数据库。

### 独立作业失败怎么排查

作业页面的结构和提交参数会随平台更新而变化。遇到「提交失败」「题干识别成课程标题」「题目数明显偏少」
这类问题时，先用只读自检脚本核对解析与提交报文：

```powershell
python tools/check_work_page.py --list                              # 列出账号下的课程
python tools/check_work_page.py --course-id 244694077 --limit 1      # 检查一个待处理作业
python tools/check_work_page.py --course-id 244694077 --kind exam    # 只读列出可作答考试
python tools/check_work_page.py --exam-url "<答题页地址>"            # 只读核对粘进来的考试页
```

脚本只发送 GET 请求读取作业页面，**不会提交答案、不会调用 AI**，也不打印任何密钥。输出包含：

- 解析到的题目数、题型、题干与选项（以及无法识别的原因）；
- 提交 URL 与将要提交的全部表单字段（可与浏览器 `$("#submitForm").serialize()` 对照）；
- 提交前置校验结果（平台 `work/validate` 返回「可提交 / 需要验证码 / 状态异常」）。

考试默认只列出列表与将要请求的「开始考试」地址，**不会真的发起该请求**（发起即开始计时）；
只有显式加 `--fetch-start` 才会去读答题页，请自行确认后果。

### 课程任务点显示 0/0、或「没做完就显示已完成」怎么排查

- 任务点数量来自平台课程页的「已完成任务点 N/M」。每次启动应用会自动同步一次；也可在
  「账号与课程」点「同步」立即刷新。设置 → 运行与存储 里有「启动时自动同步课程」开关。
- 如果同步后仍是 0/0，说明该课程平台侧确实没有任务点（例如纯考试课），可以在该课程的
  学习通页面确认「已完成任务点」字样是否存在。
- 如果任务执行完立刻结束、但平台其实还有任务点：v2.2.1 起会直接报错
  「平台显示还有 N 个任务点未完成（a/b），但未能识别具体任务」，并写进诊断日志，
  不会再静默显示已完成。把该日志连同课程名反馈即可。

### 考试进不去 / 提示「需要安全验证」

学习通对进入考试做了平台侧校验，考试说明页里的 `captchaCheck` / `examCheck` 为 1 时，
必须先通过人机验证（或考试码）才会跳到答题页。这类校验与账号绑定，程序**不会**尝试绕过，
遇到时只会记录原因并安全中止（不启动考试计时、不提交任何答案）。

**推荐做法（v2.2.2，真实考试已验证）**：

1. 在浏览器里打开该考试，完成平台验证并进入答题页；
2. 复制地址栏里的完整地址（形如
   `https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?...&enc=...`，
   必须带 `reVersionTestStartNew` 与 `enc` 参数）；
3. 在 CourseArk 新建「独立考试」任务，把地址粘贴到「考试答题页地址（推荐）」后执行：
   程序逐题 AI 作答、保存、自动进入下一题，最后一题后交卷；任务详情「AI 做题」可见每题答案。

地址里的 `enc` 有时效，过期后重新进入考试再复制一次即可。若提示「答题页没有前进」，
刷新考试页并重新复制地址。

仍按考试列表处理（不粘贴地址）时：可以在考试列表点「在浏览器中打开」手动完成验证，
验证后重新执行考试任务，程序会先只读查询验证状态，通过才继续进入考试。
若只想核对解析结果，可用
`python tools/check_work_page.py --exam-url "<答题页地址>"`（只读，不提交答案），
或 `python tools/check_work_page.py --kind exam --course-id <课程ID>`（只读，不请求开始考试地址）。

任务执行过程中的逐题记录在任务详情「AI 做题」页签，逐题显示题干、选项、答案来源与失败原因。

### 考试显示「已完成」但看不到逐题明细

平台在**交卷后不再提供逐题回顾**，所以已交卷的考试本来就没有逐题记录可展示。
v2.2.3 起不再只显示一个空洞的「已完成」：

- 任务详情的「AI 做题」页签会显示一条说明（`answers_note`），例如
  「考试已交卷，但平台在考后不提供逐题回顾，本场考试没有可展示的逐题明细。」
- 「已完成」页面每一行都有「结果说明」（`outcome.reason`）写明原因；
  若任务真的失败，这里显示的是失败原因原文（例如平台安全验证不通过）。
- 若该场考试是程序逐题作答完成的（v2.2.2 的粘贴地址流程），逐题明细会正常出现。

历史任务同样适用：旧版本完成、没有留下明细的任务也会显示这条说明，不需要迁移数据。

### 「上次任务未完成」的黄色提示怎么不再提醒

黄色续跑提示上新增「不再提醒」：点击后该任务被记入设置里的 `ui.dismissed_resume_tasks`，
之后不再出现。这个开关**只针对被点过的那几条任务**——出现新的中断任务仍会照常提醒，
避免把真正的新问题一起静音。想恢复提醒可在「偏好设置」里查看并调整该列表。

### 从源码构建桌面版

构建环境需要 Windows x64、Node.js 22.12 或更新版本、CPython 3.13 x64 和网络连接。首次构建会下载 Electron、Python 运行时及依赖。

```powershell
npm --prefix frontend ci
npm --prefix desktop ci
npm --prefix desktop run dev
npm --prefix desktop run dist:win
npm --prefix desktop run smoke:runtime
npm --prefix desktop run smoke:packaged
```

`dist:win` 在 `desktop/dist/` 生成安装版和便携版。若构建机有多个 Python 版本，可通过 `AUTOCXWEBUI_BUILD_PYTHON` 指定 CPython 3.13 x64 的 `python.exe`；开发模式可通过 `AUTOCXWEBUI_PYTHON` 指定 Python。

## 数据与隐私

- 网页版运行数据保存在项目的 `data/` 目录；桌面版保存在当前 Windows 用户的 `%APPDATA%\AutoCxWebUI`。
- 账号、Cookie、配置、答题缓存、任务数据库和日志均为本机运行数据，不应提交到 GitHub。
- 作业页面内容只在本机解析，不会落盘保存；自检脚本也不写入任何页面内容。
- `data/`、`cli_copy/config.yml`、本地密钥和构建目录已加入 Git 忽略规则。
- 服务仅绑定 `127.0.0.1`；桌面窗口通过本机服务访问界面。
- 写操作校验请求来源：跨站网页对本机接口的调用会被拒绝。

## 架构

```text
Vue 3 / TypeScript ── HTTP / SSE ── FastAPI
                                      ├─ SQLite：账号设置、任务、事件、课程缓存、答题缓存
                                      └─ Worker：课程任务、作业、同步和会话子进程

Electron ── 启动本机 Python/FastAPI ── 加载同一套 Vue 页面
```

更多结构说明见 [`docs/architecture.md`](docs/architecture.md)。

## 开发与测试

```powershell
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix desktop ci
npm --prefix desktop test
npm --prefix desktop run smoke:packaged
python -m pytest tests -q
python -m pytest cli_copy/tests -q
python tools/smoke_test.py --mock
python tools/vue_check.py
python tools/ui_check.py --serve --port 8899
```

`smoke:packaged` 会启动 `desktop/dist` 里的打包应用，需要先构建安装包（`npm --prefix desktop run dist:win`）。
若你在 Electron 相关的终端里运行它，先清掉 `ELECTRON_RUN_AS_NODE` 环境变量
（`Remove-Item Env:ELECTRON_RUN_AS_NODE`），否则打包应用会被当成纯 Node 进程启动并立刻退出，
烟测会失败但并不是产品问题。

浏览器检查使用临时数据并停用调度器，不连接学习通，也不执行真实学习任务。需要连接真实账号核对
作业解析时，使用上面的 `tools/check_work_page.py`（只读）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | 组件划分、作业/考试/同步链路、事件与前端结构 |
| [`docs/release-2.2.3.md`](docs/release-2.2.3.md) | 当前版本：「已完成」可解释 + 已完成专页 + 不再提醒 + 界面重做 |
| [`docs/release-2.2.2.md`](docs/release-2.2.2.md) | 独立考试「粘贴答题页地址」直连作答 |
| [`docs/release-2.2.1.md`](docs/release-2.2.1.md) | 任务点同步、中断续跑、考试风控识别 |
| [`docs/release-2.2.md`](docs/release-2.2.md) | 独立考试、作业/考试勾选、进度小窗、AI 提示词 v2 |
| [`docs/release-2.1.md`](docs/release-2.1.md) | 独立作业提交链路修复、删除在线题库、答题缓存 |
| [`docs/research-exam.md`](docs/research-exam.md) | 考试协议调研（手机端 / PC 端端点、逐题提交、风控） |
| [`docs/research-github.md`](docs/research-github.md) | 同类开源项目调研与作业协议结论 |

历史版本的实施方案（`next-version-*.md`）已在 v2.2.2 清理时删除，结论全部并入上面的发布说明。

## 来源与致谢

- `cli_copy/` 包含同一维护者的 **AutoChaoxingCLI** 源码副本及本项目的 WebUI 适配。该源码目录目前没有公开远端地址；源项目 README 声明采用 MIT 许可，CourseArk 在仓库根目录保留 MIT `LICENSE`。
- `cli_copy/resource/font_ref_cx.bin` 来自 [OCS CDN](https://cdn.ocsjs.com/resources/font/font_ref_cx.bin)；字体参考数据与协议参考 [ocsjs 的字体解码实现](https://github.com/ocsjs/ocsjs/tree/main/packages/scripts/src/utils/font-decrypt)。OCS MIT 许可保存在 [`cli_copy/resource/OCS-MIT-LICENSE.txt`](cli_copy/resource/OCS-MIT-LICENSE.txt)，来源说明见 [`font-reference-NOTICE.md`](cli_copy/resource/font-reference-NOTICE.md)。
- 字体匹配参考特征以 [Adobe Source Han Sans（思源黑体）](https://github.com/adobe-fonts/source-han-sans) 字形为基础；仅包含匹配特征数据，不捆绑完整字体。SIL OFL 1.1 许可保存在 [`cli_copy/resource/SourceHanSans-OFL-LICENSE.txt`](cli_copy/resource/SourceHanSans-OFL-LICENSE.txt)。
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) 与 [sweetcornna/chaoxing-fanya](https://github.com/sweetcornna/chaoxing-fanya) 是播放确认、题目解析和字体协议的只读技术参考，不作为随项目分发的源码副本。
- Vue、FastAPI、Electron 及 Python 依赖由 `frontend/package.json`、`desktop/package.json` 和 `requirements.txt` 管理；各依赖遵循其上游许可。

## 许可证

项目许可见仓库根目录 [`LICENSE`](LICENSE)。第三方数据和代码的许可与来源说明保留在相应资源目录中。
