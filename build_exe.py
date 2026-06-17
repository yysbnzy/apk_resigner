#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键打包脚本 - 将 GUI 版本打包为 EXE
"""

import os
import sys
import subprocess
from pathlib import Path

def check_pyinstaller():
    """检查 PyInstaller 是否安装"""
    try:
        import PyInstaller
        return True
    except ImportError:
        return False

def install_pyinstaller():
    """安装 PyInstaller"""
    print("[+] 正在安装 PyInstaller...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], 
                          capture_output=True, text=True)
    if result.returncode == 0:
        print("[✓] PyInstaller 安装成功")
        return True
    else:
        print(f"[✗] 安装失败: {result.stderr}")
        return False

def build_exe():
    """执行打包"""
    script_dir = Path(__file__).parent
    gui_script = script_dir / "apk_resigner_gui.py"

    if not gui_script.exists():
        print(f"[✗] 找不到 GUI 脚本: {gui_script}")
        print("请确保 build_exe.py 和 apk_resigner_gui.py 在同一目录")
        return False

    print("="*60)
    print("APK 签名替换工具 - EXE 打包")
    print("="*60)
    print()

    # 选择打包模式
    print("选择打包模式:")
    print("  1. 单文件 EXE（推荐，便携）")
    print("  2. 目录式 EXE（启动快）")
    print("  3. 调试版（带控制台窗口）")
    print()

    choice = input("请输入选项 (1-3): ").strip()

    if choice == "1":
        mode = ["--onefile", "--windowed"]
        name = "APK签名替换工具"
    elif choice == "2":
        mode = ["--windowed"]
        name = "APK签名替换工具"
    elif choice == "3":
        mode = ["--onefile"]
        name = "APK签名替换工具-Debug"
    else:
        print("[✗] 无效选项")
        return False

    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        *mode,
        "--name", name,
        "--clean",
        str(gui_script)
    ]

    print(f"[+] 执行命令: {' '.join(cmd)}")
    print(f"[+] 开始打包，请稍候...")
    print()

    result = subprocess.run(cmd, cwd=script_dir)

    if result.returncode == 0:
        print()
        print("="*60)
        print("[✓] 打包成功！")
        print("="*60)
        print(f"\n输出位置:")
        print(f"  {script_dir / 'dist' / name}")
        if choice == "1":
            print(f"  文件: {script_dir / 'dist' / (name + '.exe')}")
        print()
        print("提示:")
        print("  - 运行需要 apktool, zipalign, apksigner, keytool 在 PATH 中")
        print("  - 首次启动可能较慢（单文件模式需要解压）")
        return True
    else:
        print()
        print("[✗] 打包失败，请检查错误信息")
        return False

def main():
    if not check_pyinstaller():
        print("PyInstaller 未安装")
        install = input("是否自动安装? (y/n): ").strip().lower()
        if install == 'y':
            if not install_pyinstaller():
                sys.exit(1)
        else:
            print("请手动安装: pip install pyinstaller")
            sys.exit(1)

    build_exe()

    print()
    input("按回车键退出...")

if __name__ == '__main__':
    main()
