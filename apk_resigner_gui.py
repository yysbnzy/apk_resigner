#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 签名替换工具 - 便携版 GUI v1.3.0
支持从 _tools/ 目录加载内置依赖，无需系统安装
自动检测签名方案 + 5按钮布局
"""

import os
import sys
import subprocess
import shutil
import threading
import hashlib
import zipfile
import urllib.request
from pathlib import Path
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
except ImportError:
    import Tkinter as tk
    from Tkinter import ttk, filedialog, messagebox, scrolledtext

from pure_python_sign import PurePythonAPKSigner


class ToolManager:
    """管理工具路径，优先使用内置工具"""

    def __init__(self):
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                self.base_dir = Path(sys._MEIPASS)
            else:
                self.base_dir = Path(sys.executable).parent
        else:
            self.base_dir = Path(__file__).parent

        self.tools_dir = self.base_dir / "_tools"
        self.java_dir = self.tools_dir / "java" / "bin"
        self.tool_paths = {}
        self._detect_tools()

    def _detect_tools(self):
        apktool_jar = self.tools_dir / "apktool.jar"
        if apktool_jar.exists():
            self.tool_paths['apktool'] = str(apktool_jar)
        elif shutil.which('apktool'):
            self.tool_paths['apktool'] = 'apktool'

        zipalign = self._find_tool("zipalign", [".exe", ""])
        if zipalign:
            self.tool_paths['zipalign'] = zipalign

        apksigner = self._find_tool("apksigner", [".bat", ".exe", ""])
        if apksigner:
            self.tool_paths['apksigner'] = apksigner

        java = self._find_java()
        if java:
            self.tool_paths['java'] = java
            keytool = self._find_tool("keytool", [".exe", ""], subdir="java/bin")
            if keytool:
                self.tool_paths['keytool'] = keytool
            elif shutil.which('keytool'):
                self.tool_paths['keytool'] = 'keytool'

            jarsigner = self._find_tool("jarsigner", [".exe", ""], subdir="java/bin")
            if jarsigner:
                self.tool_paths['jarsigner'] = jarsigner
            elif shutil.which('jarsigner'):
                self.tool_paths['jarsigner'] = 'jarsigner'

        adb = self._find_tool("adb", [".exe", ""])
        if adb:
            self.tool_paths['adb'] = adb
        elif shutil.which('adb'):
            self.tool_paths['adb'] = 'adb'

    def _find_tool(self, name, exts, subdir=None):
        search_dirs = [self.tools_dir]
        if subdir:
            search_dirs.append(self.tools_dir / subdir)
        for d in search_dirs:
            for ext in exts:
                path = d / f"{name}{ext}"
                if path.exists():
                    return str(path)
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path
        return None

    def _find_java(self):
        java_exe = self.java_dir / "java.exe"
        if java_exe.exists():
            return str(java_exe)
        java_exe = self.tools_dir / "java.exe"
        if java_exe.exists():
            return str(java_exe)
        sys_java = shutil.which('java')
        if sys_java:
            return sys_java
        return None

    def get_cmd(self, tool_name):
        path = self.tool_paths.get(tool_name)
        if not path:
            return None
        if tool_name == 'apktool' and path.endswith('.jar'):
            java = self.tool_paths.get('java')
            if java:
                return [java, '-jar', path]
            return None
        return [path]

    def check_all(self):
        required = ['apktool', 'zipalign', 'apksigner', 'keytool']
        missing = []
        for tool in required:
            if not self.tool_paths.get(tool):
                missing.append(tool)
        return missing

    def get_info(self):
        lines = ["工具检测状态:"]
        for tool, path in sorted(self.tool_paths.items()):
            source = "内置" if self.tools_dir in Path(path).parents or self.tools_dir == Path(path).parent else "系统"
            lines.append(f"  ✓ {tool}: {source} ({Path(path).name})")
        missing = self.check_all()
        if missing:
            lines.append(f"\n  ✗ 缺失: {', '.join(missing)}")
        return '\n'.join(lines)


class APKResignerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("APK 签名替换工具 - 便携版 v1.3.0")
        self.root.geometry("950x750")
        self.root.minsize(850, 650)

        self.work_dir = Path(os.path.expanduser("~")) / "apk_resign_work"
        self.work_dir.mkdir(exist_ok=True)

        self.apk_path = tk.StringVar()
        self.keystore_path = tk.StringVar()
        self.alias = tk.StringVar(value="testkey")
        self.password = tk.StringVar(value="123456")
        self.modify_manifest = tk.BooleanVar(value=True)
        self.modify_smali = tk.BooleanVar(value=False)
        self.auto_generate_key = tk.BooleanVar(value=True)
        self.detected_scheme = tk.StringVar(value="v2+v3+v4")
        self.detected_v1 = False
        self.detected_v2 = False
        self.detected_v3 = False
        self.detected_v4 = False

        self.tools = ToolManager()
        self.pure_python = PurePythonAPKSigner(str(self.work_dir))
        self.pure_python_mode = False

        self.build_ui()
        self.log(self.tools.get_info(), "INFO")

        missing = self.tools.check_all()
        if missing:
            self.log(f"\n⚠️ 缺少必需工具: {', '.join(missing)}", "WARNING")
            self.log("纯 Python 模式已启用：快速签名 / V1 签名可用，无需 JDK/Android SDK", "INFO")
            self.pure_python_mode = True
            self.status_var.set(f"纯 Python 模式 (缺少: {', '.join(missing)})")
            self.btn_full.config(state="disabled")
        else:
            self.status_var.set("就绪 (全部内置)")

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="APK 签名替换工具 - 便携版 v1.3.0", font=("Microsoft YaHei", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky=tk.W)

        self.btn_help = ttk.Button(main_frame, text="❓ 使用说明", command=self.show_help, width=12)
        self.btn_help.grid(row=0, column=2, pady=(0, 5), sticky=tk.E)

        subtitle = ttk.Label(main_frame, text="自动检测签名方案 | 内置依赖，无需安装 Android SDK / JDK", font=("Microsoft YaHei", 9), foreground="gray")
        subtitle.grid(row=1, column=0, columnspan=3, pady=(0, 15))

        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="10")
        file_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="APK 文件:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(file_frame, textvariable=self.apk_path).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.browse_apk).grid(row=0, column=2, padx=5)

        ttk.Label(file_frame, text="密钥库:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.keystore_path, state="readonly").grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.browse_keystore).grid(row=1, column=2, padx=5)

        ttk.Checkbutton(file_frame, text="自动生成测试密钥", variable=self.auto_generate_key, command=self.toggle_keystore).grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5)

        self.scheme_label = ttk.Label(file_frame, text="检测到签名: 未知 (请选 APK)", foreground="gray")
        self.scheme_label.grid(row=3, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)

        config_frame = ttk.LabelFrame(main_frame, text="签名参数", padding="10")
        config_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        ttk.Label(config_frame, text="密钥别名:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.alias, width=20).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="密钥密码:").grid(row=0, column=2, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.password, show="*", width=20).grid(row=0, column=3, sticky=tk.W, padx=5)

        modify_frame = ttk.LabelFrame(main_frame, text="修改选项 (仅完整流程有效)", padding="10")
        modify_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        ttk.Checkbutton(modify_frame, text="修改 AndroidManifest.xml（添加 [MODIFIED] 标记）", variable=self.modify_manifest).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(modify_frame, text="修改 smali 代码（添加完整性测试标记）", variable=self.modify_smali).grid(row=1, column=0, sticky=tk.W, padx=5)

        # 5个操作按钮
        btn_frame = ttk.LabelFrame(main_frame, text="操作按钮", padding="10")
        btn_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        self.btn_full = ttk.Button(btn_frame, text="🔧 修改内容+签名", command=lambda: self.run_task("full"), width=22)
        self.btn_full.pack(side=tk.LEFT, padx=5)

        self.btn_v1 = ttk.Button(btn_frame, text="⚡ V1 签名", command=lambda: self.run_task("v1"), width=18)
        self.btn_v1.pack(side=tk.LEFT, padx=5)

        self.btn_v2 = ttk.Button(btn_frame, text="⚡ V2 签名", command=lambda: self.run_task("v2"), width=18)
        self.btn_v2.pack(side=tk.LEFT, padx=5)

        self.btn_v23 = ttk.Button(btn_frame, text="⚡ V2+V3 签名", command=lambda: self.run_task("v23"), width=18)
        self.btn_v23.pack(side=tk.LEFT, padx=5)

        self.btn_v4 = ttk.Button(btn_frame, text="⚡ V4 签名", command=lambda: self.run_task("v4"), width=18)
        self.btn_v4.pack(side=tk.LEFT, padx=5)

        verify_frame = ttk.Frame(main_frame)
        verify_frame.grid(row=6, column=0, columnspan=3, pady=5)

        self.btn_verify = ttk.Button(verify_frame, text="🔍 验证签名", command=self.verify_apk, width=15)
        self.btn_verify.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        log_frame = ttk.LabelFrame(main_frame, text="执行日志", padding="5")
        log_frame.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=18, font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.log_text.tag_config("INFO", foreground="blue")
        self.log_text.tag_config("SUCCESS", foreground="green")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("WARNING", foreground="orange")

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        main_frame.rowconfigure(8, weight=1)

    def toggle_keystore(self):
        if self.auto_generate_key.get():
            self.keystore_path.set("")

    def detect_apk_scheme(self, apk_path):
        """自动检测 APK 的签名方案"""
        self.log(f"[+] 检测 APK 签名方案: {Path(apk_path).name}", "INFO")
        cmd = self.tools.get_cmd('apksigner')
        if not cmd:
            self.log("  ⚠ apksigner 不可用，使用默认方案 v2+v3+v4", "WARNING")
            self.detected_scheme.set("v2+v3+v4")
            self.scheme_label.config(text="检测到签名: 未知 (默认 v2+v3+v4)", foreground="orange")
            return

        cmd += ['verify', '-v', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            self.log(f"  ⚠ 检测失败: {result.stderr[:200]}", "WARNING")
            self.detected_scheme.set("v2+v3+v4")
            self.scheme_label.config(text="检测到签名: 未知 (默认 v2+v3+v4)", foreground="orange")
            return

        output = result.stdout
        self.detected_v1 = "Verified using v1 scheme" in output
        self.detected_v2 = "Verified using v2 scheme" in output
        self.detected_v3 = "Verified using v3 scheme" in output
        self.detected_v4 = "Verified using v4 scheme" in output

        if self.detected_v4:
            scheme = "v4"
        elif self.detected_v3 and self.detected_v2:
            scheme = "v2+v3+v4"
        elif self.detected_v2:
            scheme = "v2"
        elif self.detected_v1:
            scheme = "v1"
        else:
            scheme = "v2+v3+v4"

        self.detected_scheme.set(scheme)
        v1s = "✓" if self.detected_v1 else "✗"
        v2s = "✓" if self.detected_v2 else "✗"
        v3s = "✓" if self.detected_v3 else "✗"
        v4s = "✓" if self.detected_v4 else "✗"
        scheme_text = f"V1={v1s} V2={v2s} V3={v3s} V4={v4s}"
        self.scheme_label.config(text=f"检测到签名: {scheme_text} | 自动使用: {scheme}", foreground="green")
        self.log(f"  ✓ 检测到签名方案: {scheme}", "SUCCESS")

    def browse_apk(self):
        path = filedialog.askopenfilename(title="选择 APK 文件", filetypes=[("APK 文件", "*.apk"), ("所有文件", "*.*")])
        if path:
            self.apk_path.set(path)
            self.log(f"已选择 APK: {path}", "INFO")
            self.detect_apk_scheme(path)

    def browse_keystore(self):
        path = filedialog.askopenfilename(title="选择密钥库文件", filetypes=[("密钥库", "*.jks *.keystore *.p12"), ("所有文件", "*.*")])
        if path:
            self.keystore_path.set(path)
            self.auto_generate_key.set(False)
            self.log(f"已选择密钥库: {path}", "INFO")

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", level)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def set_buttons_state(self, state):
        self.btn_full.config(state=state)
        self.btn_v1.config(state=state)
        self.btn_v2.config(state=state)
        self.btn_v23.config(state=state)
        self.btn_v4.config(state=state)
        self.btn_verify.config(state=state)

    def run_task(self, task_type):
        apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择有效的 APK 文件")
            return
        self.set_buttons_state("disabled")
        self.progress.start()
        self.status_var.set("执行中...")
        thread = threading.Thread(target=self._do_task, args=(task_type, apk))
        thread.daemon = True
        thread.start()

    def _do_task(self, task_type, apk):
        try:
            if task_type == "full":
                self._full_process(apk)
            elif task_type == "v1":
                self._quick_replace(apk, "v1")
            elif task_type == "v2":
                self._quick_replace(apk, "v2")
            elif task_type == "v23":
                self._quick_replace(apk, "v2+v3+v4")
            elif task_type == "v4":
                self._quick_replace(apk, "v4")
        except Exception as e:
            self.log(f"❌ 执行出错: {str(e)}", "ERROR")
        finally:
            self.root.after(0, self._task_done)

    def _task_done(self):
        self.progress.stop()
        self.set_buttons_state("normal")
        self.status_var.set("就绪")

    def _full_process(self, apk):
        self.log("="*50, "INFO")
        self.log("开始修改内容+签名流程", "INFO")
        self.log("="*50, "INFO")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.auto_generate_key.get():
            keystore = self.work_dir / f"test_keystore_{timestamp}.jks"
            self._generate_keystore(keystore)
        else:
            keystore = Path(self.keystore_path.get())
            if not keystore.exists():
                self.log("❌ 密钥库不存在", "ERROR")
                return

        if not self.pure_python_mode:
            decompiled = self.work_dir / f"decompiled_{timestamp}"
            self._decompile(apk, decompiled)
            if self.modify_manifest.get():
                self._modify_manifest(decompiled)
            if self.modify_smali.get():
                self._modify_smali(decompiled)
            unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
            self._rebuild(decompiled, unsigned)
            aligned = self.work_dir / f"aligned_{timestamp}.apk"
            self._zipalign(unsigned, aligned)
        else:
            stripped = self.work_dir / f"stripped_{timestamp}"
            self._strip_signature(apk, stripped)
            unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
            self._repack_zip(stripped, unsigned)
            aligned = self.work_dir / f"aligned_{timestamp}.apk"
            self._zipalign(unsigned, aligned)

        scheme = self.detected_scheme.get()
        self._sign(apk_path=aligned, keystore=keystore, scheme=scheme)

        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self.log(f"🔑 密钥库: {keystore}", "INFO")
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: messagebox.showinfo("完成", f"签名替换完成！\n\n最终 APK:\n{final}\n\n密钥库:\n{keystore}"))

    def _quick_replace(self, apk, scheme):
        if self.pure_python_mode and scheme == "v1":
            self.log("="*50, "INFO")
            self.log("纯 Python V1 签名模式", "INFO")
            self.log("="*50, "INFO")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            keystore = self.work_dir / f"test_key_{timestamp}.pem"
            self.pure_python.generate_keystore(keystore, self.alias.get())
            final = self.pure_python.quick_replace(apk, keystore, self.alias.get())
            if final:
                self.log(f"\n✅ V1 签名完成！", "SUCCESS")
                self.log(f"📦 最终 APK: {final}", "SUCCESS")
                self.log(f"🔑 密钥: {keystore}", "INFO")
                self._compare_signatures(apk, final)
                self.root.after(0, lambda: messagebox.showinfo("完成", f"V1 签名完成！\n\n最终 APK:\n{final}"))
            return

        self.log("="*50, "INFO")
        self.log(f"开始 {scheme} 签名流程", "INFO")
        self.log("="*50, "INFO")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.auto_generate_key.get():
            keystore = self.work_dir / f"test_keystore_{timestamp}.jks"
            self._generate_keystore(keystore)
        else:
            keystore = Path(self.keystore_path.get())

        stripped = self.work_dir / f"stripped_{timestamp}"
        self._strip_signature(apk, stripped)

        unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
        self._repack_zip(stripped, unsigned)

        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(unsigned, aligned)

        self._sign(apk_path=aligned, keystore=keystore, scheme=scheme)

        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ {scheme} 签名完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: messagebox.showinfo("完成", f"{scheme} 签名完成！\n\n最终 APK:\n{final}"))

    def _generate_keystore(self, path):
        self.log(f"[+] 生成测试密钥库: {path.name}")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self.tools.get_cmd('keytool')
        if not cmd:
            self.log("❌ keytool 不可用", "ERROR")
            raise RuntimeError("keytool 不可用")
        cmd += [
            '-genkey', '-v',
            '-keystore', str(path),
            '-alias', self.alias.get(),
            '-keyalg', 'RSA',
            '-keysize', '2048',
            '-validity', '36500',
            '-dname', 'CN=Test, OU=Test, O=Test, L=Test, ST=Test, C=CN',
            '-storepass', self.password.get(),
            '-keypass', self.password.get(),
            '-noprompt'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and path.exists():
            self.log(f"  ✓ 密钥库生成成功", "SUCCESS")
        else:
            self.log(f"  ✗ 密钥库生成失败", "ERROR")
            raise RuntimeError(f"密钥库生成失败: rc={result.returncode}")

    def _decompile(self, apk, out_dir):
        self.log(f"[+] 反编译 APK...")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        cmd = self.tools.get_cmd('apktool')
        if not cmd:
            raise RuntimeError("apktool 不可用")
        cmd += ['d', '-f', '-o', str(out_dir), str(apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 反编译完成", "SUCCESS")
        else:
            raise RuntimeError(f"反编译失败: {result.stderr}")

    def _modify_manifest(self, decompiled_dir):
        self.log(f"[+] 修改 AndroidManifest.xml...")
        manifest = Path(decompiled_dir) / "AndroidManifest.xml"
        if not manifest.exists():
            return
        with open(manifest, 'r', encoding='utf-8') as f:
            content = f.read()
        if 'android:label="' in content:
            content = content.replace('android:label="', 'android:label="[MODIFIED] ')
            with open(manifest, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log(f"  ✓ 已添加 [MODIFIED] 标记", "SUCCESS")

    def _modify_smali(self, decompiled_dir):
        self.log(f"[+] 修改 smali 代码...")
        smali_dir = Path(decompiled_dir) / "smali"
        if not smali_dir.exists():
            return
        target = None
        for smali_file in smali_dir.rglob("*.smali"):
            with open(smali_file, 'r', encoding='utf-8') as f:
                content = f.read()
            if "onCreate" in content:
                target = smali_file
                break
        if target:
            with open(target, 'r', encoding='utf-8') as f:
                content = f.read()
            content = content.replace(".method protected onCreate(", "\n    # MODIFIED BY APKRESIGNER\n    .method protected onCreate(")
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log(f"  ✓ 已修改 smali: {target.name}", "SUCCESS")

    def _rebuild(self, decompiled_dir, output_apk):
        self.log(f"[+] 重打包...")
        cmd = self.tools.get_cmd('apktool')
        if not cmd:
            raise RuntimeError("apktool 不可用")
        cmd += ['b', '-o', str(output_apk), str(decompiled_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 重打包完成", "SUCCESS")
        else:
            raise RuntimeError(f"重打包失败: {result.stderr}")

    def _strip_signature(self, apk, out_dir):
        self.log(f"[+] 去除原签名...")
        out_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(apk, 'r') as zf:
            for item in zf.namelist():
                if item.startswith('META-INF/'):
                    self.log(f"  - 移除: {item}")
                    continue
                zf.extract(item, out_dir)
        self.log(f"  ✓ 签名已去除", "SUCCESS")

    def _repack_zip(self, source_dir, output_apk):
        self.log(f"[+] 重新打包 ZIP...")
        with zipfile.ZipFile(output_apk, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = str(file_path.relative_to(source_dir))
                    zf.write(file_path, arcname)
        self.log(f"  ✓ 打包完成", "SUCCESS")

    def _zipalign(self, input_apk, output_apk):
        self.log(f"[+] zipalign 对齐...")
        cmd = self.tools.get_cmd('zipalign')
        if not cmd:
            raise RuntimeError("zipalign 不可用")
        cmd += ['-p', '-f', '-v', '4', str(input_apk), str(output_apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 对齐完成", "SUCCESS")
        else:
            raise RuntimeError(f"zipalign 失败: {result.stderr}")

    def _sign(self, apk_path, keystore, scheme="v2+v3+v4"):
        self.log(f"[+] 签名 APK...")
        self.log(f"    签名方案: {scheme}", "INFO")
        cmd = self.tools.get_cmd('apksigner')
        if not cmd:
            raise RuntimeError("apksigner 不可用")
        cmd += ['sign', '--ks', str(keystore), '--ks-key-alias', self.alias.get(), '--ks-pass', f'pass:{self.password.get()}', '--key-pass', f'pass:{self.password.get()}', '--min-sdk-version', '21', str(apk_path)]
        if scheme == "v1":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'true', '--v2-signing-enabled', 'false', '--v3-signing-enabled', 'false', '--v4-signing-enabled', 'false'] + [str(apk_path)]
        elif scheme == "v2":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'false', '--v4-signing-enabled', 'false'] + [str(apk_path)]
        elif scheme == "v4":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true', '--v4-signing-enabled', 'true'] + [str(apk_path)]
        else:
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true', '--v4-signing-enabled', 'true'] + [str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 签名完成", "SUCCESS")
        else:
            self.log(f"  ✗ 签名失败: {result.stderr}", "ERROR")
            raise RuntimeError("签名失败")

    def _compare_signatures(self, original, modified):
        self.log(f"\n[+] 签名对比:", "INFO")
        for label, path in [("原始", original), ("修改", modified)]:
            with open(path, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            self.log(f"  {label}: {md5}", "INFO")
        self.log(f"\n⚠️ 签名已替换，完整性校验应当失败！", "WARNING")

    def verify_apk(self):
        apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择 APK 文件")
            return
        self.log(f"\n[+] 验证签名: {apk}", "INFO")
        cmd = self.tools.get_cmd('apksigner')
        if not cmd:
            self.log("❌ apksigner 不可用", "ERROR")
            return
        cmd += ['verify', '-v', str(apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 签名验证通过", "SUCCESS")
            for line in result.stdout.strip().split('\n'):
                self.log(f"    {line}", "INFO")
        else:
            self.log(f"  ✗ 验证失败: {result.stderr}", "ERROR")
        cmd = self.tools.get_cmd('zipalign')
        if cmd:
            cmd += ['-c', '-v', '4', str(apk)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"  ✓ zipalign 对齐正常", "SUCCESS")
            else:
                self.log(f"  ⚠ zipalign 可能有问题", "WARNING")

    def show_help(self):
        """显示使用说明弹窗"""
        help_win = tk.Toplevel(self.root)
        help_win.title("使用说明")
        help_win.geometry("720x580")
        help_win.transient(self.root)
        help_win.grab_set()

        text = scrolledtext.ScrolledText(help_win, wrap=tk.WORD, font=("Microsoft YaHei", 10), padx=10, pady=10)
        text.pack(fill=tk.BOTH, expand=True)
        text.tag_config("title", font=("Microsoft YaHei", 12, "bold"))
        text.tag_config("heading", font=("Microsoft YaHei", 10, "bold"), foreground="blue")
        text.tag_config("warning", foreground="red")
        text.tag_config("note", foreground="gray")

        content = """
