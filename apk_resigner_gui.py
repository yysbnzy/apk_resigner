#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 签名替换工具 - 便携版 GUI
支持从 _tools/ 目录加载内置依赖，无需系统安装
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

# Lazy import pure_python_sign to avoid cryptography dependency at startup
try:
    from pure_python_sign import PurePythonAPKSigner, CRYPTO_AVAILABLE
except ImportError:
    PurePythonAPKSigner = None
    CRYPTO_AVAILABLE = False


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
        self.root.title("APK 签名替换工具 - 便携版")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        self.work_dir = Path(os.path.expanduser("~")) / "apk_resign_work"
        self.work_dir.mkdir(exist_ok=True)

        self.apk_path = tk.StringVar()
        self.keystore_path = tk.StringVar()
        self.alias = tk.StringVar(value="testkey")
        self.password = tk.StringVar(value="123456")
        self.auto_generate_key = tk.BooleanVar(value=True)
        self.detected_scheme = tk.StringVar(value="v2+v3+v4")
        self.has_v1 = False
        self.has_v2 = False
        self.has_v3 = False
        self.has_v4 = False

        self.tools = ToolManager()
        if CRYPTO_AVAILABLE:
            self.pure_python = PurePythonAPKSigner(str(self.work_dir))
        else:
            self.pure_python = None
        self.pure_python_mode = False

        self.build_ui()
        self.log(self.tools.get_info(), "INFO")

        missing = self.tools.check_all()
        if missing:
            self.log(f"\n⚠️ 缺少必需工具: {', '.join(missing)}", "WARNING")
            self.log("纯 Python 模式已启用：V1-only 签名可用，无需 JDK/Android SDK", "INFO")
            self.pure_python_mode = True
            self.status_var.set(f"纯 Python 模式 (缺少: {', '.join(missing)})")
            self.btn_sign.config(state="disabled")
        else:
            self.status_var.set("就绪 (全部内置)")

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="APK 签名替换工具 - 便携版", font=("Microsoft YaHei", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky=tk.W)

        self.btn_help = ttk.Button(main_frame, text="❓ 使用说明", command=self.show_help, width=12)
        self.btn_help.grid(row=0, column=2, pady=(0, 5), sticky=tk.E)

        subtitle = ttk.Label(main_frame, text="内置依赖，无需安装 Android SDK / JDK", font=("Microsoft YaHei", 9), foreground="gray")
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

        self.scheme_label = ttk.Label(file_frame, text="检测到签名: 未选择APK", foreground="gray")
        self.scheme_label.grid(row=3, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)

        config_frame = ttk.LabelFrame(main_frame, text="签名参数", padding="10")
        config_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        ttk.Label(config_frame, text="密钥别名:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.alias, width=20).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(config_frame, text="密钥密码:").grid(row=0, column=2, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.password, show="*", width=20).grid(row=0, column=3, sticky=tk.W, padx=5)

        # 2个操作按钮
        btn_frame = ttk.LabelFrame(main_frame, text="操作按钮", padding="10")
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        self.btn_sign = ttk.Button(btn_frame, text="🔧 修改内容+签名", command=self.run_sign, width=30)
        self.btn_sign.pack(side=tk.LEFT, padx=15)
        self._tooltip(self.btn_sign, "解压APK→添加test.txt→重新打包→按原方案签名")

        self.btn_verify = ttk.Button(btn_frame, text="🔍 验证签名", command=self.verify_apk, width=20)
        self.btn_verify.pack(side=tk.LEFT, padx=15)
        self._tooltip(self.btn_verify, "检查APK的签名状态和对齐情况")

        self.progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        log_frame = ttk.LabelFrame(main_frame, text="执行日志", padding="5")
        log_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20, font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.log_text.tag_config("INFO", foreground="blue")
        self.log_text.tag_config("SUCCESS", foreground="green")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("WARNING", foreground="orange")

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        main_frame.rowconfigure(6, weight=1)

    def _tooltip(self, widget, text):
        def enter(event):
            self.status_var.set(text)
        def leave(event):
            self.status_var.set("就绪")
        widget.bind('<Enter>', enter)
        widget.bind('<Leave>', leave)

    def toggle_keystore(self):
        if self.auto_generate_key.get():
            self.keystore_path.set("")

    def detect_apk_scheme(self, apk_path):
        self.log(f"[+] 检测 APK 签名方案: {apk_path}", "INFO")
        cmd = self.tools.get_cmd('apksigner')
        if not cmd:
            self.log("  ⚠ apksigner 不可用，使用默认方案 v2+v3+v4", "WARNING")
            self.detected_scheme.set("v2+v3+v4")
            self.has_v1 = False
            self.has_v2 = True
            self.has_v3 = True
            self.has_v4 = False
            self.scheme_label.config(text="检测到签名: 未知 (默认 v2+v3+v4)", foreground="orange")
            return

        cmd += ['verify', '-v', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            self.log(f"  ⚠ 检测失败: {result.stderr}", "WARNING")
            self.detected_scheme.set("v2+v3+v4")
            self.has_v1 = False
            self.has_v2 = True
            self.has_v3 = True
            self.has_v4 = False
            self.scheme_label.config(text="检测到签名: 未知 (默认 v2+v3+v4)", foreground="orange")
            return

        output = result.stdout
        self.has_v1 = "Verified using v1 scheme" in output
        self.has_v2 = "Verified using v2 scheme" in output
        self.has_v3 = "Verified using v3 scheme" in output
        self.has_v4 = "Verified using v4 scheme" in output

        if self.has_v4:
            scheme = "v4"
        elif self.has_v3 and self.has_v2:
            scheme = "v2+v3+v4"
        elif self.has_v2:
            scheme = "v2"
        elif self.has_v1:
            scheme = "v1"
        else:
            scheme = "v2+v3+v4"

        self.detected_scheme.set(scheme)
        parts = []
        if self.has_v1: parts.append("V1")
        if self.has_v2: parts.append("V2")
        if self.has_v3: parts.append("V3")
        if self.has_v4: parts.append("V4")
        sig_text = "+".join(parts) if parts else "无签名"
        self.scheme_label.config(text=f"检测到签名: {sig_text} (使用: {scheme})", foreground="green")
        self.log(f"  ✓ 检测到签名方案: {sig_text}", "SUCCESS")

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
        self.btn_sign.config(state=state)
        self.btn_verify.config(state=state)

    def run_sign(self, apk=None):
        if apk is None:
            apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择有效的 APK 文件")
            return
        self.set_buttons_state("disabled")
        self.progress.start()
        self.status_var.set("执行中...")
        thread = threading.Thread(target=self._do_sign, args=(apk,))
        thread.daemon = True
        thread.start()

    def _do_sign(self, apk):
        try:
            self._full_process(apk)
        except Exception as e:
            self.log(f"❌ 执行出错: {str(e)}", "ERROR")
        finally:
            self.root.after(0, self._task_done)

    def _task_done(self):
        self.progress.stop()
        self.set_buttons_state("normal")
        self.status_var.set("就绪")

    def _get_keystore(self):
        if self.auto_generate_key.get():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            keystore = self.work_dir / f"test_keystore_{timestamp}.jks"
            self._generate_keystore(keystore)
            return keystore
        else:
            keystore = Path(self.keystore_path.get())
            if not keystore.exists():
                self.log("❌ 密钥库不存在", "ERROR")
                raise RuntimeError("密钥库不存在")
            return keystore

    def _full_process(self, apk):
        self.log("="*50, "INFO")
        self.log("🔧 修改内容+签名流程", "INFO")
        self.log("="*50, "INFO")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keystore = self._get_keystore()

        extracted = self.work_dir / f"extracted_{timestamp}"
        self._unzip_apk(apk, extracted)

        # 添加 test.txt 到指定路径
        test_file = extracted / "assets" / "test.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("MODIFIED BY APK_RESIGNER", encoding="utf-8")
        self.log(f"  ✓ 已添加 test.txt 到 assets/", "SUCCESS")

        unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
        self._rezip_apk(extracted, unsigned)

        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(unsigned, aligned)

        scheme = self.detected_scheme.get()
        self._sign_with_scheme(aligned, keystore, scheme)

        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self.log(f"📋 签名方案: {scheme}", "INFO")
        self.log(f"🔑 密钥库: {keystore}", "INFO")
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: messagebox.showinfo("完成", f"签名替换完成！\n\n最终 APK:\n{final}\n\n签名方案: {scheme}\n密钥库:\n{keystore}"))

        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self.log(f"📋 签名方案: {scheme}", "INFO")
        self.log(f"🔑 密钥库: {keystore}", "INFO")
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: messagebox.showinfo("完成", f"签名替换完成！\n\n最终 APK:\n{final}\n\n签名方案: {scheme}\n密钥库:\n{keystore}"))

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

    def _unzip_apk(self, apk, out_dir):
        self.log(f"[+] 解压 APK...")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(apk, 'r') as zf:
            zf.extractall(out_dir)
        self.log(f"  ✓ 解压完成", "SUCCESS")

    def _rezip_apk(self, source_dir, output_apk):
        self.log(f"[+] 重新打包 APK...")
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

    def _sign_with_scheme(self, apk_path, keystore, scheme="v2+v3+v4"):
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
        help_text = """APK 签名替换工具 - 使用说明

版本：v1.7.4  |  适用：GB 44495 / R155 测试

一、工具概述

APK 签名替换工具是一款用于 APK 签名完整性测试的便携工具，适用于 GB 44495（汽车信息安全技术要求）和 R155（汽车网络安全）等法规的 OTA 安全测试场景。

特点：
  零依赖：无需安装 Android SDK、JDK，所有工具内置
  单文件 EXE：复制到任何 Windows 电脑都能直接运行
  自动检测签名：自动识别 APK 的签名方案（V1/V2/V3/V4）并保持一致
  懒加载加密：缺少 cryptography 模块时不崩溃，自动降级
  GUI 界面：可视化操作，无需命令行

二、功能说明

🔧 修改内容+签名
  功能：自动检测原 APK 的签名方案 → 直接解压 APK（无需反编译）
        → 在 assets/ 目录添加 test.txt 标记文件 → 重新打包 → zipalign 对齐
        → 按原签名方案重新签名（新密钥）
  输出：内容被修改 + 签名被替换的 APK
  用途：测试系统对"篡改 APK"的响应（内容+签名双重校验失败）

🔍 验证签名
  功能：检查 APK 的签名状态（V1/V2/V3/V4）和对齐情况
  输出：不生成新 APK，仅显示签名信息
  用途：检查 APK 当前签名状态

三、使用指南

测试场景：完整性校验失败
  1. 点击"浏览..."选择原始 APK 文件
  2. 勾选"自动生成测试密钥"
  3. 点击 🔧 修改内容+签名
  4. 等待处理完成，获取输出 APK
  5. 在目标系统尝试安装输出 APK
  6. 预期结果：系统拒绝安装，并记录安全事件

测试场景：验证签名状态
  1. 选择 APK 文件
  2. 点击 🔍 验证签名
  3. 查看日志窗口显示的签名信息

四、签名方案说明

  V1（Android 5.0-6.0）：JAR 签名，META-INF/ 下文件
  V2（Android 7.0+）：APK Signing Block，整包签名
  V3（Android 9.0+）：V2 基础上支持密钥轮换
  V4（Android 11.0+）：V3 基础上支持增量签名

五、常见问题

  Q: 提示缺少 cryptography 模块？
  A: 工具会自动降级，无需手动安装。如需完整功能，运行 pip install cryptography。

  Q: 密钥库生成失败（rc=2）？
  A: 检查 _tools/java/bin/ 下是否包含 jli.dll、java.dll、jvm.dll。
     如缺失，运行 collect_tools.py 自动收集，或从系统 JDK 复制。

  Q: 签名后的 APK 无法安装？
  A: 这是预期行为。签名已替换，原完整性校验会失败。
     如需安装，需关闭系统签名校验或使用测试设备。

六、法规测试对应

  GB 44495 7.3 OTA 安全要求：验证 OTA 包完整性校验机制
  R155 7.5 软件更新：验证签名验证机制

  测试方法：
    1. 使用本工具生成篡改后的 APK（🔧 修改内容+签名）
    2. 尝试在目标系统安装/更新
    3. 观察系统是否拒绝并记录安全事件
"""
        messagebox.showinfo("使用说明", help_text)


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
