# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for FileFinder.

Builds a standalone cross-platform desktop executable:
- macOS: FileFinder.app bundle with com.filefinder.app identifier and icon
- Windows: FileFinder/ directory containing FileFinder.exe and dependencies
- Linux: FileFinder/ directory containing FileFinder binary and dependencies
"""

import os
import sys
from pathlib import Path

# Resolve project root directory
spec_dir = Path(SPECPATH).resolve()
project_root = spec_dir if (spec_dir / "app" / "main.py").exists() else spec_dir.parent

entry_point = str((project_root / "app" / "main.py").resolve())
icons_src = str((project_root / "resources" / "icons").resolve())

# Resolve application icon (prefer .icns on macOS, fallback to .png)
icon_icns = project_root / "resources" / "icons" / "icon.icns"
icon_png = project_root / "resources" / "icons" / "app_icon.png"
if not icon_png.exists():
    icon_png = project_root / "resources" / "icons" / "icon.png"

if icon_icns.exists():
    macos_icon = str(icon_icns.resolve())
elif icon_png.exists():
    macos_icon = str(icon_png.resolve())
else:
    macos_icon = None

# Windows icon resolution
icon_ico = project_root / "resources" / "icons" / "app_icon.ico"
windows_icon = str(icon_ico.resolve()) if icon_ico.exists() else macos_icon

a = Analysis(
    [entry_point],
    pathex=[str(project_root.resolve())],
    binaries=[],
    datas=[
        (icons_src, "resources/icons"),
    ],
    hiddenimports=[
        "charset_normalizer",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
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
    [],
    exclude_binaries=True,
    name="FileFinder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=macos_icon if sys.platform == "darwin" else windows_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FileFinder",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FileFinder.app",
        icon=macos_icon,
        bundle_identifier="com.filefinder.app",
        info_plist={
            "CFBundleName": "FileFinder",
            "CFBundleDisplayName": "FileFinder",
            "CFBundleGetInfoString": "FileFinder - Cross-Platform File Content Search Tool",
            "CFBundleIdentifier": "com.filefinder.app",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHumanReadableCopyright": "Copyright (c) 2026 FileFinder Contributors",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
