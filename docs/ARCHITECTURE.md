# FileFinder Architecture Specification & Implementation Plan

> **Author**: Explorer M1-1  
> **Milestone**: Milestone 1 (Project Setup & Architecture)  
> **Target Document**: `docs/ARCHITECTURE.md`  
> **Date**: 2026-09-20  

---

## 1. System Overview and Design Philosophy

FileFinder is a high-performance, cross-platform desktop application and command-line utility engineered for fast, recursive text content searching across local filesystems. It is built in **Python 3.13** with a **PySide6** graphical user interface.

### Core Design Principles

1. **Strictly Local & Zero Telemetry**:
   - The application performs all scanning, decoding, and searching strictly on the user's local hardware.
   - Zero outbound network calls, zero analytics, zero telemetry, and zero third-party cloud dependencies.
   - Search queries and file contents reside only in volatile memory during active search execution.

2. **O(1) Streaming Memory Footprint**:
   - Files are never read entirely into memory (`file.read()` or `file.readlines()` are strictly prohibited on search paths).
   - All file scanning processes lines sequentially using Python stream iterators (`for line_idx, line in enumerate(f, start=1)`).
   - Even multi-gigabyte log files are processed with a bounded memory footprint determined only by the length of a single line.

3. **High-Throughput Concurrency**:
   - Search operations are parallelized across available CPU cores using `concurrent.futures.ThreadPoolExecutor`.
   - GIL release during file I/O and compiled C-level regular expression matching (`re` module) allows near-linear speedup on multi-core systems with fast storage (NVMe/SSD).
   - Worker concurrency adapts dynamically to host hardware via `max_workers = min(32, (os.cpu_count() or 1) * 4)`.

4. **UI Thread Isolation & Large-Scale Virtualization**:
   - Complete architectural decoupling between the core search engine and the presentation layers (GUI & CLI).
   - GUI responsiveness is guaranteed through background worker threads (`QThread`) communicating exclusively via Qt Signals/Slots.
   - Results are rendered in a virtualized `QAbstractTableModel` that can seamlessly handle 100,000+ matches at 60 FPS without memory bloat or UI freezes.
   - Worker results are batched in chunks of 100–500 rows to prevent Qt event-queue starvation.

5. **Fault Tolerance & Resilience**:
   - A search operation must never terminate abnormally due to local file permission errors, broken encodings, locked files, or files deleted mid-traversal (race conditions).
   - Errors are trapped at the individual file boundary, recorded into a structured error list, and surfaced to the user without interrupting the search.

6. **Cross-Platform Parity**:
   - Unified path abstractions via `pathlib.Path` across Windows, macOS, and Linux.
   - Platform-specific operations (file opening, desktop file manager revelation, clipboard interaction) are strictly isolated in `app/utils/platform_utils.py`.

---

## 2. Component Architecture and Relationships

### High-Level Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                Presentation Layer                                 |
|                                                                                   |
|      CLI Mode (app/main.py)              GUI Mode (app/gui/main_window.py)        |
|    - argparse option parsing           - PySide6 MainWindow                       |
|    - Terminal stdout streaming         - QTableView + ResultsTableModel           |
|    - Interactive exit codes            - Preview panel (±5 context lines)         |
|                 |                      - Search history & QSettings store         |
|                 |                                      |                          |
|                 |                               (Qt Signals/Slots)                |
|                 |                                      |                          |
|                 |                            +---------v---------+                |
|                 |                            | app/gui/          |                |
|                 |                            | search_worker.py  |                |
|                 |                            | (QThread Worker)  |                |
|                 |                            +---------+---------+                |
|                 |                                      |                          |
+-----------------+--------------------------------------+--------------------------+
                  |                                      |
                  +------------------+-------------------+
                                     |
                                     v
