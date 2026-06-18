@echo off
title APK Resigner - Portable Build

echo ==========================================
echo APK Resigner - Portable Build Script
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Please install Python 3.8+
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found

REM Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [FAIL] PyInstaller installation failed
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller ready
echo.

REM Run build
echo [INFO] Starting build...
echo.

python build_portable.py

if errorlevel 1 (
    echo.
    echo [FAIL] Build failed
    pause
    exit /b 1
)

echo.
echo ==========================================
echo [OK] Build complete!
echo ==========================================
echo.

pause
