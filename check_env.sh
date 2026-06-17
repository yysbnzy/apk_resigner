#!/bin/bash
echo "=========================================="
echo "APK 签名替换工具 - 环境检查"
echo "=========================================="
echo ""

error_count=0

check_tool() {
    if command -v $1 &> /dev/null; then
        echo "  [✓] $1 - 已安装"
        if [ -n "$2" ]; then
            $2 2>/dev/null | head -1 | sed 's/^/      /'
        fi
    else
        echo "  [✗] $1 - 未安装！请添加到 PATH"
        ((error_count++))
    fi
}

echo "[检查必要工具...]"
echo ""

check_tool apktool "apktool --version"
check_tool zipalign ""
check_tool apksigner "apksigner version"
check_tool keytool ""
check_tool adb "adb version"

echo ""
echo "=========================================="
if [ $error_count -gt 0 ]; then
    echo "[警告] 发现 $error_count 个缺失工具"
    echo "请参考 README.md 安装缺失工具"
else
    echo "[✓] 所有工具已就绪！"
fi
echo "=========================================="
