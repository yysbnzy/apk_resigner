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

# 新增 ADB 模块导入
try:
    from adb_manager import ADBManager, DeviceInfo, PackageInfo, ExportResult, ADBError
    from backup_manager import BackupManager, BackupInfo, BackupResult
    from install_manager import InstallManager, InstallResult, InstallLog
    ADB_AVAILABLE = True
except ImportError:
    ADB_AVAILABLE = False

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
        self.root.title("APK 签名替换工具 v2.2.1")
        self.root.geometry("900x800")
        self.root.minsize(800, 700)

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

        # ────────────────────────────────────────
        # 新增 ADB 相关初始化
        # ────────────────────────────────────────
        self.adb_manager = None
        self.backup_manager = None
        self.install_manager = None
        self.selected_device = None
        self.selected_package = tk.StringVar()
        self.scanned_packages = []  # 扫描到的应用列表
        self._init_adb_modules()

        self.build_ui()
        self.log(self.tools.get_info(), "INFO")

        missing = self.tools.check_all()
        if missing:
            self.log(f"\n⚠️ 缺少必需工具: {', '.join(missing)}", "WARNING")
            self.log("纯 Python 模式已启用：V1-only 签名可用，无需 JDK/Android SDK", "INFO")
            self.pure_python_mode = True
            self.status_var.set(f"纯 Python 模式 (缺少: {', '.join(missing)})")
        else:
            self.status_var.set("就绪 (全部内置)")

    def _init_adb_modules(self):
        """初始化 ADB 相关模块"""
        if not ADB_AVAILABLE:
            print("ADB 模块未加载（adb_manager.py 不存在）")
            return
        
        try:
            self.adb_manager = ADBManager(self.tools)
            self.backup_manager = BackupManager()
            self.install_manager = InstallManager(self.adb_manager)
            print("ADB 模块初始化完成")
        except Exception as e:
            print(f"ADB 模块初始化失败: {e}")

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="APK 签名替换工具 v2.2.4", font=("Microsoft YaHei", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky=tk.W)

        self.btn_help = ttk.Button(main_frame, text="❓ 使用说明", command=self.show_help, width=12)
        self.btn_help.grid(row=0, column=2, pady=(0, 5), sticky=tk.E)

        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="10")
        file_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
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

        self.progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=2)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        # Notebook 放在 row=6，与状态栏相邻，分配剩余空间
        main_frame.rowconfigure(6, weight=1)

        # ────────────────────────────────────────
        # 新增 ADB Notebook 标签页
        # ────────────────────────────────────────
        if ADB_AVAILABLE:
            self._build_adb_notebook(main_frame, 6)
        else:
            # ADB不可用时的提示
            ttk.Label(main_frame, text="ADB模块未加载", foreground="gray").grid(row=6, column=0, columnspan=3, pady=10)

    def _build_adb_notebook(self, main_frame, row=8):
        """构建 ADB 相关 Notebook 标签页"""
        # Notebook 容器
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=row, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        main_frame.rowconfigure(row, weight=1)

        # Tab 5: 本地签名（移到最前面）
        config_tab = ttk.Frame(notebook, padding="10")
        notebook.add(config_tab, text="📝 本地APK签名")
        self._build_config_tab(config_tab)

        # Tab 1: 设备连接
        device_tab = ttk.Frame(notebook, padding="10")
        notebook.add(device_tab, text="📱 ADB设备")
        self._build_device_tab(device_tab)

        # Tab 2: 应用列表
        app_tab = ttk.Frame(notebook, padding="10")
        notebook.add(app_tab, text="📦 应用列表")
        self._build_app_tab(app_tab)

        # Tab 3: 备份还原
        backup_tab = ttk.Frame(notebook, padding="10")
        notebook.add(backup_tab, text="💾 备份还原")
        self._build_backup_tab(backup_tab)

        # Tab 4: 操作日志（扩展现有日志）
        log_tab = ttk.Frame(notebook, padding="10")
        notebook.add(log_tab, text="📝 ADB日志")
        self._build_adb_log_tab(log_tab)
        
        # 保存 notebook 引用并绑定页签切换事件
        self._notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

    def _build_config_tab(self, parent):
        """构建本地APK签名标签页（使用主界面已选的APK文件）"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        
        # 主容器
        main_container = ttk.Frame(parent)
        main_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(0, weight=0)  # 本地签名区域
        main_container.rowconfigure(1, weight=0)  # 工具区域
        main_container.rowconfigure(2, weight=1)  # 说明区域占满剩余
        
        # ── 本地APK签名 ──
        local_frame = ttk.LabelFrame(main_container, text="本地 APK 签名", padding="10")
        local_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        local_frame.columnconfigure(1, weight=1)
        
        # 提示使用主界面已选的APK
        ttk.Label(local_frame, text="使用主界面选择的APK文件", foreground="gray").grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)
        self.local_apk_path_label = ttk.Label(local_frame, text="当前APK: 未选择", foreground="blue", wraplength=700)
        self.local_apk_path_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)
        
        # 绑定主界面apk_path变化，自动更新显示
        self.local_apk_var = tk.StringVar()
        def update_local_apk_label(*args):
            path = self.apk_path.get()
            self.local_apk_var.set(path)
            if path:
                self.local_apk_path_label.config(text=f"当前APK: {path}", foreground="green")
            else:
                self.local_apk_path_label.config(text="当前APK: 未选择", foreground="blue")
        self.apk_path.trace_add("write", update_local_apk_label)
        
        ttk.Label(local_frame, text="签名方案:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.local_scheme_var = tk.StringVar(value="v2+v3+v4")
        scheme_combo = ttk.Combobox(local_frame, textvariable=self.local_scheme_var, 
                                    values=["v1", "v2", "v2+v3", "v2+v3+v4", "v4"], 
                                    state="readonly", width=15)
        scheme_combo.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        ttk.Label(local_frame, text="密钥库:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.local_keystore_var = tk.StringVar()
        ttk.Entry(local_frame, textvariable=self.local_keystore_var, state="readonly").grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        ttk.Button(local_frame, text="浏览...", command=self._browse_local_keystore).grid(row=3, column=2, padx=5, pady=5)
        
        ttk.Checkbutton(local_frame, text="自动生成测试密钥", variable=self.auto_generate_key).grid(row=4, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)
        
        # 签名按钮
        btn_frame = ttk.Frame(local_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)
        
        ttk.Button(btn_frame, text="🔧 修改内容+签名", 
                   command=lambda: self._local_full_process(), 
                   width=20).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⚡ 快速签名替换", 
                   command=lambda: self._local_quick_sign(), 
                   width=20).pack(side=tk.LEFT, padx=5)
        
        # ── 签名工具 ──
        tools_frame = ttk.LabelFrame(main_container, text="签名工具", padding="10")
        tools_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Button(tools_frame, text="🔍 验证签名", 
                   command=self._verify_apk_signature, 
                   width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(tools_frame, text="📊 签名对比", 
                   command=self._compare_signatures, 
                   width=15).pack(side=tk.LEFT, padx=5)
        
        # ── 说明 ──
        help_frame = ttk.LabelFrame(main_container, text="说明", padding="10")
        help_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        help_text = """本地签名功能：不连接ADB设备时，直接使用主界面选择的APK文件进行重签名。
