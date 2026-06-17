# APK 签名替换工具集

用于测试 Android 应用完整性校验的工具集，包含反编译、修改、重打包、签名替换等完整流程。

## 工具清单

| 工具 | 文件名 | 功能 |
|------|--------|------|
| **完整签名替换** | `apk_resigner.py` | 反编译 -> 修改内容 -> 重打包 -> zipalign -> 重签名 |
| **快速签名替换** | `quick_sign_replace.py` | 不解包，直接去除原签名并重新签名 |
| **签名对比分析** | `apk_signature_compare.py` | 对比两个 APK 的签名、证书、哈希差异 |

## 环境要求

### 必需工具
- **apktool**: https://apktool.org/docs/install/
- **Android SDK Build-Tools**: 包含 `zipalign` 和 `apksigner`
  - 下载: https://developer.android.com/studio#command-tools
  - 或从 Android Studio 的 SDK Manager 安装
- **JDK 8+**: 包含 `keytool` 和 `jarsigner`
  - 推荐: https://adoptium.net/

### 环境变量配置
确保以下命令在 PATH 中可用：
```bash
apktool --version
zipalign
apksigner version
keytool -help
```

## 使用说明

### 1. 完整签名替换（修改内容 + 替换签名）

```bash
# 自动生成测试密钥，完整流程
python apk_resigner.py -i original.apk

# 使用已有密钥库
python apk_resigner.py -i original.apk -k my.keystore -p mypassword

# 指定签名方案（v1/v2/v3）
python apk_resigner.py -i original.apk --scheme v3

# 同时修改 smali 代码（更深层测试）
python apk_resigner.py -i original.apk --modify-smali

# 仅反编译查看，不重新打包
python apk_resigner.py -i original.apk --decompile-only
```

**流程说明：**
1. 反编译 APK（apktool d）
2. 修改 AndroidManifest.xml（添加 [MODIFIED] 标记）
3. 可选：修改 smali 代码
4. 重打包（apktool b）
5. zipalign 对齐
6. 重新签名（apksigner）
7. 验证签名

### 2. 快速签名替换（仅替换签名，不修改内容）

```bash
# 快速替换签名
python quick_sign_replace.py -i original.apk

# 使用已有密钥
python quick_sign_replace.py -i original.apk -k my.keystore -p mypassword
```

**适用场景：**
- 测试纯签名校验逻辑
- 不需要修改 APK 内容
- 速度更快

### 3. 签名对比分析

```bash
# 对比两个 APK
python apk_signature_compare.py -a original.apk -b modified.apk

# 对比并尝试安装验证
python apk_signature_compare.py -a original.apk -b modified.apk --install-test
```

**输出内容：**
- 文件 MD5/SHA1/SHA256 对比
- 签名方案（v1/v2/v3/v4）对比
- 证书指纹对比
- 完整性校验结论

## 测试完整性校验的建议流程

```bash
# 1. 准备原始 APK
original.apk

# 2. 生成修改版 APK（签名已替换）
python apk_resigner.py -i original.apk
# 输出: ./apk_work/resigned_original_20240617_143022.apk

# 3. 对比签名差异
python apk_signature_compare.py -a original.apk -b ./apk_work/resigned_original_*.apk

# 4. 在车机/设备上测试安装
adb install ./apk_work/resigned_original_*.apk
# 预期结果：安装失败（签名不一致）或应用运行异常
```

## 常见问题

### Q: 反编译失败？
A: 检查 apktool 版本，某些加固 APK 可能无法反编译。

### Q: 签名后安装失败？
A: 检查是否经过 zipalign，v2+ 签名必须对齐。

### Q: 如何测试自己的完整性校验逻辑？
A: 在应用中实现签名校验后，用本工具生成修改版 APK，测试校验是否拦截。

## 注意事项

⚠️ **本工具仅用于测试和学习，请勿用于非法用途**

- 替换签名后的 APK 无法通过 Google Play Protect 等安全检测
- 系统级应用或受保护应用可能无法安装
- 某些应用（如银行、支付类）有额外的完整性校验机制

## 完整性校验测试点

| 测试项 | 预期结果 |
|--------|----------|
| 证书指纹对比 | 修改版应不同 |
| 文件哈希对比 | 修改版应不同 |
| 覆盖安装测试 | 应失败（签名不一致） |
| 运行时校验 | 应用应检测到异常 |
| 服务端校验 | 服务端应拒绝 |
