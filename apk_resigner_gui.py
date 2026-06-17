#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 签名替换工具 - GUI 版本
基于 tkinter，无需额外依赖，支持打包为 exe 便携使用
"""

import os
import sys
import subprocess
import shutil
import threading
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime

# 尝试导入 tkinter，兼容不同 Python 版本
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
except ImportError:
    import Tkinter as tk
    from Tkinter import ttk, filedialog, messagebox, scrolledtext


class APKResignerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("APK 签名替换工具 - 完整性校验测试")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        # 工作目录
        self.work_dir = Path(os.path.expanduser("~")) / "apk_resign_work"
        self.work_dir.mkdir(exist_ok=True)

        # 变量
        self.apk_path = tk.StringVar()
        self.keystore_path = tk.StringVar()
        self.alias = tk.StringVar(value="testkey")
        self.password = tk.StringVar(value="123456")
        self.scheme = tk.StringVar(value="v2+v3+v4")
        self.modify_manifest = tk.BooleanVar(value=True)
        self.modify_smali = tk.BooleanVar(value=False)
        self.auto_generate_key = tk.BooleanVar(value=True)

        self.build_ui()
        self.check_dependencies()

    def build_ui(self):
        """构建界面"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # ===== 标题 =====
        title_label = ttk.Label(
            main_frame, 
            text="APK 签名替换工具", 
            font=("Microsoft YaHei", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 5))

        subtitle = ttk.Label(
            main_frame,
            text="用于测试 Android 应用完整性校验",
            font=("Microsoft YaHei", 9),
            foreground="gray"
        )
        subtitle.grid(row=1, column=0, columnspan=3, pady=(0, 15))

        # ===== 文件选择区 =====
        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="10")
        file_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        file_frame.columnconfigure(1, weight=1)

        # APK 文件
        ttk.Label(file_frame, text="APK 文件:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(file_frame, textvariable=self.apk_path).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.browse_apk).grid(row=0, column=2, padx=5)

        # 密钥库
        ttk.Label(file_frame, text="密钥库:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(file_frame, textvariable=self.keystore_path, state="readonly").grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.browse_keystore).grid(row=1, column=2, padx=5)

        # 自动生成密钥选项
        ttk.Checkbutton(
            file_frame, 
            text="自动生成测试密钥（不选则需指定密钥库）",
            variable=self.auto_generate_key,
            command=self.toggle_keystore
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5)

        # ===== 参数配置区 =====
        config_frame = ttk.LabelFrame(main_frame, text="签名参数", padding="10")
        config_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=1)

        # 别名
        ttk.Label(config_frame, text="密钥别名:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.alias, width=20).grid(row=0, column=1, sticky=tk.W, padx=5)

        # 密码
        ttk.Label(config_frame, text="密钥密码:").grid(row=0, column=2, sticky=tk.W, padx=5)
        ttk.Entry(config_frame, textvariable=self.password, show="*", width=20).grid(row=0, column=3, sticky=tk.W, padx=5)

        # 签名方案
        ttk.Label(config_frame, text="签名方案:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        scheme_combo = ttk.Combobox(
            config_frame, 
            textvariable=self.scheme,
            values=["v1", "v2", "v3", "v4", "v2+v3+v4"],
            state="readonly",
            width=15
        )
        scheme_combo.grid(row=1, column=1, sticky=tk.W, padx=5)

        # ===== 修改选项区 =====
        modify_frame = ttk.LabelFrame(main_frame, text="修改选项", padding="10")
        modify_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        ttk.Checkbutton(
            modify_frame,
            text="修改 AndroidManifest.xml（添加 [MODIFIED] 标记）",
            variable=self.modify_manifest
        ).grid(row=0, column=0, sticky=tk.W, padx=5)

        ttk.Checkbutton(
            modify_frame,
            text="修改 smali 代码（添加完整性测试标记）",
            variable=self.modify_smali
        ).grid(row=1, column=0, sticky=tk.W, padx=5)

        # ===== 操作按钮区 =====
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)

        self.btn_full = ttk.Button(
            btn_frame, 
            text="🔧 完整流程（反编译+修改+签名）",
            command=lambda: self.run_task("full"),
            width=35
        )
        self.btn_full.pack(side=tk.LEFT, padx=5)

        self.btn_quick = ttk.Button(
            btn_frame,
            text="⚡ 快速签名替换（仅换签名）",
            command=lambda: self.run_task("quick"),
            width=30
        )
        self.btn_quick.pack(side=tk.LEFT, padx=5)

        self.btn_verify = ttk.Button(
            btn_frame,
            text="🔍 验证签名",
            command=self.verify_apk,
            width=15
        )
        self.btn_verify.pack(side=tk.LEFT, padx=5)

        # ===== 进度条 =====
        self.progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        # ===== 日志输出区 =====
        log_frame = ttk.LabelFrame(main_frame, text="执行日志", padding="5")
        log_frame.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            wrap=tk.WORD, 
            height=15,
            font=("Consolas", 10)
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 日志标签颜色
        self.log_text.tag_config("INFO", foreground="blue")
        self.log_text.tag_config("SUCCESS", foreground="green")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("WARNING", foreground="orange")

        # ===== 状态栏 =====
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        # 设置权重
        main_frame.rowconfigure(7, weight=1)

    def toggle_keystore(self):
        """切换密钥库输入状态"""
        if self.auto_generate_key.get():
            self.keystore_path.set("")

    def browse_apk(self):
        """浏览 APK 文件"""
        path = filedialog.askopenfilename(
            title="选择 APK 文件",
            filetypes=[("APK 文件", "*.apk"), ("所有文件", "*.*")]
        )
        if path:
            self.apk_path.set(path)
            self.log(f"已选择 APK: {path}", "INFO")

    def browse_keystore(self):
        """浏览密钥库文件"""
        path = filedialog.askopenfilename(
            title="选择密钥库文件",
            filetypes=[("密钥库", "*.jks *.keystore *.p12"), ("所有文件", "*.*")]
        )
        if path:
            self.keystore_path.set(path)
            self.auto_generate_key.set(False)
            self.log(f"已选择密钥库: {path}", "INFO")

    def log(self, message, level="INFO"):
        """输出日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", level)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def check_dependencies(self):
        """检查依赖工具"""
        tools = ['apktool', 'zipalign', 'apksigner', 'keytool']
        missing = []
        for tool in tools:
            if not shutil.which(tool):
                missing.append(tool)

        if missing:
            self.log(f"⚠️ 缺少工具: {', '.join(missing)}", "WARNING")
            self.log("请安装 Android SDK Build-Tools 和 apktool", "WARNING")
            self.status_var.set(f"缺少依赖: {', '.join(missing)}")
        else:
            self.log("✓ 所有依赖工具已就绪", "SUCCESS")
            self.status_var.set("就绪")

    def set_buttons_state(self, state):
        """设置按钮状态"""
        self.btn_full.config(state=state)
        self.btn_quick.config(state=state)
        self.btn_verify.config(state=state)

    def run_task(self, task_type):
        """运行任务"""
        apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择有效的 APK 文件")
            return

        self.set_buttons_state("disabled")
        self.progress.start()
        self.status_var.set("执行中...")

        # 在新线程中执行
        thread = threading.Thread(target=self._do_task, args=(task_type, apk))
        thread.daemon = True
        thread.start()

    def _do_task(self, task_type, apk):
        """实际执行任务"""
        try:
            if task_type == "full":
                self._full_process(apk)
            elif task_type == "quick":
                self._quick_replace(apk)
        except Exception as e:
            self.log(f"❌ 执行出错: {str(e)}", "ERROR")
        finally:
            self.root.after(0, self._task_done)

    def _task_done(self):
        """任务完成回调"""
        self.progress.stop()
        self.set_buttons_state("normal")
        self.status_var.set("就绪")

    def _full_process(self, apk):
        """完整流程"""
        self.log("="*50, "INFO")
        self.log("开始完整签名替换流程", "INFO")
        self.log("="*50, "INFO")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 生成密钥
        if self.auto_generate_key.get():
            keystore = self.work_dir / f"test_keystore_{timestamp}.jks"
            self._generate_keystore(keystore)
        else:
            keystore = Path(self.keystore_path.get())
            if not keystore.exists():
                self.log("❌ 密钥库不存在", "ERROR")
                return

        # 2. 反编译
        decompiled = self.work_dir / f"decompiled_{timestamp}"
        self._decompile(apk, decompiled)

        # 3. 修改
        if self.modify_manifest.get():
            self._modify_manifest(decompiled)

        if self.modify_smali.get():
            self._modify_smali(decompiled)

        # 4. 重打包
        unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
        self._rebuild(decompiled, unsigned)

        # 5. zipalign
        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(unsigned, aligned)

        # 6. 签名
        self._sign(apk_path=aligned, keystore=keystore)

        # 7. 输出最终文件
        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")
        self.log(f"🔑 密钥库: {keystore}", "INFO")

        # 对比签名
        self._compare_signatures(apk, final)

        # 弹窗提示
        self.root.after(0, lambda: messagebox.showinfo(
            "完成", 
            f"签名替换完成！\n\n最终 APK:\n{final}\n\n密钥库:\n{keystore}"
        ))

    def _quick_replace(self, apk):
        """快速签名替换"""
        self.log("="*50, "INFO")
        self.log("开始快速签名替换", "INFO")
        self.log("="*50, "INFO")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 生成密钥
        if self.auto_generate_key.get():
            keystore = self.work_dir / f"test_keystore_{timestamp}.jks"
            self._generate_keystore(keystore)
        else:
            keystore = Path(self.keystore_path.get())

        # 2. 去除签名
        stripped = self.work_dir / f"stripped_{timestamp}"
        self._strip_signature(apk, stripped)

        # 3. 重新打包
        unsigned = self.work_dir / f"unsigned_{timestamp}.apk"
        self._repack_zip(stripped, unsigned)

        # 4. zipalign
        aligned = self.work_dir / f"aligned_{timestamp}.apk"
        self._zipalign(unsigned, aligned)

        # 5. 签名
        self._sign(apk_path=aligned, keystore=keystore)

        # 6. 输出
        final = self.work_dir / f"resigned_{Path(apk).stem}_{timestamp}.apk"
        shutil.copy(aligned, final)

        self.log(f"\n✅ 快速签名替换完成！", "SUCCESS")
        self.log(f"📦 最终 APK: {final}", "SUCCESS")

        self._compare_signatures(apk, final)

        self.root.after(0, lambda: messagebox.showinfo(
            "完成",
            f"快速签名替换完成！\n\n最终 APK:\n{final}"
        ))

    # ===== 底层操作 =====
    def _generate_keystore(self, path):
        self.log(f"[+] 生成测试密钥库: {path.name}")
        cmd = [
            'keytool', '-genkey', '-v',
            '-keystore', str(path),
            '-alias', self.alias.get(),
            '-keyalg', 'RSA', '-keysize', '2048',
            '-validity', '36500',
            '-dname', 'CN=Test, OU=Test, O=Test, L=Test, ST=Test, C=CN',
            '-storepass', self.password.get(),
            '-keypass', self.password.get()
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, input=f"{self.password.get()}\n")
        if result.returncode == 0:
            self.log(f"  ✓ 密钥库生成成功", "SUCCESS")
        else:
            self.log(f"  ⚠ keytool: {result.stderr}", "WARNING")

    def _decompile(self, apk, out_dir):
        self.log(f"[+] 反编译 APK...")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        cmd = ['apktool', 'd', '-f', '-o', str(out_dir), str(apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 反编译完成", "SUCCESS")
        else:
            self.log(f"  ✗ 失败: {result.stderr}", "ERROR")
            raise RuntimeError("反编译失败")

    def _modify_manifest(self, decompiled_dir):
        self.log(f"[+] 修改 AndroidManifest.xml...")
        manifest = Path(decompiled_dir) / "AndroidManifest.xml"
        if not manifest.exists():
            self.log(f"  ⚠ 未找到 manifest", "WARNING")
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
            content = content.replace(
                ".method protected onCreate(",
                "\n    # MODIFIED BY APKRESIGNER\n    .method protected onCreate("
            )
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log(f"  ✓ 已修改 smali: {target.name}", "SUCCESS")

    def _rebuild(self, decompiled_dir, output_apk):
        self.log(f"[+] 重打包...")
        cmd = ['apktool', 'b', '-o', str(output_apk), str(decompiled_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 重打包完成", "SUCCESS")
        else:
            self.log(f"  ✗ 失败: {result.stderr}", "ERROR")
            raise RuntimeError("重打包失败")

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
        cmd = ['zipalign', '-p', '-f', '-v', '4', str(input_apk), str(output_apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ 对齐完成", "SUCCESS")
        else:
            self.log(f"  ✗ 对齐失败: {result.stderr}", "ERROR")
            raise RuntimeError("zipalign 失败")

    def _sign(self, apk_path, keystore):
        self.log(f"[+] 签名 APK...")
        scheme = self.scheme.get()

        cmd = [
            'apksigner', 'sign',
            '--ks', str(keystore),
            '--ks-key-alias', self.alias.get(),
            '--ks-pass', f'pass:{self.password.get()}',
            '--key-pass', f'pass:{self.password.get()}',
            '--min-sdk-version', '21',
            str(apk_path)
        ]

        # 签名方案控制
        if scheme == "v1":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'true', '--v2-signing-enabled', 'false'] + [str(apk_path)]
        elif scheme == "v2":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true'] + [str(apk_path)]
        elif scheme == "v3":
            cmd = cmd[:-1] + ['--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true'] + [str(apk_path)]

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
        """验证 APK 签名"""
        apk = self.apk_path.get()
        if not apk or not Path(apk).exists():
            messagebox.showerror("错误", "请选择 APK 文件")
            return

        self.log(f"\n[+] 验证签名: {apk}", "INFO")

        cmd = ['apksigner', 'verify', '-v', str(apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            self.log(f"  ✓ 签名验证通过", "SUCCESS")
            for line in result.stdout.strip().split('\n'):
                self.log(f"    {line}", "INFO")
        else:
            self.log(f"  ✗ 验证失败: {result.stderr}", "ERROR")

        # zipalign 检查
        cmd = ['zipalign', '-c', '-v', '4', str(apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self.log(f"  ✓ zipalign 对齐正常", "SUCCESS")
        else:
            self.log(f"  ⚠ zipalign 可能有问题", "WARNING")


def main():
    root = tk.Tk()

    # 设置 DPI 感知（Windows）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    # 设置主题
    style = ttk.Style()
    style.theme_use('clam')

    app = APKResignerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