+-----------------------------------------------------------------------------------+
|                                Core Engine Layer                                  |
|                            (app/core/search_engine.py)                            |
|                                                                                   |
|   SearchEngine:                                                                   |
|   - ThreadPoolExecutor parallel pipeline (max_workers = min(32, cpu_count * 4))   |
|   - Thread-safe result and progress callbacks                                     |
|   - Cooperative cancellation via threading.Event                                  |
|   - ScanStatistics aggregation and timing                                         |
|                                                                                   |
|         +-------------------+--------------------+--------------------+           |
|         |                   |                    |                    |           |
|   +-----v-----+       +-----v------------+ +-----v------------+ +-----v------+    |
|   | file_     |       | encoding_        | | file_scanner.py  | | models.py  |    |
|   | filter.py |       | detector.py      | |                  | |            |    |
|   |           |       |                  | | - pathlib        | | - Search   |    |
|   | - Binary  |       | - BOM detector   | |   traversal      | |   Result   |    |
|   |   check   |       | - UTF-8 probe    | | - Symlink safe   | | - Search   |    |
|   | - Exts    |       | - charset-       | | - Line-by-line   | |   Options  |    |
|   | - Hidden  |       |   normalizer     | |   streaming      | | - Scan     |    |
|   |   files   |       | - CP949 / Latin1 | |   generator      | |   Stats    |    |
|   +-----------+       +------------------+ +------------------+ +------------+    |
+-----------------------------------------------------------------------------------+
|                                 Utility Layer                                     |
|                                                                                   |
|  app/utils/platform_utils.py       app/utils/file_utils.py  app/utils/logging_... |
|  - os.startfile (Windows)          - size formatting        - safe standard       |
|  - open (macOS)                    - relative pathing         logging setup       |
|  - xdg-open (Linux)                                                               |
+-----------------------------------------------------------------------------------+
```

### Component Breakdown & Responsibilities

1. **`app/core/models.py`**:
   - Pure data container module defining standard dataclasses: `SearchResult`, `SearchOptions`, `ScanStatistics`.
   - Has zero dependencies outside the Python standard library (`pathlib`, `dataclasses`).

2. **`app/core/file_filter.py`**:
   - Evaluates whether candidate filesystem paths should be scanned based on user options and file safety checks.
   - Enforces binary file exclusion:
     * Fast-path: Extension matching against `KNOWN_BINARY_EXTENSIONS` (e.g. `.exe`, `.dll`, `.zip`, `.png`, `.pyc`, `.pdf`).
     * Content probe: Reads first 8KB; if null byte (`\x00`) is detected, rejects as binary.
   - Enforces user extension filtering: case-insensitive comparison against allowed suffixes.
   - Enforces hidden file filtering: rejects dot-prefixed files/directories unless `include_hidden` is True.

3. **`app/core/encoding_detector.py`**:
   - Detects text file encoding using an ordered fallback chain:
     `UTF-8 BOM / UTF-16 / UTF-32 (BOM probe)` → `Strict UTF-8 validation` → `charset-normalizer` → `CP949/EUC-KR` → `Latin-1`.
   - Never crashes on arbitrary byte patterns; always returns a usable encoding string.

4. **`app/core/file_scanner.py`**:
   - Traverses directories using `pathlib.Path.iterdir()` or `os.scandir()`.
   - Guarantees symlink safety: skips symlinks by default (`follow_symlinks = False`) to prevent infinite recursion and duplicate scans.
   - Provides line streaming generator (`stream_lines`) yielding `(line_number, line_content)` with `errors="replace"`.

5. **`app/core/search_engine.py`**:
   - The central coordinator for all searching operations. GUI-independent and CLI-independent.
   - Manages task distribution across `ThreadPoolExecutor`.
   - Compiles regex or plain-text matching functions.
   - Dispatches results and progress updates through thread-safe callbacks.
   - Tracks execution timing and compiles final `ScanStatistics`.

6. **`app/gui/search_worker.py`**:
   - PySide6 `QThread` subclass wrapping `SearchEngine`.
   - Executes search without blocking the Qt main event loop.
   - Implements result batching: buffers results and emits `results_batch_found` every 100–500 rows or on search completion.
   - Exposes `cancel()` method triggering a cooperative `threading.Event`.

7. **`app/gui/main_window.py`**:
   - PySide6 `QMainWindow` hosting input controls, options bar, virtualized table view, preview panel, and status bar.
   - Contains `ResultsTableModel` (`QAbstractTableModel`) providing row virtualization.
   - Wires user actions to worker start/cancel, handles CSV export, and displays error dialogues.

8. **`app/utils/platform_utils.py`**:
   - Encapsulates operating-system-specific integrations:
     * Windows: `os.startfile()` and `explorer.exe /select,"<path>"`
     * macOS: `/usr/bin/open` and `/usr/bin/open -R "<path>"`
     * Linux: `xdg-open` and D-Bus / file manager commands
     * System clipboard interactions via PySide6 `QGuiApplication.clipboard()` or fallback.

---

## 3. Concurrency Architecture

### ThreadPoolExecutor Model

The search engine executes searches across multiple files concurrently using Python's `concurrent.futures.ThreadPoolExecutor`.

#### 1. Worker Pool Sizing
The number of concurrent worker threads is determined dynamically:
$$\text{max\_workers} = \min(32, \max(4, (\text{os.cpu\_count()} \text{ or } 1) \times 4))$$
- On an 8-core CPU: $\min(32, 32) = 32$ threads.
- On a 4-core CPU: $\min(32, 16) = 16$ threads.
- On a 2-core CPU: $\min(32, 8) = 8$ threads.
- On a single-core VM: $\min(32, 4) = 4$ threads.

**Rationale**: Text file searching is primarily I/O-bound (disk reads, filesystem metadata) and secondarily CPU-bound (regex parsing, encoding decoding). Because Python releases the Global Interpreter Lock (GIL) during C-level file I/O (`read()`) and C-accelerated regex matching, a thread pool ratio of 4× CPU cores achieves optimal I/O overlap without incurring excessive context switching overhead.

### Execution Flow & Two-Phase Pipeline

```
[Main Thread / Worker Thread]
            |
            v
+-------------------------------------------------------------+
| Phase 1: Candidate File Discovery                           |
| - Fast traversal via FileScanner (pathlib/os.scandir)       |
| - Evaluates extension filters and hidden flags              |
| - Respects cancel_event during traversal                    |
| - Collects list of candidate Path objects: [Path, ...]     |
| - Computes total_files count                                |
+-------------------------------------------------------------+
            |
            | candidate_files: list[Path]
            v
