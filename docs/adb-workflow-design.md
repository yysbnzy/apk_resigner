# ADB 取包 → 重签名 → 回装方案设计文档

**版本**: v1.0  
**日期**: 2026-06-25  
**工具**: APK 签名替换工具 v2.2.x

---

## 1. 方案概述

### 1.1 目标
实现车机应用的安全测试闭环：通过 ADB 从车机导出 APK → 重签名替换 → 回装验证，用于量产前签名校验机制测试。

### 1.2 适用场景
- 车机 APK 签名验证测试
- 第三方应用兼容性验证
- OTA 更新前签名一致性检查
- 安全审计：验证系统拒绝非原厂签名 APK

### 1.3 核心流程
```
┌─────────┐   ADB导出   ┌─────────┐   备份     ┌─────────┐
│ 车机APK │ ──────────→ │ 本地APK │ ────────→ │ 备份目录 │
└─────────┘             └─────────┘            └─────────┘
                              │
                              ↓ 重签名
                        ┌─────────┐
                        │ 新签名  │
                        │  APK   │
                        └─────────┘
                              │
                              ↓ ADB安装
                        ┌─────────┐
                        │  验证   │
                        │ 拒绝安装 │  ← 预期结果
                        └─────────┘
```

---

## 2. 技术实现

### 2.1 架构设计

```
┌─────────────────────────────────────────┐
│           APKResignerGUI (主界面)         │
├─────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ADB设备  │ │应用列表 │ │备份还原 │   │
│  │(Tab 1)  │ │(Tab 2)  │ │(Tab 3)  │   │
│  └────┬────┘ └────┬────┘ └────┬────┘   │
│       │           │           │         │
│  ┌────┴───────────┴───────────┴────┐   │
│  │        ADBManager (设备管理)      │   │
│  ├─────────────────────────────────┤   │
│  │  list_devices()                 │   │
│  │  select_device(serial)          │   │
│  │  scan_packages()                │   │
│  │  export_apk(package, work_dir)  │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │      BackupManager (备份管理)    │   │
│  ├─────────────────────────────────┤   │
│  │  create_backup_from_export()    │   │
│  │  restore_backup()               │   │
│  │  list_backups()                 │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │     InstallManager (安装管理)    │   │
│  ├─────────────────────────────────┤   │
│  │  install_overwrite()            │   │
│  │  install_uninstall_then_install()│  │
│  │  install_multiple()             │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### 2.2 模块详解

#### 2.2.1 ADBManager（设备管理）

**核心功能：**
| 方法 | 功能 | 返回值 |
|------|------|--------|
| `list_devices()` | 扫描 USB/WiFi 连接的设备 | `List[DeviceInfo]` |
| `select_device(serial)` | 选择指定设备为当前目标 | `None` |
| `scan_packages()` | 扫描设备所有应用（第三方/系统） | `List[PackageInfo]` |
| `export_apk(package, work_dir)` | 导出 APK 到工作目录 | `ExportResult` |
| `get_device_info()` | 获取设备详细信息 | `Dict` |

**设备自动连接策略：**
```python
def _refresh_devices(self):
    devices = self.adb_manager.list_devices()
    # 自动选择第一个可用设备
    if self.selected_device is None and first_ready_device:
        self.adb_manager.select_device(first_ready_device.serial)
        self.selected_device = first_ready_device.serial
```

#### 2.2.2 BackupManager（备份管理）

**备份结构设计：**
```
backup/
└── {package_name}/
    └── {timestamp}_{device_model}/
        ├── base.apk          # 主 APK
        ├── split_apks/       # Split APK（如有）
        ├── metadata.json     # 备份元数据
        └── icon.png          # 应用图标
```

**元数据格式：**
```json
{
    "package_name": "com.desaysv.qmktv",
    "version_name": "2.1.0",
    "version_code": 210,
    "device_model": "Desay SV",
    "backup_time": "2026-06-25T10:02:13",
    "apk_size": 15728640,
    "signature_scheme": "v2+v3"
}
```

#### 2.2.3 InstallManager（安装管理）

**安装策略对比：**

| 策略 | ADB 命令 | 适用场景 | 风险 |
|------|----------|----------|------|
| 覆盖安装 | `install -r -d -t` | 同签名更新 | 低 |
| 卸载重装 | `uninstall` + `install` | 签名变更 | **数据丢失** |
| 多 APK | `install-multiple` | Split APK | 中 |

**安装结果状态码：**
```python
class InstallStatus:
    SUCCESS = "success"              # 安装成功（异常！应被拒绝）
    SIGNATURE_CONFLICT = "signature_conflict"  # 签名冲突（预期结果）
    INSTALL_FAILED = "install_failed"          # 其他失败
    UNKNOWN = "unknown"
