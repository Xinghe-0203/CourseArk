# 课舟 CourseArk

> 超星学习通多账号本机学习工作台

课舟集中管理多个学习通账号的课程和学习任务。网页端与 Windows 桌面端共用本机 FastAPI 服务；独立 Worker 执行任务，并在工作台展示进度、近期结果和需要处理的问题。

## 功能

- 多账号课程工作台：查看账号状态、课程、执行中的任务和最近结果。
- 课程任务点：处理章节内的视频、音频、阅读、文档、图书、测验，以及平台已有的投票和讨论任务点。
- 独立作业：单独创建并处理课程“作业”页中待处理且未过期的作业。
- 任务控制：按账号或跨账号暂停、继续、停止；查看任务进度、历史和问题通知。
- 本地题库与可选 AI 答题接口；题目、选项和字体识别均经过校验，未确认的结果会保留为待处理状态。
- 诊断日志和站内通知便于定位问题；默认不启用外部推送。

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

- `CourseArk-2.0.0-Setup.exe`：Windows x64 安装版。
- `CourseArk-2.0.0-Portable.exe`：Windows x64 便携版。

桌面版内置 Python 运行时，不要求最终用户安装 Python 或 Node.js。关闭应用时会停止本机服务和 Worker。为兼容现有安装，桌面数据目录继续使用 `%APPDATA%\AutoCxWebUI`；安装包不包含账号、配置、题库或任务数据库。

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
- 账号、Cookie、配置、题库、任务数据库和日志均为本机运行数据，不应提交到 GitHub。
- `data/`、`cli_copy/config.yml`、本地密钥和构建目录已加入 Git 忽略规则。
- 服务仅绑定 `127.0.0.1`；桌面窗口通过本机服务访问界面。

## 架构

```text
Vue 3 / TypeScript ── HTTP / SSE ── FastAPI
                                      ├─ SQLite：账号设置、任务、事件、课程缓存、题库
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
python -m pytest tests -q
python -m pytest cli_copy/tests -q
python tools/smoke_test.py --mock
python tools/vue_check.py
python tools/ui_check.py --serve --port 8899
```

浏览器检查使用临时数据并停用调度器，不连接学习通，也不执行真实学习任务。

## 来源与致谢

- `cli_copy/` 包含同一维护者的 **AutoChaoxingCLI** 源码副本及本项目的 WebUI 适配。该源码目录目前没有公开远端地址；源项目 README 声明采用 MIT 许可，CourseArk 在仓库根目录保留 MIT `LICENSE`。
- `cli_copy/resource/font_ref_cx.bin` 来自 [OCS CDN](https://cdn.ocsjs.com/resources/font/font_ref_cx.bin)；字体参考数据与协议参考 [ocsjs 的字体解码实现](https://github.com/ocsjs/ocsjs/tree/main/packages/scripts/src/utils/font-decrypt)。OCS MIT 许可保存在 [`cli_copy/resource/OCS-MIT-LICENSE.txt`](cli_copy/resource/OCS-MIT-LICENSE.txt)，来源说明见 [`font-reference-NOTICE.md`](cli_copy/resource/font-reference-NOTICE.md)。
- 字体匹配参考特征以 [Adobe Source Han Sans（思源黑体）](https://github.com/adobe-fonts/source-han-sans) 字形为基础；仅包含匹配特征数据，不捆绑完整字体。SIL OFL 1.1 许可保存在 [`cli_copy/resource/SourceHanSans-OFL-LICENSE.txt`](cli_copy/resource/SourceHanSans-OFL-LICENSE.txt)。
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) 与 [sweetcornna/chaoxing-fanya](https://github.com/sweetcornna/chaoxing-fanya) 是播放确认、题目解析和字体协议的只读技术参考，不作为随项目分发的源码副本。
- Vue、FastAPI、Electron 及 Python 依赖由 `frontend/package.json`、`desktop/package.json` 和 `requirements.txt` 管理；各依赖遵循其上游许可。

## 许可证

项目许可见仓库根目录 [`LICENSE`](LICENSE)。第三方数据和代码的许可与来源说明保留在相应资源目录中。
