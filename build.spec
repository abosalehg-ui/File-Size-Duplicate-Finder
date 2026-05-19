# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — يبني تنفيذياً قابلاً للتوزيع لـ Windows/Linux/macOS.

الاستخدام:
    pip install pyinstaller
    pyinstaller build.spec --clean
    # المخرجات: dist/FileSizeDuplicateFinder

ملاحظات:
- يضمّن مجلد assets/ بكامله ليكون الأيقونة متاحة وقت التشغيل.
- على ويندوز يستخدم icon.ico، على macOS يحتاج icon.icns (يُولّد لاحقاً).
- console=False ليكون GUI نقياً (لا نافذة CMD على Windows).
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
ICON_ICO = str(ROOT / "assets" / "icon.ico")

block_cipher = None

a = Analysis(
    ['file_size_duplicate_finder.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=['send2trash', 'PyQt5.QtMultimedia'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FileSizeDuplicateFinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=ICON_ICO if sys.platform.startswith('win') else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
