@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================
echo   PDF 工具箱 - 安装程序
echo ====================================

:: 1. 找 Python
where python >nul 2>nul
if errorlevel 1 (
    echo 没找到 Python，正在打开下载页...
    start https://www.python.org/downloads/
    echo 请安装时勾选 "Add Python to PATH"，装完重新运行本脚本
    pause
    exit /b 1
)

:: 2. 检查版本 >= 3.9
python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)"
if errorlevel 1 (
    echo Python 版本太低，需要 3.9 以上
    pause
    exit /b 1
)

:: 3. 建虚拟环境（不污染系统 Python）
if not exist ".venv" (
    echo 正在创建虚拟环境...
    python -m venv .venv
)

:: 4. 装依赖（用清华源，国内快）
echo 正在安装依赖，请稍候...
.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install -r deps.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 5. 生成桌面快捷方式
echo 正在创建桌面快捷方式...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\PDF工具箱.lnk'); $sc.TargetPath = '%~dp0run.bat'; $sc.WorkingDirectory = '%~dp0'; $sc.Save()"

echo.
echo 安装完成！双击桌面的"PDF工具箱"即可使用。
pause