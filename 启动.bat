@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先用项目自带 venv，其次系统 Python
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

rem 检查依赖，缺则安装
%PYTHON% -c "import fitz, PIL" 2>nul
if errorlevel 1 (
    echo [启动器] 缺少依赖，正在安装...
    %PYTHON% -m pip install -r requirements.txt
)

rem 无参数时启动 GUI；带参数则透传给 CLI
%PYTHON% main.py %*
pause
