"""
AutoChaoxingCLI - 主程序入口

超星学习通自动学习CLI工具
"""

import os
import sys

# Windows下设置UTF-8编码
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from loguru import logger

from core.config import Config
from core.paths import get_user_data_path
from core.request_client import init_client
from functions.tui import TUI
from core.logging_utils import patch_log, visible_log


def setup_logging(config: dict):
    """配置日志"""
    log_level = config.get("advanced", {}).get("log_level", "INFO")
    log_file = config.get("advanced", {}).get("log_file", "logs/autochaoxing.log")

    # 解析日志文件路径（兼容 PyInstaller 打包）
    if log_file and not os.path.isabs(log_file):
        log_file = get_user_data_path(log_file)

    # 移除默认处理器
    logger.remove()
    logger.configure(patcher=patch_log)

    # 控制台输出
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>",
        level=log_level,
        filter=lambda record: record["extra"].get("name") != "debug" and visible_log(record),
        diagnose=False,
    )

    # 文件输出
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            encoding="utf-8", filter=visible_log, diagnose=False,
        )


def main(argv=None):
    """加载配置与本地账号库，再进入多账号菜单。"""
    import argparse
    from core.account_store import AccountStore
    from functions.cli_app import CLIApplication

    parser = argparse.ArgumentParser(description="AutoChaoxingCLI 多账号学习工具")
    parser.add_argument("-c", "--config", default="config.yml", help="配置文件路径")
    parser.add_argument("--accounts-file", help="独立 CLI 账号库路径")
    parser.add_argument("--list-accounts", action="store_true", help="查看已保存账号，不连接平台")
    args = parser.parse_args(argv)
    config_path = args.config if os.path.isabs(args.config) else get_user_data_path(args.config)
    config = Config.load(config_path)
    setup_logging(config)
    init_client(config)
    try:
        store_path = args.accounts_file or Config.get("accounts.storage_path", "data/cli_accounts.json")
        if not os.path.isabs(store_path):
            store_path = get_user_data_path(store_path)
        store = AccountStore(store_path)
        if args.list_accounts:
            TUI().show_accounts(store.list_accounts(), store.selected_ids)
            return 0
        store.import_legacy(config.get("account", {}))
        return CLIApplication(store).run()
    except (KeyboardInterrupt, EOFError):
        logger.info("用户退出")
        return 0
    except Exception as exc:
        logger.error(f"程序未能完成操作：{exc}")
        return 1


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
