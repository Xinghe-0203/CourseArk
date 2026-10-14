"""
AutoChaoxingCLI - 一键打包脚本

使用 PyInstaller 将项目打包为 Windows exe 可执行文件。
打包后 font_map_table.json 内嵌到 exe 中，
config.yml / data/ / logs/ 作为外部文件在 exe 同级目录。
"""

import subprocess
import sys
import shutil
import os

import yaml

from core.config import Config


def build(onefile: bool = True):
    """执行打包"""
    # 仅在缺失时安装 PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 只清理中间构建目录；dist 中可能存在用户配置、数据和日志，禁止整目录删除
    shutil.rmtree("build", ignore_errors=True)
    os.makedirs("dist", exist_ok=True)

    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "AutoChaoxingCLI",
        "--add-data", f"resource{os.pathsep}resource",
        "--hidden-import", "lxml._elementpath",
        "--hidden-import", "pyDes",
        "--hidden-import", "fontTools.ttLib",
        "--hidden-import", "core.paths",
        "--console",
        "--noconfirm",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append("main.py")

    print(f"正在打包 ({'单文件' if onefile else '目录'} 模式)...")
    subprocess.check_call(cmd)

    # 生成无本机运行数据的配置模板
    dist_dir = "dist"
    with open(os.path.join(dist_dir, "config.yml.example"), "w", encoding="utf-8") as f:
        yaml.safe_dump(Config._default_config(), f, allow_unicode=True, sort_keys=False)

    print("\n" + "=" * 50)
    print("打包完成！输出在 dist/ 目录")
    print("=" * 50)
    print("\n使用方法：")
    print("1. 将 dist/config.yml.example 复制为 dist/config.yml")
    print("2. 编辑 config.yml 填写账号和 LLM 配置")
    print("3. 运行 AutoChaoxingCLI.exe")
    print("\n首次运行会自动创建 data/ 和 logs/ 目录")


if __name__ == "__main__":
    use_onefile = "--dir" not in sys.argv
    build(onefile=use_onefile)
