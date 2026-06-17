# APK 签名替换工具 - 便携版

## 特点

- **零依赖**：无需安装 Android SDK、JDK、apktool，所有工具内置
- **单文件 EXE**：复制到任何 Windows 电脑都能直接运行
- **GUI 界面**：可视化操作，无需命令行

## 文件说明

| 文件 | 用途 |
|------|------|
| `apk_resigner_gui.py` | 主程序源码（支持内置工具路径） |
| `build_portable.py` | 自动收集工具并打包为 EXE |
| `build_portable.bat` | Windows 一键打包批处理 |
| `build_exe.bat` | 旧版打包脚本（需要系统已安装依赖） |
| `_tools/` | 依赖工具目录（打包时自动包含） |

## 快速使用（推荐）

### 方法一：直接下载预编译 EXE（如果有）

从 Release 页面下载 `APK签名替换工具.exe`，双击运行。

### 方法二：自己打包便携版

#### 前提条件
- Windows 电脑
- 已安装 Python 3.8+（`python --version` 能显示版本）
- 已安装 **Android SDK Build-Tools**（用于收集 zipalign、apksigner）
- 已安装 **JDK 8+**（用于收集 keytool、jarsigner、java）
- 已安装 **apktool**（或让脚本自动下载）

#### 打包步骤

1. **克隆仓库**
```bash
git clone https://github.com/yysbnzy/apk_resigner.git
cd apk_resigner
```

2. **双击运行打包脚本**
```bash
build_portable.bat
```

或命令行：
```bash
python build_portable.py
```

3. **等待完成**

脚本会自动：
- 下载 `apktool.jar`（约 15MB）
- 从本地 Android SDK 复制 `zipalign.exe`、`apksigner` 及依赖
- 从本地 JDK 复制 `java.exe`、`keytool.exe`、`jarsigner.exe` 及最小 JRE
- 执行 PyInstaller 打包，生成单文件 EXE

4. **找到 EXE**

打包完成后，EXE 在：
```
dist/
└── APK签名替换工具.exe
```

复制这个文件到任意位置，双击即可运行。

#### 如果自动收集失败

如果脚本找不到你的 SDK 或 JDK，可以手动复制：

```
apk_resigner/
├── _tools/                    <-- 手动创建这个目录
│   ├── apktool.jar            <-- 从 https://apktool.org 下载
│   ├── zipalign.exe           <-- 从 Android SDK build-tools/ 复制
│   ├── apksigner.bat          <-- 从 Android SDK build-tools/ 复制
│   ├── lib/                   <-- apksigner 依赖
│   │   └── apksigner.jar
│   └── java/                  <-- 最小 JDK
│       └── bin/
│           ├── java.exe
│           ├── keytool.exe
│           ├── jarsigner.exe
│           └── ... (DLL 和 lib 目录)
```

然后重新运行 `build_portable.bat`。

## 使用说明

### 界面功能

- **APK 文件**：选择要处理的 APK
- **密钥库**：可选，不选则自动生成测试密钥
- **签名参数**：别名、密码、签名方案（v1/v2/v3/v4）
- **修改选项**：
  - 修改 AndroidManifest.xml（添加 [MODIFIED] 标记）
  - 修改 smali 代码（添加测试标记）

### 操作按钮

| 按钮 | 功能 |
|------|------|
| 🔧 完整流程 | 反编译 → 修改内容 → 重打包 → zipalign → 重签名 |
| ⚡ 快速签名替换 | 去除原签名 → 重新签名（不改内容） |
| 🔍 验证签名 | 检查 APK 签名状态和对齐情况 |

### 输出文件

处理后的 APK 保存在用户目录下：
```
%USERPROFILE%\apk_resign_work\
└── resigned_xxx_20240617_143022.apk
```

## 工具工作原理

```
┌─────────────────┐
│  APK签名替换工具.exe  │
│  (PyInstaller单文件)  │
└────────┬────────┘
         │ 启动时解压内置工具到临时目录
         ▼
┌─────────────────┐
│  _tools/        │
│  ├── apktool.jar│
│  ├── zipalign.exe│
│  ├── apksigner  │
│  └── java/bin/  │
│      ├── java.exe│
│      ├── keytool.exe│
│      └── jarsigner.exe│
└────────┬────────┘
         │ 调用内置工具处理 APK
         ▼
┌─────────────────┐
│  工作目录/       │
│  └── 生成的 APK  │
└─────────────────┘
```

## 常见问题

### Q: 打包后的 EXE 有多大？
A: 约 50-150MB，取决于内置的 JDK 大小。如果 JDK 包含完整 JRE 会更大。

### Q: 可以去掉 Java 依赖吗？
A: 不行。apktool 是 Java 写的，keytool/jarsigner 也是 Java 程序，必须包含 JRE。

### Q: 为什么启动比较慢？
A: 单文件 EXE 启动时需要把内置的 `_tools/` 解压到临时目录，首次启动约 5-10 秒。

### Q: 杀毒软件报毒？
A: PyInstaller 打包的 EXE 常被误报，添加信任即可。也可使用 `--noupx` 参数禁用 UPX 压缩。

### Q: 支持 Linux/Mac 吗？
A: GUI 代码本身跨平台，但 `_tools/` 里的工具需要对应平台版本。Linux/Mac 用户需要手动收集对应平台的工具。

## 安全提示

⚠️ 本工具仅用于测试 Android 应用完整性校验，请勿用于非法用途。

替换签名后的 APK：
- 无法通过原开发者签名校验
- 无法通过 Google Play Protect / SafetyNet
- 系统级应用通常无法安装

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

## 更新日志

### v1.1 便携版
- 支持内置工具路径，无需系统安装依赖
- 自动收集工具脚本
- 单文件 EXE 打包

### v1.0 基础版
- 命令行工具
- GUI 界面
- 签名替换功能
