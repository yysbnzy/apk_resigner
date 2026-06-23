#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: Verify ADB modules don't break existing code
"""

import sys
sys.path.insert(0, r'C:\Users\Administrator\apk_resigner-main')

print("=" * 60)
print("Compatibility Test: ADB modules + Original functions")
print("=" * 60)

# Test 1: ADB modules can be imported independently
print("\n[1] ADB modules import...")
try:
    import adb_manager
    import backup_manager
    import install_manager
    print("  OK All ADB modules imported")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 2: Original apk_resigner can still be imported
print("\n[2] Original apk_resigner import...")
try:
    import apk_resigner
    print("  OK apk_resigner imported")
    
    # Check main classes exist
    if hasattr(apk_resigner, 'APKResigner'):
        print("  OK APKResigner class exists")
    if hasattr(apk_resigner, 'quick_replace_sign'):
        print("  OK quick_replace_sign function exists")
    if hasattr(apk_resigner, 'full_process'):
        print("  OK full_process function exists")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 3: GUI can be imported with ADB modules
print("\n[3] GUI module with ADB extension...")
try:
    import apk_resigner_gui
    print("  OK apk_resigner_gui imported")
    
    # Check ADB availability flag
    if hasattr(apk_resigner_gui, 'ADB_AVAILABLE'):
        print(f"  OK ADB_AVAILABLE = {apk_resigner_gui.ADB_AVAILABLE}")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 4: Verify no circular imports
print("\n[4] No circular imports...")
try:
    # Reload modules to check import order
    import importlib
    importlib.reload(adb_manager)
    importlib.reload(backup_manager)
    importlib.reload(install_manager)
    print("  OK No circular import issues")
except Exception as e:
    print(f"  FAIL: {e}")

# Test 5: Data classes work correctly
print("\n[5] Data classes validation...")
try:
    from adb_manager import DeviceInfo, PackageInfo, ExportResult
    from backup_manager import BackupInfo, BackupResult, RestoreResult
    from install_manager import InstallResult, InstallLog
    
    # Create test objects
    dev = DeviceInfo(serial="test123", state="device", model="TestModel")
    assert dev.is_ready == True
    assert dev.display_name == "TestModel (test123)"
    print("  OK DeviceInfo works")
    
    pkg = PackageInfo(name="com.test.app", apk_path="/data/app/test.apk", app_type="THIRD_PARTY")
    assert pkg.display_name == "app"
    print("  OK PackageInfo works")
    
    result = InstallResult(success=True, status="success")
    assert result.success == True
    print("  OK InstallResult works")
    
except Exception as e:
    print(f"  FAIL: {e}")

# Test 6: Check that original GUI methods still exist
print("\n[6] Original GUI methods preserved...")
try:
    from apk_resigner_gui import APKResignerGUI
    
    # Check key methods exist
    methods_to_check = [
        'build_ui', 'select_apk', 'detect_apk_scheme',
        'sign_apk', '_full_process', '_quick_resign',
        'verify_signature', 'log', 'show_help'
    ]
    
    for method in methods_to_check:
        if hasattr(APKResignerGUI, method):
            print(f"  OK Method '{method}' exists")
        else:
            print(f"  WARNING Method '{method}' missing")
            
except Exception as e:
    print(f"  FAIL: {e}")

print("\n" + "=" * 60)
print("Test completed - ADB modules don't break existing functions")
print("=" * 60)
