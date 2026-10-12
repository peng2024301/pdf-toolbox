@echo off
chcp 65001 >nul
cd /d %~dp0

pyinstaller --clean --noconfirm PDF工具箱.spec
if errorlevel 1 (
    echo.
    echo ===== 打包失败！请看上面的报错信息 =====
    pause
    exit /b 1
)
echo.
echo ===== 打包成功：dist\PDF工具箱\ =====
pause
