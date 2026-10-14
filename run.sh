#!/bin/bash
# AutoChaoxingCLI 启动脚本
# venv 位于 home 目录 (避免 FAT32 不支持 symlink 的问题)

VENV_PATH="$HOME/.venvs/autochaoxingcli"
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# 检查 venv 是否存在
if [ ! -d "$VENV_PATH" ]; then
    echo "虚拟环境不存在，正在创建..."
    if command -v uv >/dev/null 2>&1; then
        uv venv "$VENV_PATH"
    else
        "$PYTHON_CMD" -m venv "$VENV_PATH"
    fi
fi

# 激活 venv 并运行
if [ -f "$VENV_PATH/bin/activate" ]; then
    source "$VENV_PATH/bin/activate"
else
    source "$VENV_PATH/Scripts/activate"
fi

REQUIREMENTS_MARKER="$VENV_PATH/.requirements-installed"
if [ ! -f "$REQUIREMENTS_MARKER" ] || [ "$PROJECT_DIR/requirements.txt" -nt "$REQUIREMENTS_MARKER" ]; then
    echo "正在同步依赖..."
    if command -v uv >/dev/null 2>&1; then
        uv pip install -r "$PROJECT_DIR/requirements.txt"
    else
        python -m pip install -r "$PROJECT_DIR/requirements.txt"
    fi
    touch "$REQUIREMENTS_MARKER"
fi

cd "$PROJECT_DIR"
python main.py "$@"
