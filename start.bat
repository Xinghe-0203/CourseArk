@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools\launcher.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo No Python,No Path
        pause
        exit /b 1
    )
    python tools\launcher.py %*
)
if errorlevel 1 (
    echo.
    echo ERROR!!!
    pause
    exit /b 1
)
endlocal
