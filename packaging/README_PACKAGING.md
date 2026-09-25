# FileFinder Packaging and Distribution Guide

This document provides complete instructions for building, packaging, and distributing **FileFinder** across macOS, Windows, and Linux.

---

## 1. Architecture & Overview

FileFinder is a cross-platform desktop application built with **Python 3.13 / 3.12** and **PySide6 (Qt 6)**. Packaging produces standalone, zero-dependency native executables and installers so end users do not need Python or external dependencies installed.

### Packaging Pipeline
```
[Source Code + Resources]
          │
          ▼
   1. Virtualenv & Dependencies Validation (requirements.txt, requirements-dev.txt)
          │
          ▼
   2. Strict Quality Gate: pytest tests/ (QT_QPA_PLATFORM=offscreen)
          │
          ▼
   3. PyInstaller Compilation (packaging/filefinder.spec)
          │
          ├─── macOS   ──► dist/FileFinder.app  ──► create-dmg ──► FileFinder.dmg
          ├─── Windows ──► dist/FileFinder/     ──► Inno Setup ──► FileFinder-Setup-x64.exe
          └─── Linux   ──► dist/FileFinder/     ──► AppImage   ──► FileFinder-x86_64.AppImage
```

### PyInstaller Spec: `packaging/filefinder.spec`
- **Entry point**: `app/main.py` (CLI & GUI dual mode)
- **Data assets**: Bundles `resources/icons` into `resources/icons`
- **Hidden imports**: `charset_normalizer`, `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtWidgets`
- **Windowed configuration**: `console=False` for clean desktop utility launch
- **macOS bundle**: Creates `FileFinder.app` with `bundle_identifier='com.filefinder.app'` and native `.icns` / `.png` icon assets

---

## 2. Platform Build Scripts

FileFinder includes automated, turn-key build scripts for all three platforms. Each script enforces a strict QA gate: **if any test in `pytest tests/` fails, the build is aborted immediately**.

| Platform | Script | Target Artifact |
| :--- | :--- | :--- |
| **macOS** | `scripts/build_macos.sh` | `dist/FileFinder.app` |
| **Windows** | `scripts/build_windows.ps1` | `dist\FileFinder\FileFinder.exe` + `dist\FileFinder-Setup-x64.exe` |
| **Linux** | `scripts/build_linux.sh` | `dist/FileFinder/FileFinder` |

---

## 3. macOS Build Guide

### 3.1 Build Environment Requirements
- **Operating System**: macOS 11.0 (Big Sur) or newer (tested on macOS 14/15/26 Sonoma/Sequoia, arm64 & x86_64)
- **Xcode Command Line Tools**: `xcode-select --install`
- **Python**: Python 3.12 or 3.13 (installed via python.org, Homebrew, or `uv`)
- **Built-in macOS utilities**: `iconutil` (included in macOS for `.icns` creation)

### 3.2 Automated Build Execution
From the project root directory, run:
```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

The script will:
1. Detect host architecture (`arm64` Apple Silicon or `x86_64` Intel).
2. Verify or initialize the virtual environment (`.venv`).
3. Ensure runtime and development dependencies are installed.
4. Auto-generate `resources/icons/icon.icns` from multi-resolution PNGs if needed.
5. Execute the full pytest test suite in offscreen mode (`QT_QPA_PLATFORM=offscreen`).
6. Run `pyinstaller packaging/filefinder.spec --clean --noconfirm`.
7. Verify `dist/FileFinder.app` and execute a smoke test (`--version`).

### 3.3 Creating a macOS DMG (`create-dmg`)
To create a polished drag-and-drop disk image for distribution:

1. Install `create-dmg`:
   ```bash
   brew install create-dmg
   ```
2. Build the `.dmg`:
   ```bash
   test -f dist/FileFinder.dmg && rm dist/FileFinder.dmg
   create-dmg \
     --volname "FileFinder Installer" \
     --volicon "resources/icons/icon.icns" \
     --window-pos 200 120 \
     --window-size 600 400 \
     --icon-size 100 \
     --icon "FileFinder.app" 175 120 \
     --hide-extension "FileFinder.app" \
     --app-drop-link 425 120 \
     "dist/FileFinder.dmg" \
     "dist/FileFinder.app"
   ```

### 3.4 Universal 2 Binary Considerations (Apple Silicon + Intel)
By default, PyInstaller compiles for the host machine's architecture (`arm64` on Apple Silicon, `x86_64` on Intel).
To distribute a single **Universal 2** binary supporting both architectures:
1. Ensure Python and all native C-extensions (PySide6, shiboken6) provide `universal2` slices or compile both `x86_64` and `arm64` bundles separately.
2. Alternatively, use Apple's `lipo` tool to merge binaries and dylibs:
   ```bash
   lipo -create -output dist/FileFinder-Universal \
     dist/FileFinder-arm64.app/Contents/MacOS/FileFinder \
     dist/FileFinder-x86_64.app/Contents/MacOS/FileFinder
   ```
3. PyInstaller also supports `--target-arch universal2` when invoked with a Universal 2 Python runtime.

### 3.5 Code Signing & Notarization (Apple Developer ID)
To distribute outside the Mac App Store without Gatekeeper warnings:
```bash
# 1. Sign the bundle with hardened runtime
codesign --deep --force --verify --verbose \
  --options runtime \
  --timestamp \
  --sign "Developer ID Application: Your Name (TEAM_ID)" \
  dist/FileFinder.app

