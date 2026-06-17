@echo off
chcp 65001 >nul
title APK签名替换工具 - 便携版打包

echo ==========================================
echo APK 签名替换工具 - 便携版打包脚本
echo ==========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [✗] 未找到 Python，请先安装 Python 3.8+
    echo     下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [✓] Python 已安装

REM 检查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [+] 正在安装 PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [✗] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo [✓] PyInstaller 已就绪
echo.

REM 执行便携包构建
echo [+] 开始构建便携包...
echo.

python build_portable.py

if errorlevel 1 (
    echo.
    echo [✗] 构建失败
    pause
    exit /b 1
)

echo.
echo ==========================================
echo [✓] 构建完成！
echo ==========================================
echo.

pause
