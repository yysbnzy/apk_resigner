# APK 签名替换工具 - 故障排查与常见问题

## GitHub API 认证头格式问题

### 问题现象
调用 GitHub API 时返回 401 未授权：
```
remote: Invalid username or token. Password authentication is not supported for Git operations.
```
或
```
{"message":"Requires authentication","documentation_url":"https://docs.github.com/rest"}
```

### 原因
GitHub REST API 要求认证头使用 `token` 前缀，而非 `Bearer` 或其他格式。

### 错误写法
```powershell
# ❌ 错误：Bearer 格式
$headers = @{Authorization = "Bearer ghp_xxxx"}

# ❌ 错误：Basic 格式（不需要 Base64 编码）
$headers = @{Authorization = "Basic ghp_xxxx"}

# ❌ 错误：直接写 Token
$headers = @{Authorization = "ghp_xxxx"}
```

### 正确写法
```powershell
# ✅ 正确：token 前缀
$token = "ghp_xxxx"
$headers = @{Authorization = "***"}

# 示例：获取用户信息
Invoke-WebRequest -Uri "https://api.github.com/user" -Headers $headers -UseBasicParsing

# 示例：上传 Release 资产
$uploadUrl = "https://uploads.github.com/repos/owner/repo/releases/123/assets?name=file.exe"
$fileBytes = [System.IO.File]::ReadAllBytes("path/to/file.exe")
Invoke-WebRequest -Uri $uploadUrl -Method POST -Headers $headers -Body $fileBytes
```

### 参考文档
https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api

---

## GitHub Release 上传文件覆盖问题

### 问题现象
上传文件到 Release 时返回 `already_exists` 错误：
```json
{"errors":[{"resource":"ReleaseAsset","code":"already_exists","field":"name"}]}
```

### 原因
GitHub Release 不允许同名文件重复上传，必须先删除旧文件。

### 解决方案
1. 先获取 Release 的 assets 列表
2. 删除同名旧文件
3. 重新上传

```powershell
# 获取 assets 列表
$assets = Invoke-WebRequest -Uri "https://api.github.com/repos/owner/repo/releases/123/assets" -Headers $headers | ConvertFrom-Json

# 删除同名旧文件
foreach ($asset in $assets) {
    if ($asset.name -eq "APK.exe") {
        Invoke-WebRequest -Uri "https://api.github.com/repos/owner/repo/releases/assets/$($asset.id)" -Method DELETE -Headers $headers
    }
}

# 重新上传
Invoke-WebRequest -Uri $uploadUrl -Method POST -Headers $headers -Body $fileBytes
```

---

## GitHub Token 失效问题

### 问题现象
Token 之前能用，突然返回 401 未授权。

### 可能原因
1. **Token 在群聊/公共场合暴露过** → GitHub 安全机制自动撤销
2. **Token 过期**（classic token 默认无过期，但可设置）
3. **权限不足**（如需要 `repo` 权限但只给了 `public_repo`）

### 解决方案
1. 检查 Token 是否被撤销：https://github.com/settings/tokens
2. 重新生成 Token，**不要在群聊中发送完整 Token**
3. 使用环境变量或安全方式传递：
   ```powershell
   $env:GITHUB_TOKEN = "ghp_xxxx"
   ```

---

## 打包产物过大问题

### 问题现象
EXE 文件过大（100MB+），GitHub 仓库推送失败或 Release 上传超时。

### 原因
1. 打包时包含了完整的 JDK 二进制文件（`lib/modules` 约 140MB）
2. 包含了 `build/` 和 `dist/` 目录到 Git 仓库

### 解决方案
1. **精简 JDK**：只复制必需文件（`java.exe`, `keytool.exe`, `jvm.dll` + 依赖 DLL）
2. **排除打包产物**：在 `.gitignore` 中添加 `build/`, `dist/`, `_tools/java/`
3. **打包时动态复制**：从本地 JDK 复制到 `_tools/java/`，不存入 Git

详见 `build_portable.py` 中的 `_copy_minimal_jre()` 和 `collect_jdk()` 实现。

---

## 运行时缺少 JDK 依赖文件

### 问题现象
运行 `keytool.exe` 时报错：
```
java.io.FileNotFoundException: ...\lib\tzdb.dat (系统找不到指定的文件)
```

### 原因
精简 JDK 时遗漏了时区数据库文件 `tzdb.dat` 和 `tzmappings`。

### 解决方案
在 `build_portable.py` 的必需文件清单中添加：
```python
required_lib_files = [
    "modules",
    "jvm.cfg",
    "classlist",
    "tzdb.dat",        # 时区数据库（必需）
    "tzmappings",      # 时区映射（必需）
    # ...
]
```

---

*最后更新: 2026-06-23*
