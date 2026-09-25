# Project: FileFinder

## Architecture
FileFinder is a cross-platform desktop file content search application built with Python 3.13 and PySide6.
The system is strictly decoupled into three functional layers:

1. **Core Layer (`app/core`)**: Standalone search engine with zero GUI dependencies. Includes:
   - `models.py`: Immutable `SearchResult`, mutable `SearchOptions` and `ScanStatistics`.
   - `encoding_detector.py`: Multi-stage encoding detection fallback chain (BOM -> strict UTF-8 -> charset-normalizer with CJK heuristics -> CP949 -> Latin-1).
   - `file_filter.py`: Extension whitelist, compound extensions, exact filenames, and binary null-byte heuristic.
   - `file_scanner.py`: Symlink-safe recursive directory traversal and memory-bounded line streaming.
   - `search_engine.py`: Multi-threaded parallel file searcher using `concurrent.futures.ThreadPoolExecutor`.

2. **Utility Layer (`app/utils`)**: Headless utility modules decoupled from GUI. Includes:
   - `file_utils.py`: File size formatting, relative path calculation, extension normalization/parsing, CSV export with UTF-8 BOM (`utf-8-sig`), bounded context line reading.
   - `platform_utils.py`: OS-specific operations (`open_file_in_default_app`, `reveal_in_file_manager`, `open_folder_in_file_manager`, `copy_to_clipboard`).
   - `logging_utils.py`: Structured application logging with duplicate handler prevention.

3. **Presentation & CLI Layer (`app/gui`, `app/main.py`)**:
   - `app/gui/search_worker.py`: Background `QThread` wrapping `SearchEngine` with thread-safe batch buffering (250 items / 100ms flush).
   - `app/gui/main_window.py`: Virtualized `ResultsTableModel(QAbstractTableModel)` for 100k+ rows, drag-and-drop, context menu, double-click, recent history, Korean validation, status bar.
   - `app/gui/settings_dialog.py`: `QSettings` persistence dialog.
   - `app/gui/styles.py`: Clean developer utility styling.
   - `app/main.py`: Dual-mode entry point routing to headless CLI mode or PySide6 GUI mode.

4. **Packaging & Automation (`packaging/`, `scripts/`, `.github/`)**:
   - PyInstaller spec `packaging/filefinder.spec`.
   - Per-platform build scripts (`scripts/build_macos.sh`, `scripts/build_windows.ps1`, `scripts/build_linux.sh`).
   - GitHub Actions CI workflow (`.github/workflows/ci.yml`).
   - Inno Setup script (`packaging/installer.iss`).

---

