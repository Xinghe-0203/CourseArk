"""
AutoChaoxingCLI - 路径工具模块

统一处理 PyInstaller 打包后的路径解析。
- 内嵌资源（font_map_table.json）从 sys._MEIPASS 临时目录读取
- 用户数据（config.yml、数据库、日志）在 exe 同级目录

WebUI 适配：当设置了 AUTOCXWEBUI_DATA_DIR 环境变量时，
用户数据一律落到该目录，保证副本目录只读、不产生运行时文件。
"""

import os
import sys

# WebUI 数据目录环境变量（由 Worker 进程注入）
DATA_DIR_ENV = "AUTOCXWEBUI_DATA_DIR"


def get_base_dir() -> str:
    """获取程序根目录（兼容 PyInstaller 打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        # Worker 场景：用户数据统一写到 WebUI 的 data 目录
        return override
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """获取内嵌资源文件路径（打包后从 _MEIPASS 临时目录读取）"""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def get_user_data_path(relative_path: str) -> str:
    """获取用户数据文件路径（配置、数据库等，在 exe 同级目录）"""
    return os.path.join(get_base_dir(), relative_path)