+-------------------------------------------------------------+
| Phase 2: Parallel Content Search (ThreadPoolExecutor)       |
|                                                             |
|   Worker Thread 1      Worker Thread 2      Worker Thread N |
|   +--------------+     +--------------+     +-------------+ |
|   | Binary check |     | Binary check |     | Binary check| |
|   | Encoding det |     | Encoding det |     | Encoding det| |
|   | Line stream  |     | Line stream  |     | Line stream | |
|   | Match search |     | Match search |     | Match search| |
|   +-------+------+     +-------+------+     +------+------+ |
|           |                    |                   |        |
|           +--------------------+-------------------+        |
|                                |                            |
|                                v                            |
|                     [Callback Synchronization]              |
|                     - Thread Lock on stats                  |
|                     - progress_callback(scanned, total, p)  |
|                     - result_callback(SearchResult)         |
+-------------------------------------------------------------+
```

### Thread Safety & State Synchronization

- **Stat Counters**: The engine maintains atomic/locked counters for `scanned_files`, `success_count`, and `error_count` via `threading.Lock()`.
- **Callback Invocations**: Because worker threads invoke `result_callback` and `progress_callback` concurrently from different threads:
  * In CLI mode: Output writing is serialized or synchronized to prevent garbled lines.
  * In GUI mode: `SearchWorker` accumulates results into a thread-safe buffer or dispatches via Qt's thread-safe signal delivery mechanism (`Qt.ConnectionType.QueuedConnection`).
- **Cooperative Cancellation**:
  * Managed via a standard `threading.Event`.
  * Checked at three granularities:
    1. During directory traversal before descending into subdirectories.
    2. Before submitting a file to a worker thread.
    3. Inside the inner line-by-line reading loop of every active worker thread.
  * When `cancel_event.set()` is called, in-flight line iterations terminate immediately (`break`), pending executor tasks exit without scanning, and all results already gathered remain valid and accessible.

---

## 4. File Traversal and Streaming Strategy

### Pathlib Traversal & Symlink Safety

- All path manipulation uses `pathlib.Path` objects. Manual string concatenation (e.g. `path + "/" + file`) is strictly prohibited.
- **Symlink Protection**:
  ```python
  if entry.is_symlink():
      # Skip symlinked files and directories by default
      continue
  ```
  Skipping symlinks avoids cyclic filesystem graphs (e.g., recursive directory links) that cause infinite recursion or duplicate result reporting.

- **Hidden File Detection**:
  - A path is considered hidden if any component of its relative path starts with a dot `.` (e.g. `.git`, `.venv`, `.DS_Store`, `config/.secret.txt`).
  - On Windows, paths can additionally be checked for `FILE_ATTRIBUTE_HIDDEN` via `stat().st_file_attributes`.

### Binary File Detection Strategy

A file is rejected prior to searching if it meets either condition:
1. **Extension Check**: The file extension matches `KNOWN_BINARY_EXTENSIONS`.
   - Executables & Libraries: `.exe`, `.dll`, `.so`, `.dylib`, `.bin`, `.o`, `.obj`
   - Archives: `.zip`, `.tar`, `.gz`, `.7z`, `.rar`, `.bz2`, `.xz`, `.iso`, `.dmg`, `.pkg`
   - Media: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.ico`, `.webp`, `.mp3`, `.mp4`, `.wav`, `.avi`, `.mkv`, `.mov`
   - Documents & Bytecode: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`, `.pyc`, `.pyd`, `.class`
   - Databases & Data: `.db`, `.sqlite`, `.sqlite3`, `.wasm`
2. **Null-Byte Heuristic**:
   - If the extension is unknown or text-like, the engine opens the file in binary mode and reads up to **8,192 bytes (8KB)**.
   - If `b'\x00'` is present in the sample, the file is identified as binary and skipped.
   - *Exception*: UTF-16 and UTF-32 files contain null bytes in their byte patterns; however, BOM detection precedes the null-byte heuristic. If a valid UTF-16/32 BOM is detected, the file is recognized as encoded text rather than binary.

### Bounded Line-by-Line Streaming

```python
def stream_file_lines(path: Path, encoding: str) -> Iterator[tuple[int, str]]:
    with open(path, mode="r", encoding=encoding, errors="replace", newline=None) as f:
        for line_number, raw_line in enumerate(f, start=1):
            yield line_number, raw_line.rstrip("\r\n")
```
- Memory consumption per file is strictly $O(\text{longest\_line\_length})$.
- A 500MB log file with 10,000,000 lines requires only a few kilobytes of active working memory.
- `errors="replace"` guarantees that in the rare event of isolated corrupt bytes mid-file, the stream does not crash with `UnicodeDecodeError`, replacing the bad byte with `\ufffd` and allowing search on the remainder of the file.

---

## 5. Encoding Detection Fallback Chain

Files encountered across Windows, macOS, and Linux may be encoded in various legacy and modern formats. FileFinder employs a deterministic 5-stage detection pipeline:

```
+-------------------------------------------------------+
| Input: File Path (reads initial 64KB sample)          |
+-------------------------------------------------------+
                           |
                           v
          [Stage 1: Byte Order Mark (BOM) Check]
          - b'\xef\xbb\xbf'        -> 'utf-8-sig'
          - b'\xff\xfe\x00\x00'    -> 'utf-32-le'
          - b'\x00\x00\xfe\xff'    -> 'utf-32-be'
          - b'\xff\xfe'            -> 'utf-16-le'
          - b'\xfe\xff'            -> 'utf-16-be'
                           | (No BOM matched)
                           v
          [Stage 2: Strict UTF-8 Validation Probe]
          - sample.decode('utf-8', errors='strict')
          - If valid -> return 'utf-8'
                           | (UnicodeDecodeError raised)
                           v
          [Stage 3: charset-normalizer Probe + CJK/CP949 Tiebreaker]
          - charset_normalizer.from_bytes(sample).best()
          - Guard: Discard UTF-16/32 if no BOM and no null bytes present.
          - Tiebreaker Rule: When Big5 is suggested and sample decodes
            as CP949 with Hangul codepoints:
            * If Big5 decode has Cyrillic/Kana artifacts -> return 'cp949'
            * If CP949 candidate has zero chaos / coherence == 0.0 -> return 'cp949'
          - If detected with confidence/chaos <= 0.3 -> return encoding
                           | (Low confidence or None)
                           v
          [Stage 4: Korean Legacy Probe (CP949 / EUC-KR)]
          - sample.decode('cp949', errors='strict')
          - If valid -> return 'cp949'
                           | (UnicodeDecodeError raised)
                           v
          [Stage 5: Latin-1 Ultimate Fallback]
          - Return 'latin-1' (maps all bytes 0x00-0xFF, cannot fail)
