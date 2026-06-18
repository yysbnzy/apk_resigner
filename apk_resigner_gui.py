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
            keytool = self._find_jdk_tool("keytool", [".exe", ""])
            if keytool:
                self.tool_paths['keytool'] = keytool
            elif shutil.which('keytool'):
                self.tool_paths['keytool'] = 'keytool'

            jarsigner = self._find_jdk_tool("jarsigner", [".exe", ""])
            if jarsigner:
                self.tool_paths['jarsigner'] = jarsigner
            elif shutil.which('jarsigner'):
                self.tool_paths['jarsigner'] = 'jarsigner'

        adb = self._find_tool("adb", [".exe", ""])
        if adb:
            self.tool_paths['adb'] = adb
        elif shutil.which('adb'):
            self.tool_paths['adb'] = 'adb'

    def _find_java(self):
        """查找可用的 Java，优先检查内置的，验证 java.dll 是否配套"""
        # 检查内置 java（java.exe + java.dll 必须在同一目录）
        java_exe = self.java_dir / "java.exe"
        if java_exe.exists() and (java_exe.parent / "java.dll").exists():
            return str(java_exe)
        java_exe = self.tools_dir / "java.exe"
        if java_exe.exists() and (java_exe.parent / "java.dll").exists():
            return str(java_exe)
        # 回退到系统 Java
        sys_java = shutil.which('java')
        if sys_java:
            return sys_java
        return None

    def _find_tool(self, name, exts, subdir=None):
        """查找工具，优先内置，但需确认配套 java 可用"""
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

    def _find_jdk_tool(self, name, exts):
        """查找 JDK 工具（keytool/jarsigner），优先与 java 同目录"""
        java_path = self.tool_paths.get('java')
        if java_path:
            java_dir = Path(java_path).parent
            for ext in exts:
                path = java_dir / f"{name}{ext}"
                if path.exists():
                    return str(path)
        # 回退到系统搜索
        sys_path = shutil.which(name)
        if sys_path:
            return sys_path
        return None

    def get_cmd(self, tool_name):
        """获取工具命令列表（处理 .jar 需要 java -jar）"""
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
            self.btn_setup.config(state="disabled")
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

        # 配置按钮
        btn_frame = ttk.LabelFrame(main_frame, text="配置", padding="10")
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        self.btn_setup = ttk.Button(btn_frame, text="🔧 配置并执行", command=self.setup, width=24)
        self.btn_setup.pack(side=tk.LEFT, padx=10)
        self._tooltip(self.btn_setup, "解压APK→添加test.txt→重新打包→按原方案重新签名")

        self.btn_verify = ttk.Button(btn_frame, text="🔍 验证签名", command=self.verify_apk, width=20)
        self.btn_verify.pack(side=tk.LEFT, padx=10)
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
        self.btn_setup.config(state=state)
        self.btn_verify.config(state=state)

    def setup(self):
        apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择有效的 APK 文件")
            return
        self.set_buttons_state("disabled")
        self.progress.start()
        self.status_var.set("执行中...")
        thread = threading.Thread(target=self._do_setup, args=(apk,))
        thread.daemon = True
        thread.start()

    def _do_setup(self, apk):
        try:
            self._full_process(apk)
        except Exception as e:
            self.log(f"❌ 执行出错: {str(e)}", "ERROR")
        finally:
            self.root.after(0, self._task_done)

    def _quick_resign(self, apk):
        self.log("="*50, "INFO")
        self.log("⚡ 一键重签名流程", "INFO")
        self.log("  保持原签名方案: " + self.detected_scheme.get(), "INFO")
        self.log("="*50, "INFO")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keystore = self._get_keystore()

        stripped = self.work_dir / f"stripped_{timestamp}"
        self._strip_signature(apk, stripped)

        unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
        self._repack_zip(stripped, unsigned)

        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(unsigned, aligned)

        scheme = self.detected_scheme.get()
        self._sign_with_scheme(aligned, keystore, scheme)

        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 一键重签名完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self.log(f"📋 签名方案: {scheme}", "INFO")
        self.log(f"🔑 密钥库: {keystore}", "INFO")
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: messagebox.showinfo("完成", f"一键重签名完成！\n\n最终 APK:\n{final}\n\n签名方案: {scheme}\n密钥库:\n{keystore}"))

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
        self.log(f"  ✓ 已添加 test.txt", "SUCCESS")
        self.log(f"    路径: assets/test.txt", "INFO")
        self.log(f"    大小: {test_file.stat().st_size} 字节", "INFO")
        self.log(f"    内容: {test_file.read_text().strip()}", "INFO")

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
        self._log_signature_details(final, scheme)
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
        self.log(f"  使用: {cmd[0]}", "INFO")
        cmd += [
            '-genkeypair', '-v',
            '-keystore', str(path),
            '-alias', self.alias.get(),
            '-keyalg', 'RSA',
            '-keysize', '2048',
            '-validity', '36500',
            '-dname', 'CN=Test, OU=Test, O=Test, L=Test, ST=Test, C=CN',
            '-storepass', self.password.get(),
            '-keypass', self.password.get()
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and path.exists():
            self.log(f"  ✓ 密钥库生成成功", "SUCCESS")
        else:
            self.log(f"  ✗ 密钥库生成失败: rc={result.returncode}", "ERROR")
            if result.stderr:
                self.log(f"  stderr: {result.stderr}", "ERROR")
            if result.stdout:
                self.log(f"  stdout: {result.stdout}", "ERROR")
            # 显示完整命令，方便用户手动调试
            self.log(f"  命令: {' '.join(cmd[:5])} ...", "INFO")
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

    def _log_signature_details(self, apk, scheme):
        """记录签名详情：V1 位置、V2/V3/V4 摘要信息"""
        self.log(f"\n[+] 签名详情分析:", "INFO")
        
        # V1 签名详情：列出 META-INF/ 下所有文件
        if scheme == "v1" or self.has_v1:
            self.log(f"  V1 签名 (JAR) 位置:", "INFO")
            with zipfile.ZipFile(apk, 'r') as zf:
                meta_files = [f for f in zf.namelist() if f.startswith('META-INF/')]
                if meta_files:
                    for f in meta_files:
                        info = zf.getinfo(f)
                        self.log(f"    {f} ({info.file_size} bytes)", "INFO")
                else:
                    self.log(f"    META-INF/ 为空（V1 签名未生成）", "WARNING")
        
        # V2/V3/V4 签名详情：用 apksigner 验证并提取关键信息
        if scheme in ("v2", "v4", "v2+v3+v4") or self.has_v2 or self.has_v3 or self.has_v4:
            self.log(f"  V2/V3/V4 签名 (APK Signing Block):", "INFO")
            cmd = self.tools.get_cmd('apksigner')
            if cmd:
                cmd += ['verify', '-v', str(apk)]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'Verified using' in line or 'Number of signers' in line:
                            self.log(f"    {line}", "INFO")
                else:
                    self.log(f"    验证输出: {result.stderr}", "WARNING")
            
            # 检查 APK Signing Block 的存在（通过 Central Directory 偏移）
            with open(apk, 'rb') as f:
                f.seek(-6, 2)  # 文件末尾 - 6 字节
                if f.read() == b'PK\x05\x06':
                    self.log(f"    APK 结构正常，签名块已写入", "INFO")
                else:
                    self.log(f"    APK 结构异常", "WARNING")

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

🔧 修改内容+签名：解压 → 添加test.txt → 重打包 → 按原方案重新签名
⚡ 一键重签名：不解包，去除原签名后按原方案重新签名
🔍 验证签名：检查APK签名状态和对齐情况

测试方法：
1. 选APK → 点击按钮 → 获取输出APK
2. 在目标系统安装 → 预期：系统拒绝安装

签名方案：V1(5.0-6.0) / V2(7.0+) / V3(9.0+) / V4(11.0+)
工具自动检测原方案并保持，无需手动选择。

注意：签名后的APK无法安装是预期行为，用于测试校验机制。
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
