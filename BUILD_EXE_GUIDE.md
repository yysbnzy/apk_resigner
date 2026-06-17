# GUI 版本打包为 EXE 指南

## 方案一：单文件 EXE（推荐，最便携）

### 步骤

1. **安装 PyInstaller**
```bash
pip install pyinstaller
```

2. **执行打包命令**
```bash
pyinstaller --noconfirm --onefile --windowed --name "APK签名替换工具" --icon=NONE apk_resigner_gui.py
```

参数说明：
- `--onefile`：打包为单文件 exe
- `--windowed`：不显示控制台窗口
- `--name`：输出文件名
- `--noconfirm`：覆盖旧文件不提示

3. **输出位置**
```
dist/APK签名替换工具.exe
```

### 单文件特点
- ✅ 只有一个 .exe 文件，复制即用
- ✅ 适合 U 盘携带
- ⚠️ 启动稍慢（需要解压临时文件）
- ⚠️ 体积较大（约 15-20MB）

---

## 方案二：目录式 EXE（启动更快）

### 步骤

```bash
pyinstaller --noconfirm --windowed --name "APK签名替换工具" apk_resigner_gui.py
```

输出：
```
dist/APK签名替换工具/
    APK签名替换工具.exe
    _internal/          # 依赖文件目录
```

### 目录式特点
- ✅ 启动速度快
- ✅ 体积分散，主文件较小
- ⚠️ 需要整个目录一起复制

---

## 方案三：使用打包脚本（一键打包）

已提供 `build_exe.py` 脚本，双击运行即可：

```bash
python build_exe.py
```

---

## 便携使用注意事项

### 1. 依赖工具需要单独准备

打包后的 exe **不包含**以下工具，需要在使用环境中安装：

| 工具 | 下载地址 | 安装后需添加到 PATH |
|------|---------|-------------------|
| apktool | https://apktool.org/docs/install/ | ✅ |
| Android SDK Build-Tools | Android Studio SDK Manager | ✅ |
| JDK 8+ | https://adoptium.net/ | ✅ |
| adb | 随 SDK Platform-Tools 提供 | 可选 |

### 2. 制作完整便携包

建议将以下文件打包为一个压缩包，实现真正便携：

```
APK签名替换工具便携版/
├── APK签名替换工具.exe          # GUI 工具
├── apktool.jar                  # 从官网下载
├── _tools/                      # 依赖工具目录
│   ├── zipalign.exe             # 从 SDK Build-Tools 复制
│   ├── apksigner.bat            # 从 SDK Build-Tools 复制
│   ├── keytool.exe              # 从 JDK bin 复制
│   ├── jarsigner.exe            # 从 JDK bin 复制
│   └── adb.exe                  # 可选
└── 使用说明.txt
```

### 3. 修改源码以支持内置工具路径

如果需要将工具打包在 exe 内部，可修改 `apk_resigner_gui.py` 中的工具调用逻辑：

```python
# 在 __init__ 中添加内置工具路径检测
import sys
if getattr(sys, 'frozen', False):
    # 运行在 exe 中
    base_path = Path(sys.executable).parent
else:
    # 运行在源码中
    base_path = Path(__file__).parent

# 使用内置工具
self.apktool_path = base_path / "_tools" / "apktool.jar"
# 调用时: java -jar {self.apktool_path} ...
```

---

## 常见问题

### Q: 打包后提示缺少 DLL？
A: 安装 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### Q: 杀毒软件误报？
A: PyInstaller 打包的 exe 有时会被误报，可：
1. 添加信任
2. 使用 `--noupx` 参数禁用 UPX 压缩
3. 购买代码签名证书进行签名

### Q: 界面显示模糊？
A: 在 Windows 显示设置中关闭"高 DPI 缩放替代"

### Q: 如何减小 exe 体积？
A: 使用 UPX 压缩：
```bash
pip install pyinstaller
# 下载 upx 放到 PATH 中
pyinstaller --onefile --windowed --upx-dir=UPX_PATH apk_resigner_gui.py
```

---

## 命令行快速打包

### 最小体积版
```bash
pyinstaller --noconfirm --onefile --windowed --strip --upx-dir=UPX apk_resigner_gui.py
```

### 调试版（带控制台，方便看错误）
```bash
pyinstaller --noconfirm --onefile --name "APK签名替换工具-Debug" apk_resigner_gui.py
```