```

### Detection Details

1. **BOM Detection**: Checks the first 4 bytes against standard BOM signatures. If present, returns the exact Unicode variant immediately.
2. **UTF-8 Fast-Path**: >90% of modern source code, configs, and documents are UTF-8. Testing `sample.decode('utf-8')` is instantaneous and avoids unnecessary heuristic overhead.
3. **charset-normalizer with CP949/Big5 Tiebreaker**: Uses statistical character frequency and language models to detect Shift-JIS, GBK, Windows-1252, etc., augmented with CJK tiebreaker heuristics to prevent Korean CP949 byte sequences from being falsely categorized as Traditional Chinese (Big5) or non-BOM UTF-16.
4. **CP949 / EUC-KR Validation**: Explicitly validates Korean Windows legacy text files (ANSI/CP949).
5. **Latin-1 Safety Net**: Because ISO-8859-1 (Latin-1) defines a code point for every byte from `0x00` to `0xFF`, decoding under Latin-1 is guaranteed never to raise a `UnicodeDecodeError`.

### CP949 vs Big5 Byte Space Collision & Tiebreaker Algorithm

Statistical character encoding detectors (including `charset-normalizer`) face an inherent mathematical byte collision between Korean EUC-KR/CP949 and Traditional Chinese Big5 on short text sequences (< 20–30 bytes):

#### 1. Mathematical Proof of Byte Space Overlap
- **EUC-KR / KS X 1001**: 2,350 precomposed Hangul syllables use two-byte sequences with lead bytes `0xB0..0xC8` (176–200) and trail bytes `0xA1..0xFE` (161–254).
- **Big5**: Lead bytes span `0xA1..0xF9` (161–249) and trail bytes span `0x40..0x7E` and `0xA1..0xFE`.
- **Collision**: Every KS X 1001 lead byte falls strictly within Big5's lead byte range, and every trail byte falls strictly within Big5's second trail byte range. Empirically, **2,254 of all 2,350 KS X 1001 syllables (95.91%)** decode cleanly under Python's `big5` codec without raising a `UnicodeDecodeError`.
- **Short-String Bias**: On short strings (e.g. `한글`, `공지사항`, `테스트`, `설정`, `버그`), `charset-normalizer` computes `chaos = 0.0` and `coherence = 0.0` for both candidates. Because `big5` is probed before `cp949` in the candidate list, Python's stable sort leaves `big5` at index 0, causing `matches.best()` to erroneously select `big5`.

#### 2. Cyrillic / Kana Artifact Signature
When KS X 1001 Korean bytes are decoded under Big5, a distinctive anomaly appears:
- Big5 code blocks `0xC6A1` to `0xC875` represent **Graphical Characters and Symbols**, specifically Cyrillic letters (`U+0400..U+04FF`) and Japanese Hiragana/Katakana (`U+3040..U+30FF`).
- In CP949, rows `0xC6`, `0xC7`, and `0xC8` encode the common Hangul syllables starting with 'ㅌ', 'ㅍ', and 'ㅎ':
  * `한` (`0xC7D1`) $\rightarrow$ Big5: `и` (Cyrillic Small Letter I, `U+0438`)
  * `항` (`0xC7D7`) $\rightarrow$ Big5: `о` (Cyrillic Small Letter O, `U+043E`)
  * `트` (`0xC6AE`) $\rightarrow$ Big5: `お` (Hiragana Letter O, `U+304A`)
  * `파` (`0xC6C4`) $\rightarrow$ Big5: `だ` (Hiragana Letter Da, `U+3060`)
- **Diagnostic Invariant**: Genuine Traditional Chinese text never contains isolated Russian Cyrillic or Japanese Kana characters interspersed inside Chinese vocabulary. The presence of Cyrillic or Kana in a Big5 decode of CP949-compatible bytes is definitive proof of misdetection.

#### 3. Formal Tiebreaker Rules

##### Rule 3.1: Big5 Family Disambiguation
Triggered when `best.encoding.lower()` is in `{'big5', 'big5hkscs', 'cp950'}`:
1. Attempt `sample.decode('cp949', errors='strict')`. If decoding fails with `UnicodeDecodeError`, accept Big5 (genuine Traditional Chinese).
2. If `cp949` decoding succeeds and the decoded text contains at least one Hangul character (`U+AC00..U+D7A3`, `U+3131..U+318E`, or `U+1100..U+11FF`):
   - **Sub-rule 3.1.a (Cyrillic/Kana Artifact Check)**: Decode `sample` under `big5` with `errors='replace'`. If the decoded string contains any Cyrillic (`U+0400..U+04FF`) or Kana (`U+3040..U+30FF`) character, return `'cp949'` immediately.
   - **Sub-rule 3.1.b (Zero-Chaos / Zero-Coherence Candidate Check)**: If `cp949` (or `euc_kr`) is present in `matches` with `chaos <= 0.05`, OR if `best.coherence == 0.0` (short string ambiguity), return `'cp949'`.

##### Rule 3.2: False-Positive UTF-16 / UTF-32 Guard
Triggered when `best.encoding.lower()` starts with `'utf_16'` or `'utf_32'`:
- Standard UTF-16/32 text containing ASCII, punctuation, or whitespace always contains null bytes (`b'\x00'`).
- If `b'\x00' not in sample`:
  1. If `sample.decode('cp949')` succeeds and contains Hangul, return `'cp949'`.
  2. Otherwise, discard the UTF-16/32 candidate and inspect the next best non-UTF candidate in `matches`.

##### Rule 3.3: Preserving Other Language Encodings
- If `best.encoding` is Japanese (`cp932`, `shift_jis`, `euc_jp`) or Simplified Chinese (`gbk`, `gb18030`), do not override to CP949 unless explicit Big5 collision conditions are met. Genuine CJK text in those encodings is preserved.

---

## 6. Exception Handling and Error Resilience Strategy

A core requirement is zero-crash operation: individual file or system errors must never abort the overall search.

### Error Matrix & Handling Protocols

| Exception Type | Triggering Scenario | Layer Handled | Action Taken | User Visibility |
| :--- | :--- | :--- | :--- | :--- |
| `PermissionError` | Restricted system folder or locked file | `FileScanner` / `SearchEngine` | Log error, skip item, increment `error_count` | Added to `ScanStatistics.errors`; visible in `[오류 파일 N개]` dialog |
| `FileNotFoundError` | File deleted mid-search (race condition) | `FileScanner` / `SearchEngine` | Catch `open()` / `stat()`, skip item | Logged to errors list; search continues uninterrupted |
| `IsADirectoryError` | Path changed to directory or special file | `SearchEngine` | Catch `open()`, skip item | Logged to errors list |
| `UnicodeDecodeError`| Unexpected byte stream despite detection | `SearchEngine` | Handled via `errors="replace"` + try-catch | Line decoded with `\ufffd` or file skipped to error list |
| `re.error` | Invalid regex syntax entered by user | Presentation (`MainWindow` / `run_cli`) | Validate upfront prior to search execution | Inline user error: "올바르지 않은 정규식입니다." |
| `BrokenPipeError` | CLI output piped into closed reader (e.g. `\| head`) | CLI (`app/main.py`) | Catch in stdout loop, exit cleanly with 0 | Clean exit without Python traceback dump |
| `OSError` | I/O bus error, bad disk sector, offline drive | `SearchEngine` worker | Catch in worker try-block, record `(path, str(e))` | Added to `ScanStatistics.errors`; search continues |

### Worker Boundary Safety

Every task dispatched to `ThreadPoolExecutor` executes within a top-level guard:
```python
def _search_single_file(self, path: Path, options: SearchOptions) -> list[SearchResult]:
    try:
        if not self.file_filter.should_scan(path):
            return []
        encoding = self.encoding_detector.detect(path)
        return self._scan_lines(path, encoding, options)
    except (PermissionError, FileNotFoundError, IsADirectoryError, OSError) as exc:
        with self._lock:
            self._stats.error_count += 1
            self._stats.errors.append((path, str(exc)))
        return []
    except Exception as exc:
        logger.warning(f"Unexpected error scanning {path}: {exc}", exc_info=True)
        with self._lock:
            self._stats.error_count += 1
            self._stats.errors.append((path, f"Unexpected: {exc}"))
        return []
    finally:
        with self._lock:
            self._stats.scanned_files += 1
        if self._progress_callback:
            self._progress_callback(self._stats.scanned_files, self._stats.total_files, path)
