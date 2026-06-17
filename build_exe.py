#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 PyInstaller 打包 APK Resigner 为单文件 EXE
包含所有 _tools/ 依赖
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 配置
APP_NAME = "APK签名替换工具"
MAIN_SCRIPT = "apk_resigner_gui.py"
ICON_FILE = None  # 如果有图标文件，请指定路径


def check_pyinstaller():
    """检查 PyInstaller 是否安装"""
    if shutil.which("pyinstaller"):
        return "pyinstaller"

    # 尝试通过 Python 调用
    result = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                          capture_output=True, text=True)
    if result.returncode == 0:
        return f"{sys.executable} -m PyInstaller"

    print("[✗] PyInstaller 未安装")
    print("    请运行: pip install pyinstaller")
    return None


def build():
    """执行打包"""
    print("="*50)
    print("APK Resigner - PyInstaller 打包")
    print("="*50)

    # 检查 PyInstaller
    pyinst = check_pyinstaller()
    if not pyinst:
        return 1

    print(f"[+] PyInstaller: {pyinst}")

    # 检查主脚本
    if not Path(MAIN_SCRIPT).exists():
        print(f"[✗] 未找到 {MAIN_SCRIPT}")
        return 1

    # 检查 _tools 目录（可选，纯 Python 模式不需要）
    tools_dir = Path("_tools")
    if tools_dir.exists() and any(tools_dir.iterdir()):
        print("[+] _tools/ 目录已找到，将打包内置工具")
        add_data = f"_tools{os.pathsep}_tools"
    else:
        print("[!] _tools/ 目录为空，将使用纯 Python 模式（无需外部工具）")
        add_data = None

    # 清理旧构建
    for d in ["build", "dist"]:
        if Path(d).exists():
            print(f"[*] 清理 {d}/")
            shutil.rmtree(d)

    # 构建参数
    cmd = pyinst.split() if " " in pyinst else [pyinst]
    cmd += [
        "--onefile",           # 单文件
        "--windowed",          # GUI 模式（不显示控制台）
        "--name", APP_NAME,
        "--clean",             # 清理缓存
        "--noconfirm",         # 不确认覆盖
    ]

    # 隐藏导入（tkinter 相关 + cryptography 相关）
    cmd += [
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.filedialog",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.scrolledtext",
        "--hidden-import", "pure_python_sign",
        "--hidden-import", "cryptography",
        "--hidden-import", "cryptography.x509",
        "--hidden-import", "cryptography.x509.oid",
        "--hidden-import", "cryptography.hazmat.primitives",
        "--hidden-import", "cryptography.hazmat.primitives.hashes",
        "--hidden-import", "cryptography.hazmat.primitives.serialization",
        "--hidden-import", "cryptography.hazmat.primitives.asymmetric.rsa",
        "--hidden-import", "cryptography.hazmat.primitives.asymmetric.padding",
        "--hidden-import", "cryptography.hazmat.primitives.serialization.pkcs7",
    ]

    # 添加 _tools 数据
    if add_data:
        cmd += ["--add-data", add_data]

    # 图标
    if ICON_FILE and Path(ICON_FILE).exists():
        cmd += ["--icon", ICON_FILE]

    # 主脚本
    cmd.append(MAIN_SCRIPT)

    print(f"\n[+] 执行命令:")
    print(f"    {' '.join(cmd)}\n")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        exe_path = Path("dist") / f"{APP_NAME}.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\n[OK] Build successful!")
            print(f"    Output: {exe_path.absolute()}")
            print(f"    Size: {size_mb:.1f} MB")
            print(f"\n[*] Pure Python mode: no JDK/Android SDK needed")
            print(f"[*] Supported: quick sign replace / V1 sign / verify")
            print(f"[*] For full features (decompile/modify), add tools to _tools/ and rebuild")
            return 0

    print(f"\n[FAIL] Build failed")
    return 1


def main():
    return build()


if __name__ == "__main__":
    sys.exit(main())
