#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 签名对比分析工具
功能：对比两个 APK 的签名信息、证书指纹、文件哈希差异
用于验证完整性校验是否生效
"""

import os
import sys
import subprocess
import argparse
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime

class APKSignatureAnalyzer:
    def __init__(self):
        pass

    def get_file_hash(self, file_path, algorithm='md5'):
        """计算文件哈希"""
        h = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def extract_cert_info(self, apk_path):
        """提取 APK 证书信息"""
        apk_path = Path(apk_path)

        # 使用 apksigner 验证
        cmd = ['apksigner', 'verify', '-v', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        info = {
            'path': str(apk_path),
            'name': apk_path.name,
            'size': apk_path.stat().st_size,
            'md5': self.get_file_hash(apk_path, 'md5'),
            'sha1': self.get_file_hash(apk_path, 'sha1'),
            'sha256': self.get_file_hash(apk_path, 'sha256'),
            'v1_signed': False,
            'v2_signed': False,
            'v3_signed': False,
            'v4_signed': False,
            'signatures': []
        }

        if result.returncode == 0:
            output = result.stdout
            if 'Verified using v1 scheme' in output:
                info['v1_signed'] = True
            if 'Verified using v2 scheme' in output:
                info['v2_signed'] = True
            if 'Verified using v3 scheme' in output:
                info['v3_signed'] = True
            if 'Verified using v4 scheme' in output:
                info['v4_signed'] = True

        # 尝试提取证书指纹（从 META-INF 目录）
        try:
            with zipfile.ZipFile(apk_path, 'r') as zf:
                for name in zf.namelist():
                    if name.startswith('META-INF/') and name.endswith('.RSA'):
                        # 提取 RSA 证书并解析
                        cert_data = zf.read(name)
                        # 使用 keytool 解析
                        temp_cert = f"/tmp/cert_{datetime.now().strftime('%s')}.der"
                        with open(temp_cert, 'wb') as f:
                            f.write(cert_data)

                        cmd = ['keytool', '-printcert', '-file', temp_cert]
                        cert_result = subprocess.run(cmd, capture_output=True, text=True)
                        if cert_result.returncode == 0:
                            info['signatures'].append(cert_result.stdout)

                        os.remove(temp_cert)
        except Exception as e:
            info['cert_error'] = str(e)

        return info

    def compare_apks(self, apk1_path, apk2_path):
        """对比两个 APK"""
        apk1_path = Path(apk1_path)
        apk2_path = Path(apk2_path)

        print(f"[+] 分析 APK 签名信息...")
        info1 = self.extract_cert_info(apk1_path)
        info2 = self.extract_cert_info(apk2_path)

        print(f"\n{'='*60}")
        print(f"APK 签名对比分析报告")
        print(f"{'='*60}")

        # 基本信息
        print(f"\n【基本信息】")
        print(f"  原始 APK: {info1['name']} ({info1['size']:,} bytes)")
        print(f"  修改 APK: {info2['name']} ({info2['size']:,} bytes)")

        # 文件哈希对比
        print(f"\n【文件哈希对比】")
        print(f"  {'算法':<10} {'原始 APK':<35} {'修改 APK':<35} {'是否一致'}")
        print(f"  {'-'*85}")

        for algo in ['md5', 'sha1', 'sha256']:
            match = "✓ 一致" if info1[algo] == info2[algo] else "✗ 不同"
            print(f"  {algo:<10} {info1[algo]:<35} {info2[algo]:<35} {match}")

        # 签名方案对比
        print(f"\n【签名方案对比】")
        print(f"  {'方案':<10} {'原始 APK':<15} {'修改 APK':<15} {'是否一致'}")
        print(f"  {'-'*50}")

        for scheme in ['v1_signed', 'v2_signed', 'v3_signed', 'v4_signed']:
            s1 = "✓" if info1[scheme] else "✗"
            s2 = "✓" if info2[scheme] else "✗"
            match = "✓ 一致" if info1[scheme] == info2[scheme] else "✗ 不同"
            print(f"  {scheme:<10} {s1:<15} {s2:<15} {match}")

        # 证书指纹对比
        print(f"\n【证书信息对比】")
        if info1['signatures'] and info2['signatures']:
            # 提取 MD5 指纹
            cert1_md5 = self._extract_md5_fingerprint(info1['signatures'][0])
            cert2_md5 = self._extract_md5_fingerprint(info2['signatures'][0])

            print(f"  原始证书 MD5: {cert1_md5}")
            print(f"  修改证书 MD5: {cert2_md5}")

            if cert1_md5 == cert2_md5:
                print(f"  ⚠ 证书指纹一致（可能使用了相同密钥）")
            else:
                print(f"  ✗ 证书指纹不同（签名已替换）")
        else:
            print(f"  无法提取证书信息（可能是 v2/v3 签名或 APK 结构问题）")

        # 完整性校验结论
        print(f"\n{'='*60}")
        print(f"【完整性校验结论】")

        if info1['md5'] != info2['md5']:
            print(f"  ✗ 文件内容已变更（MD5 不同）")

        if info1['sha256'] != info2['sha256']:
            print(f"  ✗ 文件哈希已变更（SHA256 不同）")

        # 检查签名是否一致
        cert1_md5 = self._extract_md5_fingerprint(info1['signatures'][0]) if info1['signatures'] else None
        cert2_md5 = self._extract_md5_fingerprint(info2['signatures'][0]) if info2['signatures'] else None

        if cert1_md5 and cert2_md5:
            if cert1_md5 != cert2_md5:
                print(f"  ✗ 签名证书已替换")
                print(f"  → 完整性校验应当：失败（检测到签名不一致）")
            else:
                print(f"  ⚠ 签名证书相同")
                print(f"  → 完整性校验可能：通过（需结合其他校验逻辑）")
        else:
            print(f"  ! 无法自动判断证书差异，建议手动验证")

        print(f"{'='*60}\n")

        return {
            'original': info1,
            'modified': info2,
            'hash_match': info1['sha256'] == info2['sha256'],
            'cert_match': cert1_md5 == cert2_md5 if (cert1_md5 and cert2_md5) else None
        }

    def _extract_md5_fingerprint(self, cert_text):
        """从 keytool 输出中提取 MD5 指纹"""
        for line in cert_text.split('\n'):
            if 'MD5:' in line:
                return line.split('MD5:')[1].strip()
        return None

    def verify_install(self, apk_path):
        """验证 APK 是否能安装（通过 adb）"""
        apk_path = Path(apk_path)
        print(f"[+] 尝试安装验证: {apk_path.name}")

        cmd = ['adb', 'install', '-r', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if "Success" in result.stdout:
            print(f"  ✓ 安装成功")
            return True
        elif "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in result.stdout:
            print(f"  ✗ 安装失败：签名与已安装应用不一致")
            print(f"  → 这证明完整性校验生效！")
            return False
        elif "INSTALL_PARSE_FAILED_NO_CERTIFICATES" in result.stdout:
            print(f"  ✗ 安装失败：没有证书")
            return False
        else:
            print(f"  ! 安装结果: {result.stdout}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="APK 签名对比分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 对比两个 APK 的签名
  python apk_signature_compare.py -a original.apk -b modified.apk

  # 对比并尝试安装验证
  python apk_signature_compare.py -a original.apk -b modified.apk --install-test
        """
    )

    parser.add_argument('-a', '--apk1', required=True, help='原始 APK 路径')
    parser.add_argument('-b', '--apk2', required=True, help='修改后 APK 路径')
    parser.add_argument('--install-test', action='store_true', 
                       help='尝试安装第二个 APK 进行验证')

    args = parser.parse_args()

    analyzer = APKSignatureAnalyzer()
    result = analyzer.compare_apks(args.apk1, args.apk2)

    if args.install_test:
        print(f"\n[+] 安装测试...")
        analyzer.verify_install(args.apk2)


if __name__ == '__main__':
    main()