```

---

## 7. GUI Architecture

The FileFinder graphical interface is built with **PySide6 (Qt 6 for Python)**, prioritizing responsiveness, developer ergonomics, and native platform aesthetics.

### Architecture Diagram

```
+---------------------------------------------------------------------------------+
|                                 MainWindow                                      |
|                                                                                 |
|  +---------------------------------------------------------------------------+  |
|  | Path Input: [ /path/to/search                       ] [ Browse ] [ Search]|  |
|  | Query Input: [ search_query                         ] [ Case ] [ Regex ]  |  |
|  | Options: [x] Recursive  [ ] Hidden  Ext: [.py, .txt, .md                ] |  |
|  +---------------------------------------------------------------------------+  |
|                                                                                 |
|  +---------------------------------------------------------------------------+  |
|  | QTableView (Virtualized View) <---> ResultsTableModel (QAbstractTableModel) |  |
|  |   Columns: [#] [Filename] [Path] [Line] [Matched Content]                 |  |
|  |   Handles 100,000+ rows seamlessly using row index slicing                |  |
|  +---------------------------------------------------------------------------+  |
|                                                                                 |
|  +---------------------------------------------------------------------------+  |
|  | Preview Panel (QPlainTextEdit): Context ±5 lines with match highlighting  |  |
|  +---------------------------------------------------------------------------+  |
|                                                                                 |
|  +---------------------------------------------------------------------------+  |
|  | Progress: [=========>          ] 45% (450/1000) | Results: 1,234          |  |
|  | [ Cancel ] [ 오류 파일 2개 ]                                                |  |
|  +---------------------------------------------------------------------------+  |
+---------------------------------------------------------------------------------+
           |                                                      ^
           | (starts / cancels)                                   | (emits signals)
           v                                                      |
+---------------------------------------------------------------------------------+
|                       SearchWorker (subclasses QThread)                         |
|                                                                                 |
|  - Holds SearchEngine instance and SearchOptions                                |
|  - Executes search() in background POSIX/Windows OS thread                      |
|  - Result Buffer: accumulates up to 200 items before emitting Signal            |
|  - Signals:                                                                     |
|      * results_batch_found(list[SearchResult])                                  |
|      * progress_updated(scanned: int, total: int, current_file: str)            |
|      * search_completed(stats: ScanStatistics)                                  |
|      * search_error(message: str)                                               |
+---------------------------------------------------------------------------------+
```

### Table Virtualization with `QAbstractTableModel`

Standard `QTableWidget` creates a `QTableWidgetItem` object for every cell. For 100,000 results with 5 columns, this generates 500,000 Qt C++ wrapper objects, consuming >500MB of RAM and freezing the UI.

In contrast, FileFinder implements `ResultsTableModel` derived from `QAbstractTableModel`:
- The model stores only a lightweight Python list: `self._results: list[SearchResult]`.
- `rowCount()` returns `len(self._results)`.
- `data(index, role)` is queried by Qt **only for the rows currently visible on the screen** (typically 30–50 rows).
- Memory overhead for 100,000 results is ~25MB total.
- Scrolling remains silky-smooth at 60 FPS regardless of result count.

### Chunked Batching (100–500 Results)

When search matches appear at high frequency (e.g. 50,000 matches in 2 seconds), emitting an individual Qt Signal for each match overwhelms the Qt event loop, leading to UI unresponsiveness.

- `SearchWorker` buffers results in `self._batch: list[SearchResult]`.
- When `len(self._batch) >= 250` (or after a 50ms flush interval), it emits `results_batch_found.emit(self._batch)`.
- In `MainWindow`, the slot updates the model in a single atomic operation:
  ```python
  def on_results_batch_found(self, batch: list[SearchResult]) -> None:
      first_new_idx = len(self._results)
      last_new_idx = first_new_idx + len(batch) - 1
      self.beginInsertRows(QModelIndex(), first_new_idx, last_new_idx)
      self._results.extend(batch)
      self.endInsertRows()
  ```

### Context Preview Panel (±5 Lines)

When a row is selected in the table:
1. `MainWindow` retrieves the corresponding `SearchResult`.
2. Opens the file using the discovered `SearchResult.encoding`.
3. Reads lines from $\max(1, \text{line\_number} - 5)$ to $\text{line\_number} + 5$.
4. Formats the preview in a `QPlainTextEdit` / `QTextEdit` with line numbers and highlights the matched substring using `match_start` and `match_end`.

### Settings Persistence with `QSettings`

On application launch and shutdown, user preferences are persisted natively using `QSettings`:
- Window geometry and state (position, size, maximized state).
- Last selected search directory.
- Last search options (case sensitivity, regex, recursive, hidden files, custom extension list).
- Last 10 search history entries (query + path pairs).

### CSV Export with UTF-8 BOM

- Exports search results to CSV using Python's standard `csv.writer`.
- Pre-pends the UTF-8 Byte Order Mark (`\ufeff`) so that Microsoft Excel on Windows opens the exported file directly with correct Korean and international character rendering without requiring manual encoding import.
- Columns: `file_name`, `file_path`, `line_number`, `matched_line`, `encoding`.

---

## 8. Exact Interfaces and Type Signatures

### 8.1. `app/core/models.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Represents a single match found within a file."""

    file_path: Path
    file_name: str
    line_number: int
    matched_line: str
    match_start: int
    match_end: int
    encoding: str


@dataclass(slots=True)
class SearchOptions:
    """Configuration parameters for a search operation."""

    path: Path
    query: str
    is_regex: bool = False
    case_sensitive: bool = False
    recursive: bool = True
    include_hidden: bool = False
    extensions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScanStatistics:
    """Aggregated statistics and telemetry for a completed or cancelled search."""

    total_files: int = 0
    scanned_files: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    cancelled: bool = False
```

### 8.2. `app/core/file_filter.py`

```python
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Set


class FileFilter:
    """Filters files based on extensions, binary heuristics, and hidden attributes."""

    KNOWN_BINARY_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".dat",
            ".iso",
            ".img",
            ".zip",
            ".tar",
            ".gz",
            ".7z",
            ".rar",
            ".bz2",
            ".xz",
            ".z",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".webp",
            ".tiff",
            ".psd",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".mp3",
            ".mp4",
            ".wav",
            ".avi",
            ".mkv",
            ".mov",
            ".flv",
            ".wmv",
            ".m4a",
            ".pyc",
            ".pyd",
            ".pyo",
            ".class",
            ".o",
            ".obj",
            ".wasm",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".mdb",
            ".pdb",
            ".dmg",
            ".pkg",
            ".deb",
            ".rpm",
            ".msi",
        }
    )

    DEFAULT_TEXT_EXTENSIONS: tuple[str, ...] = (
        ".txt",
        ".log",
        ".md",
        ".csv",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".ini",
        ".conf",
        ".config",
        ".properties",
        ".env",
        ".java",
        ".kt",
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sql",
        ".cs",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".swift",
        ".sh",
        ".bat",
        ".ps1",
        ".gradle",
    )

    def __init__(
        self,
        extensions: Iterable[str] | None = None,
        include_hidden: bool = False,
    ) -> None:
        """Initialize filter with optional extension whitelist and hidden file toggle."""
        ...

    def is_hidden(self, path: Path) -> bool:
        """Check if path or any of its parent components is hidden."""
        ...

    def matches_extension(self, path: Path) -> bool:
        """Check if path matches user-specified extension whitelist."""
        ...

    def is_binary_by_extension(self, path: Path) -> bool:
        """Check if path has a known binary extension."""
        ...

    def is_binary_content(self, path: Path, sample_size: int = 8192) -> bool:
        """Inspect the first sample_size bytes for null bytes (\x00)."""
        ...

    def should_scan(self, path: Path) -> bool:
        """Determine if a file should be scanned, combining all filter checks."""
        ...
```

### 8.3. `app/core/encoding_detector.py`

```python
from __future__ import annotations

from pathlib import Path


class EncodingDetector:
    """Detects text file encoding using an ordered fallback chain with CJK tiebreakers."""

    BOM_MAP: dict[bytes, str] = {
        b"\xef\xbb\xbf": "utf-8-sig",
        b"\xff\xfe\x00\x00": "utf-32-le",
        b"\x00\x00\xfe\xff": "utf-32-be",
        b"\xff\xfe": "utf-16-le",
        b"\xfe\xff": "utf-16-be",
    }

    BIG5_FAMILY: frozenset[str] = frozenset({"big5", "big5hkscs", "cp950"})
    KOREAN_FAMILY: frozenset[str] = frozenset({"cp949", "euc_kr"})
    DEFAULT_SAMPLE_SIZE: int = 65536  # 64KB

    def detect(self, path: Path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
        """
        Detect file encoding following the fallback chain:
        BOM -> UTF-8 -> charset-normalizer (with tiebreakers) -> CP949 -> Latin-1.
        """
        ...

    def detect_from_bytes(self, raw_bytes: bytes) -> str:
        """Detect encoding from in-memory byte slice."""
        ...

    def detect_bom(self, raw_bytes: bytes) -> str | None:
        """Check for known Byte Order Marks at start of byte stream."""
        ...

    def try_utf8(self, raw_bytes: bytes) -> bool:
        """Attempt strict UTF-8 decoding on byte slice."""
        ...

    def try_charset_normalizer(self, raw_bytes: bytes) -> str | None:
        """Probe charset-normalizer with CP949 vs Big5 tiebreakers and UTF-16 guards."""
        ...

    def try_cp949(self, raw_bytes: bytes) -> bool:
        """Attempt strict CP949 decoding on byte slice."""
        ...

    @staticmethod
    def _is_hangul_codepoint(cp: int) -> bool:
        """Check if Unicode codepoint falls within Korean Hangul ranges."""
        ...

    @classmethod
    def _contains_hangul(cls, text: str) -> bool:
        """Return True if text contains at least one Korean Hangul character."""
        ...

    @staticmethod
    def _has_cyrillic_or_kana(text: str) -> bool:
        """Check if text contains Cyrillic or Japanese Kana characters."""
        ...
```

### 8.4. `app/core/file_scanner.py`

```python
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

from app.core.file_filter import FileFilter


class FileScanner:
    """Performs filesystem traversal and provides line-by-line file streaming."""

    def __init__(self, file_filter: FileFilter) -> None:
        self.file_filter = file_filter

    def scan_files(
        self,
        base_path: Path,
        recursive: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[Path]:
        """
        Yields all candidate files matching filter criteria.
        Symlinks are not followed. Checks cancel_event cooperatively.
        """
        ...

    def stream_lines(
        self,
        path: Path,
        encoding: str,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[tuple[int, str]]:
        """
        Streams (line_number, line_text) without loading entire file into memory.
        Uses errors='replace' for decoding resilience.
        """
        ...
```

### 8.5. `app/core/search_engine.py`

```python
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable, Sequence

from app.core.models import ScanStatistics, SearchOptions, SearchResult

ResultCallback = Callable[[SearchResult], None]
ProgressCallback = Callable[[int, int, Path], None]  # scanned, total, current_path


class SearchEngine:
    """Core search engine orchestrating parallel file searches."""

    def __init__(self, max_workers: int | None = None) -> None:
        """Initialize SearchEngine with optional custom worker thread limit."""
        ...

    @staticmethod
    def calculate_max_workers() -> int:
        """Compute optimal thread count: min(32, max(4, (os.cpu_count() or 1) * 4))."""
        ...

    def search(
        self,
        options: SearchOptions,
        result_callback: ResultCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ScanStatistics:
        """
        Execute search across files in parallel.
        Dispatches callbacks and aggregates ScanStatistics.
        """
        ...

    def _search_single_file(
        self,
        path: Path,
        options: SearchOptions,
        pattern: re.Pattern[str] | None,
        result_callback: ResultCallback | None,
        cancel_event: threading.Event | None,
    ) -> list[SearchResult]:
        """Search within a single file. Traps errors, streams lines, returns matches."""
        ...
```

### 8.6. `app/gui/search_worker.py`

```python
from __future__ import annotations

import threading
from PySide6.QtCore import QObject, QThread, Signal

from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.core.search_engine import SearchEngine


class SearchWorker(QThread):
    """QThread worker executing SearchEngine in the background."""

    result_found = Signal(SearchResult)
    results_batch_found = Signal(list)  # list[SearchResult]
    progress_updated = Signal(int, int, str)  # scanned, total, current_file
    search_completed = Signal(ScanStatistics)
    search_error = Signal(str)

    def __init__(
        self,
        engine: SearchEngine,
        options: SearchOptions,
        batch_size: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        ...

    def run(self) -> None:
        """Worker thread entry point. Runs engine.search() and batches signals."""
        ...

    def cancel(self) -> None:
        """Trigger cooperative cancellation of running search."""
        ...
```

### 8.7. `app/gui/main_window.py`

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, Qt
from PySide6.QtWidgets import QMainWindow

from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.gui.search_worker import SearchWorker


class ResultsTableModel(QAbstractTableModel):
    """Virtualized table model supporting 100k+ search results."""

    COLUMNS: list[str] = ["#", "Filename", "Path", "Line", "Matched Content"]

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._results: list[SearchResult] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int: ...
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int: ...
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any: ...
    def headerData(self, section: int, orientation: Qt.Orientation, role: int) -> Any: ...
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None: ...

    def append_batch(self, batch: list[SearchResult]) -> None: ...
    def clear(self) -> None: ...
    def get_result(self, row: int) -> SearchResult | None: ...
    def get_all_results(self) -> list[SearchResult]: ...


class MainWindow(QMainWindow):
    """Main desktop application window for FileFinder."""

    def __init__(self) -> None:
        super().__init__()
        ...

    def setup_ui(self) -> None: ...
    def load_settings(self) -> None: ...
    def save_settings(self) -> None: ...

    # Action Slots
    def on_start_search(self) -> None: ...
    def on_cancel_search(self) -> None: ...
    def on_results_batch(self, batch: list[SearchResult]) -> None: ...
    def on_progress(self, scanned: int, total: int, current_file: str) -> None: ...
    def on_search_completed(self, stats: ScanStatistics) -> None: ...
    def on_row_selected(self, index: QModelIndex) -> None: ...
    def on_row_double_clicked(self, index: QModelIndex) -> None: ...
    def on_context_menu(self, pos: QPoint) -> None: ...
    def on_export_csv(self) -> None: ...
    def on_show_errors(self) -> None: ...
```

### 8.8. `app/utils/platform_utils.py`

```python
from __future__ import annotations

from pathlib import Path


def open_file_in_default_app(file_path: Path) -> bool:
    """
    Opens the specified file using the host OS default associated application.
    Windows: os.startfile()
    macOS: subprocess.run(['open', str(file_path)])
    Linux: subprocess.run(['xdg-open', str(file_path)])
    """
    ...


def reveal_in_file_manager(file_path: Path) -> bool:
    """
    Opens the host desktop file manager with the target file highlighted.
    Windows: explorer.exe /select,"path"
    macOS: open -R "path"
    Linux: dbus show items or xdg-open parent directory
    """
    ...


def copy_to_clipboard(text: str) -> bool:
    """Copies provided text to the system clipboard."""
    ...
```

### 8.9. `app/utils/file_utils.py`

```python
from __future__ import annotations

from pathlib import Path


def format_file_size(size_in_bytes: int) -> str:
    """Format byte integer into human-readable size string (KB, MB, GB)."""
    ...


def get_safe_relative_path(path: Path, base: Path) -> str:
    """Return path relative to base if subpath, else str(path)."""
    ...
```

### 8.10. `app/utils/logging_utils.py`

```python
from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure structured, clean application logging for debugging."""
    ...
```

### 8.11. `app/main.py`

```python
from __future__ import annotations

import argparse
import sys


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for CLI mode."""
    ...


def run_cli(args: argparse.Namespace) -> int:
    """Execute command-line search and stream results to stdout."""
    ...


def run_gui() -> int:
    """Instantiate QApplication and launch MainWindow."""
    ...


def main() -> int:
    """Application entry point: routes to CLI or GUI depending on arguments."""
    ...


if __name__ == "__main__":
    sys.exit(main())
```

---

## 9. Verification & Acceptance Checklist

To verify that the architectural design fulfills all system requirements, the following test and verification gates are established:

1. **GUI Independence**:
   - `from app.core.search_engine import SearchEngine` executes cleanly in environments without `PySide6` installed or without an X11/Wayland/Cocoa display server.
2. **Memory Boundedness**:
   - Searching a synthesized 200MB text file consumes $< 50\text{MB}$ resident set size (RSS) RAM at peak.
3. **Symlink Cycle Safety**:
   - Symlinked directories pointing to ancestors do not cause infinite recursion or crash `FileScanner`.
4. **Encoding Fallback Chain**:
   - Files encoded in UTF-8, UTF-8 with BOM, CP949, and Latin-1 all return matching lines without `UnicodeDecodeError`.
5. **Concurrency & Cancellation**:
   - Invoking `cancel()` during a 10,000-file search halts execution within $< 500\text{ms}$ while retaining already-accumulated results in `ResultsTableModel`.
6. **GUI Virtualization**:
   - Mocking or injecting 100,000 results into `ResultsTableModel` renders immediately and scrolls at 60 FPS.
