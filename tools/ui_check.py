"""在临时数据和停用调度器的服务中验收界面，不连接学习通。"""

import argparse
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))


def prepare():
    sandbox = tempfile.mkdtemp(prefix='autocx-ui-')
    os.environ['UI_SEED_DIR'] = sandbox
    os.environ.pop('UI_SEED_RESET', None)
    import ui_seed
    from app import paths
    paths.SOURCE_CONFIG = os.path.join(sandbox, 'no-source.yml')
    paths.SOURCE_QUESTION_BANK = os.path.join(sandbox, 'no-source.db')
    from app.task_manager import TaskManager
    # 演示任务仅落库，任何课程任务都不会启动 Worker。
    TaskManager.start = lambda self: None
    ui_seed.seed()
    from app import main
    main.db.upsert_notification(category='llm', title='AI 接口认证失败，请检查设置',
        detail='接口返回 HTTP 401，请检查 API Key 与接口地址。', level='error', dedupe_key='demo-auth')
    return main.create_app(), sandbox


def launch_browser(playwright):
    for channel in (None, 'msedge', 'chrome'):
        try:
            return playwright.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
        except Exception:
            continue
    raise RuntimeError('未找到可用于验收的 Chromium、Edge 或 Chrome')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', help='保留隔离预览服务')
    parser.add_argument('--port', type=int, default=8899)
    parser.add_argument('--output', default=str(ROOT / 'docs' / 'vue-validation'))
    args = parser.parse_args()
    app, sandbox = prepare()
    import uvicorn
    if args.serve:
        print(f'隔离预览: http://127.0.0.1:{args.port}，数据位于 {sandbox}，任务不会执行')
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
        return
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, '验收服务器启动超时'
        from vue_check import check
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        assert check(f'http://127.0.0.1:{port}', output), 'Vue 浏览器验收未通过'
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == '__main__':
    main()
