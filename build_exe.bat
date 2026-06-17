@echo off
title APK Resigner - Build EXE

echo ==========================================
echo APK Resigner - EXE Build Script
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)
echo [OK] Python installed

REM Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller installation failed
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller ready
echo.

REM Select mode
echo Select build mode:
echo   1. Single EXE (portable, recommended)
echo   2. Directory EXE (faster startup)
echo   3. Debug (with console window)
echo.
set /p choice="Enter option (1-3): "

if "%choice%"=="1" (
    set MODE=--onefile --windowed
    set NAME=APKResigner
) else if "%choice%"=="2" (
    set MODE=--windowed
    set NAME=APKResigner
) else if "%choice%"=="3" (
    set MODE=--onefile
    set NAME=APKResigner-Debug
) else (
    echo [ERROR] Invalid option
    pause
    exit /b 1
)

echo.
echo [INFO] Building: %NAME%
echo [INFO] Mode: %MODE%
echo.

python -m PyInstaller --noconfirm %MODE% --name "%NAME%" --clean apk_resigner_gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo.
echo ==========================================
echo [OK] Build successful!
echo ==========================================
echo.
echo Output:
echo   dist\%NAME%
echo.
echo Notes:
echo   - Requires apktool, zipalign, apksigner, keytool in PATH
echo   - First startup may be slow (single file extraction)
echo.

pause
