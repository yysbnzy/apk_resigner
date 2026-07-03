#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK证书扫描器 - 纯Python证书解析
支持V1/V2/V3签名证书提取与对比
"""

import os
import io
import zipfile
import hashlib
import struct
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# 证书解析依赖
try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


@dataclass
class CertificateInfo:
    """证书信息数据结构"""
    index: int = 0                    # 证书序号
    filename: str = ""                # 文件名（根证书使用）
    sha1: str = ""                    # SHA1指纹 (冒号分隔)
    sha256: str = ""                  # SHA256指纹 (冒号分隔)
    md5: str = ""                     # MD5指纹 (冒号分隔)
    issuer: str = ""                  # 颁发者
    subject: str = ""                 # 主题
    serial_number: str = ""           # 序列号
    not_before: datetime = None      # 生效时间
    not_after: datetime = None       # 过期时间
    signature_algorithm: str = ""     # 签名算法
    public_key_algorithm: str = ""   # 公钥算法
    public_key_size: int = 0         # 公钥位数
    raw_cert: bytes = None           # 原始证书数据

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.not_after is None:
            return False
        return datetime.now() > self.not_after

    @property
    def is_expiring_soon(self, days: int = 30) -> bool:
        """是否即将过期（默认30天内）"""
        if self.not_after is None:
            return False
        return datetime.now() <= self.not_after <= datetime.now() + timedelta(days=days)

    @property
    def status_icon(self) -> str:
        """状态图标"""
        if self.is_expired:
            return "[错误]"
        if self.is_expiring_soon():
            return "警告:️"
        return "[OK]"

    @property
    def status_text(self) -> str:
        """状态文本"""
        if self.is_expired:
            return "已过期"
        if self.is_expiring_soon():
            return f"即将过期 ({(self.not_after - datetime.now()).days}天)"
        return "正常"


@dataclass
class APKCertInfo:
    """APK证书扫描结果"""
    apk_path: str = ""                # APK路径
    apk_name: str = ""                # APK文件名
    package_name: str = ""            # 包名（从AndroidManifest解析）
    version: str = ""                 # 版本号
    signing_scheme: str = ""         # 签名方案 V1/V2/V3/V4
    v1_present: bool = False
    v2_present: bool = False
    v3_present: bool = False
    v4_present: bool = False
    certificates: List[CertificateInfo] = field(default_factory=list)
    scan_time: datetime = None
    error: str = ""

    @property
    def primary_cert(self) -> Optional[CertificateInfo]:
        """主证书（第一个）"""
        return self.certificates[0] if self.certificates else None

    @property
    def cert_count(self) -> int:
        return len(self.certificates)

    @property
    def has_expired(self) -> bool:
        """是否有证书已过期"""
        return any(c.is_expired for c in self.certificates)

    @property
    def has_expiring_soon(self) -> bool:
        """是否有证书即将过期"""
        return any(c.is_expiring_soon() for c in self.certificates)

    @property
    def overall_status_icon(self) -> str:
        """整体状态"""
        if self.has_expired:
            return "[错误]"
        if self.has_expiring_soon:
            return "警告:️"
        return "[OK]"


@dataclass
class DeviceAppCertInfo:
    """设备应用证书信息"""
    app_name: str = ""                # 应用名称
    package_name: str = ""            # 包名
    version_name: str = ""            # 版本名
    version_code: str = ""            # 版本号
    app_type: str = ""                # SYSTEM / THIRD_PARTY
    apk_path: str = ""                # APK路径
    apk_cert_info: APKCertInfo = None # APK证书信息
    scan_time: datetime = None
    error: str = ""                   # 扫描错误信息

    @property
    def is_system_app(self) -> bool:
        return self.app_type == "SYSTEM"

    @property
    def status_icon(self) -> str:
        if self.error:
            return "[?]"
        if self.apk_cert_info:
            return self.apk_cert_info.overall_status_icon
        return "[?]"


class CertScanner:
    """APK证书扫描器"""

    # APK Signing Block 魔法数字
    APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
    
    # V2/V3 ID常量
    APK_SIGNATURE_SCHEME_V2_BLOCK_ID = 0x7109871a
    APK_SIGNATURE_SCHEME_V3_BLOCK_ID = 0xf05368c0
    APK_SIGNATURE_SCHEME_V4_BLOCK_ID = 0x1b93ad10
    
    def __init__(self, work_dir: str = "./cert_work"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._available = CRYPTO_AVAILABLE

    def is_available(self) -> bool:
        return self._available

    def scan_apk(self, apk_path: str) -> APKCertInfo:
        """扫描单个APK证书"""
        apk_path = Path(apk_path)
        info = APKCertInfo(
            apk_path=str(apk_path),
            apk_name=apk_path.name,
            scan_time=datetime.now()
        )

        if not apk_path.exists():
            info.error = "文件不存在"
            return info

        try:
            # 1. 检测签名方案
            self._detect_signing_scheme(info)
            
            # 2. 提取V1证书
            if info.v1_present:
                self._extract_v1_certs(info)
            
            # 3. 提取V2/V3证书
            if info.v2_present or info.v3_present:
                self._extract_v2_v3_certs(info)
            
            # 4. 尝试解析包名和版本
            self._parse_apk_info(info)
            
        except Exception as e:
            info.error = f"解析异常: {str(e)}"

        return info

    def scan_apk_batch(self, apk_paths: List[str]) -> List[APKCertInfo]:
        """批量扫描APK"""
        results = []
        for path in apk_paths:
            info = self.scan_apk(path)
            results.append(info)
        return results

    def scan_directory(self, dir_path: str) -> List[APKCertInfo]:
        """扫描目录下所有APK"""
        dir_path = Path(dir_path)
        apk_files = list(dir_path.rglob("*.apk"))
        return self.scan_apk_batch([str(p) for p in apk_files])

    def compare_apks(self, apk1: APKCertInfo, apk2: APKCertInfo) -> Dict:
        """对比两个APK的证书"""
        result = {
            "same_signature": False,
            "same_issuer": False,
            "same_subject": False,
            "same_sha1": False,
            "same_sha256": False,
            "details": []
        }

        c1 = apk1.primary_cert
        c2 = apk2.primary_cert

        if not c1 or not c2:
            result["details"].append("[错误] 至少一个APK没有证书")
            return result

        result["same_sha1"] = c1.sha1 == c2.sha1
        result["same_sha256"] = c1.sha256 == c2.sha256
        result["same_issuer"] = c1.issuer == c2.issuer
        result["same_subject"] = c1.subject == c2.subject
        result["same_signature"] = result["same_sha1"] and result["same_sha256"]

        if result["same_signature"]:
            result["details"].append("[OK] 证书完全相同")
        else:
            result["details"].append("[错误] 证书不同")
            if not result["same_sha1"]:
                result["details"].append(f"  SHA1: {c1.sha1} vs {c2.sha1}")
            if not result["same_sha256"]:
                result["details"].append(f"  SHA256: {c1.sha256} vs {c2.sha256}")
            if not result["same_issuer"]:
                result["details"].append(f"  颁发者不同")

        return result

    # ────────────────────────────────────────
    # 内部解析方法
    # ────────────────────────────────────────

    def _detect_signing_scheme(self, info: APKCertInfo):
        """检测签名方案"""
        apk_path = Path(info.apk_path)
        
        with zipfile.ZipFile(apk_path, 'r') as zf:
            # 检测V1: 检查META-INF下的签名文件
            for name in zf.namelist():
                if name.startswith('META-INF/'):
                    if any(name.endswith(ext) for ext in ['.RSA', '.DSA', '.EC']):
                        info.v1_present = True
                        break
            
            # 检测V2/V3/V4: 检查APK Signing Block
            try:
                v2, v3, v4 = self._check_apk_signing_block(apk_path)
                info.v2_present = v2
                info.v3_present = v3
                info.v4_present = v4
            except Exception:
                pass

        # 构建签名方案字符串
        schemes = []
        if info.v1_present:
            schemes.append("V1")
        if info.v2_present:
            schemes.append("V2")
        if info.v3_present:
            schemes.append("V3")
        if info.v4_present:
            schemes.append("V4")
        info.signing_scheme = "+".join(schemes) if schemes else "无签名"

    def _check_apk_signing_block(self, apk_path: Path) -> Tuple[bool, bool, bool]:
        """检查APK Signing Block中是否存在V2/V3/V4签名"""
        with open(apk_path, 'rb') as f:
            # 读取CD偏移量（文件末尾22字节之前）
            f.seek(-22, 2)  # 跳到EOCD前
            # 查找EOCD签名
            f.seek(0, 2)
            file_size = f.tell()
            
            # 搜索EOCD (PK\x05\x06)
            f.seek(-22, 2)
            data = f.read(22)
            if not data.endswith(b'PK\x05\x06'):
                # 需要搜索EOCD
                f.seek(0, 2)
                for offset in range(min(file_size, 65535 + 22), 0, -1):
                    f.seek(-offset, 2)
                    if f.read(4) == b'PK\x05\x06':
                        break
                else:
                    return False, False, False
            else:
                f.seek(-22, 2)
            
            # 读取CD偏移量（EOCD偏移16字节）
            f.seek(16, 1)
            cd_offset = struct.unpack('<I', f.read(4))[0]
            
            # 检查APK Signing Block是否存在（在CD偏移量之前）
            if cd_offset < 32:
                return False, False, False
            
            f.seek(cd_offset - 24, 0)  # 24 = 8(size) + 16(magic)
            block_size_data = f.read(8)
            if len(block_size_data) < 8:
                return False, False, False
            
            block_size = struct.unpack('<Q', block_size_data)[0]
            magic = f.read(16)
            
            if magic != self.APK_SIG_BLOCK_MAGIC:
                return False, False, False
            
            # 读取Signing Block内容
            f.seek(cd_offset - block_size - 8, 0)
            block_data = f.read(block_size - 24)  # 减去两个size字段和magic
            
            # 解析ID-Value对
            v2 = False
            v3 = False
            v4 = False
            pos = 0
            while pos < len(block_data):
                if pos + 8 > len(block_data):
                    break
                pair_size = struct.unpack('<Q', block_data[pos:pos+8])[0]
                if pair_size < 4 or pos + pair_size > len(block_data):
                    break
                id_value = block_data[pos+8:pos+8+pair_size-4]
                if len(id_value) < 4:
                    break
                block_id = struct.unpack('<I', id_value[:4])[0]
                
                if block_id == self.APK_SIGNATURE_SCHEME_V2_BLOCK_ID:
                    v2 = True
                elif block_id == self.APK_SIGNATURE_SCHEME_V3_BLOCK_ID:
                    v3 = True
                elif block_id == self.APK_SIGNATURE_SCHEME_V4_BLOCK_ID:
                    v4 = True
                
                pos += 8 + pair_size - 4
            
            return v2, v3, v4

    def _extract_v1_certs(self, info: APKCertInfo):
        """提取V1签名证书"""
        apk_path = Path(info.apk_path)
        
        with zipfile.ZipFile(apk_path, 'r') as zf:
            for name in zf.namelist():
                if not name.startswith('META-INF/'):
                    continue
                if not any(name.endswith(ext) for ext in ['.RSA', '.DSA', '.EC']):
                    continue
                
                try:
                    cert_data = zf.read(name)
                    # 解析PKCS#7/CMS或X.509证书
                    cert = self._parse_certificate(cert_data)
                    if cert:
                        cert.index = len(info.certificates) + 1
                        info.certificates.append(cert)
                except Exception as e:
                    pass  # 忽略解析失败的证书

    def _extract_v2_v3_certs(self, info: APKCertInfo):
        """提取V2/V3签名证书（简化版，提取证书块）"""
        # V2/V3证书提取较为复杂，需要完整解析APK Signing Block
        # 这里标记为V2/V3存在，但证书详情通过keytool/apksigner获取
        # 实际实现中，可以调用外部工具或完整实现解析
        pass

    def _parse_certificate(self, cert_data: bytes) -> Optional[CertificateInfo]:
        """解析X.509证书"""
        if not CRYPTO_AVAILABLE:
            return None
        
        try:
            # 尝试DER格式
            cert = x509.load_der_x509_certificate(cert_data)
        except Exception:
            try:
                # 尝试PEM格式
                cert = x509.load_pem_x509_certificate(cert_data)
            except Exception:
                # 尝试PKCS#7格式（需要提取证书）
                try:
                    from cryptography.hazmat.primitives.serialization import pkcs7
                    # 尝试解析PKCS7
                    p7 = pkcs7.load_der_pkcs7_certificates(cert_data)
                    if p7:
                        cert = p7[0]
                    else:
                        return None
                except Exception:
                    return None
        
        # 提取证书信息
        info = CertificateInfo()
        
        # 指纹
        info.sha1 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA1()))
        info.sha256 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))
        info.md5 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.MD5()))
        
        # 颁发者和主题
        info.issuer = cert.issuer.rfc4514_string() if cert.issuer else ""
        info.subject = cert.subject.rfc4514_string() if cert.subject else ""
        
        # 序列号
        info.serial_number = str(cert.serial_number)
        
        # 有效期
        info.not_before = cert.not_valid_before
        info.not_after = cert.not_valid_after
        
        # 签名算法
        try:
            info.signature_algorithm = cert.signature_algorithm_oid._name
        except:
            info.signature_algorithm = "Unknown"
        
        # 公钥信息
        try:
            pub_key = cert.public_key()
            if hasattr(pub_key, 'key_size'):
                info.public_key_size = pub_key.key_size
            # 检测公钥算法
            key_type = pub_key.__class__.__name__
            if 'RSA' in key_type:
                info.public_key_algorithm = f"RSA-{info.public_key_size}"
            elif 'EC' in key_type or 'EllipticCurve' in key_type:
                info.public_key_algorithm = f"EC-{info.public_key_size}"
            elif 'DSA' in key_type:
                info.public_key_algorithm = f"DSA-{info.public_key_size}"
            else:
                info.public_key_algorithm = key_type
        except:
            info.public_key_algorithm = "Unknown"
        
        info.raw_cert = cert_data
        return info

    def _parse_apk_info(self, info: APKCertInfo):
        """解析APK基本信息（包名、版本）"""
        try:
            apk_path = Path(info.apk_path)
            with zipfile.ZipFile(apk_path, 'r') as zf:
                # 解析AndroidManifest.xml（简化版）
                # 实际实现需要使用AXML解析器，这里暂用文件名
                if 'AndroidManifest.xml' in zf.namelist():
                    info.package_name = "(需AXML解析)"
        except Exception:
            pass

    # ────────────────────────────────────────
    # 导出功能
    # ────────────────────────────────────────

    def export_to_csv(self, results: List[APKCertInfo], output_path: str):
        """导出CSV"""
        import csv
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'APK文件', '包名', '版本', '签名方案', '证书数量',
                'SHA1', 'SHA256', '颁发者', '有效期至', '公钥算法', '状态'
            ])
            for info in results:
                cert = info.primary_cert
                if cert:
                    writer.writerow([
                        info.apk_name,
                        info.package_name or "",
                        info.version or "",
                        info.signing_scheme,
                        info.cert_count,
                        cert.sha1,
                        cert.sha256,
                        cert.issuer,
                        cert.not_after.strftime("%Y-%m-%d") if cert.not_after else "",
                        cert.public_key_algorithm,
                        cert.status_text
                    ])
                else:
                    writer.writerow([
                        info.apk_name, "", "", info.signing_scheme,
                        0, "", "", "", "", "", "无证书"
                    ])

    def export_to_txt(self, results: List[APKCertInfo], output_path: str):
        """导出文本报告"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("APK 证书扫描报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            
            for info in results:
                f.write(f"\n{'─' * 60}\n")
                f.write(f"APK: {info.apk_name}\n")
                f.write(f"签名方案: {info.signing_scheme}\n")
                f.write(f"证书数量: {info.cert_count}\n")
                
                for cert in info.certificates:
                    f.write(f"\n  [证书 #{cert.index}]\n")
                    f.write(f"  SHA1: {cert.sha1}\n")
                    f.write(f"  SHA256: {cert.sha256}\n")
                    f.write(f"  颁发者: {cert.issuer}\n")
                    f.write(f"  主题: {cert.subject}\n")
                    f.write(f"  有效期: {cert.not_before.strftime('%Y-%m-%d') if cert.not_before else '?'} ~ {cert.not_after.strftime('%Y-%m-%d') if cert.not_after else '?'}\n")
                    f.write(f"  状态: {cert.status_text}\n")
                    f.write(f"  公钥算法: {cert.public_key_algorithm}\n")
                
                if info.error:
                    f.write(f"  警告:️ 错误: {info.error}\n")

    def export_to_json(self, results: List[APKCertInfo], output_path: str):
        """导出JSON"""
        import json
        data = []
        for info in results:
            data.append({
                "apk_name": info.apk_name,
                "apk_path": info.apk_path,
                "package_name": info.package_name,
                "version": info.version,
                "signing_scheme": info.signing_scheme,
                "cert_count": info.cert_count,
                "certificates": [
                    {
                        "sha1": c.sha1,
                        "sha256": c.sha256,
                        "md5": c.md5,
                        "issuer": c.issuer,
                        "subject": c.subject,
                        "serial_number": c.serial_number,
                        "not_before": c.not_before.isoformat() if c.not_before else None,
                        "not_after": c.not_after.isoformat() if c.not_after else None,
                        "status": c.status_text,
                        "public_key_algorithm": c.public_key_algorithm
                    }
                    for c in info.certificates
                ],
                "error": info.error
            })
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ────────────────────────────────────────
# 设备证书扫描（ADB相关）
# ────────────────────────────────────────

