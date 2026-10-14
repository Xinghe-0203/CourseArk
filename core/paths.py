"""
AutoChaoxingCLI - 路径工具模块

统一处理 PyInstaller 打包后的路径解析。
- 内嵌资源（font_map_table.json）从 sys._MEIPASS 临时目录读取
- 用户数据（config.yml、数据库、日志）在 exe 同级目录
"""

import os
import sys


def get_base_dir() -> str:
    """获取程序根目录（兼容 PyInstaller 打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
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
