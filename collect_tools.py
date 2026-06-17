#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动收集 Android SDK / JDK 工具到 _tools/ 目录
运行后可直接打包便携版 EXE
"""

import os
import sys
import shutil
import urllib.request
import zipfile
from pathlib import Path


class ToolCollector:
    def __init__(self, project_dir=None):
        if project_dir is None:
            project_dir = Path(__file__).parent
        self.project_dir = Path(project_dir)
        self.tools_dir = self.project_dir / "_tools"
        self.tools_dir.mkdir(exist_ok=True)

        self.found = []
        self.missing = []

    def log(self, msg):
        print(f"[+] {msg}")

    def warn(self, msg):
        print(f"[WARNING] {msg}")

    def error(self, msg):
        print(f"[ERROR] {msg}")

    def success(self, msg):
        print(f"[OK] {msg}")

    # ========== 1. 下载 apktool ==========
    def download_apktool(self):
        target = self.tools_dir / "apktool.jar"
        if target.exists():
            self.success(f"apktool.jar already exists ({target.stat().st_size/1024/1024:.1f}MB)")
            return True

        self.log("Downloading apktool.jar...")
        urls = [
            "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar",
        ]

        for url in urls:
            try:
                print(f"  Trying {url}...")
                urllib.request.urlretrieve(url, target)
                self.success(f"apktool.jar downloaded ({target.stat().st_size/1024/1024:.1f}MB)")
                return True
            except Exception as e:
                self.warn(f"Failed: {e}")
                continue

        self.error("apktool.jar download failed!")
        self.error("Please download manually from https://apktool.org/docs/install/")
        self.error("And place it in _tools/apktool.jar")
        self.missing.append("apktool.jar")
        return False

    # ========== 2. 收集 Android SDK Build-Tools ==========
    def collect_build_tools(self):
        self.log("Searching for Android SDK Build-Tools...")

        search_paths = []

        # 从环境变量
        for env in ["ANDROID_SDK", "ANDROID_HOME", "ANDROID_SDK_ROOT"]:
            val = os.environ.get(env, "")
            if val:
                search_paths.append(Path(val) / "build-tools")

        # 常见默认路径
        search_paths += [
            Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "build-tools",
            Path.home() / "Android" / "Sdk" / "build-tools",
            Path("C:/") / "Program Files (x86)" / "Android" / "android-sdk" / "build-tools",
            Path("C:/") / "Android" / "Sdk" / "build-tools",
        ]

        found = False
        for base in search_paths:
            if not base.exists():
                continue

            versions = [d for d in base.iterdir() if d.is_dir()]
            if not versions:
                continue

            # 找最新版本
            latest = sorted(versions, key=lambda x: x.name)[-1]
            self.log(f"  Found Build-Tools: {latest.name} at {latest}")

            files_to_copy = {
                "zipalign.exe": "zipalign.exe",
                "zipalign": "zipalign",
                "apksigner.bat": "apksigner.bat",
                "apksigner": "apksigner",
                "libwinpthread-1.dll": "libwinpthread-1.dll",
            }

            copied_any = False
            for src_name, dst_name in files_to_copy.items():
                src = latest / src_name
                if src.exists():
                    dst = self.tools_dir / dst_name
                    shutil.copy2(src, dst)
                    self.success(f"  Copied: {src_name}")
                    copied_any = True

            # 复制 apksigner 依赖的 lib/
            apksigner_lib = latest / "lib" / "apksigner.jar"
            if apksigner_lib.exists():
                lib_dir = self.tools_dir / "lib"
                lib_dir.mkdir(exist_ok=True)
                shutil.copy2(apksigner_lib, lib_dir / "apksigner.jar")
                self.success(f"  Copied: lib/apksigner.jar")

            if copied_any:
                found = True
                self.found.append(f"Build-Tools {latest.name}")
                break

        if not found:
            self.error("Android SDK Build-Tools not found!")
            self.error("Please install from Android Studio -> SDK Manager")
            self.error("Or manually copy zipalign.exe and apksigner to _tools/")
            self.missing.append("zipalign, apksigner")

        return found

    # ========== 3. 收集 JDK ==========
    def collect_jdk(self):
        self.log("Searching for JDK...")

        search_paths = []

        # 从环境变量
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            search_paths.append(Path(java_home) / "bin")

        # 常见默认路径
        search_paths += [
            Path("C:/") / "Program Files" / "Java",
            Path("C:/") / "Program Files" / "Eclipse Adoptium",
            Path("C:/") / "Program Files" / "Microsoft" / "jdk*",
            Path("C:/") / "Program Files" / "Amazon Corretto",
            Path("C:/") / "Program Files" / "Zulu",
            Path.home() / ".sdkman" / "candidates" / "java" / "current" / "bin",
        ]

        found = False
        for base in search_paths:
            if not base.exists():
                continue

            # 如果 base 是 bin 目录
            if base.name == "bin":
                java_bins = [base]
            else:
                # 搜索子目录下的 bin/
                java_bins = list(base.rglob("bin/java.exe")) + list(base.rglob("bin/java"))
                if not java_bins:
                    continue
                java_bins = [p.parent for p in java_bins]

            for java_bin in java_bins:
                if not (java_bin / "java.exe").exists() and not (java_bin / "java").exists():
                    continue

                self.log(f"  Found JDK: {java_bin}")

                # 复制关键工具
                tools_to_copy = ["java", "java.exe", "keytool", "keytool.exe", 
                               "jarsigner", "jarsigner.exe"]

                java_dst = self.tools_dir / "java" / "bin"
                java_dst.mkdir(parents=True, exist_ok=True)

                copied_any = False
                for fname in tools_to_copy:
                    src = java_bin / fname
                    if src.exists():
                        dst = java_dst / fname
                        shutil.copy2(src, dst)
                        self.success(f"  Copied: {fname}")
                        copied_any = True

                if copied_any:
                    # 复制 JRE 核心模块
                    jdk_root = java_bin.parent
                    self._copy_jre_libs(jdk_root, self.tools_dir / "java")
                    found = True
                    self.found.append(f"JDK at {jdk_root}")
                    break

            if found:
                break

        if not found:
            self.error("JDK not found!")
            self.error("Please install JDK 8+ and set JAVA_HOME")
            self.error("Or manually copy java.exe, keytool.exe to _tools/java/bin/")
            self.missing.append("java, keytool, jarsigner")

        return found

    def _copy_jre_libs(self, jdk_root, target_java):
        """复制 JRE 运行库（最小化）"""
        self.log("Copying JRE libraries...")

        dirs_to_copy = ["lib", "conf"]
        for dname in dirs_to_copy:
            src = jdk_root / dname
            if src.exists():
                dst = target_java / dname
                if dst.exists():
                    shutil.rmtree(dst)

                # 忽略不必要的大文件
                def ignore_patterns(dir, files):
                    return [f for f in files if f.endswith('.diz') or f == 'src.zip' 
                            or f in ['demo', 'sample', 'man']]

                shutil.copytree(src, dst, ignore=ignore_patterns)
                size = sum(f.stat().st_size for f in dst.rglob('*') if f.is_file())
                self.success(f"  Copied: {dname}/ ({size/1024/1024:.1f}MB)")

    # ========== 4. 收集 adb (可选) ==========
    def collect_adb(self):
        self.log("Searching for adb (optional)...")
        adb = shutil.which("adb")
        if adb:
            shutil.copy2(adb, self.tools_dir / "adb.exe")
            self.success("adb copied")
            return True

        # 从 SDK platform-tools 找
        for env in ["ANDROID_SDK", "ANDROID_HOME", "ANDROID_SDK_ROOT"]:
            val = os.environ.get(env, "")
            if val:
                adb_path = Path(val) / "platform-tools" / "adb.exe"
                if adb_path.exists():
                    shutil.copy2(adb_path, self.tools_dir / "adb.exe")
                    self.success("adb copied from platform-tools")
                    return True

        self.warn("adb not found (optional)")
        return False

    # ========== 主流程 ==========
    def run(self):
        print("="*60)
        print("APK Resigner - Tool Collector")
        print("="*60)
        print()
        print(f"Project: {self.project_dir}")
        print(f"Tools:   {self.tools_dir}")
        print()

        self.download_apktool()
        self.collect_build_tools()
        self.collect_jdk()
        self.collect_adb()

        print()
        print("="*60)
        if self.missing:
            print(f"[WARNING] Missing: {', '.join(self.missing)}")
            print("Please install missing tools and re-run this script")
        else:
            print("[OK] All tools collected!")
        print("="*60)
        print()

        # 显示收集结果
        total_size = sum(f.stat().st_size for f in self.tools_dir.rglob('*') if f.is_file())
        print(f"Total size: {total_size/1024/1024:.1f}MB")
        print()
        if self.missing:
            print()
            print("[WARNING] Some tools are missing. Please install them and re-run.")
            print()
            input("Press Enter to exit...")
            return

        # ========== 自动打包 EXE ==========
        print()
        print("="*60)
        print("Starting PyInstaller build...")
        print("="*60)
        print()

        import subprocess
        import sys

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--name", "APKResigner",
            "--add-data", "_tools;_tools",
            "--clean",
            str(self.project_dir / "apk_resigner_gui.py")
        ]

        print(f"Command: {' '.join(cmd)}")
        print()

        result = subprocess.run(cmd, cwd=self.project_dir)

        if result.returncode == 0:
            print()
            print("="*60)
            print("[OK] Build successful!")
            print("="*60)
            print()
            print(f"Output: {self.project_dir / 'dist' / 'APKResigner.exe'}")
            print()
            print("You can now copy dist/APKResigner.exe to any Windows PC")
            print("and run it without installing any dependencies.")
        else:
            print()
            print("[ERROR] Build failed!")
            print()
            print("Try running manually:")
            print("  pyinstaller --noconfirm --onefile --windowed --name APKResigner --add-data '_tools;_tools' --clean apk_resigner_gui.py")

        print()
        input("Press Enter to exit...")


def main():
    collector = ToolCollector()
    collector.run()


if __name__ == '__main__':
    main()