class RootCertScanner:
    """车机根证书扫描器（系统CA证书）"""
    
    # 证书文件扩展名
    CERT_EXTENSIONS = ['.0', '.pem', '.crt']
    
    def __init__(self, adb_manager, work_dir: str = "./cert_work"):
        self.adb_manager = adb_manager
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._available = CRYPTO_AVAILABLE
    
    def is_available(self) -> bool:
        return self._available
    
    def list_root_certs(self) -> List[CertificateInfo]:
        """列出设备上所有根证书（从根目录递归搜索）"""
        if not self.adb_manager or not self.adb_manager.selected_device:
            raise RuntimeError("ADB设备未连接")
        
        # 从根目录递归搜索证书文件
        all_cert_files = self._find_cert_files_from_root()
        
        if not all_cert_files:
            return []
        
        # 去重
        seen = set()
        unique_files = []
        for filepath in all_cert_files:
            if filepath not in seen:
                seen.add(filepath)
                unique_files.append(filepath)
        
        results = []
        temp_dir = self.work_dir / "root_certs"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        for remote_path in unique_files:
            try:
                # 提取到本地临时目录
                filename = Path(remote_path).name
                local_path = temp_dir / filename
                
                # 避免文件名冲突（不同路径同名文件）
                counter = 1
                original_local = local_path
                while local_path.exists():
                    local_path = original_local.parent / f"{original_local.stem}_{counter}{original_local.suffix}"
                    counter += 1
                
                # 尝试使用 adb pull 提取
                rc, stdout, stderr = self.adb_manager._run(['pull', remote_path, str(local_path)])
                
                if rc != 0 or not local_path.exists():
                    # pull 失败，尝试使用 root 权限读取
                    rc, stdout, stderr = self.adb_manager._run(['shell', f'su -c cat {remote_path}'])
                    if rc != 0 or not stdout:
                        # 再尝试 run-as
                        rc, stdout, stderr = self.adb_manager._run(['shell', f'run-as com.android.shell cat {remote_path}'])
                        if rc != 0 or not stdout:
                            continue
                    # 将内容写入本地文件
                    local_path.write_bytes(stdout.encode('utf-8'))
                
                # 解析本地证书文件
                cert_info = self._parse_cert_file(local_path, filename)
                if cert_info:
                    cert_info.filename = f"{remote_path} ({filename})"
                    results.append(cert_info)
                    
            except Exception as e:
                # 解析失败但继续扫描其他证书
                continue
        
        return results
    
    def _find_cert_files_from_root(self) -> List[str]:
        """从根目录递归搜索证书文件"""
        all_files = []
        
        # 方法1: 直接从根目录扫描（最全面）
        files = self._run_find("/")
        if files:
            return files
        
        # 方法2: 如果根目录扫描失败，分步扫描关键分区
        for search_path in ["/system", "/vendor", "/data", "/etc", "/product", "/oem"]:
            try:
                files = self._run_find(search_path)
                all_files.extend(files)
            except Exception:
                continue
        
        return all_files
    
    def _run_find(self, search_path: str) -> List[str]:
        """执行 find 命令搜索证书文件"""
        if not hasattr(self.adb_manager, '_run'):
            return []
        
        # 构建 find 命令
        # find /path -name "*.0" -type f 2>/dev/null
        find_cmd = f'find {search_path} -name "*.0" -type f 2>/dev/null'
        
        rc, stdout, stderr = self.adb_manager._run(['shell', find_cmd])
        
        if rc != 0 or not stdout:
            return []
        
        files = []
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if line and line.endswith('.0'):
                files.append(line)
        
        return files
    
    def _parse_cert_file(self, local_path: Path, filename: str) -> Optional[CertificateInfo]:
        """解析本地证书文件"""
        if not CRYPTO_AVAILABLE:
            return None
        
        try:
            cert_data = local_path.read_bytes()
        except Exception:
            return None
        
        # 解析PEM证书
        try:
            cert = x509.load_pem_x509_certificate(cert_data)
        except Exception:
            # 尝试DER格式
            try:
                cert = x509.load_der_x509_certificate(cert_data)
            except Exception:
                return None
        
        # 提取信息
        info = CertificateInfo()
        info.filename = filename
        info.index = 0
        info.sha1 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA1()))
        info.sha256 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))
        info.md5 = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.MD5()))
        info.issuer = cert.issuer.rfc4514_string() if cert.issuer else ""
        info.subject = cert.subject.rfc4514_string() if cert.subject else ""
        info.serial_number = str(cert.serial_number)
        info.not_before = cert.not_valid_before
        info.not_after = cert.not_valid_after
        try:
            info.signature_algorithm = cert.signature_algorithm_oid._name
        except:
            info.signature_algorithm = "Unknown"
        
        try:
            pub_key = cert.public_key()
            if hasattr(pub_key, 'key_size'):
                info.public_key_size = pub_key.key_size
            key_type = pub_key.__class__.__name__
            if 'RSA' in key_type:
                info.public_key_algorithm = f"RSA-{info.public_key_size}"
            elif 'EC' in key_type or 'EllipticCurve' in key_type:
                info.public_key_algorithm = f"EC-{info.public_key_size}"
            elif 'DSA' in key_type:
                info.public_key_algorithm = f"DSA-{info.public_key_size}"
            else:
                info.public_key_algorithm = key_type
        except:
            info.public_key_algorithm = "Unknown"
        
        info.raw_cert = cert_data
        return info


if __name__ == "__main__":
    # 测试代码
    import sys
    if len(sys.argv) > 1:
        scanner = CertScanner()
        if not scanner.is_available():
            print("[错误] 需要安装 cryptography 库: pip install cryptography")
            sys.exit(1)
        
        apk_path = sys.argv[1]
        print(f"扫描: {apk_path}\n")
        
        info = scanner.scan_apk(apk_path)
        print(f"APK: {info.apk_name}")
        print(f"签名方案: {info.signing_scheme}")
        print(f"证书数量: {info.cert_count}")
        print()
        
        for cert in info.certificates:
            print(f"[证书 #{cert.index}]")
            print(f"  SHA1: {cert.sha1}")
            print(f"  SHA256: {cert.sha256}")
            print(f"  颁发者: {cert.issuer}")
            print(f"  有效期: {cert.not_before} ~ {cert.not_after}")
            print(f"  状态: {cert.status_text}")
            print(f"  公钥算法: {cert.public_key_algorithm}")
            print()
    else:
        print("Usage: python cert_scanner.py <apk_path>")
