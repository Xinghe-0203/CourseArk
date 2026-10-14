# AutoChaoxingCLI

[项目主页](https://github.com/Xinghe-0203/CourseArk)

面向终端的超星学习通课程任务工具，提供交互式菜单、账号管理和任务进度显示。

## 功能概览

- 可管理多个账号、复用本地登录会话，并并行处理多个账号的任务。

| 菜单 | 功能 |
| --- | --- |
| 1 | 一键处理课程章节任务点，包括视频、音频、阅读、文档、图书、直播、测验/作业、投票和讨论等 |
| 2 | 处理章节任务点中的测验和作业 |
| 3 | 刷取视频时长 |
| 4 | 刷取课程学习次数 |
| 5 | 下载课程资源 |
| 6 | 选择或管理账号 |
| 7 | 处理课程“作业”页面中的独立作业 |

## 环境与启动

需要 Python 3.10 或更高版本。启动脚本会创建独立虚拟环境，并根据 `requirements.txt` 安装依赖；如已安装 `uv`，脚本会优先使用它。

**Windows**（在项目目录运行）：

```bat
run.bat
run.bat -c my_config.yml
```

**Linux / macOS**（在项目目录运行）：

```bash
bash run.sh
bash run.sh -c my_config.yml
```

也可以手动安装依赖后运行：

```bash
python -m pip install -r requirements.txt
python main.py
```

启动后按菜单提示管理账号、选择课程和功能。默认读取 `config.yml`；可使用 `-c` 指定其他配置文件。

## 配置与本地数据

复制默认配置为本地配置文件，再按需编辑：

```powershell
Copy-Item config.yml my_config.yml
```

Linux / macOS：

```bash
cp config.yml my_config.yml
```

`my_config.yml`、`config.local.yml` 和 `config.*.local.yml`（含临时副本）已加入 Git 忽略规则。其他自定义配置文件请放在仓库目录之外。需要使用 LLM 服务时，在本地文件中填写自己的 API Key；仓库默认配置中该字段为空：

```yaml
llm:
  api_key: "你的 API Key"
```

使用自定义配置启动：`run.bat -c my_config.yml`（Windows）或 `bash run.sh -c my_config.yml`（Linux / macOS）。

账号密码和登录 Cookie 以 JSON 明文保存在本地账号库（文件不加密），默认路径为 `data/cli_accounts.json`。请勿将其放在共享或云同步目录，也不要提交或分享。自定义账号库应放在仓库目录之外；仓库忽略文件名中包含 `accounts` 的 JSON 文件及其临时副本。

## 离线测试

```bash
python -m pytest tests -q
```

## 许可证

MIT License
