# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — يبني تنفيذياً قابلاً للتوزيع لـ Windows/Linux/macOS.

الاستخدام:
    pip install pyinstaller
    pyinstaller build.spec --clean
    # المخرجات: dist/FileSizeDuplicateFinder

ملاحظات:
- يضمّن مجلد assets/ بكامله ليكون الأيقونة متاحة وقت التشغيل.
- على ويندوز يستخدم icon.ico، على macOS يحتاج icon.icns (يُولّد لاحقاً).
- console=False ليكون GUI نقياً (لا نافذة CMD على Windows).
- upx=False: ضغط UPX معروف بكسر بعض Qt DLLs على Windows.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
ICON_ICO = str(ROOT / "assets" / "icon.ico")

a = Analysis(
    ['file_size_duplicate_finder.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
    ],
    # QtSvg يُستورد داخل try/except لرسم الأيقونات — نصرّح به كي لا يُستبعد
    hiddenimports=['send2trash', 'PyQt5.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

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
    upx=False,
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
