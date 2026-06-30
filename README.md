# APK 签名替换工具

> 用于 Android 应用签名验证测试的便携工具，支持 ADB 设备管理、应用扫描、备份还原、一键签名替换。

## 特点

- **零依赖运行**：无需安装 Android SDK、JDK，所有工具内置（可选纯 Python 模式）
- **单文件 EXE**：复制到任何 Windows 电脑都能直接运行
- **GUI 界面**：可视化操作，无需命令行
- **ADB 集成**：设备连接、应用扫描、备份还原、一键处理
- **自动检测签名**：选择 APK 后自动识别 V1/V2/V3/V4 签名方案
- **备份还原**：导出原版 APK 备份，随时还原

## 版本信息

- **当前版本**: v2.3.0
- **最新更新**: 2026-06-25

## 文件说明

| 文件 | 用途 |
|------|------|
| `apk_resigner_gui.py` | GUI 主程序（含 ADB 模块集成） |
| `apk_resigner.py` | 命令行版本 |
| `quick_sign_replace.py` | 快速签名替换（不解包） |
| `pure_python_sign.py` | 纯 Python 签名引擎（无需 JDK） |
| `adb_manager.py` | ADB 设备管理模块 |
| `backup_manager.py` | 备份/还原管理模块 |
| `install_manager.py` | APK 安装策略模块 |
| `build_portable.py` | 自动收集工具并打包为 EXE |
| `build_portable.bat` | Windows 一键打包批处理 |
| `_tools/` | 依赖工具目录（打包时自动包含） |

## 快速使用

### 方法一：直接下载预编译 EXE