# 2. Package into DMG and sign the DMG
codesign --force --sign "Developer ID Application: Your Name (TEAM_ID)" dist/FileFinder.dmg

# 3. Submit for notarization
xcrun notarytool submit dist/FileFinder.dmg \
  --apple-id "developer@example.com" \
  --team-id "TEAM_ID" \
  --password "app-specific-password" \
  --wait

# 4. Staple the notarization ticket
xcrun stapler staple dist/FileFinder.dmg
```

---

## 4. Windows Build Guide

### 4.1 Build Environment Requirements
- **Operating System**: Windows 10 or 11 (64-bit)
- **Python**: Python 3.12 or 3.13 (64-bit) from [python.org](https://www.python.org/) (ensure "Add Python to PATH" is checked)
- **C++ Runtime**: [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- **Shell**: PowerShell 5.1 or PowerShell 7+
- **Installer Compiler**: [Inno Setup 6](https://jrsoftware.org/isdl.php) (for creating `FileFinder-Setup-x64.exe`)

### 4.2 Automated Build Execution
Open PowerShell in the project directory and run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\build_windows.ps1
```

The script will:
1. Verify the 64-bit Python environment.
2. Install dependencies from `requirements.txt` and `requirements-dev.txt`.
3. Verify or generate `resources\icons\app_icon.ico`.
4. Run the full pytest test suite with `QT_QPA_PLATFORM=offscreen`.
5. Execute PyInstaller using `packaging\filefinder.spec`.
6. Verify `dist\FileFinder\FileFinder.exe` and execute smoke test.
7. Automatically detect `ISCC.exe` (Inno Setup) and compile `dist\FileFinder-Setup-x64.exe`.

### 4.3 Inno Setup 6 Installer (`packaging/installer.iss`)
The installer configuration provides:
- **64-bit Program Files** installation (`{autopf}\FileFinder`)
- **Desktop & Start Menu Shortcuts**
- **Explorer Context Menu Integration**: Right-click any folder or drive to select **"Search with FileFinder"**
- **Clean Uninstallation** with complete registry cleanup

To manually compile the installer:
```cmd
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```
Output artifact: `dist\FileFinder-Setup-x64.exe`.

### 4.4 Windows Code Signing (Authenticode)
To prevent Windows SmartScreen warnings:
```cmd
signtool.exe sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a dist\FileFinder-Setup-x64.exe
```

---

## 5. Linux Build Guide

### 5.1 Build Environment Requirements
- **Distribution**: Ubuntu 22.04/24.04 LTS, Debian 12, Fedora 39/40, or Arch Linux
- **Python**: Python 3.12 or 3.13 with `python3-venv` and `python3-pip`
- **System Qt & X11 / Wayland Dependencies**:
  ```bash
  sudo apt-get update && sudo apt-get install -y \
    libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 \
    libdbus-1-3 libfontconfig1 libxcb-cursor0 libxcb-icccm4 \
    libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xfixes0 libxcb-sync1 libxi6 libxrender1
  ```