```

### 2.3 一键处理流程

```python
def _do_one_click_process(self, package_name):
    # 1. 导出 APK
    export_result = self.adb_manager.export_apk(package_name, self.work_dir)
    
    # 2. 创建备份（异步，不阻塞）
    device_info = self.adb_manager.get_device_info()
    backup_result = self.backup_manager.create_backup_from_export(
        export_result, device_info
    )
    
    # 3. 重签名（复用主界面签名逻辑）
    self._full_process(export_result.base_apk)
    
    # 4. 查找签名后的 APK
    resigned_apk = glob.glob(f"{apk_path.stem}_resigned_*.apk")[0]
    
    # 5. 显示安装选项对话框
    self._show_install_dialog(resigned_apk, package_name)
```

---

## 3. 失败处理与自动恢复策略

### 3.1 导出阶段

| 异常 | 原因 | 处理策略 |
|------|------|----------|
| `ADBError` (设备未连接) | USB 断开/未授权 | 提示用户检查连接，自动重试一次 |
| `ExportResult.success=False` | APK 路径解析失败 | 使用 `pm path` 备用方案获取路径 |
| Split APK 导出不完整 | 多 APK 应用 | 检测并导出所有 split APK |

**自动恢复代码：**
```python
def export_apk(self, package_name, work_dir):
    try:
        # 主方案：直接 pull
        result = self._pull_apk(package_name, work_dir)
    except ADBError:
        # 备用方案：通过 pm path 获取路径
        apk_path = self._get_apk_path_via_pm(package_name)
        result = self._pull_direct(apk_path, work_dir)
    return result
```

### 3.2 签名阶段

| 异常 | 原因 | 处理策略 |
|------|------|----------|
| `keytool` 不可用 | 内置 JDK 缺失 | 自动切换纯 Python 签名模式 |
| 密钥库生成失败 | 密码复杂度/权限 | 使用默认密码重试，降级提示 |
| zipalign 失败 | APK 结构异常 | 跳过对齐（仅影响性能，不影响功能） |

### 3.3 安装阶段

| 异常 | 预期行为 | 处理策略 |
|------|----------|----------|
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | ✅ 签名不匹配，拒绝安装 | 记录为测试通过 |
| `INSTALL_FAILED_ALREADY_EXISTS` | 同签名已存在 | 提示用户选择覆盖或跳过 |
| `INSTALL_PARSE_FAILED` | APK 损坏 | 检查 APK 完整性，重新签名 |
| `INSTALL_FAILED_INSUFFICIENT_STORAGE` | 存储空间不足 | 提示清理空间，提供一键清理 |

**安装失败自动重试：**
```python
def _do_install(self, mode, apk_path, package_name=None):
    result = self.install_manager.install_overwrite(apk_path)
    
    if result.status == "signature_conflict":
        # 预期结果：签名验证拒绝正常
        self._adb_log(f"✓ 签名验证拒绝正常 ({result.code})", "SUCCESS")
    elif result.status == "success":
        # 异常：APK 被成功安装，可能存在绕过
        self._adb_log("⚠ APK 安装成功，签名验证可能被绕过", "WARNING")
    else:
        # 其他失败，打印原始 ADB 输出
        self._adb_log(f"✗ 安装失败: {result.message}", "ERROR")
        if result.raw_output:
            for line in result.raw_output.strip().split('\n')[:10]:
                self._adb_log(f"  > {line}", "ERROR")
```

### 3.4 备份还原阶段

| 异常 | 原因 | 处理策略 |
|------|------|----------|
| 备份 APK 无效 | 导出时损坏/不完整 | 导出前校验 APK 结构（ZIP 格式） |
| 还原失败 | 设备未连接 | 提示连接设备，保留备份可后续还原 |
| 版本不匹配 | 备份版本与设备不同 | 提示版本差异，允许强制还原 |

**备份文件校验：**
```python
def _validate_backup(self, backup_dir):
    """验证备份完整性"""
    apk_path = Path(backup_dir) / "base.apk"
    
    # 1. 文件存在性检查
    if not apk_path.exists():
        return False, "APK 文件不存在"
    
    # 2. ZIP 格式验证
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            zf.testzip()
    except zipfile.BadZipFile:
        return False, "APK 文件无效或损坏"
    
    # 3. APK 结构检查
    if 'AndroidManifest.xml' not in [f.filename for f in zf.infolist()]:
        return False, "缺少 AndroidManifest.xml"
    
    return True, "备份有效"
```

---

## 4. 日志记录设计

### 4.1 日志级别

| 级别 | 颜色 | 使用场景 |
|------|------|----------|
| INFO | 蓝色 | 一般操作信息 |
| SUCCESS | 绿色 | 操作成功完成 |
| WARNING | 橙色 | 非致命警告 |
| ERROR | 红色 | 操作失败 |
| ADB | 紫色 | ADB 原始输出 |

### 4.2 日志格式

```
[HH:MM:SS] [LEVEL] 消息内容
```

**示例：**
```
[10:02:13] [INFO] 开始还原备份: com.desaysv.qmktv
[10:02:13] [SUCCESS] 导出成功: com.desaysv.qmktv_v2.1.0.apk
[10:02:19] [ERROR] 还原失败: APK 文件无效或损坏
[10:02:19] [ERROR] ADB 原始输出:
[10:02:19] [ERROR]   Failure [INSTALL_FAILED_INVALID_APK]
```

### 4.3 日志去重机制

**问题：** 同一事件被两处代码同时打印

**原因分析：**
```python
# _adb_log → _do_adb_log (写入 ADB 日志区域)
#             └── 同时调用 self.log() → _do_log_to_adb (再次写入)
```

**解决方案：**
```python
def _do_adb_log(self, timestamp, message, level):
    """仅写入 ADB 日志区域，不重复调用主日志"""
    try:
        if hasattr(self, 'adb_log_text') and self.adb_log_text:
            self.adb_log_text.insert(tk.END, f"[{timestamp}] [{level}] {message}\n", level)
            self.adb_log_text.see(tk.END)
    except Exception:
        pass
    # 删除：self.log(f"[ADB] {message}", level)  ← 导致重复
