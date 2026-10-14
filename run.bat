@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "PROJECT_DIR=%~dp0"
if defined AUTO_CHAOXING_VENV (
    set "VENV_PATH=%AUTO_CHAOXING_VENV%"
) else (
    set "VENV_PATH=%USERPROFILE%\.venvs\autochaoxingcli"
)
set "VENV_PYTHON=%VENV_PATH%\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo 虚拟环境不存在，正在创建...
    where uv >nul 2>nul
    if not errorlevel 1 (
        uv venv "%VENV_PATH%"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            py -3 -m venv "%VENV_PATH%"
        ) else (
            where python >nul 2>nul
            if errorlevel 1 (
                echo [错误] 未找到 Python。请先安装 Python 3.10 或更高版本。
                exit /b 1
            )
            python -m venv "%VENV_PATH%"
        )
    )
    if errorlevel 1 goto :venv_error
)

if not exist "%VENV_PYTHON%" goto :venv_error

if not defined AUTO_CHAOXING_SKIP_INSTALL (
    setlocal EnableDelayedExpansion
    set "REQ_MARKER=%VENV_PATH%\.requirements-installed.txt"
    set "NEEDS_INSTALL=1"
    if exist "!REQ_MARKER!" (
        fc /b "%PROJECT_DIR%requirements.txt" "!REQ_MARKER!" >nul 2>nul
        if not errorlevel 1 set "NEEDS_INSTALL=0"
    )

    if "!NEEDS_INSTALL!"=="1" (
        echo 正在同步依赖...
        where uv >nul 2>nul
        if not errorlevel 1 (
            uv pip install --python "%VENV_PYTHON%" -r "%PROJECT_DIR%requirements.txt"
        ) else (
            "%VENV_PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt"
        )
        if errorlevel 1 goto :dependency_error
        copy /y "%PROJECT_DIR%requirements.txt" "!REQ_MARKER!" >nul
    )
    endlocal
)

pushd "%PROJECT_DIR%"
"%VENV_PYTHON%" main.py %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:venv_error
echo [错误] 虚拟环境创建失败: %VENV_PATH%
exit /b 1

:dependency_error
echo [错误] 依赖安装失败，请检查网络或 requirements.txt。
exit /b 1