### 5.2 Automated Build Execution
```bash
chmod +x scripts/build_linux.sh
./scripts/build_linux.sh
```

Output directory: `dist/FileFinder/` containing the `FileFinder` binary and bundled libraries.

### 5.3 AppImage Packaging
To package `dist/FileFinder` into a single standalone portable `FileFinder-x86_64.AppImage`:

1. Download `appimagetool`:
   ```bash
   wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
   chmod +x appimagetool-x86_64.AppImage
   ```

2. Construct the `AppDir` layout:
   ```bash
   mkdir -p AppDir/usr/bin AppDir/usr/lib AppDir/usr/share/icons/hicolor/256x256/apps
   cp -r dist/FileFinder/* AppDir/usr/bin/
   cp resources/icons/app_icon_256.png AppDir/usr/share/icons/hicolor/256x256/apps/filefinder.png
   cp resources/icons/app_icon_256.png AppDir/filefinder.png

   # Create desktop entry
   cat << 'EOF' > AppDir/filefinder.desktop
   [Desktop Entry]
   Name=FileFinder
   Comment=Cross-Platform File Content Search Tool
   Exec=FileFinder
   Icon=filefinder
   Terminal=false
   Type=Application
   Categories=Utility;Filesystem;Development;
   EOF

   # Create AppRun script
   cat << 'EOF' > AppDir/AppRun
   #!/bin/sh
   HERE="$(dirname "$(readlink -f "${0}")")"
   export LD_LIBRARY_PATH="${HERE}/usr/bin:${HERE}/usr/lib:${LD_LIBRARY_PATH}"
   export QT_PLUGIN_PATH="${HERE}/usr/bin/PySide6/plugins"
   exec "${HERE}/usr/bin/FileFinder" "$@"
   EOF
   chmod +x AppDir/AppRun
   ```

3. Build the AppImage:
   ```bash
   ./appimagetool-x86_64.AppImage AppDir dist/FileFinder-x86_64.AppImage
   ```

---

## 6. GitHub Actions CI/CD Matrix

FileFinder includes a multi-platform CI/CD workflow defined in `.github/workflows/ci.yml`.

### Matrix Grid
- **Operating Systems**: `windows-latest`, `macos-latest`, `ubuntu-latest`
- **Python Versions**: `3.12`, `3.13`
- **Total Configurations**: 6 concurrent runner jobs

### Pipeline Stages
1. **Checkout**: `actions/checkout@v4`
2. **Environment Setup**: `actions/setup-python@v5` with pip caching
3. **Dependency Installation**: System Qt libraries + Python runtime & development dependencies
4. **Code Quality Lint Gate**: `ruff check .`
5. **Static Type Checking Gate**: `mypy app`
6. **Automated Testing Gate**: `pytest tests/` with `QT_QPA_PLATFORM=offscreen`
7. **Production PyInstaller Build**: Generates platform executables and validates `--version`
8. **Artifact Publishing**: Uploads compiled artifacts via `actions/upload-artifact@v4`

---

## 7. Troubleshooting & FAQ

### Q: Why do tests require `QT_QPA_PLATFORM=offscreen`?
**A**: PySide6 GUI tests initialize Qt application objects. On headless CI servers or build servers without an active X11/Wayland display, Qt will crash unless configured with `offscreen` or `minimal` QPA platform.

### Q: Why onedir instead of onefile for Windows?
**A**: A PySide6 desktop application bundles ~120MB of Qt runtime dynamic libraries and plugins. PyInstaller's `onefile` mode extracts this entire archive to `%TEMP%` on *every launch*, creating a 5–10 second startup delay and triggering anti-virus false positives. The `onedir` layout (`dist\FileFinder\`) launches instantaneously. Inno Setup compresses the folder into a single setup `.exe` for distribution.

### Q: How to troubleshoot missing Qt plugins in PyInstaller?
**A**: Check that `PySide6.QtCore`, `PySide6.QtGui`, and `PySide6.QtWidgets` are listed in `hiddenimports` in `packaging/filefinder.spec`. PyInstaller's built-in PySide6 hooks automatically discover and bundle the required Qt platform plugins (`libqcocoa.dylib`, `qwindows.dll`, `libqxcb.so`).
