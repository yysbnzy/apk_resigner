@echo off
chcp 65001 >nul
title APK签名替换工具 - EXE打包

echo ==========================================
echo APK 签名替换工具 - EXE 打包脚本
echo ==========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [✗] 未找到 Python，请先安装 Python 3.8+
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

REM 选择模式
echo 选择打包模式:
echo   1. 单文件 EXE (推荐，便携)
echo   2. 目录式 EXE (启动快)
echo   3. 调试版 (带控制台窗口)
echo.
set /p choice="请输入选项 (1-3): "

if "%choice%"=="1" (
    set MODE=--onefile --windowed
    set NAME=APK签名替换工具
) else if "%choice%"=="2" (
    set MODE=--windowed
    set NAME=APK签名替换工具
) else if "%choice%"=="3" (
    set MODE=--onefile
    set NAME=APK签名替换工具-Debug
) else (
    echo [✗] 无效选项
    pause
    exit /b 1
)

echo.
echo [+] 开始打包: %NAME%
echo [+] 模式: %MODE%
echo.

python -m PyInstaller --noconfirm %MODE% --name "%NAME%" --clean apk_resigner_gui.py

if errorlevel 1 (
    echo.
    echo [✗] 打包失败
    pause
    exit /b 1
)

echo.
echo ==========================================
echo [✓] 打包成功！
echo ==========================================
echo.
echo 输出位置:
echo   dist\%NAME%
echo.
echo 提示:
echo   - 运行需要 apktool, zipalign, apksigner, keytool 在 PATH 中
echo   - 首次启动可能较慢（单文件模式需要解压）
echo.

pause