【工具简介】
本工具用于 APK 签名替换测试，支持自动检测原 APK 签名方案。

═══════════════════════════════════════════════════

【5个按钮说明】

🔧 修改内容+签名（完整流程）
  流程：反编译 APK → 修改内容 → 重打包 → zipalign → 签名
  修改选项：
    • AndroidManifest.xml（添加 [MODIFIED] 标记）
    • smali 代码（添加测试标记）
  签名方案：自动检测原 APK 的方案并保持一致
  用途：测试 APK 完整性校验（内容+签名双重校验）
  ⚠ 需要内置工具：apktool + zipalign + apksigner

⚡ V1 签名（仅替换签名）
  流程：去除原签名 → 重新打包 → 用 jarsigner 做 V1 签名
  输出：仅含 V1 (JAR) 签名的 APK
  注意：Android 7.0+ 会拒绝安装！
  用途：测试旧版兼容性或 Android 7.0+ 拦截效果
  ✅ 纯 Python 模式可用

⚡ V2 签名（仅替换签名）
  流程：去除原签名 → 重新 zipalign → 用 apksigner 做 V2 签名
  输出：仅含 V2 签名块的 APK
  用途：测试 Android 7.0+ 的签名校验

⚡ V2+V3 签名（仅替换签名）
  流程：去除原签名 → 重新 zipalign → 用 apksigner 做 V2+V3 签名
  输出：含 V2+V3 签名块的 APK（默认推荐）
  用途：测试 Android 9.0+ 的密钥轮换兼容性