```

### 4.4 日志持久化

```python
# 日志文件路径
log_dir = Path.home() / "apk_resign_work" / "logs"
log_file = log_dir / f"adb_{datetime.now().strftime('%Y%m%d')}.log"

# 写入日志文件
with open(log_file, 'a', encoding='utf-8') as f:
    f.write(f"[{timestamp}] [{level}] {message}\n")
```

---

## 5. 与其他方案对比

### 5.1 方案对比表

| 特性 | 本方案 (ADB+GUI) | 手动命令行 | 第三方工具 (apktool) | 自动化脚本 |
|------|------------------|-----------|---------------------|-----------|
| **操作门槛** | 低（图形界面） | 高（需熟悉 ADB） | 中（命令行） | 中（需配置） |
| **一键流程** | ✅ 完整闭环 | ❌ 手动分步 | ❌ 仅反编译 | ⚠️ 需定制 |
| **备份管理** | ✅ 自动备份+还原 | ❌ 手动复制 | ❌ 无 | ⚠️ 需额外实现 |
| **签名检测** | ✅ 自动检测原方案 | ❌ 手动检查 | ❌ 无 | ⚠️ 需集成 |
| **失败恢复** | ✅ 自动重试+提示 | ❌ 完全手动 | ❌ 无 | ⚠️ 需实现 |
| **日志记录** | ✅ 分级+持久化 | ❌ 控制台输出 | ❌ 无 | ⚠️ 需实现 |
| **多设备支持** | ✅ 设备列表+切换 | ⚠️ 手动指定 | ❌ 无 | ⚠️ 需实现 |
| **离线签名** | ✅ 纯 Python 模式 | ❌ 需环境 | ❌ 需 Java | ⚠️ 需配置 |

### 5.2 优势分析

1. **闭环测试**：从取包到验证一键完成，无需切换工具
2. **自动备份**：每次操作自动创建备份，支持随时还原
3. **智能检测**：自动检测原 APK 签名方案，保持一致性
4. **失败恢复**：内置多重异常处理，降低测试中断率
5. **日志完整**：统一日志系统，便于问题排查和审计

### 5.3 局限性

1. **依赖 ADB**：需要设备开启 USB 调试
2. **签名限制**：仅支持 RSA 密钥（纯 Python 模式）
3. **平台限制**：当前仅支持 Windows（依赖 adb.exe）
4. **存储占用**：备份文件可能占用大量磁盘空间

---

## 6. 测试用例

### 6.1 功能测试

| 用例 ID | 场景 | 预期结果 |
|---------|------|----------|
| TC-001 | 正常一键处理 | 导出→备份→签名→安装被拒绝 |
| TC-002 | 设备未连接 | 提示连接设备，流程中断 |
| TC-003 | 导出后手动删除 APK | 签名阶段报错，提示文件不存在 |
| TC-004 | 还原旧版本备份 | 安装成功，功能正常 |
| TC-005 | 备份 APK 损坏 | 还原失败，提示 APK 无效 |

### 6.2 异常测试

| 用例 ID | 场景 | 预期结果 |
|---------|------|----------|
| TC-101 | 安装时被拔掉 USB | 提示设备断开，保留签名 APK |
| TC-102 | 存储空间不足 | 提示清理空间，提供日志路径 |
| TC-103 | 设备未授权 ADB | 提示授权，等待用户操作 |
| TC-104 | 车机重启 | 自动重连，继续流程 |

---

## 7. 未来优化方向

1. **多设备并发**：同时连接多台车机，批量测试
2. **报告生成**：自动生成测试报告（PDF/HTML）
3. **签名对比**：可视化对比原/新签名证书信息
4. **OTA 模拟**：模拟 OTA 更新流程，验证签名链
5. **CI/CD 集成**：提供命令行模式，接入 Jenkins/GitHub Actions

---

## 附录：代码提交记录

| Commit | 说明 | 时间 |
|--------|------|------|
| d6c152c | Bug修复：备份还原页签切换自动刷新 + 日志重复输出去重 | 2026-06-25 |
| 0d1e8a7 | UI调整：ADB页签按钮上移 | 2026-06-25 |
| 0f22cd1 | UI调整：窗口高度缩小到800 | 2026-06-25 |
| 7d302be | UI调整：配置页签改为本地APK签名 | 2026-06-25 |
