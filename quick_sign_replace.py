#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 快速签名替换工具
功能：不解包，直接替换 APK 签名（用于测试签名校验逻辑）
原理：解压 -> 删除 META-INF -> 重新 zipalign -> 重新签名
"""

import os
import sys
import subprocess
import shutil
import argparse
import zipfile
import hashlib
from pathlib import Path
from datetime import datetime

class QuickSignReplacer:
    def __init__(self, work_dir="./apk_work", tool_paths=None):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True)
        self.tool_paths = tool_paths or {}  # 传入 ToolManager 解析的完整路径

    def _get_cmd(self, tool_name):
        """获取工具的完整命令路径"""
        path = self.tool_paths.get(tool_name)
        if path:
            return [path]
        # 回退到系统 PATH
        sys_path = shutil.which(tool_name)
        if sys_path:
            return [sys_path]
        return [tool_name]  # 最后回退，可能仍会报错

    def strip_signature(self, apk_path, output_dir=None):
        """去除 APK 原有签名"""
        apk_path = Path(apk_path)

        if output_dir is None:
            output_dir = self.work_dir / f"stripped_{apk_path.stem}"
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(exist_ok=True)

        print(f"[+] 解压并去除签名: {apk_path}")

        # 解压 APK
        with zipfile.ZipFile(apk_path, 'r') as zip_ref:
            for item in zip_ref.namelist():
                # 跳过 META-INF 目录（签名相关）
                if item.startswith('META-INF/'):
                    print(f"  - 移除签名文件: {item}")
                    continue
                zip_ref.extract(item, output_dir)

        print(f"[✓] 签名已去除，解压到: {output_dir}")
        return output_dir

    def repack_apk(self, source_dir, output_apk):
        """重新打包为 APK（ZIP 格式）"""
        source_dir = Path(source_dir)
        output_apk = Path(output_apk)

        print(f"[+] 重新打包: {source_dir} -> {output_apk}")

        with zipfile.ZipFile(output_apk, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = str(file_path.relative_to(source_dir))
                    zipf.write(file_path, arcname)

        print(f"[✓] 打包完成: {output_apk}")
        return output_apk

    def zipalign_apk(self, input_apk, output_apk=None):
        """zipalign 对齐"""
        input_apk = Path(input_apk)

        if output_apk is None:
            output_apk = input_apk.parent / f"aligned_{input_apk.name}"
        else:
            output_apk = Path(output_apk)

        print(f"[+] zipalign 对齐: {input_apk}")

        cmd = self._get_cmd('zipalign') + ['-p', '-f', '-v', '4', str(input_apk), str(output_apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] zipalign 失败: {result.stderr}")
            return None

        print(f"[✓] 对齐完成: {output_apk}")
        return output_apk

    def sign_apk(self, apk_path, keystore_path, alias="testkey", password="123456",
                 v1_only=False):
        """签名 APK"""
        apk_path = Path(apk_path)
        keystore_path = Path(keystore_path)

        if not keystore_path.exists():
            print(f"[错误] 密钥库不存在: {keystore_path}")
            return False

        if v1_only:
            return self._sign_v1(apk_path, keystore_path, alias, password)

        print(f"[+] 签名 APK: {apk_path}")

        cmd = self._get_cmd('apksigner') + [
            'sign',
            '--ks', str(keystore_path),
            '--ks-key-alias', alias,
            '--ks-pass', f'pass:{password}',
            '--key-pass', f'pass:{password}',
            str(apk_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] 签名失败: {result.stderr}")
            return False

        print(f"[✓] 签名完成")
        return True

    def _sign_v1(self, apk_path, keystore_path, alias="testkey", password="123456"):
        """使用 jarsigner 进行 V1 (JAR) 签名"""
        apk_path = Path(apk_path)
        keystore_path = Path(keystore_path)

        print(f"[+] V1 签名 APK (jarsigner): {apk_path}")
        print(f"    ⚠️  V1 签名仅含 JAR 签名，Android 7.0+ 可能拒绝安装")

        cmd = self._get_cmd('jarsigner') + [
            '-verbose',
            '-sigalg', 'SHA256withRSA',
            '-digestalg', 'SHA-256',
            '-keystore', str(keystore_path),
            '-storepass', password,
            '-keypass', password,
            str(apk_path),
            alias
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] V1 签名失败: {result.stderr}")
            return False

        print(f"[✓] V1 签名完成")
        return True

    def generate_keystore(self, keystore_path, alias="testkey", password="123456"):
        """生成测试密钥库"""
        print(f"[+] 生成测试密钥库: {keystore_path}")

        cmd = self._get_cmd('keytool') + [
            '-genkey', '-v',
            '-keystore', str(keystore_path),
            '-alias', alias,
            '-keyalg', 'RSA',
            '-keysize', '2048',
            '-validity', '36500',
            '-dname', 'CN=Test, OU=Test, O=Test, L=Test, ST=Test, C=CN',
            '-storepass', password,
            '-keypass', password
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, input=f"{password}\n")
            print(f"[✓] 密钥库生成成功")
            return True
        except Exception as e:
            print(f"[错误] 生成密钥库失败: {e}")
            return False

    def quick_replace(self, original_apk, keystore_path=None, alias="testkey", 
                     password="123456", v1_only=False):
        """快速替换签名流程"""
        original_apk = Path(original_apk)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 生成密钥（如果没有提供）
        if keystore_path is None:
            keystore_path = self.work_dir / f"test_keystore_{timestamp}.jks"
            self.generate_keystore(keystore_path, alias, password)
        else:
            keystore_path = Path(keystore_path)

        # 2. 去除原签名
        stripped_dir = self.strip_signature(original_apk)

        # 3. 重新打包
        unsigned_apk = self.work_dir / f"unsigned_{original_apk.stem}_{timestamp}.apk"
        self.repack_apk(stripped_dir, unsigned_apk)

        # 4. zipalign
        aligned_apk = self.zipalign_apk(unsigned_apk)
        if not aligned_apk:
            return None

        # 5. 签名
        if not self.sign_apk(aligned_apk, keystore_path, alias, password, v1_only=v1_only):
            return None

        # 6. 输出最终文件
        final_apk = self.work_dir / f"resigned_{original_apk.stem}_{timestamp}.apk"
        shutil.copy(aligned_apk, final_apk)

        print(f"\n[✓] 快速签名替换完成！")
        print(f"    最终 APK: {final_apk}")
        print(f"    密钥库: {keystore_path}")

        if v1_only:
            print(f"\n⚠️  注意：此 APK 仅含 V1 签名")
            print(f"    - Android 5.0-6.0: 可能安装成功")
            print(f"    - Android 7.0+: 会拒绝安装（缺少 v2+ 签名）")

        # 对比信息
        print(f"\n[+] 签名对比:")
        for label, apk in [("原始", original_apk), ("新签名", final_apk)]:
            with open(apk, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            print(f"    {label}: {md5}")

        print(f"\n[注意] 签名已替换，原完整性校验应当失败！")

        return final_apk


def main():
    parser = argparse.ArgumentParser(
        description="APK 快速签名替换工具 - 不解包直接替换签名",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 快速替换签名（自动生成密钥）
  python quick_sign_replace.py -i original.apk

  # 使用已有密钥库
  python quick_sign_replace.py -i original.apk -k my.keystore -p mypassword

  # 仅使用 V1 签名
  python quick_sign_replace.py -i original.apk --v1-only

与完整工具的区别:
  - 不解包反编译，不修改 APK 内容
  - 仅去除原签名 + 重新签名
  - 速度快，适合测试纯签名校验场景
        """
    )

    parser.add_argument('-i', '--input', required=True, help='原始 APK 文件路径')
    parser.add_argument('-k', '--keystore', help='密钥库路径（不指定则自动生成）')
    parser.add_argument('-a', '--alias', default='testkey', help='密钥别名')
    parser.add_argument('-p', '--password', default='123456', help='密钥库密码')
    parser.add_argument('-w', '--work-dir', default='./apk_work', help='工作目录')
    parser.add_argument('--v1-only', action='store_true',
                       help='仅使用 V1 签名（jarsigner），不添加 v2/v3 签名块')

    args = parser.parse_args()

    replacer = QuickSignReplacer(args.work_dir)
    final_apk = replacer.quick_replace(
        args.input,
        args.keystore,
        args.alias,
        args.password,
        v1_only=args.v1_only
    )

    if final_apk:
        print(f"\n测试命令:")
        print(f"  adb install {final_apk}")
        print(f"  apksigner verify -v {final_apk}")


if __name__ == '__main__':
    main()
