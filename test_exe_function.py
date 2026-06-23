#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证EXE打包后的核心签名功能
直接使用底层代码测试（EXE内部就是这套代码）
"""

import sys
import os
import subprocess
import tempfile
import shutil

sys.path.insert(0, r'C:\Users\Administrator\apk_resigner-main')

TEST_APK = r'C:\Users\Administrator\apk_resigner-main\test_apk.apk'
WORK_DIR = tempfile.mkdtemp(prefix="apk_test_")

print("=" * 60)
print("APK Resigner v2.0.0 EXE 功能测试")
print("=" * 60)
print(f"测试目录: {WORK_DIR}")
print(f"测试APK: {TEST_APK}")
print(f"APK存在: {os.path.exists(TEST_APK)}")
print()

# 检查test_apk是否存在
if not os.path.exists(TEST_APK):
    print("ERROR: test_apk.apk 不存在，无法测试")
    sys.exit(1)

# Test 1: 纯Python V1签名
print("[Test 1] 纯Python V1签名...")
try:
    from pure_python_sign import PurePythonAPKSigner, CRYPTO_AVAILABLE
    
    if not CRYPTO_AVAILABLE:
        print("  SKIP: cryptography库不可用")
    else:
        signer = PurePythonAPKSigner(WORK_DIR)
        
        # 生成密钥
        key_obj, cert_obj = signer.generate_keystore("test_key")
        print(f"  OK 密钥生成成功")
        
        # 签名APK (需要先生成keystore文件)
        import glob
        keystore_files = glob.glob(os.path.join(WORK_DIR, "*.pem"))
        if keystore_files:
            keystore_path = keystore_files[0]
            result = signer.sign_apk_v1(TEST_APK, keystore_path, "testkey")
            
            # 查找生成的签名文件
            signed_files = glob.glob(os.path.join(WORK_DIR, "*signed*.apk")) + glob.glob(os.path.join(WORK_DIR, "*resigned*.apk"))
            
            if signed_files:
                signed_apk = signed_files[0]
                size = os.path.getsize(signed_apk)
                print(f"  OK V1签名成功: {signed_apk} ({size} bytes)")
            else:
                print(f"  FAIL V1签名失败，未找到输出文件")
        else:
            print("  FAIL 未找到生成的keystore文件")
except Exception as e:
    import traceback
    print(f"  ERROR: {e}")
    traceback.print_exc()

# Test 2: 快速签名替换（纯Python模式）
print("\n[Test 2] 快速签名替换...")
try:
    from pure_python_sign import PurePythonAPKSigner
    
    signer = PurePythonAPKSigner(WORK_DIR)
    
    result = signer.quick_replace(TEST_APK, None, "quick_test")
    
    # 查找生成的文件
    import glob
    signed_files = glob.glob(os.path.join(WORK_DIR, "*resigned*.apk"))
    
    if signed_files:
        signed_apk = signed_files[0]
        size = os.path.getsize(signed_apk)
        print(f"  OK 快速签名成功: {signed_apk} ({size} bytes)")
    else:
        print(f"  FAIL 快速签名失败")
except Exception as e:
    import traceback
    print(f"  ERROR: {e}")
    traceback.print_exc()

# Test 3: 验证签名文件结构
print("\n[Test 3] 验证签名后APK结构...")
try:
    import zipfile
    import glob
    
    # 查找签名后的APK
    signed_files = glob.glob(os.path.join(WORK_DIR, "*signed*.apk")) + glob.glob(os.path.join(WORK_DIR, "*resigned*.apk"))
    
    if signed_files:
        signed_apk = signed_files[0]
        with zipfile.ZipFile(signed_apk, 'r') as zf:
            files = zf.namelist()
            
            # 检查V1签名文件
            has_manifest = 'META-INF/MANIFEST.MF' in files
            has_cert_sf = 'META-INF/CERT.SF' in files
            has_cert_rsa = any(f.startswith('META-INF/') and f.endswith('.RSA') for f in files)
            
            print(f"  MANIFEST.MF: {'OK' if has_manifest else 'FAIL'}")
            print(f"  CERT.SF: {'OK' if has_cert_sf else 'FAIL'}")
            print(f"  CERT.RSA: {'OK' if has_cert_rsa else 'FAIL'}")
            
            if has_manifest and has_cert_sf and has_cert_rsa:
                print(f"  OK V1签名文件结构完整")
            else:
                print(f"  FAIL V1签名文件缺失")
    else:
        print(f"  SKIP 没有签名后的APK")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 4: ADB模块导入测试
print("\n[Test 4] ADB模块导入测试...")
try:
    import adb_manager
    import backup_manager
    import install_manager
    print("  OK ADB模块导入成功")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 5: GUI模块导入测试
print("\n[Test 5] GUI模块导入测试...")
try:
    import apk_resigner_gui
    print("  OK GUI模块导入成功")
    
    # 检查ADB可用性标志
    if hasattr(apk_resigner_gui, 'ADB_AVAILABLE'):
        print(f"  ADB_AVAILABLE = {apk_resigner_gui.ADB_AVAILABLE}")
except Exception as e:
    print(f"  ERROR: {e}")

# 清理
print(f"\n[Test 6] 清理测试目录...")
try:
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    print(f"  OK 测试目录已清理")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
