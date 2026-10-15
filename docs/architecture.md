# 架构概览

CourseArk 由网页前端、本机 API 服务和独立 Worker 组成。网页端与 Electron 桌面端共用 Vue 页面和 FastAPI 后端；桌面端负责启动随包 Python 服务，并通过回环地址加载本机页面。

```text
Vue 3 / TypeScript ── HTTP + SSE ── FastAPI
                                      ├─ SQLite：设置、账号、任务、课程缓存、事件和题库
                                      ├─ Worker：任务执行及课程/会话同步
                                      └─ 控制状态：运行、暂停和停止

Electron ── Python runtime ── FastAPI ── Vue 页面
```

## 组件

- `frontend/`：Vue 组件、类型、请求和状态管理。
- `webui_static/vue/`：由前端生产构建生成，随服务提供。
- `app/`：FastAPI 路由、持久化、任务调度、会话、课程同步和通知。
- `worker/`：任务、同步与会话子进程入口。
- `cli_copy/`：复用的 AutoChaoxingCLI 业务代码及 WebUI 适配；资源来源与许可见其 `resource/`。
- `desktop/`：Electron 桌面壳、Windows 构建和打包冒烟检查。

每项任务按账号、课程和模块隔离执行；数据库保存任务状态、事件、设置和题库。Worker 通过本机数据目录与服务共享运行状态。桌面版的 FastAPI 仅监听 `127.0.0.1`。

## 本机数据

网页版默认在项目 `data/` 中保存账号、配置、SQLite 数据库、日志和任务数据。桌面版使用 `%APPDATA%\AutoCxWebUI`，该目录名为兼容既有安装而保留。运行数据不随源码或安装包分发。

服务仅监听 `127.0.0.1`，并校验写请求来源；跨站网页无法调用本机接口。