⚡ V4 签名（仅替换签名）
  流程：去除原签名 → 重新 zipalign → 用 apksigner 做 V4 签名
  输出：含 V2+V3+V4 签名块的 APK
  用途：测试 Android 11+ 的增量签名

🔍 验证签名
  功能：检查 APK 的签名状态和对齐情况
  输出：显示 v1/v2/v3/v4 签名验证结果 + zipalign 对齐状态
  注意：不生成新 APK，仅查看信息

═══════════════════════════════════════════════════

【自动检测签名方案】
选择 APK 文件后，工具会自动用 apksigner verify 检测原 APK 的签名：
  • 检测 V1 / V2 / V3 / V4 是否存在
  • "🔧 修改内容+签名"按钮使用自动检测到的方案
  • 其他按钮使用各自固定的签名方案

═══════════════════════════════════════════════════

【签名方案对比】

  特性      V1 (JAR)        V2/V3/V4
  ─────────────────────────────────────
  Android 5-6  ✅ 支持       ✅ 支持
  Android 7+   ❌ 拒绝安装   ✅ 支持
  安全性       低            高
  速度         慢            快

═══════════════════════════════════════════════════

【纯 Python 模式】
当系统未安装 JDK / Android SDK 时，工具自动切换到纯 Python 模式：
  ✅ V1 签名（⚡ V1 签名按钮）
  ⚠ 其他按钮可能受限 — 需手动添加工具到 _tools/ 目录

═══════════════════════════════════════════════════

【输出目录】
生成 APK 保存在：%USERPROFILE%\\apk_resign_work\\

【安全提示】
本工具仅用于测试和学习，请勿用于非法用途。
替换签名后的 APK 无法通过原开发者签名校验。
"""
        text.insert(tk.END, content)
        text.config(state=tk.DISABLED)

        ttk.Button(help_win, text="关闭", command=help_win.destroy).pack(pady=10)


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    style = ttk.Style()
    style.theme_use('clam')
    app = APKResignerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
