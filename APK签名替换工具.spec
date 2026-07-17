# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\Administrator\\apk_resigner-main\\apk_resigner_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('_tools', '_tools')],
    hiddenimports=['cryptography', 'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.asymmetric', 'cryptography.hazmat.primitives.serialization', 'cryptography.x509', 'cert_scanner', 'adb_manager', 'backup_manager', 'install_manager'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='APK签名替换工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
