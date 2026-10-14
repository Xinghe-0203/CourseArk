"""
CourseArk 启动入口

本工具只在本机运行：监听地址限制为回环接口，
局域网内其它设备无法访问。

用法:
    python run.py                 # 使用配置中的端口
    python run.py --port 8848
    python run.py --host 127.0.0.1 --port 8848
    python run.py --open          # 启动后自动打开浏览器
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import paths, settings  # noqa: E402


def resolve_host(requested: str | None = None) -> str:
    """Return a configured loopback host; never bind the API to a network interface."""
    host = requested or settings.resolve("server.host", "127.0.0.1")
    return host if host in settings.LOOPBACK_HOSTS else "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="CourseArk 本机 Web 控制台")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取配置）")
    parser.add_argument("--host", default=None, help="监听回环地址（桌面版固定使用 127.0.0.1）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    paths.ensure_dirs()
    settings.ensure_initialized()

    import uvicorn
    from app.main import app

    # 即使配置保留了 ::1/localhost，Electron 桌面窗口也通过 IPv4 loopback 连接。
    host = resolve_host(args.host)
    port = int(args.port or settings.resolve("server.port", 8848))

    url_host = f"[{host}]" if ":" in host else host
    local_url = f"http://{url_host}:{port}"
    print("=" * 62)
    print("  CourseArk 本机控制台")
    print(f"  访问地址: {local_url}")
    print(f"  数据目录: {paths.DATA_DIR}")
    print(f"  源 CLI 目录（只读）: {paths.SOURCE_CLI_DIR}")
    print("  仅限本机访问：服务只监听回环地址，局域网设备无法连接")
    print("=" * 62)

    if args.open:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(local_url)).start()

    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port, log_level="info",
    ))
    app.state.uvicorn_server = server
    server.run()


if __name__ == "__main__":
    main()
