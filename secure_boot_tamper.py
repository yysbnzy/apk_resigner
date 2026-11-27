#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全启动验签故障注入模块 - 多平台版
==========================================
选择平台 + 烧录包目录后，自动遍历查找目标镜像文件，在【原目录】生成篡改文件。
界面含"阶段说明"页签：文件 ↔ 安全启动阶段 ↔ 校验点 ↔ 串口判定关键词。

平台支持：
  高通 SA8155/8295 : 完整实现（偏移已实测校准）
  NXP / 瑞萨 / TI / 芯驰 / 芯擎 / 地平线 / 联发科 : AVB 层通用，
    bootloader 层按签名特征自动定位（首次使用需用该平台样本核对偏移）
依赖：仅 Python 标准库，可独立运行，也可嵌入 APK 签名替换工具
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ---------- 平台配置 ----------
# 每个平台: 目标文件 -> (阶段, 篡改策略)
# 策略: qc_sig=高通签名块  avb_self=vbmeta自身  avb_chain=AVB链式  cert_auto=自动定位证书链/签名
PLATFORMS = {
    '高通 SA8155/8295': {
        'calibrated': True,
        'targets': {
            'xbl.elf':         ('S1 PBL', 'qc_sig'),
            'tz.mbn':          ('S2 XBL', 'qc_sig'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
            'dtbo.img':        ('S3 ABL', 'avb_chain'),
            'vendor_boot.img': ('S3 ABL', 'avb_chain'),
        },
    },
    'NXP i.MX8/95': {
        'calibrated': False,
        'targets': {
            'flash.bin':       ('S1 ROM(AHAB)', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
            'dtbo.img':        ('S3 ABL', 'avb_chain'),
            'vendor_boot.img': ('S3 ABL', 'avb_chain'),
        },
    },
    '瑞萨 R-Car': {
        'calibrated': False,
        'targets': {
            'bl2.srec':        ('S1 ROM', 'cert_auto'),
            'bl31.srec':       ('S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
        },
    },
    'TI Jacinto7': {
        'calibrated': False,
        'targets': {
            'tiboot3.bin':     ('S1 ROM(HSM)', 'cert_auto'),
            'tispl.bin':       ('S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
        },
    },
    '芯驰 X9': {
        'calibrated': False,
        'targets': {
            'bl2.img':         ('S1 ROM', 'cert_auto'),
            'u-boot.img':      ('S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
            'dtbo.img':        ('S3 ABL', 'avb_chain'),
        },
    },
    '芯擎 龍鹰一号': {
        'calibrated': False,
        'targets': {
            'bootloader.img':  ('S1/S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
            'dtbo.img':        ('S3 ABL', 'avb_chain'),
        },
    },
    '地平线 J5': {
        'calibrated': False,
        'targets': {
            'bootloader.img':  ('S1/S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
            'dtbo.img':        ('S3 ABL', 'avb_chain'),
        },
    },
    '联发科 MT86xx': {
        'calibrated': False,
        'targets': {
            'preloader.img':   ('S1 ROM', 'cert_auto'),
            'lk.img':          ('S2', 'cert_auto'),
            'vbmeta.img':      ('S3 ABL', 'avb_self'),
            'boot.img':        ('S3 ABL', 'avb_chain'),
        },
    },
}

HELP_TEXT = """\
════════════════════════════════════════════════════════════
 一、安全启动阶段与目标文件对照（分平台）
════════════════════════════════════════════════════════════
通用信任链（各平台层级一致，机制名称不同）：

  硬件信任根 (eFuse/OTP 中的 RootCA 或公钥哈希)
    └─ S1: BootROM/安全岛 验签一级 bootloader
         └─ S2: 一级 bootloader 验签二级/安全世界镜像
              └─ S3: ABL/U-Boot 用内置公钥验 vbmeta,
                     再由 vbmeta 链式校验 boot/dtbo/vendor_boot
                       └─ S4: 内核 dm-verity 校验 system/vendor

┌──────────────┬──────────────────────────┬───────────────────┐
│ 平台         │ S1/S2 关键文件           │ S1/S2 机制        │
├──────────────┼──────────────────────────┼───────────────────┤
│ 高通         │ xbl.elf(S1)/tz.mbn(S2)   │ ELF哈希段+证书链  │
│ NXP          │ flash.bin                │ HABv4/AHAB+CSF    │
│ 瑞萨         │ bl2/bl31.srec            │ ICUMX 安全岛验签  │
│ TI           │ tiboot3.bin / tispl.bin  │ HSM + X.509证书头 │
│ 芯驰/芯擎/地平线│ bl2/u-boot 等           │ 自研安全启动链    │
│ 联发科       │ preloader.img / lk.img   │ DAA/SLA 逐级验签  │
└──────────────┴──────────────────────────┴───────────────────┘
★ S3 层全平台统一为 Android AVB：vbmeta.img(信任锚) +
  boot.img / dtbo.img / vendor_boot.img(链式校验)，通用。

════════════════════════════════════════════════════════════
 二、各篡改文件导致的校验失败点
════════════════════════════════════════════════════════════
■ S1/S2 bootloader 类（xbl.elf / flash.bin / tiboot3.bin …）
  篡改：破坏签名块（高通为实测偏移；其他平台自动定位证书链
       前256B，首次使用请先用样本文件核对注入点）
  失败点：BootROM/安全核验签不通过 → 拒绝执行该级镜像

■ vbmeta-S3阶段已篡改.img
  篡改：破坏 vbmeta 描述符区（使自身签名失效）
  失败点：ABL/U-Boot 验 vbmeta 签名不通过，信任锚失效

■ boot-S3阶段已篡改.img
  篡改：boot 镜像内容翻 1bit（vbmeta 不动）
  失败点：vbmeta 中记录的 boot 哈希与实测不匹配

■ dtbo / vendor_boot-S3阶段已篡改.img
  篡改：镜像内容翻 1bit（vbmeta 不动）
  ⚠ 若正常启动 = vbmeta 漏链该分区 = Finding
    （很多项目只链 boot，漏链 dtbo/vendor_boot）

════════════════════════════════════════════════════════════
 三、串口日志判定关键词
════════════════════════════════════════════════════════════
■ S1/S2 判定 —— 看"有没有打印"，不靠关键词：
  ✅ 有效(Pass)：串口【完全无任何打印】，设备管理器出现
     下载模式端口(高通=QDLoader 9008) → ROM 干净拒绝
  ❌ 失效(Finding)：串口出现 bootloader 正常打印 =
     被篡改的镜像已被执行
  高通基准日志关键字：
     "bl_hash_seg_auth_timestamp"     PBL 验 xbl 外层签名
     "bl_sec_hash_seg_auth_timestamp" PBL 验 xbl 第二哈希段
     "SBL1, Start"                    XBL 开始执行(出现=已放行)

■ S3 判定 —— 看关键词：
  基准(正常)日志依次出现：
     "Load Image vbmeta_a" / "Load Image boot_a"
     "VB2: Authenticate complete! boot state is: ..."
  ✅ 有效(Pass)：日志停在 "Load Image xxx" 后无
     Authenticate complete，或报 Authenticate fail；
     或设备进 fastboot/复位循环
  ❌ 失效(Finding)：仍打印 Authenticate complete 且正常进系统
  ⚠ boot state 为 "orange" 说明设备可解锁/自定义密钥，
     部分篡改可能被放行，该状态本身应记录为核查项。

════════════════════════════════════════════════════════════
 四、刷写方法与恢复
════════════════════════════════════════════════════════════
1. 篡改文件改名回原名，替换烧录目录中的原文件；
2. 用平台对应下载工具单分区刷入(高通: PCAT/QFIL+精简XML)；
3. 复位启动，抓串口日志，按第三节关键词判定；
4. 恢复：刷回原版文件。S1 失败后停在下载模式属正常，非变砖。

⚠ 非高通平台的 S1/S2 注入点为通用策略自动定位，
  首次在某平台使用前，请先用该平台原始镜像文件核对
  工具日志中打印的注入偏移是否落在签名/证书区域内。
"""

# ---------- 篡改策略 ----------
def find_last_cert_chain(d):
    """全文件扫描，返回最后一条 DER 证书链的起点（签名在链前256B）"""
    last, pos = None, 0
    while True:
        pos = d.find(b'\x30\x82', pos)
        if pos < 0:
            break
        p = pos
        while p + 4 <= len(d) and d[p] == 0x30 and d[p+1] == 0x82:
            ln = int.from_bytes(d[p+2:p+4], 'big') + 4
            if not (0x100 < ln < 0x1000) or p + ln > len(d):
                break
            p += ln
        if p > pos:
            last = pos
            pos = p   # 跳过整条链，避免把链内后续证书误当新链起点
        else:
            pos += 4
    return last

def tamper_qc_sig(d):
    """高通: 破坏签名块。xbl.elf 用实测校准偏移；tz.mbn 等定位末尾证书链前256B"""
    v = bytearray(d)
    if len(d) == 2779204:
        off = 0x14a8 + 10
        note = '破坏外层签名组1（基准校准偏移）'
    else:
        cs = find_last_cert_chain(d)
        if cs and cs > 256:
            off = cs - 256 + 10
            note = '破坏签名块（自动定位末尾证书链前256B）'
        else:
            off = 0x1000
            note = '未检出证书链，翻固定偏移(需人工核对!)'
    v[off] ^= 0x01
    return v, f'{note} @0x{off:x}（验证该级签名验签）'

def tamper_cert_auto(d):
    """通用: 自动定位 DER 证书链/签名区，找不到则翻固定偏移"""
    v = bytearray(d)
    pos = d.find(b'\x30\x82', 0, min(len(d), 0x10000))
    if pos > 256:
        off = pos - 256 + 10   # 签名通常在证书链前
        note = '自动定位: 破坏证书链前签名区'
    elif pos > 0:
        off = pos + 20
        note = '自动定位: 破坏证书区'
    else:
        off = 0x100 if len(d) > 0x200 else len(d) // 2
        note = '未检出证书特征，翻文件头附近字节(需人工核对偏移!)'
    v[off] ^= 0x01
    return v, f'{note} @0x{off:x}（验证 ROM/安全核验签）【待样本校准】'

def tamper_vbmeta(d):
    v = bytearray(d)
    off = 0x100 if len(d) > 0x200 else len(d) // 2
    v[off] ^= 0x01
    return v, f'破坏 vbmeta 描述符区 @0x{off:x}（验证信任锚自身签名验签）'

def tamper_avb_chain(d, name):
    v = bytearray(d)
    off = 0x1000 if len(d) > 0x2000 else len(d) // 2
    v[off] ^= 0x01
    return v, f'翻转内容 @0x{off:x}（验证 vbmeta 对 {name} 的链式校验/是否漏链）'

def do_tamper(path, strategy):
    fn = os.path.basename(path)
    d = open(path, 'rb').read()
    if strategy == 'qc_sig':
        v, desc = tamper_qc_sig(d)
    elif strategy == 'cert_auto':
        v, desc = tamper_cert_auto(d)
    elif strategy == 'avb_self':
        v, desc = tamper_vbmeta(d)
    else:
        v, desc = tamper_avb_chain(d, fn)
    return v, desc

# ---------- 可嵌入 GUI ----------
class SecureBootTamperFrame(ttk.Frame):
    """安全启动篡改页，可嵌入任意 ttk.Notebook。"""

    HINTS = {
        'xbl.elf': 'S1 PBL：失败点=bl_hash_seg_auth。判定：串口完全无打印+出现9008=Pass；出现"SBL1, Start"=失效',
        'tz.mbn': 'S2 XBL：验TrustZone。判定：SBL1日志停在"Loading QSEE Image"后无APPSBL/UEFI打印=Pass；正常启动=失效',
        'vbmeta.img': 'S3 ABL：信任锚自身签名失效。判定：日志无"VB2: Authenticate complete"或报Authenticate失败=Pass',
        'boot.img': 'S3 ABL：vbmeta 哈希链校验 boot 不匹配。判定：停在 Load Image boot 后无 Authenticate complete=Pass',
        'dtbo.img': 'S3 ABL：验证 dtbo 是否被 vbmeta 链接。⚠正常启动=漏链 Finding',
        'vendor_boot.img': 'S3 ABL：验证 vendor_boot 是否被链接。⚠正常启动=漏链 Finding',
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.found = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky='nsew')
        tab_op = ttk.Frame(nb)
        tab_help = ttk.Frame(nb)
        nb.add(tab_op, text='  篡改操作  ')
        nb.add(tab_help, text='  阶段说明与日志判定  ')
        self._build_op(tab_op)
        self._build_help(tab_help)

    def _build_help(self, parent):
        t = scrolledtext.ScrolledText(parent, font=('Consolas', 10), wrap='none')
        t.pack(fill='both', expand=True)
        t.insert('1.0', HELP_TEXT)
        t.config(state='disabled')

    def _build_op(self, parent):
        top = ttk.Frame(parent, padding=8)
        top.pack(fill='x')
        ttk.Label(top, text='平台:').pack(side='left')
        self.plat_var = tk.StringVar(value='高通 SA8155/8295')
        cb = ttk.Combobox(top, textvariable=self.plat_var, state='readonly',
                          values=list(PLATFORMS.keys()), width=18)
        cb.pack(side='left', padx=(4, 12))
        cb.bind('<<ComboboxSelected>>', self._on_platform_changed)
        ttk.Label(top, text='烧录包目录:').pack(side='left')
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(top, text='浏览...', command=self.pick_dir).pack(side='left')
        ttk.Button(top, text='扫描', command=self.scan).pack(side='left', padx=(6, 0))

        mid = ttk.LabelFrame(parent, text='扫描结果（双击行 = 仅生成该文件的篡改版本）', padding=6)
        mid.pack(fill='both', expand=True, padx=8, pady=(0, 4))
        cols = ('file', 'stage', 'path', 'status')
        self.tree = ttk.Treeview(mid, columns=cols, show='headings', height=10)
        for c, w, text in [('file', 150, '文件'), ('stage', 110, '阶段'),
                           ('path', 400, '路径'), ('status', 100, '状态')]:
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', self.gen_one)
        self.tree.bind('<<TreeviewSelect>>', self.show_hint)

        self.hint = ttk.Label(parent, text='选中文件可查看该文件的校验点说明',
                              foreground='#555', padding=(10, 2))
        self.hint.pack(fill='x')

        bot = ttk.Frame(parent, padding=8)
        bot.pack(fill='x')
        ttk.Button(bot, text='一键生成全部篡改文件', command=self.gen_all).pack(side='left')
        ttk.Label(bot, text='输出位置：与源文件同目录').pack(side='left', padx=12)

        self.logw = scrolledtext.ScrolledText(parent, height=8, state='disabled')
        self.logw.pack(fill='both', padx=8, pady=(0, 8))

    def _on_platform_changed(self, _event=None):
        """平台切换后仅在目录有效时自动重扫，避免空目录弹窗。"""
        if os.path.isdir(self.path_var.get()):
            self.scan()

    def show_hint(self, _event=None):
        sel = self.tree.selection()
        if sel:
            fn = self.tree.item(sel[0], 'values')[0]
            default = 'S1/S2 bootloader 验签（该平台注入点待样本校准，请核对日志中的注入偏移）'
            self.hint.config(text=self.HINTS.get(fn, default))

    def log(self, msg):
        self.logw.config(state='normal')
        self.logw.insert('end', msg + '\n')
        self.logw.see('end')
        self.logw.config(state='disabled')

    def current_platform(self):
        return PLATFORMS[self.plat_var.get()]

    def pick_dir(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.path_var.set(path)
            self.scan()

    def scan(self):
        root = self.path_var.get()
        if not root or not os.path.isdir(root):
            messagebox.showwarning('提示', '请先选择有效的烧录包目录', parent=self)
            return
        plat = self.current_platform()
        self.tree.delete(*self.tree.get_children())
        self.found = {}
        for dirpath, _, files in os.walk(root):
            for filename in files:
                key = filename.lower()
                if '已篡改' in filename:
                    continue
                if key in plat['targets']:
                    self.found.setdefault(key, []).append(os.path.join(dirpath, filename))
        for fn, (stage, _strategy) in plat['targets'].items():
            paths = self.found.get(fn, [])
            if paths:
                for path in paths:
                    self.tree.insert('', 'end', values=(fn, stage, path, '待生成'))
            else:
                self.tree.insert('', 'end', values=(fn, stage, '(未找到)', '-'))
        count = sum(len(paths) for paths in self.found.values())
        calibration = '' if plat['calibrated'] else '  ⚠该平台S1/S2注入点待样本校准'
        self.log(f'[{self.plat_var.get()}] 扫描完成：找到 {count} 个目标文件{calibration}')

    def _gen(self, path, item=None):
        fn = os.path.basename(path).lower()
        plat = self.current_platform()
        stage, strategy = plat['targets'][fn]
        try:
            data, desc = do_tamper(path, strategy)
            stem, ext = os.path.splitext(os.path.basename(path))
            out = os.path.join(os.path.dirname(path), f'{stem}-{stage.split()[0]}阶段已篡改{ext}')
            with open(out, 'wb') as f:
                f.write(data)
            self.log(f'[OK] {os.path.basename(out)}\n     {desc}')
            if item:
                self.tree.set(item, 'status', '已生成')
        except Exception as exc:
            self.log(f'[FAIL] {path}: {exc}')

    def gen_one(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        path = self.tree.item(sel[0], 'values')[2]
        if os.path.isfile(path):
            self._gen(path, sel[0])

    def gen_all(self):
        count = 0
        for paths in self.found.values():
            for path in paths:
                self._gen(path)
                count += 1
        if count == 0:
            messagebox.showinfo('提示', '未找到目标文件，请先扫描', parent=self)
        else:
            self.log(f'—— 共生成 {count} 个篡改文件 ——')
            messagebox.showinfo('完成', f'已生成 {count} 个篡改文件，位于各源文件同目录', parent=self)


def main():
    root = tk.Tk()
    root.title('安全启动验签故障注入工具 (多平台版)')
    root.geometry('820x660')
    frame = SecureBootTamperFrame(root)
    frame.pack(fill='both', expand=True)
    root.mainloop()


if __name__ == '__main__':
    main()
