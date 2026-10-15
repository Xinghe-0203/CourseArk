"""BAT 启动助手：独立环境、构建检查、端口识别，不终止其他服务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def configured_port(root=ROOT):
    database = root / 'data' / 'webui.db'
    if database.exists():
        try:
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
                row = conn.execute('SELECT value FROM app_settings WHERE key=?', ('global',)).fetchone()
            port = int(json.loads(row[0]).get('server', {}).get('port', 8848)) if row else 8848
            return port if 1 <= port <= 65535 else 8848
        except (sqlite3.Error, ValueError, TypeError):
            pass
    return 8848


def existing_service(port, root=ROOT):
    with socket.socket() as sock:
        sock.settimeout(.5)
        if sock.connect_ex(('127.0.0.1', port)):
            return 'free'
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
            health = json.load(response)
        if health.get('ok') is True and Path(health.get('data_dir', '')).resolve() == (root / 'data').resolve():
            return 'ours'
    except (OSError, ValueError):
        pass
    return 'occupied'


def frontend_stale(root=ROOT):
    built = root / 'webui_static' / 'vue' / 'index.html'
    if not built.exists():
        return True
    sources = list((root / 'frontend' / 'src').rglob('*')) + [root / 'frontend' / p for p in ('index.html', 'package.json', 'package-lock.json', 'vite.config.ts')]
    return any(p.is_file() and p.stat().st_mtime > built.stat().st_mtime for p in sources)


def run(command, cwd=ROOT):
    subprocess.run(command, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description='CourseArk 快捷启动')
    parser.add_argument('--port', type=int)
    parser.add_argument('--check', action='store_true', help='仅检查，不安装或启动')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或更新版本')
    port = args.port or configured_port()
    if not 1 <= port <= 65535:
        raise RuntimeError('端口必须在 1—65535 之间')
    service = existing_service(port)
    if args.check:
        print(json.dumps({'port': port, 'service': service, 'frontend_stale': frontend_stale()}, ensure_ascii=False))
        return
    if service == 'ours':
        print('课舟已经在运行，正在打开浏览器。')
        webbrowser.open(f'http://127.0.0.1:{port}')
        return
    if service == 'occupied':
        raise RuntimeError(f'端口 {port} 已被其他服务占用，可运行 start.bat --port 8850 使用另一端口')
    environment = Path.home() / '.venvs' / 'autocxwebui'
    interpreter = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    uv = shutil.which('uv')
    if not interpreter.exists():
        print('正在为课舟准备独立运行环境…')
        run([uv, 'venv', str(environment), '--python', sys.executable] if uv else [sys.executable, '-m', 'venv', str(environment)])
    digest = hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()
    marker = environment / 'autocx-requirements.sha256'
    if not marker.exists() or marker.read_text().strip() != digest:
        print('正在安装或更新运行依赖，首次启动可能需要几分钟…')
        run([uv, 'pip', 'install', '--python', str(interpreter), '-r', str(ROOT / 'requirements.txt')] if uv else [str(interpreter), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')])
        marker.write_text(digest)
    if frontend_stale():
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise RuntimeError('前端源码有更新，需要安装 Node.js 后再次启动，以生成最新页面')
        print('正在生成最新的网页界面…')
        run([npm, 'ci', '--no-fund', '--no-audit'], ROOT / 'frontend')
        run([npm, 'run', 'build'], ROOT / 'frontend')
    print(f'启动课舟：http://127.0.0.1:{port}；关闭此窗口会停止服务。')
    run([str(interpreter), str(ROOT / 'run.py'), '--port', str(port), '--open'])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        sys.exit(1)
