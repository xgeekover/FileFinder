# FileFinder

> **Cross-Platform File Content Search Tool**

[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![GUI Framework](https://img.shields.io/badge/GUI-PySide6%20(Qt%206)-green.svg)](https://www.qt.io/qt-for-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform Support](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)]()

FileFinder is a high-performance, cross-platform desktop application and command-line utility for fast, recursive text content searching across local filesystems. Built with **Python 3.13** and **PySide6 (Qt 6 for Python)**, FileFinder delivers an intuitive, developer-friendly interface powered by a multithreaded streaming search engine capable of handling hundreds of thousands of files with an $O(1)$ memory footprint.

---

## Screenshots

```
+---------------------------------------------------------------------------------+
|  FileFinder - Cross-Platform File Content Search Tool               [_][o][x]   |
+---------------------------------------------------------------------------------+
| Search Folder: [/Users/username/workspace/projects           ] [Browse...]      |
| Search Query:  [calculate_tax                                ] [Search] [Cancel]|
| Options:       [x] Recursive  [ ] Case Sensitive  [ ] Regex  [ ] Hidden Files   |
| Extensions:    [.py, .txt, .md, .json, .csv, .yaml                            ] |
+---------------------------------------------------------------------------------+
| #  | Filename        | Path                         | Line | Matched Content    |
|----+-----------------+------------------------------+------+--------------------|
| 1  | order_calc.py   | src/billing/order_calc.py    | 42   | def calculate_t... |
| 2  | test_billing.py | tests/test_billing.py        | 115  | res = calculate... |
| 3  | invoice.py      | src/models/invoice.py        | 88   | total += calcula...|
+---------------------------------------------------------------------------------+
| Context Preview (src/billing/order_calc.py : 42)                                |
|   40:     # Calculate billing totals with applicable regional taxes             |
|   41:     tax_rate = 0.0825                                                     |
| > 42:     def calculate_tax(subtotal: float, rate: float) -> float:             |
|   43:         return round(subtotal * rate, 2)                                  |
|   44:                                                                           |
+---------------------------------------------------------------------------------+
| Scanned: 1,420 / 1,420 files | Results: 3 matches (0.14s)      [ 오류 파일 0개 ] |
+---------------------------------------------------------------------------------+
```

*(Graphical screenshots will be updated in `docs/screenshots/` upon final packaging.)*

---

## Features

### 🔍 High-Throughput Search Engine
- **Multithreaded Execution**: Leverages `concurrent.futures.ThreadPoolExecutor` with dynamic worker allocation (`max_workers = min(32, cpu_count * 4)`) for near-linear disk I/O and CPU scaling.
- **Bounded O(1) Memory Footprint**: Strictly reads files line-by-line via stream iterators; never loads entire files into memory. Seamlessly searches large files (>100MB) without memory pressure.
- **Search Modes**:
  - Plain string matching (default: case-insensitive; optional: case-sensitive).
  - Regular expression pattern matching with upfront syntax validation.
- **Traversal Controls**:
  - Recursive directory traversal or top-level only.
  - Symlink-safe traversal: skips filesystem symlinks by default to prevent infinite loops.
  - Hidden files and folders toggle (excluded by default).
  - Customizable extension whitelists (preset for 35+ common developer formats including `.py`, `.ts`, `.js`, `.json`, `.md`, `.txt`, `.csv`, `.xml`, `.yaml`, `.sql`, etc., or custom user-defined lists).
- **Intelligent Binary Exclusion**:
  - Fast extension rejection for known binary formats (`.exe`, `.dll`, `.so`, `.png`, `.jpg`, `.zip`, `.pdf`, `.pyc`, etc.).
  - 8KB null-byte (`\x00`) content probe for unlisted binary file detection.
- **Multi-Encoding Auto-Detection**:
  - Deterministic 5-stage fallback chain:
    1. Byte Order Mark (BOM) inspection (UTF-8-SIG, UTF-16, UTF-32).
    2. Strict UTF-8 validation fast-path.
    3. Statistical charset detection via `charset-normalizer`.
    4. Korean legacy encoding probe (`CP949` / `EUC-KR`).
    5. Fallback safety net (`Latin-1`).
- **Fault-Tolerant Resilience**:
  - File errors (`PermissionError`, `FileNotFoundError`, `UnicodeDecodeError`, `OSError`) never crash or abort active searches.
  - Gracefully tolerates files deleted or modified mid-scan (race conditions).
  - Structured error recording viewable via the GUI error list dialog.
- **Cooperative Cancellation**: Instantly halts traversal and file searching upon user request while retaining all matches found up to that moment.

### 🖥️ Modern PySide6 Desktop GUI
- **Fast Virtualized Results Table**: Custom `QAbstractTableModel` handles 100,000+ results smoothly at 60 FPS. Results are batched (100–500 items per GUI cycle) to ensure the interface never freezes.
- **Rich Context Preview**: Displays $\pm 5$ lines of surrounding file context with search term highlighting.
- **Real-Time Telemetry**: Live progress bar indicating scanned files, total files, current file path, match count, and elapsed search time.
- **Ergonomic Context Menu**: Right-click any match to open the file, reveal it in the native file manager (Finder on macOS, Explorer on Windows, xdg-open on Linux), or copy path/filename/content to clipboard.
- **Native Default Application Launch**: Double-click any row to open the file in the operating system's default editor or viewer.
- **Search History**: Automatically persists the last 10 search queries and directory paths for instant recall.
- **Settings Persistence**: User preferences (directory, options, filters, window geometry) are natively saved via `QSettings`.
- **CSV Export with UTF-8 BOM**: Export search results to CSV with UTF-8 BOM (`\ufeff`) for seamless viewing in Microsoft Excel across all operating systems.
- **Background Worker**: All searching runs inside a dedicated `QThread`, keeping the UI responsive at all times.

### 💻 Headless CLI Mode
- Run searches directly from the command line:
  ```bash
  python -m app.main --path /path/to/search --query "search_term" [--ignore-case] [--regex]
  ```
- Integrates into terminal workflows, shell pipes, and headless servers using the identical core search engine.

---

## Requirements

### Runtime Requirements
- **Python**: 3.12 or 3.13 (strictly verified on CPython 3.13.14)
- **PySide6**: `>=6.6.0,<7.0.0`
- **charset-normalizer**: `>=3.3.0,<4.0.0`

### Supported Platforms
- **macOS**: macOS 11 (Big Sur) or higher (Apple Silicon ARM64 and Intel x86_64)
- **Windows**: Windows 10 or Windows 11 (64-bit)
- **Linux**: Modern desktop distributions (Ubuntu 22.04+, Fedora, Debian, Arch) running X11 or Wayland

---

## Installation

### From Source / Pip

1. **Clone the repository**:
   ```bash
   git clone https://github.com/example/FileFinder.git
   cd FileFinder
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3.13 -m venv .venv
   # On macOS / Linux:
   source .venv/bin/activate
   # On Windows (Command Prompt):
   .venv\Scripts\activate.bat
   # On Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   ```

3. **Install FileFinder**:
   ```bash
   pip install .
   ```

### Standalone Pre-Built Binaries

Pre-packaged standalone executables that require no Python installation will be available from the Releases page:
- **macOS**: `FileFinder.app` / `FileFinder-1.0.0.dmg`
- **Windows**: `FileFinder-Setup-x64.exe` / portable `FileFinder.exe`
- **Linux**: `FileFinder` standalone ELF binary / AppImage

---

## Development Guide

### 1. Environment Setup

FileFinder recommends using [uv](https://github.com/astral-sh/uv) or standard Python `venv`:

```bash
# Using uv (recommended for ultra-fast setup):
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt

# Or using standard python:
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Running the Application

```bash
# Launch GUI Mode:
python -m app.main
# or via entrypoint:
filefinder-gui

# Run CLI Mode:
python -m app.main --path . --query "SearchEngine" --ignore-case
```

### 3. Running Automated Tests

FileFinder maintains a comprehensive test suite covering all search engine features, encoding edge cases, concurrency, and UI components:

```bash
# Run pytest with strict markers and verbose reporting:
pytest

# Run tests with coverage:
pytest --cov=app tests/
```

### 4. Code Formatting and Linting

We enforce strict formatting and linting via Ruff:

```bash
# Check code style and rules:
ruff check .

# Check formatting compliance:
ruff format --check .

# Automatically apply safe fixes and formatting:
ruff check --fix .
ruff format .
```

### 5. Static Type Checking

FileFinder utilizes strict typing across all modules:

```bash
# Run Mypy:
mypy app scripts

# Run Pyright:
pyright
```

### 6. Icon Asset Generation

To re-render application icons into standard PNG resolutions (16x16 up to 512x512) from the master SVG asset:

```bash
python scripts/generate_icons.py
```

---

## Build and Packaging Instructions

FileFinder packages into standalone GUI desktop executables using **PyInstaller**:

### Platform Build Scripts

- **macOS**:
  ```bash
  chmod +x scripts/build_macos.sh
  ./scripts/build_macos.sh
  ```
  *(Produces `dist/FileFinder.app` on macOS hosts)*

- **Windows**:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
  .\scripts\build_windows.ps1
  ```
  *(Produces `dist\FileFinder.exe` on Windows hosts)*

- **Linux**:
  ```bash
  chmod +x scripts/build_linux.sh
  ./scripts/build_linux.sh
  ```
  *(Produces `dist/FileFinder` on Linux hosts)*

*Note: In accordance with PyInstaller cross-compilation boundaries, native executables must be built within their corresponding host environments or CI runners.*

For advanced packaging details, Inno Setup configurations, and DMG tooling, refer to [packaging/README_PACKAGING.md](packaging/README_PACKAGING.md).

---

## Security and Privacy Statement

> **FileFinder performs file searches locally. No file content is uploaded to an external server. No telemetry or analytics.**

### Security Commitments:
1. **100% Local & Offline**: All filesystem traversals, character encoding detections, regular expression compilations, and line matching are executed strictly on your local computer. The application requires zero internet connectivity and creates no network sockets.
2. **Zero Telemetry**: FileFinder contains no telemetry beacons, tracking pixels, crash uploaders, or usage analytics libraries.
3. **Volatile Memory Only**: File contents and user queries reside strictly in volatile process memory during active search execution and are discarded immediately.
4. **Read-Only Inspection**: FileFinder opens files strictly in read-only mode (`mode="r"` or `mode="rb"`). The search engine never modifies, truncates, or writes to the target files being searched.
5. **Safe Error Handling**: Files inaccessible due to operating system permission restrictions (`PermissionError`) are safely skipped and reported only to your local screen.

---

## Architecture

For an in-depth exploration of FileFinder's internal component design, threading synchronization, model virtualization, and fallback algorithms, see the comprehensive [Architecture Documentation](docs/ARCHITECTURE.md).

---

## License

This project is licensed under the terms of the **MIT License**. See the [LICENSE](LICENSE) file for complete license terms.