## Code Layout
```
FileFinder/
├── app/
│   ├── __init__.py
│   ├── main.py                     # [Phase 6]
│   ├── core/                       # [Phase 1-2, Complete]
│   │   ├── __init__.py
│   │   ├── search_engine.py
│   │   ├── file_scanner.py
│   │   ├── encoding_detector.py
│   │   ├── file_filter.py
│   │   └── models.py
│   ├── gui/                        # [Phase 5]
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── search_worker.py
│   │   ├── settings_dialog.py
│   │   └── styles.py
│   └── utils/                      # [Phase 4]
│       ├── __init__.py
│       ├── file_utils.py
│       ├── platform_utils.py
│       └── logging_utils.py
├── tests/
│   ├── test_e2e_scenarios.py       # [Phase 2, Complete with fixes]
│   ├── test_search_engine.py       # [Phase 3]
│   ├── test_file_scanner.py        # [Phase 3]
│   ├── test_encoding_detector.py   # [Phase 3]
│   ├── test_file_filter.py         # [Phase 3]
│   ├── test_utils.py               # [Phase 4 unit tests]
│   └── test_gui_scenarios.py       # [Phase 5/8 headless GUI tests]
├── packaging/                      # [Phase 7]
│   ├── filefinder.spec
│   ├── README_PACKAGING.md
│   └── installer.iss
├── scripts/                        # [Phase 7]
│   ├── generate_icons.py
│   ├── build_macos.sh
│   ├── build_windows.ps1
│   └── build_linux.sh
├── .github/workflows/              # [Phase 7]
│   └── ci.yml
├── docs/
│   └── ARCHITECTURE.md
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F01 | Core Engine Alignment | Fix cancellation race in `search_engine.py`, latin1 charset detection in `encoding_detector.py`, and test offsets in `test_e2e_scenarios.py` | M1 | Survey 1 |
| F02 | SearchEngine Unit Tests | 22 test scenarios in `tests/test_search_engine.py` covering all 17 requirements | M1 | R1, R2, R6 |
| F03 | FileScanner Unit Tests | 14 test scenarios in `tests/test_file_scanner.py` covering symlink safety, line streaming, error handling | M1 | R1, R6 |
| F04 | EncodingDetector Unit Tests | 14 test scenarios in `tests/test_encoding_detector.py` covering BOM, UTF-8, CP949, Latin-1, Big5 | M1 | R2, R6 |
| F05 | FileFilter Unit Tests | 14 test scenarios in `tests/test_file_filter.py` covering extensions, hidden files, binary null-byte heuristic | M1 | R1, R6 |
| F06 | File Utilities | `app/utils/file_utils.py` with CSV export (UTF-8 BOM), bounded context reader, extension parser | M2 | R3, R4 |
| F07 | Platform Utilities | `app/utils/platform_utils.py` isolating OS operations for open file, reveal in file manager, open folder, clipboard | M2 | R3, R6 |
| F08 | Logging Utilities | `app/utils/logging_utils.py` structured logging | M2 | R6 |
| F09 | SearchWorker Thread | `app/gui/search_worker.py` `QThread` with thread-safe batch buffering (250 items/100ms flush) | M3 | R3 |
| F10 | Virtualized Table Model | `ResultsTableModel(QAbstractTableModel)` for 100k+ rows with sorting, atomic row insertion | M3 | R3 |
| F11 | Main Window UI | `app/gui/main_window.py` folder browse, drag-and-drop, query input, toggles, splitter, preview with highlight | M3 | R3 |
| F12 | Settings & Styles | `app/gui/settings_dialog.py` (`QSettings`), `app/gui/styles.py` dark/light utility theme | M3 | R3 |
| F13 | Context Menus & Dialogs | Double-click open, right-click menu, error files dialog, about dialog, Korean validation | M3 | R3 |
| F14 | CLI Mode & Entry Point | `app/main.py` CLI parser (`--path`, `--query`, `--ignore-case`, `--regex`), stdout streaming, GUI fallback | M4 | R4 |
| F15 | PyInstaller Specification | `packaging/filefinder.spec` bundling icons, resources, hidden imports for macOS/Win/Linux | M5 | R5 |
| F16 | Packaging Documentation | `packaging/README_PACKAGING.md` build environment instructions | M5 | R5 |
| F17 | Platform Build Scripts | `scripts/build_macos.sh`, `scripts/build_windows.ps1`, `scripts/build_linux.sh` | M5 | R5 |
| F18 | Windows Installer Config | `packaging/installer.iss` Inno Setup 6 config | M5 | R5 |
| F19 | GitHub Actions CI | `.github/workflows/ci.yml` matrix testing across 3 OS × Python 3.12/3.13 | M5 | R5 |
| F20 | Code Quality & Lint Gate | `ruff check .` passes 0 errors, `mypy`/`pyright` passes 0 errors | M6 | R6 |
| F21 | Full Test Suite Execution | `pytest` passes 100% across all E2E and unit test suites | M6 | R6 |
| F22 | 15 Manual GUI Scenarios | Automated verification of all 15 scenarios specified in R3/R8 | M6 | R3, R8 |
| F23 | macOS PyInstaller Build | Native execution of `build_macos.sh` producing working `dist/FileFinder.app` | M6 | R5 |
| F24 | Final Report | Honest completion report with test results, packaging status, and limits | M6 | R6 |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Engine Alignment & Unit Tests | Fix 3 core engine/test defects; create `test_search_engine.py`, `test_file_scanner.py`, `test_encoding_detector.py`, `test_file_filter.py` | None | DONE |
| M2 | Utility Modules | Implement `file_utils.py`, `platform_utils.py`, `logging_utils.py`, and `test_utils.py` | None | DONE |
| M3 | PySide6 Desktop GUI | Implement `search_worker.py`, `main_window.py`, `settings_dialog.py`, `styles.py` | M1, M2 | DONE |
| M4 | Main Entry Point & CLI Mode | Implement `app/main.py` (CLI & GUI routing) | M1, M2, M3 | DONE |
| M5 | Cross-Platform Packaging & CI | Create `filefinder.spec`, `README_PACKAGING.md`, build scripts, CI workflow, Inno Setup | M2, M3, M4 | DONE |
| M6 | Final Verification & Report | Run ruff, mypy, full pytest, 15 GUI verification scenarios, macOS PyInstaller build, final report | M1-M5 | DONE |

---

## Interface Contracts

### `app.core.models`
- `SearchResult(file_path: Path, file_name: str, line_number: int, matched_line: str, match_start: int, match_end: int, encoding: str)` (frozen dataclass)
- `SearchOptions(path: Path, query: str, is_regex: bool = False, case_sensitive: bool = False, recursive: bool = True, include_hidden: bool = False, extensions: list[str] = field(default_factory=list))`
- `ScanStatistics(total_files: int, scanned_files: int, success_count: int, error_count: int, errors: list[tuple[Path, str]], elapsed_seconds: float, cancelled: bool)`

### `app.core.search_engine.SearchEngine`
- `search(options: SearchOptions, result_callback: Callable[[SearchResult], None] | None = None, progress_callback: Callable[[int, int, Path], None] | None = None, cancel_event: threading.Event | None = None) -> ScanStatistics`

### `app.utils.file_utils`
- `export_results_to_csv(results: Sequence[SearchResult], target_path: Path | str) -> int` (writes with `utf-8-sig`)
- `read_context_lines(file_path: Path | str, target_line: int, context: int = 5, encoding: str = "utf-8") -> list[tuple[int, str]]`
- `format_file_size(size_in_bytes: int | float) -> str`
- `parse_extensions_string(ext_string: str) -> list[str]`

### `app.utils.platform_utils`
- `open_file_in_default_app(file_path: Path | str) -> bool`
- `reveal_in_file_manager(file_path: Path | str) -> bool`
- `open_folder_in_file_manager(folder_path: Path | str) -> bool`
- `copy_to_clipboard(text: str) -> bool`

### `app.gui.search_worker.SearchWorker`
- Signals:
  - `progress_updated(int, int, str)`: `(scanned_files, total_files, current_path)`
  - `result_found(object)`: `SearchResult`
  - `results_batch_found(list)`: `list[SearchResult]`
  - `search_completed(object)`: `ScanStatistics`
  - `error_occurred(str)`: `str`
- Methods: `cancel() -> None`, `is_cancelled() -> bool`

### `app.main`
- `parse_args(args: Sequence[str] | None = None) -> argparse.Namespace`
- `run_cli(args: argparse.Namespace) -> int`
- `run_gui() -> int`
- `main() -> int`