从 [Release 页面](https://github.com/yysbnzy/apk_resigner/releases) 下载 `APK签名替换工具.exe`，双击运行。

### 方法二：源码运行

```bash
# 克隆仓库
git clone https://github.com/yysbnzy/apk_resigner.git
cd apk_resigner

# 安装依赖
pip install cryptography

# 运行 GUI
python apk_resigner_gui.py
```

### 方法三：自己打包便携版

#### 前提条件
- Windows 电脑
- 已安装 Python 3.8+
- 已安装 Android SDK Build-Tools（用于收集 zipalign、apksigner）
- 已安装 JDK 8+（用于收集 keytool、jarsigner、java）

#### 打包步骤

```bash
# 双击运行打包脚本
build_portable.bat

# 或命令行
python build_portable.py
```

打包完成后，EXE 在 `dist/APK签名替换工具.exe`。

## 功能说明

### 本地 APK 签名（不连接设备）

1. 选择 APK 文件
2. 工具自动检测签名方案（V1/V2/V3/V4）
3. 选择操作：
   - **🔧 修改内容+签名**：反编译 → 修改 → 重打包 → zipalign → 签名
   - **⚡ 快速签名替换**：去除原签名 → 重新签名（不改内容）
   - **🔍 验证签名**：检查 APK 签名状态
   - **📊 签名对比**：对比两个 APK 的签名差异

### ADB 设备管理（连接 Android 设备）

#### 📱 设备连接
- 自动检测并连接 USB 设备
- 显示设备信息（型号、Android 版本、序列号等）

#### 📦 应用列表
- 扫描设备上的所有应用（第三方/系统）
- 搜索过滤应用
- 查看应用详情

#### 💾 备份还原
- **创建备份**：导出 APK 并保存到备份目录
- **还原备份**：直接安装原版 APK（无需签名）
- **清理旧备份**：自动清理过期备份

#### 一键处理流程
1. **导出**：从设备 `adb pull` 原版 APK
2. **备份**：保存原版 APK 到备份目录
3. **签名**：修改内容并替换签名
4. **安装测试**：验证签名校验机制

> **注意**：签名后的 APK 预期安装失败（签名不匹配），用于测试签名校验逻辑。

### 签名方案说明

| 方案 | Android 版本 | 说明 |
|------|-------------|------|
| V1 (JAR) | 5.0-6.0 | 基于 JAR 签名，META-INF/CERT.* |
| V2 | 7.0+ | APK Signing Block，整文件签名 |
| V3 | 9.0+ | V2 + 证书轮换支持 |
| V4 | 11.0+ | 增量签名，用于 APEX |

工具会自动检测原 APK 使用的签名方案，并保持一致。

## 常见问题

### Q: 还原备份需要签名吗？
**不需要**。还原备份直接安装原版 APK（带原始厂商签名），无需重新签名。

### Q: 一键处理报 `INSTALL_PARSE_FAILED_NO_CERTIFICATES`？
此错误已在 **v2.2.9** 修复。旧版本使用 `zipfile` 追加模式破坏 V2 签名块，新版本改为：解压 → 清除 META-INF → 修改 → 重打包 → zipalign → 签名。

### Q: 打包后的 EXE 有多大？
约 50-150MB，取决于内置的 JDK 大小。

### Q: 可以去掉 Java 依赖吗？
可以！启用**纯 Python 模式**：
- 无需 JDK/Android SDK
- 仅支持 V1 (JAR) 签名
- 需要 `pip install cryptography`

### Q: 为什么启动比较慢？
单文件 EXE 启动时需要解压内置的 `_tools/` 到临时目录，首次启动约 5-10 秒。

### Q: 杀毒软件报毒？
PyInstaller 打包的 EXE 常被误报，添加信任即可。

### Q: 支持 Linux/Mac 吗？
GUI 代码本身跨平台，但 `_tools/` 里的工具需要对应平台版本。

## 工作原理

```
┌─────────────────┐
│ APK签名替换工具.exe │
│ (PyInstaller单文件) │
└────────┬────────┘
         │ 启动时解压内置工具到临时目录
         ▼
┌─────────────────┐
│ _tools/         │
│ ├── apktool.jar │
│ ├── zipalign.exe│
│ ├── apksigner   │
│ └── java/bin/   │
│     ├── java.exe│
│     ├── keytool.exe
│     └── jarsigner.exe
└────────┬────────┘
         │ 调用内置工具处理 APK
         ▼
┌─────────────────┐
│ 工作目录/        │
│ └── 生成的 APK   │
└─────────────────┘
```

## 安全提示

⚠️ 本工具仅用于测试 Android 应用完整性校验，请勿用于非法用途。

替换签名后的 APK：
- 无法通过原开发者签名校验
- 无法通过 Google Play Protect / SafetyNet
- 系统级应用通常无法安装

## 更新日志

### v2.3.0 (2026-06-25)
- 修复备份布局显示问题
- ADB 日志分割为操作日志和命令日志
- 添加命令执行记录器

### v2.2.9 (2026-06-26)
- **重要修复**：签名流程重构
  - `_full_process` 改为：解压 → 清除 META-INF → 添加 test.txt → 重打包
  - `_sign_with_scheme` 签名前自动清理旧签名残留
  - 避免 zipfile 'a' 模式破坏 V2 签名块位置

### v2.2.1 (2026-06-18)
- 添加 V1-only 签名支持
- 纯 Python 签名引擎（无需 JDK）
- 自动检测签名方案
- 5 按钮布局：修改+签名 / V1 / V2 / V2+V3 / V4

### v2.0.0 (2026-06-18)
- ADB 扩展功能 v2.0
- 新增模块：ADBManager / BackupManager / InstallManager
- 4 个 Notebook 标签页：设备/应用/备份/日志
- 一键流程：导出→备份→签名→安装测试

### v1.2.0 (2026-06-17)
- 签名对比工具
- 使用说明弹窗
- GitHub Release 发布

### v1.1 (2026-06-17)
- 便携版支持
- 内置工具路径
- 单文件 EXE 打包

### v1.0 (2026-06-17)
- 基础命令行工具
- GUI 界面
- 签名替换功能

## 技术细节

### 内置工具路径检测

程序运行时按以下优先级查找工具：

1. **PyInstaller 临时目录**（`sys._MEIPASS/_tools/`）← 单文件 EXE 模式
2. **EXE 同级目录**（`exe_dir/_tools/`）← 目录模式
3. **源码目录**（`script_dir/_tools/`）← 源码运行
4. **系统 PATH** ← 回退

### 最小化 JRE

脚本从本地 JDK 复制以下文件到 `_tools/java/`：
- `bin/java.exe`, `keytool.exe`, `jarsigner.exe`
- `lib/` 目录（运行时库，约 50-100MB）
- `conf/` 目录（配置文件）

删除了 `demo/`, `sample/`, `man/`, `src.zip` 等不必要文件以减小体积。

## 许可证

MIT License

## 作者

- GitHub: [@yysbnzy](https://github.com/yysbnzy)
- 项目地址: https://github.com/yysbnzy/apk_resigner
