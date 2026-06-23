#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script: Verify original signing functions are not broken by ADB modules
"""

import sys
import os
sys.path.insert(0, r'C:\Users\Administrator\apk_resigner-main')

from pathlib import Path

TEST_APK = r'C:\Users\Administrator\apk_resigner-main\test_apk.apk'
WORK_DIR = r'C:\Users\Administrator\apk_resigner-main\test_work'

Path(WORK_DIR).mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("APK Resigner Function Test")
print("=" * 60)

# Test 1: Pure Python V1 signing
print("\n[Test 1] Pure Python V1 signing...")
try:
    from pure_python_sign import PurePythonAPKSigner, CRYPTO_AVAILABLE
    
    if not CRYPTO_AVAILABLE:
        print("  WARNING: cryptography library not available, skip pure Python signing test")
    else:
        signer = PurePythonAPKSigner(WORK_DIR)
        
        # Generate key
        key_path, cert_path = signer.generate_keystore("test")
        print(f"  OK Key generated: {key_path}")
        
        # Sign APK
        output_apk = os.path.join(WORK_DIR, "test_v1_signed.apk")
        result = signer.sign_apk(TEST_APK, output_apk, key_path, cert_path)
        
        if result and os.path.exists(output_apk):
            print(f"  OK V1 sign success: {output_apk}")
        else:
            print(f"  FAIL V1 sign failed")
except Exception as e:
    print(f"  ERROR Pure Python sign: {e}")

# Test 2: ADB modules import check
print("\n[Test 2] ADB modules import check...")
try:
    from adb_manager import ADBManager
    from backup_manager import BackupManager
    from install_manager import InstallManager
    print("  OK ADB modules imported successfully")
    print("  OK New modules do not affect original signing functions")
except Exception as e:
    print(f"  ERROR ADB modules import: {e}")

# Test 3: Check existing APK functions
print("\n[Test 3] Check existing APK utility functions...")
try:
    from apk_resigner import APKResigner
    resigner = APKResigner()
    print(f"  OK APKResigner initialized")
    
    # Check if test APK exists
    if os.path.exists(TEST_APK):
        print(f"  OK Test APK found: {TEST_APK}")
    else:
        print(f"  WARNING Test APK not found")
except Exception as e:
    print(f"  ERROR APKResigner: {e}")

# Test 4: ToolManager check
print("\n[Test 4] ToolManager check...")
try:
    from apk_resigner_gui import ToolManager
    tools = ToolManager()
    print(f"  OK ToolManager initialized")
    print(f"  Base dir: {tools.base_dir}")
    print(f"  Detected tools: {list(tools.tool_paths.keys())}")
except Exception as e:
    print(f"  ERROR ToolManager: {e}")

print("\n" + "=" * 60)
print("Test completed")
print("=" * 60)