• 修改内容+签名：反编译APK，修改内容后重新打包并签名
• 快速签名替换：不解包，直接去除原签名并重新签名
• 支持 V1/V2/V3/V4 签名方案"""
        ttk.Label(help_frame, text=help_text, justify=tk.LEFT, wraplength=650).pack(anchor=tk.W)
    
    def _browse_local_apk(self):
        """浏览本地APK文件（已废弃，使用主界面文件选择）"""
        pass
    
    def _browse_local_keystore(self):
        """浏览密钥库文件"""
        path = filedialog.askopenfilename(
            title="选择密钥库",
            filetypes=[("JKS/Keystore", "*.jks *.keystore"), ("所有文件", "*.*")]
        )
        if path:
            self.local_keystore_var.set(path)
            self.keystore_path.set(path)
    
    def _local_full_process(self):
        """本地完整处理（修改内容+签名）"""
        apk = self.local_apk_var.get()
        if not apk:
            messagebox.showwarning("提示", "请先选择 APK 文件")
            return
        self._full_process(apk)
    
    def _local_quick_sign(self):
        """本地快速签名替换（后台线程执行）"""
        apk = self.local_apk_var.get()
        if not apk:
            messagebox.showwarning("提示", "请先选择 APK 文件")
            return
        
        # 在后台线程执行，避免阻塞UI
        thread = threading.Thread(target=self._quick_sign_replace, args=(apk,))
        thread.daemon = True
        thread.start()
    
    def _quick_sign_replace(self, apk_path):
        """快速签名替换（不解包，直接去除原签名+重新签名）"""
        try:
            self.status_var.set("正在快速签名替换...")
            self.progress.start()
            self.log("[+] 快速签名替换（不解包）", "INFO")
            
            apk_path = Path(apk_path)
            if not apk_path.exists():
                self._show_error_dialog("错误", f"APK文件不存在: {apk_path}")
                return
            
            # 使用 QuickSignReplacer 执行快速签名替换
            from quick_sign_replace import QuickSignReplacer
            
            # 创建工作目录
            work_dir = self.work_dir / "quick_sign"
            work_dir.mkdir(parents=True, exist_ok=True)
            
            replacer = QuickSignReplacer(work_dir)
            
            # 获取签名方案
            scheme = self.local_scheme_var.get() if hasattr(self, 'local_scheme_var') else "v2+v3+v4"
            v1_only = (scheme == "v1")
            
            # 执行快速签名替换
            final_apk = replacer.quick_replace(
                original_apk=apk_path,
                keystore_path=self.keystore_path.get() if self.keystore_path.get() else None,
                v1_only=v1_only
            )
            
            if final_apk and Path(final_apk).exists():
                self.log(f"[✓] 快速签名替换完成: {final_apk}", "SUCCESS")
                self.status_var.set(f"快速签名替换完成: {Path(final_apk).name}")
                
                # 显示结果对话框
                self._show_info_dialog(
                    "完成",
                    f"快速签名替换完成！\n\n"
                    f"原始APK: {apk_path.name}\n"
                    f"新签名APK: {Path(final_apk).name}\n\n"
                    f"文件位置: {final_apk}"
                )
            else:
                self.log("[✗] 快速签名替换失败", "ERROR")
                self._show_error_dialog("错误", "快速签名替换失败，请检查日志")
                
        except Exception as e:
            self.log(f"[✗] 快速签名替换异常: {e}", "ERROR")
            self._show_error_dialog("错误", f"快速签名替换失败: {e}")
        finally:
            self.progress.stop()
            self.status_var.set("就绪")
    
    def _verify_apk_signature(self):
        """验证APK签名"""
        apk = self.local_apk_var.get()
        if not apk:
            messagebox.showwarning("提示", "请先选择 APK 文件")
            return
        self._verify_signature(apk)
    
    def _compare_signatures(self):
        """对比签名"""
        messagebox.showinfo("签名对比", "请选择两个APK文件进行对比")

    def _build_device_tab(self, parent):
        """构建设备连接标签页"""
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # 左侧：设备列表
        left_frame = ttk.LabelFrame(parent, text="设备列表", padding="5")
        left_frame.grid(row=0, column=0, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5)
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

        # 设备列表 Treeview
        columns = ('serial', 'state', 'model')
        self.device_tree = ttk.Treeview(left_frame, columns=columns, show='headings', height=8)
        self.device_tree.heading('serial', text='序列号')
        self.device_tree.heading('state', text='状态')
        self.device_tree.heading('model', text='型号')
        self.device_tree.column('serial', width=120)
        self.device_tree.column('state', width=80)
        self.device_tree.column('model', width=150)
        self.device_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 滚动条
        vsb = ttk.Scrollbar(left_frame, orient="vertical", command=self.device_tree.yview)
        vsb.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.device_tree.configure(yscrollcommand=vsb.set)

        # 设备列表按钮
        btn_frame = ttk.Frame(left_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        ttk.Button(btn_frame, text="刷新", command=self._refresh_devices, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="连接", command=self._connect_device, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="断开", command=self._disconnect_device, width=12).pack(side=tk.LEFT, padx=2)

        # 右侧：设备详情
        right_frame = ttk.LabelFrame(parent, text="设备详情", padding="10")
        right_frame.grid(row=0, column=1, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)

        # 状态指示器
        self.device_status_label = ttk.Label(right_frame, text="未连接", font=("Microsoft YaHei", 12, "bold"), foreground="red")
        self.device_status_label.grid(row=0, column=0, sticky=tk.W, pady=5)

        # 详情文本框
        self.device_info_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, height=10, font=("Consolas", 9))
        self.device_info_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.device_info_text.insert(tk.END, "点击「刷新」查看已连接设备\n")
        self.device_info_text.config(state="disabled")

    def _build_app_tab(self, parent):
        """构建应用列表标签页"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)     # 列表区域占满剩余空间

        # 顶部控制栏（包含操作按钮，上移）
        ctrl_frame = ttk.Frame(parent)
        ctrl_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)

        # 标签页切换
        self.app_tab_var = tk.StringVar(value="third_party")
        ttk.Radiobutton(ctrl_frame, text="第三方应用", variable=self.app_tab_var, 
                       value="third_party", command=self._switch_app_tab).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(ctrl_frame, text="系统预装", variable=self.app_tab_var,
                       value="system", command=self._switch_app_tab).pack(side=tk.LEFT, padx=5)

        # 搜索框
        ttk.Label(ctrl_frame, text="搜索:").pack(side=tk.LEFT, padx=(20, 5))
        self.app_search_var = tk.StringVar()
        ttk.Entry(ctrl_frame, textvariable=self.app_search_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="搜索", command=self._filter_apps, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl_frame, text="扫描", command=self._scan_apps, width=10).pack(side=tk.LEFT, padx=10)

        # 操作按钮（上移到列表上方）
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # 左侧：主要操作
        ttk.Button(btn_frame, text="一键处理", command=self._one_click_process, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="仅导出", command=self._export_only, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="详情", command=self._show_app_details, width=10).pack(side=tk.LEFT, padx=5)
        
        # 右侧：安装操作（签名完成后启用）
        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.RIGHT, padx=10, fill=tk.Y)
        
        self.btn_install_overwrite = ttk.Button(btn_frame, text="覆盖安装", 
                                                 command=self._install_overwrite_signed, 
                                                 width=15, state="disabled")
        self.btn_install_overwrite.pack(side=tk.RIGHT, padx=5)
        
        self.btn_install_uninstall = ttk.Button(btn_frame, text="卸载后安装", 
                                                 command=self._install_uninstall_signed, 
                                                 width=15, state="disabled")
        self.btn_install_uninstall.pack(side=tk.RIGHT, padx=5)
        
        self.btn_export_signed = ttk.Button(btn_frame, text="导出签名APK", 
                                             command=self._export_signed_apk, 
                                             width=15, state="disabled")
        self.btn_export_signed.pack(side=tk.RIGHT, padx=5)
        
        # 当前签名后的APK路径
        self.signed_apk_path = None
        self.current_package_name = None

        # 应用列表 Treeview
        columns = ('name', 'package', 'version', 'type', 'path')
        self.app_tree = ttk.Treeview(parent, columns=columns, show='headings', height=12)
        self.app_tree.heading('name', text='应用名称')
        self.app_tree.heading('package', text='包名')
        self.app_tree.heading('version', text='版本')
        self.app_tree.heading('type', text='类型')
        self.app_tree.heading('path', text='路径')
        self.app_tree.column('name', width=100)
        self.app_tree.column('package', width=200)
        self.app_tree.column('version', width=60)
        self.app_tree.column('type', width=60)
        self.app_tree.column('path', width=300)
        self.app_tree.grid(row=2, column=0, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 滚动条
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.app_tree.yview)
        vsb.grid(row=2, column=1, rowspan=2, sticky=(tk.N, tk.S))
        self.app_tree.configure(yscrollcommand=vsb.set)

    def _build_backup_tab(self, parent):
        """构建备份还原标签页"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # 顶部控制栏（包含操作按钮，上移）
        top_frame = ttk.Frame(parent)
        top_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(top_frame, text="应用:").pack(side=tk.LEFT, padx=5)
        self.backup_package_var = tk.StringVar()
        ttk.Combobox(top_frame, textvariable=self.backup_package_var, width=30, state="readonly").pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="🔄 刷新", command=self._refresh_backups, width=10).pack(side=tk.LEFT, padx=10)

        # 操作按钮（上移到列表上方）
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)

        ttk.Button(btn_frame, text="♻️ 还原选中", command=self._restore_selected_backup, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ 删除", command=self._delete_selected_backup, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🧹 清理旧备份", command=self._cleanup_old_backups, width=15).pack(side=tk.LEFT, padx=5)
        
        # 备份列表 Treeview
        columns = ('time', 'device', 'version', 'size', 'actions')
        self.backup_tree = ttk.Treeview(parent, columns=columns, show='headings', height=10)
        self.backup_tree.heading('time', text='备份时间')
        self.backup_tree.heading('device', text='设备')
        self.backup_tree.heading('version', text='版本')
        self.backup_tree.heading('size', text='大小')
        self.backup_tree.heading('actions', text='操作')
        self.backup_tree.column('time', width=150)
        self.backup_tree.column('device', width=120)
        self.backup_tree.column('version', width=80)
        self.backup_tree.column('size', width=80)
        self.backup_tree.column('actions', width=150)
        self.backup_tree.grid(row=2, column=0, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 自动刷新备份列表
        self.root.after(100, self._refresh_backups)

    def _build_adb_log_tab(self, parent):
        """构建 ADB 操作日志标签页"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.adb_log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, height=15, font=("Consolas", 9))
        self.adb_log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.adb_log_text.tag_config("INFO", foreground="blue")
        self.adb_log_text.tag_config("SUCCESS", foreground="green")
        self.adb_log_text.tag_config("ERROR", foreground="red")
        self.adb_log_text.tag_config("WARNING", foreground="orange")
        self.adb_log_text.tag_config("ADB", foreground="purple")

        ttk.Button(parent, text="🧹 清空", command=self._clear_adb_log, width=10).grid(row=1, column=0, sticky=tk.E, pady=5)

    def _adb_log(self, message, level="INFO"):
        """ADB 专用日志输出（线程安全）"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            # 使用 after 确保在主线程中更新 UI
            self.root.after(0, lambda: self._do_adb_log(timestamp, message, level))
        except Exception:
            pass

    def _on_notebook_tab_changed(self, event):
        """Notebook 页签切换事件处理"""
        notebook = event.widget
        current_tab = notebook.tab(notebook.select(), "text")
        
        # 切换到备份还原页签时自动刷新列表
        if current_tab == "💾 备份还原":
            self._refresh_backups()

    def _do_adb_log(self, timestamp, message, level):
        """实际执行 ADB 日志插入（必须在主线程调用）"""
        try:
            if hasattr(self, 'adb_log_text') and self.adb_log_text:
                self.adb_log_text.insert(tk.END, f"[{timestamp}] [{level}] {message}\n", level)
                self.adb_log_text.see(tk.END)
        except Exception:
            pass

    def _clear_adb_log(self):
        """清空 ADB 日志"""
        self.adb_log_text.delete(1.0, tk.END)

    # ────────────────────────────────────────
    # ADB 设备操作
    # ────────────────────────────────────────

    def _refresh_devices(self):
        """刷新设备列表，如果无已连接设备则自动连接第一个可用设备"""
        if not self.adb_manager:
            self._adb_log("ADB 模块未加载", "ERROR")
            return
        
        self._adb_log("刷新设备列表...")
        self.device_tree.delete(*self.device_tree.get_children())
        
        try:
            devices = self.adb_manager.list_devices()
            self._adb_log(f"发现 {len(devices)} 个设备")
            
            # 记录第一个可用设备，用于自动连接
            first_ready_device = None
            
            for dev in devices:
                state_text = {
                    'device': '[已连接]',
                    'unauthorized': '[未授权]',
                    'offline': '[离线]'
                }.get(dev.state, dev.state)
                
                self.device_tree.insert('', tk.END, values=(
                    dev.serial, state_text, dev.model
                ))
                
                if dev.state == 'unauthorized':
                    self._adb_log(f"设备 {dev.serial} 未授权，请在设备上点击「允许」", "WARNING")
                
                # 记录第一个可用设备
                if dev.is_ready and first_ready_device is None:
                    first_ready_device = dev
            
            # 自动连接：如果没有已选中的设备，且发现了可用设备
            if self.selected_device is None and first_ready_device is not None:
                self._adb_log(f"自动连接设备: {first_ready_device.display_name}")
                try:
                    self.adb_manager.select_device(first_ready_device.serial)
                    self.selected_device = first_ready_device.serial
                    
                    # 更新UI状态
                    self.device_status_label.config(
                        text=f"[已连接]: {first_ready_device.serial}", 
                        foreground="green"
                    )
                    
                    # 获取并显示设备信息
                    info = self.adb_manager.get_device_info()
                    self.device_info_text.config(state="normal")
                    self.device_info_text.delete(1.0, tk.END)
                    for key, value in info.items():
                        self.device_info_text.insert(tk.END, f"{key}: {value}\n")
                    self.device_info_text.config(state="disabled")
                    
                    # 选中树形列表中的该设备
                    for item_id in self.device_tree.get_children():
                        values = self.device_tree.item(item_id, 'values')
                        if values and values[0] == first_ready_device.serial:
                            self.device_tree.selection_set(item_id)
                            self.device_tree.see(item_id)
                            break
                    
                    self._adb_log(f"✅ 已自动连接: {first_ready_device.display_name}")
                    
                except Exception as e:
                    self._adb_log(f"自动连接失败: {e}", "WARNING")
                    # 自动连接失败不弹窗，仅记录日志
        
        except Exception as e:
            self._adb_log(f"刷新失败: {e}", "ERROR")

    def _connect_device(self):
        """连接选中设备"""
        selection = self.device_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择设备")
            return
        
        item = self.device_tree.item(selection[0])
        values = item['values']
        serial = values[0]
        state_text = values[1] if len(values) > 1 else ""
        
        # USB已连接设备直接复用，不走select_device验证
        if '已连接' in state_text:
            self._adb_log(f"USB设备 {serial} 已连接，直接复用")
            self.adb_manager.selected_device = str(serial)
            self.selected_device = str(serial)
            self._update_device_ui_connected(serial)
            return
        
        # 网络ADB或其他状态：走标准连接流程
        try:
            self.adb_manager.select_device(str(serial))
            self.selected_device = str(serial)
            self._update_device_ui_connected(serial)
            
        except Exception as e:
            self._adb_log(f"标准连接失败，尝试降级处理: {e}", "WARNING")
            # 降级：直接设置selected_device
            try:
                self.adb_manager.selected_device = str(serial)
                self.selected_device = str(serial)
                info = self.adb_manager.get_device_info()
                self._update_device_ui_connected(serial, info)
                self._adb_log(f"降级连接成功: {serial}", "SUCCESS")
            except Exception as e2:
                self._adb_log(f"连接失败: {e2}", "ERROR")
                messagebox.showerror("错误", f"连接设备失败: {e2}")

    def _update_device_ui_connected(self, serial, info=None):
        """更新设备连接后的UI状态"""
        if info is None:
            try:
                info = self.adb_manager.get_device_info()
            except Exception:
                info = {}
        
        self.device_status_label.config(text=f"[已连接]: {serial}", foreground="green")
        
        self.device_info_text.config(state="normal")
        self.device_info_text.delete(1.0, tk.END)
        
        for key, value in info.items():
            self.device_info_text.insert(tk.END, f"{key}: {value}\n")
        
        self.device_info_text.config(state="disabled")
        self._adb_log(f"已连接设备: {serial}", "SUCCESS")
        self.status_var.set(f"已连接: {info.get('model', serial)}")

    def _disconnect_device(self):
        """断开当前设备"""
        self.selected_device = None
        if self.adb_manager:
            self.adb_manager.selected_device = None
        
        self.device_status_label.config(text="[未连接]", foreground="red")
        self.device_info_text.config(state="normal")
        self.device_info_text.delete(1.0, tk.END)
        self.device_info_text.insert(tk.END, "点击「刷新」查看已连接设备\n")
        self.device_info_text.config(state="disabled")
        
        self._adb_log("已断开设备连接")
        self.status_var.set("就绪")

    # ────────────────────────────────────────
    # ADB 应用操作
    # ────────────────────────────────────────

    def _scan_apps(self):
        """扫描车机应用"""
        if not self.adb_manager or not self.adb_manager.selected_device:
            messagebox.showwarning("提示", "请先连接设备")
            return
        
        self._adb_log("扫描车机应用...")
        self.app_tree.delete(*self.app_tree.get_children())
        self.scanned_packages = []
        
        try:
            packages = self.adb_manager.scan_packages()
            self.scanned_packages = packages
            
            self._adb_log(f"扫描完成: {len(packages)} 个应用")
            self._refresh_app_tree()
            
        except Exception as e:
            self._adb_log(f"扫描失败: {e}", "ERROR")
            messagebox.showerror("错误", f"扫描应用失败: {e}")

    def _refresh_app_tree(self):
        """刷新应用列表显示"""
        self.app_tree.delete(*self.app_tree.get_children())
        
        filter_type = self.app_tab_var.get()
        keyword = self.app_search_var.get().lower()
        
        for pkg in self.scanned_packages:
            # 类型过滤
            if filter_type == "system" and pkg.app_type != "SYSTEM":
                continue
            if filter_type == "third_party" and pkg.app_type != "THIRD_PARTY":
                continue
            
            # 关键词过滤
            if keyword and keyword not in pkg.name.lower() and keyword not in pkg.apk_path.lower():
                continue
            
            display_name = pkg.name.split('.')[-1] if pkg.name else ""
            type_text = "系统" if pkg.app_type == "SYSTEM" else "第三方"
            
            self.app_tree.insert('', tk.END, values=(
                display_name, pkg.name, pkg.version, type_text, pkg.apk_path
            ))

    def _switch_app_tab(self):
        """切换应用标签页"""
        self._refresh_app_tree()

    def _filter_apps(self):
        """过滤应用"""
        self._refresh_app_tree()

    def _show_app_details(self):
        """显示应用详情"""
        selection = self.app_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择应用")
            return
        
        item = self.app_tree.item(selection[0])
        package_name = item['values'][1]
        
        try:
            details = self.adb_manager.get_package_details(package_name)
            info = f"包名: {package_name}\n"
            for key, value in details.items():
                info += f"{key}: {value}\n"
            messagebox.showinfo("应用详情", info)
        except Exception as e:
            self._adb_log(f"获取详情失败: {e}", "ERROR")

    def _export_only(self):
        """仅导出 APK"""
        selection = self.app_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择应用")
            return
        
        item = self.app_tree.item(selection[0])
        package_name = item['values'][1]
        
        self._adb_log(f"导出应用: {package_name}")
        
        try:
            result = self.adb_manager.export_apk(package_name, self.work_dir)
            if result.success:
                self._adb_log(f"导出成功: {result.base_apk}", "SUCCESS")
                messagebox.showinfo("导出成功", f"APK 已导出到:\n{result.base_apk}")
            else:
                self._adb_log(f"导出失败: {result.error}", "ERROR")
                messagebox.showerror("导出失败", result.error)
        except Exception as e:
            self._adb_log(f"导出异常: {e}", "ERROR")

    def _one_click_process(self):
        """一键处理：导出 → 备份 → 签名 → 安装"""
        selection = self.app_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择应用")
            return
        
        item = self.app_tree.item(selection[0])
        package_name = item['values'][1]
        
        self._adb_log(f"开始一键处理: {package_name}")
        
        # 在后台线程执行
        thread = threading.Thread(target=self._do_one_click_process, args=(package_name,))
        thread.daemon = True
        thread.start()

    def _do_one_click_process(self, package_name):
        """一键处理的后台线程：导出 → 备份 → 签名"""
        # 禁用安装按钮（开始新流程时重置）
        self.root.after(0, self._disable_install_buttons)
        
        try:
            # 1. 导出 APK
            self._adb_log(f"[1/4] 导出 APK...")
            export_result = self.adb_manager.export_apk(package_name, self.work_dir)
            if not export_result.success:
                self._adb_log(f"导出失败: {export_result.error}", "ERROR")
                return
            
            self._adb_log(f"  ✓ 导出成功: {export_result.base_apk}", "SUCCESS")
            
            # 2. 自动备份
            self._adb_log(f"[2/4] 创建备份...")
            device_info = self.adb_manager.get_device_info()
            backup_result = self.backup_manager.create_backup_from_export(export_result, device_info)
            if backup_result.success:
                self._adb_log(f"  ✓ 备份完成: {backup_result.backup_dir}", "SUCCESS")
            else:
                self._adb_log(f"  ⚠️ 备份失败: {backup_result.message}", "WARNING")
                # 继续执行签名，不阻塞流程
            
            # 3. 签名（复用现有方法）
            self._adb_log(f"[3/4] 执行签名...")
            base_apk = export_result.base_apk
            self.apk_path.set(base_apk)
            self.detect_apk_scheme(base_apk)
            
            # 在主线程执行签名（因为 GUI 操作）
            self.root.after(0, lambda: self._run_sign_and_install(base_apk, package_name))
            
        except Exception as e:
            self._adb_log(f"一键处理失败: {e}", "ERROR")
            self.root.after(0, lambda: self._show_error_dialog("错误", f"一键处理失败: {e}"))

    def _run_sign_and_install(self, base_apk, package_name):
        """在主线程执行签名"""
        try:
            # 签名
            self._full_process(base_apk)
            
            # 查找签名后的 APK
            apk_path = Path(base_apk)
            resigned_pattern = f"{apk_path.stem}_resigned_*.apk"
            import glob
            resigned_files = glob.glob(str(apk_path.parent / resigned_pattern))
            
            if not resigned_files:
                self._adb_log("未找到签名后的 APK", "ERROR")
                return
            
            resigned_apk = resigned_files[0]
            self._adb_log(f"  ✓ 签名完成: {resigned_apk}", "SUCCESS")
            
            # 保存签名后的APK路径和包名，启用安装按钮
            self.signed_apk_path = resigned_apk
            self.current_package_name = package_name
            self._enable_install_buttons()
            
            self._adb_log("[4/4] 签名完成，可使用右侧安装按钮进行操作", "SUCCESS")
            self.status_var.set(f"签名完成: {Path(resigned_apk).name}")
            
        except Exception as e:
            self._adb_log(f"签名失败: {e}", "ERROR")
            self._show_error_dialog("错误", f"签名失败: {e}")

    def _enable_install_buttons(self):
        """启用安装操作按钮"""
        try:
            self.btn_install_overwrite.config(state="normal")
            self.btn_install_uninstall.config(state="normal")
            self.btn_export_signed.config(state="normal")
        except Exception:
            pass
    
    def _disable_install_buttons(self):
        """禁用安装操作按钮"""
        try:
            self.btn_install_overwrite.config(state="disabled")
            self.btn_install_uninstall.config(state="disabled")
            self.btn_export_signed.config(state="disabled")
        except Exception:
            pass
    
    def _install_overwrite_signed(self):
        """覆盖安装已签名的APK"""
        if not self.signed_apk_path or not Path(self.signed_apk_path).exists():
            messagebox.showwarning("提示", "请先执行一键处理完成签名")
            return
        self._do_install("overwrite", self.signed_apk_path)
    
    def _install_uninstall_signed(self):
        """卸载后安装已签名的APK"""
        if not self.signed_apk_path or not Path(self.signed_apk_path).exists():
            messagebox.showwarning("提示", "请先执行一键处理完成签名")
            return
        if not self.current_package_name:
            messagebox.showwarning("提示", "无法获取包名")
            return
        self._do_install("uninstall", self.signed_apk_path, self.current_package_name)
    
    def _export_signed_apk(self):
        """导出已签名的APK到指定位置"""
        if not self.signed_apk_path or not Path(self.signed_apk_path).exists():
            messagebox.showwarning("提示", "请先执行一键处理完成签名")
            return
        
        # 弹出保存对话框
        from tkinter import filedialog
        dest = filedialog.asksaveasfilename(
            title="保存签名后的APK",
            defaultextension=".apk",
            initialfile=Path(self.signed_apk_path).name,
            filetypes=[("APK 文件", "*.apk"), ("所有文件", "*.*")]
        )
        if dest:
            import shutil
            shutil.copy2(self.signed_apk_path, dest)
            self._adb_log(f"签名APK已导出到: {dest}", "SUCCESS")
            messagebox.showinfo("导出成功", f"签名APK已保存到:\n{dest}")

    def _show_install_dialog(self, apk_path, package_name):
        """显示安装方式选择对话框（已废弃，使用右侧按钮替代）"""
        pass

    def _do_install(self, mode, apk_path, package_name=None):
        """执行安装"""
        self._adb_log(f"[5/5] 安装测试...")
        
        try:
            if mode == "overwrite":
                result = self.install_manager.install_overwrite(apk_path)
            else:
                result = self.install_manager.install_uninstall_then_install(package_name, apk_path)
            
            # 解析结果
            if result.status == "signature_conflict":
                self._adb_log(f"  ✓ 签名验证拒绝正常 ({result.code})", "SUCCESS")
                self.root.after(0, lambda: messagebox.showinfo("验证通过", 
                    "签名不匹配，安装被拒绝。\n\n这是预期行为，说明签名验证机制工作正常。"))
            elif result.status == "success":
                self._adb_log(f"  ⚠ APK 安装成功，签名验证可能被绕过", "WARNING")
                self.root.after(0, lambda: messagebox.showwarning("异常", 
                    "APK 被成功安装，可能存在签名验证绕过风险！"))
            else:
                self._adb_log(f"  ✗ 安装失败: {result.message}", "ERROR")
                # 打印原始 ADB 输出到日志，便于调试
                if result.raw_output:
                    raw_lines = result.raw_output.strip().split('\n')
                    for line in raw_lines[:10]:  # 最多打印10行，避免刷屏
                        self._adb_log(f"    > {line}", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("安装失败", result.message))
        
        except Exception as e:
            self._adb_log(f"安装异常: {e}", "ERROR")

    # ────────────────────────────────────────
    # 备份操作
    # ────────────────────────────────────────

    def _refresh_backups(self):
        """刷新备份列表"""
        self.backup_tree.delete(*self.backup_tree.get_children())
        
        package = self.backup_package_var.get()
        backups = self.backup_manager.list_backups(package if package else None)
        
        for b in backups:
            # 使用 tags 存储 backup_dir，选中时可直接获取
            self.backup_tree.insert(
                '', tk.END,
                values=(
                    b.display_time, b.device_model, b.version_name, b.display_size, b.package_name
                ),
                tags=(b.backup_dir,)
            )
        
        self._adb_log(f"备份列表: {len(backups)} 个")

    def _restore_selected_backup(self):
        """还原选中的备份"""
        selection = self.backup_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择备份")
            return
        
        # 从 tags 获取 backup_dir
        item = self.backup_tree.item(selection[0])
        backup_dir = item['tags'][0] if item.get('tags') else None
        if not backup_dir:
            messagebox.showerror("错误", "无法获取备份路径")
            return
        
        # 获取备份信息
        backup_info = self.backup_manager.get_backup(backup_dir)
        if not backup_info:
            messagebox.showerror("错误", "备份信息无效或已损坏")
            return
        
        if not messagebox.askyesno(
            "确认还原",
            f"确定要还原此备份？\n\n"
            f"应用: {backup_info.package_name}\n"
            f"版本: {backup_info.version_name}\n"
            f"设备: {backup_info.device_model}\n"
            f"时间: {backup_info.display_time}"
        ):
            return
        
        self._adb_log(f"开始还原备份: {backup_info.package_name}")
        
        # 在后台线程执行还原
        thread = threading.Thread(
            target=self._do_restore,
            args=(backup_dir, backup_info.package_name)
        )
        thread.daemon = True
        thread.start()
    
    def _do_restore(self, backup_dir: str, package_name: str):
        """执行还原的后台线程"""
        try:
            result = self.backup_manager.restore_backup(
                backup_dir,
                self.install_manager
            )
            
            if result.success:
                self._adb_log(f"还原成功: {result.message}", "SUCCESS")
                self.root.after(0, lambda: messagebox.showinfo(
                    "还原成功",
                    f"应用 {package_name} 已还原\n\n{result.message}"
                ))
            else:
                self._adb_log(f"还原失败: {result.message}", "ERROR")
                # 打印原始安装输出到日志，便于调试和取证
                if result.install_output:
                    self._adb_log("=== ADB 原始输出 ===", "ERROR")
                    raw_lines = result.install_output.strip().split('\n')
                    for line in raw_lines:
                        self._adb_log(f"  {line}", "ERROR")
                    self._adb_log("=== 原始输出结束 ===", "ERROR")
                self.root.after(0, lambda: messagebox.showerror(
                    "还原失败",
                    f"应用 {package_name} 还原失败\n\n{result.message}"
                ))
        except Exception as e:
            self._adb_log(f"还原异常: {e}", "ERROR")
            self.root.after(0, lambda: messagebox.showerror("错误", f"还原异常: {e}"))

    def _delete_selected_backup(self):
        """删除选中的备份"""
        selection = self.backup_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择备份")
            return
        
        # 从 tags 获取 backup_dir
        item = self.backup_tree.item(selection[0])
        backup_dir = item['tags'][0] if item.get('tags') else None
        if not backup_dir:
            messagebox.showerror("错误", "无法获取备份路径")
            return
        
        # 获取备份信息用于确认
        backup_info = self.backup_manager.get_backup(backup_dir)
        pkg_name = backup_info.package_name if backup_info else "未知"
        
        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除此备份？\n\n"
            f"应用: {pkg_name}\n"
            f"路径: {backup_dir}\n\n"
            f"删除后无法恢复！"
        ):
            return
        
        self._adb_log(f"删除备份: {backup_dir}")
        
        try:
            success = self.backup_manager.delete_backup(backup_dir)
            if success:
                self._adb_log("备份已删除", "SUCCESS")
                self._refresh_backups()  # 刷新列表
            else:
                self._adb_log("删除失败", "ERROR")
        except Exception as e:
            self._adb_log(f"删除异常: {e}", "ERROR")

    def _cleanup_old_backups(self):
        """清理旧备份"""
        if not messagebox.askyesno("确认", "清理旧备份？"):
            return
        
        try:
            result = self.backup_manager.cleanup_old_backups(keep_count=5, keep_days=30)
            self._adb_log(f"清理完成: 删除 {result['deleted']} 个, 保留 {result['kept']} 个", "SUCCESS")
        except Exception as e:
            self._adb_log(f"清理失败: {e}", "ERROR")

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
        """输出日志到 ADB 日志区域（线程安全，如果 ADB 日志不可用则输出到控制台）"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            # 优先写入 ADB 日志
            self.root.after(0, lambda: self._do_log_to_adb(timestamp, message, level))
        except Exception:
            print(f"[{level}] {message}")

    def _do_log_to_adb(self, timestamp, message, level):
        """将日志写入 ADB 日志区域"""
        try:
            if hasattr(self, 'adb_log_text') and self.adb_log_text:
                self.adb_log_text.insert(tk.END, f"[{timestamp}] [{level}] {message}\n", level)
                self.adb_log_text.see(tk.END)
        except Exception:
            pass

    def _show_error_dialog(self, title, message):
        """显示错误对话框（带防重复机制）"""
        if self._error_dialog_open:
            return
        self._error_dialog_open = True
        try:
            messagebox.showerror(title, message)
        finally:
            self._error_dialog_open = False

    def _show_info_dialog(self, title, message):
        """显示信息对话框（带防重复机制）"""
        if self._error_dialog_open:
            return
        self._error_dialog_open = True
        try:
            messagebox.showinfo(title, message)
        finally:
            self._error_dialog_open = False

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
        self.log("修改内容+签名流程", "INFO")
        self.log("="*50, "INFO")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keystore = self._get_keystore()

        # 复制原 APK
        temp_apk = self.work_dir / f"temp_{timestamp}.apk"
        shutil.copy2(apk, temp_apk)

        # 解压 → 清除旧签名 → 添加 test.txt → 重新打包
        # 避免 zipfile 'a' 模式破坏 V2 签名块位置
        temp_dir = self.work_dir / f"temp_dir_{timestamp}"
        self._unzip_apk(temp_apk, temp_dir)
        
        # 清除旧签名（META-INF）
        meta_dir = temp_dir / "META-INF"
        if meta_dir.exists():
            shutil.rmtree(meta_dir)
            self.log("  已清除旧签名 (META-INF)", "INFO")
        
        # 添加 test.txt
        assets_dir = temp_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        with open(assets_dir / "test.txt", 'w', encoding='utf-8') as f:
            f.write('MODIFIED BY APK_RESIGNER')
        self.log("  已添加 test.txt", "SUCCESS")
        self.log("    路径: assets/test.txt", "INFO")
        
        # 重新打包
        repacked = self.work_dir / f"repacked_{timestamp}.apk"
        self._rezip_apk(temp_dir, repacked)
        
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)

        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(repacked, aligned)

        scheme = self.detected_scheme.get()
        self._sign_with_scheme(aligned, keystore, scheme)

        # 输出到原 APK 同目录
        apk_path = Path(apk)
        final = apk_path.parent / f"{apk_path.stem}_resigned_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n完成！", "SUCCESS")
        self.log(f"最终 APK: {final}", "SUCCESS")
        self.log(f"签名方案: {scheme}", "INFO")
        self.log(f"密钥库: {keystore}", "INFO")
        self._log_signature_details(final, scheme)
        self._compare_signatures(apk, final)
        self.root.after(0, lambda: self._show_info_dialog("完成", f"签名替换完成！\n\n最终 APK:\n{final}\n\n签名方案: {scheme}\n密钥库:\n{keystore}"))

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

    def _sign_with_scheme(self, apk_path, keystore, scheme="v2+v3+v4"):
        """使用 apksigner 签名，签名前自动清除旧 META-INF"""
        apk_path = Path(apk_path)
        
        # 预处理：清除旧的 META-INF（防止残留导致签名冲突）
        self.log(f"[+] 预处理: 清除旧签名...", "INFO")
        temp_dir = self.work_dir / f"sign_prep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            self._unzip_apk(apk_path, temp_dir)
            meta_dir = temp_dir / "META-INF"
            if meta_dir.exists():
                shutil.rmtree(meta_dir)
                self.log("  已清除旧 META-INF", "INFO")
            
            # 重新打包
            cleaned_apk = self.work_dir / f"cleaned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.apk"
            self._rezip_apk(temp_dir, cleaned_apk)
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            # 使用清理后的APK进行签名
            apk_path = cleaned_apk
        except Exception as e:
            self.log(f"  预处理失败，使用原始APK: {e}", "WARNING")
        
        self.log(f"[+] 签名 APK...")
        self.log(f"    签名方案: {scheme}", "INFO")
        cmd = self.tools.get_cmd('apksigner')
        if not cmd:
            raise RuntimeError("apksigner 不可用")
        
        # 基础命令
        base_cmd = [
            'sign',
            '--ks', str(keystore),
            '--ks-key-alias', self.alias.get(),
            '--ks-pass', f'pass:{self.password.get()}',
            '--key-pass', f'pass:{self.password.get()}',
            '--min-sdk-version', '21'
        ]
        
        # 根据方案添加签名参数
        if scheme == "v1":
            base_cmd += [
                '--v1-signing-enabled', 'true',
                '--v2-signing-enabled', 'false',
                '--v3-signing-enabled', 'false',
                '--v4-signing-enabled', 'false'
            ]
        elif scheme == "v2":
            base_cmd += [
                '--v1-signing-enabled', 'false',
                '--v2-signing-enabled', 'true',
                '--v3-signing-enabled', 'false',
                '--v4-signing-enabled', 'false'
            ]
        else:  # v2+v3+v4 或 v4
            base_cmd += [
                '--v1-signing-enabled', 'false',
                '--v2-signing-enabled', 'true',
                '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'true'
            ]
        
        base_cmd.append(str(apk_path))
        cmd += base_cmd
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  签名完成", "SUCCESS")
        else:
            self.log(f"  签名失败: {result.stderr}", "ERROR")
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

    def show_help(self):
        help_text = """APK 签名替换工具 - 使用说明

ADB 模块：
📱 设备连接 - 连接安卓设备，查看设备信息
📦 应用列表 - 扫描车机应用，一键导出+签名
💾 备份还原 - 创建备份，随时还原
📝 ADB日志 - 查看操作日志和签名结果

测试方法：
1. 连接设备 → 扫描应用 → 选择应用
2. 一键处理：导出 → 备份 → 签名 → 安装测试
3. 预期结果：系统拒绝安装（签名不匹配）

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
