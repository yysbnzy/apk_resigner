#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
便携包构建脚本
自动收集 apktool、Android SDK Build-Tools、JDK 工具到 _tools/ 目录
然后执行 PyInstaller 打包
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path


class PortableBuilder:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.tools_dir = self.project_dir / "_tools"
        self.tools_dir.mkdir(exist_ok=True)

        self.collected = []
        self.missing = []

    def log(self, msg):
        print(f"[+] {msg}")

    def warn(self, msg):
        print(f"[!] {msg}")

    def error(self, msg):
        print(f"[X] {msg}")

    def success(self, msg):
        print(f"[OK] {msg}")

    def _check_cryptography(self):
        """检查 cryptography 模块（可选，用于纯 Python 签名模式）"""
        try:
            import cryptography
            print(f"[OK] cryptography installed (version: {cryptography.__version__})")
            return True
        except ImportError:
            print("[!] cryptography not installed (optional, does not affect main features)")
            print("    Main signing uses built-in JDK tools, no cryptography needed")
            print("    For pure Python signing mode, run: pip install cryptography")
            return False

    # ========== 下载 apktool ==========
    def download_apktool(self):
        """下载 apktool.jar"""
        target = self.tools_dir / "apktool.jar"
        if target.exists():
            self.success(f"apktool.jar 已存在 ({target.stat().st_size/1024/1024:.1f}MB)")
            return True

        self.log("下载 apktool.jar...")
        urls = [
            "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar",
            "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.2/apktool_2.9.2.jar",
        ]

        for url in urls:
            try:
                urllib.request.urlretrieve(url, target)
                self.success(f"apktool.jar 下载完成 ({target.stat().st_size/1024/1024:.1f}MB)")
                return True
            except Exception as e:
                self.warn(f"下载失败: {e}")
                continue

        self.error("apktool.jar 下载失败，请手动下载到 _tools/ 目录")
        self.error("下载地址: https://apktool.org/docs/install/")
        return False

    # ========== 收集 SDK Build-Tools ==========
    def collect_build_tools(self):
        """从本地 Android SDK 收集 zipalign、apksigner"""
        self.log("查找 Android SDK Build-Tools...")

        # 先检查 _tools 目录是否已有这些工具
        has_zipalign = (self.tools_dir / "zipalign.exe").exists() or (self.tools_dir / "zipalign").exists()
        has_apksigner = (self.tools_dir / "apksigner.bat").exists() or (self.tools_dir / "apksigner").exists()
        if has_zipalign and has_apksigner:
            self.success("zipalign 和 apksigner 已存在于 _tools/ 目录")
            return True

        # 常见 SDK 路径
        search_paths = [
            Path(os.environ.get("ANDROID_SDK", "")) / "build-tools",
            Path(os.environ.get("ANDROID_HOME", "")) / "build-tools",
            Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "build-tools",
            Path.home() / "Library" / "Android" / "sdk" / "build-tools",  # macOS
            Path.home() / "Android" / "Sdk" / "build-tools",  # Linux
        ]

        found = False
        for base in search_paths:
            if not base.exists():
                continue

            # 找最新版本
            versions = [d for d in base.iterdir() if d.is_dir()]
            if not versions:
                continue

            latest = sorted(versions, key=lambda x: x.name)[-1]
            self.log(f"  发现 Build-Tools: {latest.name}")

            files_to_copy = {
                "zipalign.exe": "zipalign",
                "zipalign": "zipalign",
                "apksigner.bat": "apksigner",
                "apksigner": "apksigner",
                "libwinpthread-1.dll": "libwinpthread-1.dll",
            }

            for src_name, dst_name in files_to_copy.items():
                src = latest / src_name
                if src.exists():
                    dst = self.tools_dir / dst_name
                    shutil.copy2(src, dst)
                    self.success(f"  复制: {src_name} -> _tools/{dst_name}")
                    found = True

            # 复制 apksigner 依赖的 jar
            apksigner_jar = latest / "lib" / "apksigner.jar"
            if apksigner_jar.exists():
                lib_dir = self.tools_dir / "lib"
                lib_dir.mkdir(exist_ok=True)
                shutil.copy2(apksigner_jar, lib_dir / "apksigner.jar")
                self.success(f"  复制: apksigner.jar")

            if found:
                break

        if not found:
            self.error("未找到 Android SDK Build-Tools")
            self.error("请从 Android Studio 的 SDK Manager 安装，或手动复制工具到 _tools/")
            self.missing.append("zipalign, apksigner")

        return found

    # ========== 收集 JDK 工具 ==========
    def collect_jdk(self):
        """从本地 JDK 收集完整运行环境"""
        self.log("查找 JDK...")

        # 常见 JDK 路径
        search_paths = [
            Path(os.environ.get("JAVA_HOME", "")),
            Path("C:/Program Files/Java"),
            Path("C:/Program Files/Eclipse Adoptium"),
            Path.home() / ".sdkman" / "candidates" / "java" / "current",
            Path("/usr/lib/jvm"),
            Path("/Library/Java/JavaVirtualMachines"),
        ]

        found = False
        for base in search_paths:
            if not base.exists():
                continue

            # 找到 JDK 根目录（包含 bin/ 和 lib/ 的目录）
            if base.name == "bin":
                jdk_root = base.parent
            elif (base / "bin" / "java.exe").exists() or (base / "bin" / "java").exists():
                jdk_root = base
            else:
                # 搜索子目录
                java_bins = list(base.rglob("bin/java.exe")) + list(base.rglob("bin/java"))
                if not java_bins:
                    continue
                jdk_root = java_bins[0].parent.parent

            java_bin = jdk_root / "bin"
            self.log(f"  发现 JDK: {jdk_root}")

            # 清理旧的 _tools/java 目录，避免版本混合
            target_java = self.tools_dir / "java"
            if target_java.exists():
                self.log(f"  清理旧 Java 环境...")
                shutil.rmtree(target_java)

            # 复制整个 bin/ 目录
            target_bin = target_java / "bin"
            target_bin.mkdir(parents=True, exist_ok=True)
            for item in java_bin.iterdir():
                if item.is_file():
                    shutil.copy2(item, target_bin / item.name)
                elif item.is_dir() and item.name == "server":
                    # 复制 server/ 子目录（包含 jvm.dll）
                    shutil.copytree(item, target_bin / "server", dirs_exist_ok=True)
            self.success(f"  复制: bin/")
            found = True

            # 复制 JRE 核心模块（最小化）
            if found:
                self._copy_minimal_jre(jdk_root, target_java)
                break

        if not found:
            self.error("未找到 JDK")
            self.error("请安装 JDK 8+ 并设置 JAVA_HOME，或手动复制到 _tools/java/bin/")
            self.missing.append("java, keytool, jarsigner")

        return found

    def _copy_minimal_jre(self, jdk_root, target_java):
        """复制最小化 JRE 运行环境"""
        self.log("复制最小 JRE 环境...")

        # 需要复制的目录
        dirs_to_copy = ["lib", "conf"]
        for dname in dirs_to_copy:
            src = jdk_root / dname
            if src.exists():
                dst = target_java / dname
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                    "*.diz", "src.zip", "demo", "sample", "man"
                ))
                self.success(f"  复制: {dname}/")

    # ========== 收集 adb (可选) ==========
    def collect_adb(self):
        """收集 adb 工具（可选）"""
        self.log("查找 adb...")
        adb = shutil.which("adb")
        if adb:
            adb_path = Path(adb)
            shutil.copy2(adb_path, self.tools_dir / "adb.exe")
            self.success(f"adb 已复制")
            # 复制 adb 依赖的 DLL
            adb_dir = adb_path.parent
            for dll in ["AdbWinApi.dll", "AdbWinUsbApi.dll"]:
                dll_src = adb_dir / dll
                if dll_src.exists():
                    shutil.copy2(dll_src, self.tools_dir / dll)
                    self.success(f"  复制: {dll}")
            return True
        self.warn("adb 未找到（可选）")
        return False

    # ========== 主流程 ==========
    def build(self):
        """执行完整构建"""
        print("="*60)
        print("APK 签名替换工具 - 便携包构建")
        print("="*60)
        print()
        
        # 0. 检查 cryptography（可选，不影响主功能）
        has_crypto = self._check_cryptography()
        
        self.log("目标目录:")
        print(f"  项目: {self.project_dir}")
        print(f"  工具: {self.tools_dir}")
        print()

        # 1. 下载/收集工具
        self.download_apktool()
        self.collect_build_tools()
        self.collect_jdk()
        self.collect_adb()

        print()
        print("="*60)
        if self.missing:
            print(f"[!] Missing tools: {', '.join(self.missing)}")
            print("    Please manually install and re-run")
            print("="*60)
            return False
        else:
            print("[OK] All tools collected!")
            print("="*60)

        print()

        # 2. 执行 PyInstaller 打包
        self.log("开始 PyInstaller 打包...")

        # 构建打包命令
        # 使用 --add-data 把 _tools 目录打包进去
        # Windows 格式: "_tools;_tools"  (源;目标)
        add_data = f"_tools;_tools"

        # 检查 cryptography（可选，不影响主功能）
        has_crypto = self._check_cryptography()
        
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--name", "APK签名替换工具",
            "--add-data", add_data,
            "--clean",
            str(self.project_dir / "apk_resigner_gui.py")
        ]
        
        if has_crypto:
            # 只有安装了 cryptography 才加 hidden-import，避免打包报错
            cmd += [
                "--hidden-import", "cryptography",
                "--hidden-import", "cryptography.hazmat.primitives",
                "--hidden-import", "cryptography.hazmat.primitives.asymmetric",
                "--hidden-import", "cryptography.hazmat.primitives.serialization",
                "--hidden-import", "cryptography.x509",
            ]

        print(f"  命令: {' '.join(cmd)}")
        print()

        result = subprocess.run(cmd, cwd=self.project_dir)

        if result.returncode == 0:
            print()
            print("="*60)
            print("[OK] Build successful!")
            print("="*60)
            print()
            print(f"Output location:")
            print(f"  {self.project_dir / 'dist' / 'APK签名替换工具.exe'}")
            print()
            print("Instructions:")
            print("  1. Copy dist/APK签名替换工具.exe to any location")
            print("  2. Double-click to run, no installation needed")
            print("  3. All tools are built-in")
            print()
            print("NOTE:")
            print("  - Single-file EXE starts slower first time (needs to unpack built-in tools)")
            print("  - Working directory is auto-generated under user directory")
            return True
        else:
            print()
            print("[X] Build failed")
            return False


def main():
    # 脚本所在目录即项目目录
    project_dir = Path(__file__).parent
    builder = PortableBuilder(project_dir)
    success = builder.build()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
