@echo off
chcp 65001 >nul
echo ==========================================
echo APK 签名替换工具 - 环境检查
echo ==========================================
echo.

echo [检查必要工具...]
echo.

set error_count=0

call :check_tool apktool "apktool --version"
call :check_tool zipalign "zipalign"
call :check_tool apksigner "apksigner version"
call :check_tool keytool "keytool -help"
call :check_tool adb "adb version"

echo.
echo ==========================================
if %error_count% GTR 0 (
    echo [警告] 发现 %error_count% 个缺失工具
    echo 请参考 README.md 安装缺失工具
) else (
    echo [✓] 所有工具已就绪！
)
echo ==========================================
pause
exit /b

:check_tool
where %1 >nul 2>&1
if %errorlevel% == 0 (
    echo   [✓] %1 - 已安装
) else (
    echo   [✗] %1 - 未安装！请添加到 PATH
    set /a error_count+=1
)
exit /b
