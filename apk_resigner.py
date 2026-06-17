#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APK 签名替换工具 - 用于测试完整性校验
功能：反编译APK -> 修改内容 -> 重打包 -> zipalign对齐 -> 重签名
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

class APKResigner:
    def __init__(self, work_dir="./apk_work"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True)
        self.check_dependencies()

    def check_dependencies(self):
        """检查必要工具是否安装"""
        tools = {
            'apktool': 'apktool',
            'zipalign': 'zipalign (Android SDK Build-Tools)',
            'apksigner': 'apksigner (Android SDK Build-Tools)',
            'keytool': 'keytool (JDK)',
            'jarsigner': 'jarsigner (JDK)'
        }

        missing = []
        for cmd, desc in tools.items():
            if not shutil.which(cmd):
                missing.append(f"  - {cmd}: {desc}")

        if missing:
            print("[错误] 缺少以下工具，请先安装：")
            for m in missing:
                print(m)
            print("\n安装参考：")
            print("  apktool: https://apktool.org/docs/install/")
            print("  Android SDK: https://developer.android.com/studio#command-tools")
            print("  JDK: https://adoptium.net/")
            sys.exit(1)

    def generate_keystore(self, keystore_path, alias="testkey", password="123456", 
                         validity=36500, dname="CN=Test, OU=Test, O=Test, L=Test, ST=Test, C=CN"):
        """生成测试用的签名密钥库"""
        print(f"[+] 生成测试密钥库: {keystore_path}")

        cmd = [
            'keytool', '-genkey', '-v',
            '-keystore', str(keystore_path),
            '-alias', alias,
            '-keyalg', 'RSA',
            '-keysize', '2048',
            '-validity', str(validity),
            '-dname', dname,
            '-storepass', password,
            '-keypass', password
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, input=f"{password}\n")
            if result.returncode != 0:
                print(f"[警告] keytool 输出: {result.stderr}")
            print(f"[✓] 密钥库生成成功")
            return True
        except Exception as e:
            print(f"[错误] 生成密钥库失败: {e}")
            return False

    def decompile(self, apk_path, out_dir=None):
        """反编译 APK"""
        apk_path = Path(apk_path)
        if not apk_path.exists():
            print(f"[错误] APK 文件不存在: {apk_path}")
            return None

        if out_dir is None:
            out_dir = self.work_dir / f"decompiled_{apk_path.stem}"
        else:
            out_dir = Path(out_dir)

        # 清理旧目录
        if out_dir.exists():
            shutil.rmtree(out_dir)

        print(f"[+] 反编译 APK: {apk_path}")
        cmd = ['apktool', 'd', '-f', '-o', str(out_dir), str(apk_path)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[错误] 反编译失败: {result.stderr}")
            return None

        print(f"[✓] 反编译完成: {out_dir}")
        return out_dir

    def modify_manifest(self, decompiled_dir, modifications=None):
        """修改 AndroidManifest.xml 或进行其他修改"""
        manifest_path = Path(decompiled_dir) / "AndroidManifest.xml"

        if not manifest_path.exists():
            print(f"[警告] 未找到 AndroidManifest.xml")
            return False

        print(f"[+] 修改 AndroidManifest.xml")

        # 读取原始内容
        with open(manifest_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 默认修改：添加一个测试属性标记
        if modifications is None:
            # 在 application 标签中添加测试标记
            if 'android:label="' in content:
                content = content.replace(
                    'android:label="',
                    'android:label="[MODIFIED] '
                )
            print("  - 添加 [MODIFIED] 标记到应用标签")
        else:
            # 应用自定义修改
            for old, new in modifications.items():
                content = content.replace(old, new)
                print(f"  - 替换: '{old}' -> '{new}'")

        # 写回
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[✓] 修改完成")
        return True

    def modify_smali(self, decompiled_dir, target_class=None, patch_code=None):
        """修改 smali 代码（用于更深层测试）"""
        smali_dir = Path(decompiled_dir) / "smali"

        if not smali_dir.exists():
            print(f"[警告] 未找到 smali 目录")
            return False

        print(f"[+] 搜索 smali 文件...")

        # 示例：查找 MainActivity 或指定类
        if target_class:
            target_file = smali_dir / target_class.replace('.', '/') + ".smali"
        else:
            # 默认找第一个 Activity
            target_file = None
            for smali_file in smali_dir.rglob("*.smali"):
                with open(smali_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                if "Landroid/app/Activity;" in content or "onCreate" in content:
                    target_file = smali_file
                    break

        if not target_file or not target_file.exists():
            print(f"[警告] 未找到目标 smali 文件")
            return False

        print(f"[+] 修改 smali: {target_file}")

        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 默认补丁：添加注释标记
        if patch_code is None:
            patch = "\n    # MODIFIED BY APKRESIGNER - INTEGRITY TEST\n"
            if ".method protected onCreate(" in content:
                content = content.replace(
                    ".method protected onCreate(",
                    f"{patch}    .method protected onCreate("
                )
            print("  - 添加完整性测试标记")
        else:
            content = patch_code(content)

        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[✓] smali 修改完成")
        return True

    def rebuild(self, decompiled_dir, output_apk=None):
        """重打包 APK"""
        decompiled_dir = Path(decompiled_dir)

        if not decompiled_dir.exists():
            print(f"[错误] 反编译目录不存在: {decompiled_dir}")
            return None

        if output_apk is None:
            output_apk = self.work_dir / f"rebuilt_{decompiled_dir.name}.apk"
        else:
            output_apk = Path(output_apk)

        print(f"[+] 重打包: {decompiled_dir} -> {output_apk}")

        cmd = ['apktool', 'b', '-o', str(output_apk), str(decompiled_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] 重打包失败: {result.stderr}")
            return None

        print(f"[✓] 重打包完成: {output_apk}")
        return output_apk

    def zipalign_apk(self, input_apk, output_apk=None):
        """zipalign 对齐"""
        input_apk = Path(input_apk)

        if output_apk is None:
            output_apk = input_apk.parent / f"aligned_{input_apk.name}"
        else:
            output_apk = Path(output_apk)

        print(f"[+] zipalign 对齐: {input_apk}")

        cmd = ['zipalign', '-p', '-f', '-v', '4', str(input_apk), str(output_apk)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] zipalign 失败: {result.stderr}")
            return None

        print(f"[✓] 对齐完成: {output_apk}")
        return output_apk

    def sign_apk(self, apk_path, keystore_path, alias="testkey", password="123456", 
                scheme="v2+v3+v4"):
        """签名 APK"""
        apk_path = Path(apk_path)
        keystore_path = Path(keystore_path)

        if not keystore_path.exists():
            print(f"[错误] 密钥库不存在: {keystore_path}")
            return False

        print(f"[+] 签名 APK: {apk_path}")
        print(f"    使用密钥: {keystore_path} (alias: {alias})")
        print(f"    签名方案: {scheme}")

        cmd = [
            'apksigner', 'sign',
            '--ks', str(keystore_path),
            '--ks-key-alias', alias,
            '--ks-pass', f'pass:{password}',
            '--key-pass', f'pass:{password}',
            '--min-sdk-version', '21',
            str(apk_path)
        ]

        # 根据 scheme 参数调整
        if scheme == "v1":
            cmd.insert(-1, '--v1-signing-enabled')
            cmd.insert(-1, 'true')
            cmd.insert(-1, '--v2-signing-enabled')
            cmd.insert(-1, 'false')
        elif scheme == "v2":
            cmd.insert(-1, '--v1-signing-enabled')
            cmd.insert(-1, 'false')
            cmd.insert(-1, '--v2-signing-enabled')
            cmd.insert(-1, 'true')
        elif scheme == "v3":
            cmd.insert(-1, '--v1-signing-enabled')
            cmd.insert(-1, 'false')
            cmd.insert(-1, '--v2-signing-enabled')
            cmd.insert(-1, 'true')
            cmd.insert(-1, '--v3-signing-enabled')
            cmd.insert(-1, 'true')

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] 签名失败: {result.stderr}")
            return False

        print(f"[✓] 签名完成")
        return True

    def sign_apk_v1(self, apk_path, keystore_path, alias="testkey", password="123456"):
        """使用 jarsigner 进行 V1 (JAR) 签名"""
        apk_path = Path(apk_path)
        keystore_path = Path(keystore_path)

        if not keystore_path.exists():
            print(f"[错误] 密钥库不存在: {keystore_path}")
            return False

        print(f"[+] V1 签名 APK (jarsigner): {apk_path}")
        print(f"    ⚠️  V1 签名仅含 JAR 签名，Android 7.0+ 可能拒绝安装")

        cmd = [
            'jarsigner', '-verbose',
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

    def strip_signature(self, apk_path, output_dir=None):
        """去除 APK 原有签名"""
        apk_path = Path(apk_path)

        if output_dir is None:
            output_dir = self.work_dir / f"stripped_{apk_path.stem}"
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(exist_ok=True)

        print(f"[+] 解压并去除签名: {apk_path}")

        with zipfile.ZipFile(apk_path, 'r') as zip_ref:
            for item in zip_ref.namelist():
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

    def verify_apk(self, apk_path):
        """验证 APK 签名和对齐"""
        apk_path = Path(apk_path)

        print(f"[+] 验证 APK: {apk_path}")

        # 验证签名
        cmd = ['apksigner', 'verify', '-v', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[错误] 签名验证失败: {result.stderr}")
            return False

        print("  [✓] 签名验证通过")
        print(f"  {result.stdout}")

        # 验证对齐
        cmd = ['zipalign', '-c', '-v', '4', str(apk_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if "Verification succesful" in result.stdout or result.returncode == 0:
            print("  [✓] zipalign 验证通过")
        else:
            print(f"  [警告] zipalign 可能有问题: {result.stdout}")

        return True

    def compare_signatures(self, original_apk, modified_apk):
        """对比两个 APK 的签名信息"""
        print(f"[+] 对比签名信息")

        for label, apk in [("原始", original_apk), ("修改后", modified_apk)]:
            apk = Path(apk)
            print(f"\n  {label} APK: {apk.name}")

            # 提取证书指纹
            cmd = ['apksigner', 'verify', '-v', str(apk)]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if "Verified using v1 scheme" in result.stdout:
                print(f"    - v1 签名: 存在")
            if "Verified using v2 scheme" in result.stdout:
                print(f"    - v2 签名: 存在")
            if "Verified using v3 scheme" in result.stdout:
                print(f"    - v3 签名: 存在")

            # 计算文件哈希
            with open(apk, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            print(f"    - MD5: {md5}")

        print(f"\n[注意] 签名已替换，完整性校验应当失败！")

    def full_process(self, original_apk, keystore_path=None, alias="testkey", 
                    password="123456", scheme="v2+v3+v4", 
                    modify_manifest=True, modify_smali=False):
        """完整流程：反编译 -> 修改 -> 重打包 -> 对齐 -> 签名"""
        original_apk = Path(original_apk)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 生成密钥（如果没有提供）
        if keystore_path is None:
            keystore_path = self.work_dir / f"test_keystore_{timestamp}.jks"
            self.generate_keystore(keystore_path, alias, password)
        else:
            keystore_path = Path(keystore_path)

        # 2. 反编译
        decompiled_dir = self.decompile(original_apk)
        if not decompiled_dir:
            return None

        # 3. 修改内容
        if modify_manifest:
            self.modify_manifest(decompiled_dir)

        if modify_smali:
            self.modify_smali(decompiled_dir)

        # 4. 重打包
        unsigned_apk = self.rebuild(decompiled_dir)
        if not unsigned_apk:
            return None

        # 5. zipalign
        aligned_apk = self.zipalign_apk(unsigned_apk)
        if not aligned_apk:
            return None

        # 6. 签名
        if scheme == "v1":
            if not self.sign_apk_v1(aligned_apk, keystore_path, alias, password):
                return None
        else:
            if not self.sign_apk(aligned_apk, keystore_path, alias, password, scheme):
                return None

        # 7. 验证
        self.verify_apk(aligned_apk)

        # 8. 对比签名
        self.compare_signatures(original_apk, aligned_apk)

        # 9. 输出最终文件到工作目录
        final_apk = self.work_dir / f"resigned_{original_apk.stem}_{timestamp}.apk"
        shutil.copy(aligned_apk, final_apk)

        print(f"\n[✓] 完成！最终 APK: {final_apk}")
        print(f"    密钥库: {keystore_path}")

        return final_apk

    def v1_only_process(self, original_apk, keystore_path=None, alias="testkey", 
                       password="123456"):
        """仅使用 V1 签名流程：不解包修改，仅去除原签名 + V1 签名"""
        original_apk = Path(original_apk)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print("="*50)
        print("开始仅使用 V1 签名流程")
        print("="*50)
        print("⚠️  V1 签名仅兼容 Android 5.0-6.0，Android 7.0+ 会拒绝安装！")

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

        # 5. V1 签名
        if not self.sign_apk_v1(aligned_apk, keystore_path, alias, password):
            return None

        # 6. 输出最终文件
        final_apk = self.work_dir / f"v1_signed_{original_apk.stem}_{timestamp}.apk"
        shutil.copy(aligned_apk, final_apk)

        print(f"\n[✓] V1 签名完成！")
        print(f"    最终 APK: {final_apk}")
        print(f"    密钥库: {keystore_path}")
        print(f"\n⚠️  注意：此 APK 仅含 V1 签名")
        print(f"    - Android 5.0-6.0: 可能安装成功")
        print(f"    - Android 7.0+: 会拒绝安装（缺少 v2+ 签名）")
        print(f"    - 可用于测试系统对 v1-only APK 的拦截能力")

        # 对比信息
        print(f"\n[+] 签名对比:")
        for label, apk in [("原始", original_apk), ("V1签名", final_apk)]:
            with open(apk, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            print(f"    {label}: {md5}")

        return final_apk


def main():
    parser = argparse.ArgumentParser(
        description="APK 签名替换工具 - 用于测试完整性校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 完整流程（自动生成密钥）
  python apk_resigner.py -i original.apk

  # 使用已有密钥库
  python apk_resigner.py -i original.apk -k my.keystore -p mypassword

  # 仅反编译查看
  python apk_resigner.py -i original.apk --decompile-only

  # 指定签名方案（v1/v2/v3/v4）
  python apk_resigner.py -i original.apk --scheme v3

  # 同时修改 smali 代码
  python apk_resigner.py -i original.apk --modify-smali

  # 仅使用 V1 签名（不解包修改）
  python apk_resigner.py -i original.apk --v1-only

注意事项:
  - 需要安装: apktool, Android SDK Build-Tools, JDK
  - 修改后的 APK 签名已变更，无法通过原签名校验
  - 仅用于测试和学习，请勿用于非法用途
        """
    )

    parser.add_argument('-i', '--input', required=True, help='原始 APK 文件路径')
    parser.add_argument('-k', '--keystore', help='密钥库路径（不指定则自动生成）')
    parser.add_argument('-a', '--alias', default='testkey', help='密钥别名 (默认: testkey)')
    parser.add_argument('-p', '--password', default='123456', help='密钥库密码 (默认: 123456)')
    parser.add_argument('-s', '--scheme', default='v2+v3+v4', 
                       choices=['v1', 'v2', 'v3', 'v4', 'v2+v3+v4'],
                       help='签名方案 (默认: v2+v3+v4)')
    parser.add_argument('-w', '--work-dir', default='./apk_work', help='工作目录')
    parser.add_argument('--decompile-only', action='store_true', help='仅反编译，不重新打包')
    parser.add_argument('--modify-smali', action='store_true', help='同时修改 smali 代码')
    parser.add_argument('--no-modify-manifest', action='store_true', 
                       help='不修改 AndroidManifest.xml')
    parser.add_argument('--v1-only', action='store_true',
                       help='仅使用 V1 签名（不解包修改，仅去除原签名+ jarsigner V1 签名）')

    args = parser.parse_args()

    # 初始化工具
    resigner = APKResigner(args.work_dir)

    if args.decompile_only:
        # 仅反编译
        decompiled = resigner.decompile(args.input)
        if decompiled:
            print(f"\n反编译结果保存在: {decompiled}")
    elif args.v1_only:
        # V1 仅签名流程
        final_apk = resigner.v1_only_process(
            original_apk=args.input,
            keystore_path=args.keystore,
            alias=args.alias,
            password=args.password
        )
        if final_apk:
            print(f"\n测试命令:")
            print(f"  adb install {final_apk}")
            print(f"  apksigner verify -v {final_apk}")
    else:
        # 完整流程
        final_apk = resigner.full_process(
            original_apk=args.input,
            keystore_path=args.keystore,
            alias=args.alias,
            password=args.password,
            scheme=args.scheme,
            modify_manifest=not args.no_modify_manifest,
            modify_smali=args.modify_smali
        )

        if final_apk:
            print(f"\n测试建议:")
            print(f"  1. 安装测试: adb install {final_apk}")
            print(f"  2. 对比签名: apksigner verify -v {final_apk}")
            print(f"  3. 查看证书: keytool -list -v -keystore {args.keystore or '自动生成的密钥库'}")


if __name__ == '__main__':
    main()
