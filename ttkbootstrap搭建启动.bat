@echo off
chcp 65001 >nul
title PDF 工具箱 启动器
cd /d "%~dp0"

echo ==========================================
echo            PDF 工具箱 - 启动中
echo ==========================================
echo.

:: ---------- 1. 检查 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 这台电脑没有安装 Python，或 Python 没加入 PATH。
    echo.
    echo 请到下面网址下载安装 Python 3.10 以上版本：
    echo     https://www.python.org/downloads/
    echo.
    echo ★ 安装时务必勾选 "Add Python to PATH" ！
    echo.
    pause
    exit /b 1
)

:: 检查版本 >= 3.8
python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [错误] Python 版本太旧（需要 3.8 以上）。
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo 当前版本：%%i
    echo 请到 https://www.python.org/downloads/ 升级。
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [1/3] Python 环境检查通过：%%i

:: ---------- 2. 创建虚拟环境（只需一次） ----------
if not exist ".venv\Scripts\python.exe" (
    echo [2/3] 首次运行：正在创建独立运行环境，请稍候……
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败，请截图本窗口全部内容反馈。
        pause
        exit /b 1
    )
    echo [2/3] 独立运行环境创建完成。
) else (
    echo [2/3] 独立运行环境已存在，跳过。
)

:: ---------- 3. 安装依赖（装过就自动跳过，很快） ----------
".venv\Scripts\python.exe" -c "import ttkbootstrap, PIL, fitz" >nul 2>nul
if errorlevel 1 (
    echo [3/3] 正在安装依赖（首次约 1~2 分钟，走国内镜像）……
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，多半是网络问题。换个网络再试，或截图本窗口反馈。
        pause
        exit /b 1
    )
    echo [3/3] 依赖安装完成。
) else (
    echo [3/3] 依赖已就绪。
)

echo.
echo 启动程序……（本窗口可以最小化，关闭本窗口 = 关闭程序）
".venv\Scripts\pythonw.exe" gui.py

:: 如果用 pythonw 启动失败（比如代码报错），回退用带控制台的 python 再试一次，方便看报错
if errorlevel 1 (
    echo.
    echo [提示] 程序异常退出了，下面重新以调试模式启动，报错信息请截图反馈：
    ".venv\Scripts\python.exe" gui.py
    pause
)
exit /b 0
