"""Comprehensive unit test suite for SearchEngine.

Verifies:
Group 1: Plain Text Search (case-insensitive, phrases, metacharacters, multi-match, empty file, empty query)
Group 2: Case-Sensitive Toggle (exact match, toggle OFF, non-cased Unicode)
Group 3: Regular Expression Search (phone pattern, email/IP/boundaries, case toggle, multi-match)
Group 4: Invalid Regex Handling (unclosed parenthesis, dangling quantifier, unclosed bracket)
Group 5: Callback Contracts (SearchResult fields, progress monotonicity, headless mode, empty directory)
Group 6: Cooperative Cancellation (pre-start cancel, mid-search preserve results, Phase 1 cancel)
Group 7: Concurrency with ThreadPoolExecutor (worker pool sizing, multi-thread execution, thread safety)
Group 8: ScanStatistics & File Filtering (extension filter, binary exclusion, UTF-8/CP949, errors, race conditions)
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

from app.core.file_scanner import ErrorCallback, FileScanner
from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine


class TestSearchEnginePlainText:
    """Group 1: Plain text search scenarios."""

    def test_search_plain_text_case_insensitive_default(self, tmp_path: Path) -> None:
        """SE-PLAIN-01: Plain text search is case-insensitive by default."""
        (tmp_path / "f1.txt").write_text("Hello World\nSecond line\n", encoding="utf-8")
        (tmp_path / "f2.txt").write_text("Another HELLO token here\n", encoding="utf-8")
        (tmp_path / "f3.txt").write_text("Unrelated text\n", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="hello")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert stats.success_count == 3
        assert stats.error_count == 0
        assert len(results) == 2
        matched_lines = [r.matched_line for r in results]
        assert "Hello World" in matched_lines
        assert "Another HELLO token here" in matched_lines

    def test_search_multi_word_phrase_with_whitespace(self, tmp_path: Path) -> None:
        """SE-PLAIN-02: Multi-word phrase search matches whitespace and exact token sequences."""
        phrase = "database connection error: connection timeout"
        (tmp_path / "server.log").write_text(
            f"2026-09-20 12:00:00 [ERROR] {phrase}\nNormal operation\n",
            encoding="utf-8",
        )

        opts = SearchOptions(path=tmp_path, query=phrase)
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].line_number == 1
        assert results[0].match_start == 28
        assert results[0].match_end == 28 + len(phrase)
        assert results[0].matched_line[results[0].match_start : results[0].match_end] == phrase

    def test_search_plain_text_with_regex_metacharacters(self, tmp_path: Path) -> None:
        """SE-PLAIN-03: Regex metacharacters (*, +, ?, etc.) are matched literally when is_regex=False."""
        code_line = "if (ptr != nullptr && *ptr == 10) { // [TODO]: check (a+b)*2 }\n"
        (tmp_path / "code.cpp").write_text(code_line, encoding="utf-8")

        query = "[TODO]: check (a+b)*2"
        opts = SearchOptions(path=tmp_path, query=query, is_regex=False)
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert stats.error_count == 0
        assert len(results) == 1
        res = results[0]
        assert res.matched_line[res.match_start : res.match_end] == query

    def test_search_multiple_matches_on_single_line(self, tmp_path: Path) -> None:
        """SE-PLAIN-04: Line containing multiple occurrences produces distinct SearchResult items with accurate spans."""
        (tmp_path / "repeat.txt").write_text("foo bar foo baz foo\n", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="foo")
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 3
        for res in results:
            assert res.line_number == 1
            assert res.matched_line[res.match_start : res.match_end] == "foo"

        spans = [(r.match_start, r.match_end) for r in results]
        assert spans == [(0, 3), (8, 11), (16, 19)]

    def test_search_file_with_zero_matches(self, tmp_path: Path) -> None:
        """SE-PLAIN-05: Files without matching query text yield 0 results and increment success count."""
        (tmp_path / "nomatch.txt").write_text("Some unrelated text without search term\n", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="missing_term")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 0
        assert stats.total_files == 1
        assert stats.scanned_files == 1
        assert stats.success_count == 1
        assert stats.error_count == 0

    def test_search_empty_file_zero_bytes(self, tmp_path: Path) -> None:
        """SE-PLAIN-06: 0-byte file is handled without error or false positive matches."""
        (tmp_path / "empty.txt").write_bytes(b"")

        opts = SearchOptions(path=tmp_path, query="any_term")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 0
        assert stats.scanned_files == 1
        assert stats.success_count == 1
        assert stats.error_count == 0

    def test_search_empty_query_string_immediate_return(self, tmp_path: Path) -> None:
        """SE-PLAIN-07: Empty query string returns immediately with 0 results and 0 scanned files."""
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 0
        assert stats.total_files == 0
        assert stats.scanned_files == 0
        assert stats.elapsed_seconds >= 0.0


class TestSearchEngineCaseSensitivity:
    """Group 2: Case sensitivity toggle scenarios."""

    def test_search_case_sensitive_match_exact_only(self, tmp_path: Path) -> None:
        """SE-CASE-01: Case-sensitive search returns exact-case matches only."""
        (tmp_path / "case.txt").write_text("Alpha\nalpha\nALPHA\naLpHa\n", encoding="utf-8")

        engine = SearchEngine()
        opts = SearchOptions(path=tmp_path, query="Alpha", case_sensitive=True)
        results: list[SearchResult] = []
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].line_number == 1
        assert results[0].matched_line == "Alpha"

    def test_search_case_sensitive_toggle_off_matches_all(self, tmp_path: Path) -> None:
        """SE-CASE-02: When case_sensitive=False, matches all casing variations."""
        (tmp_path / "case.txt").write_text("Alpha\nalpha\nALPHA\naLpHa\n", encoding="utf-8")

        engine = SearchEngine()
        opts = SearchOptions(path=tmp_path, query="Alpha", case_sensitive=False)
        results: list[SearchResult] = []
        engine.search(opts, result_callback=results.append)

        assert len(results) == 4
        matched_lines = [r.matched_line for r in results]
        assert matched_lines == ["Alpha", "alpha", "ALPHA", "aLpHa"]

    def test_search_korean_hangul_case_sensitivity_toggle(self, tmp_path: Path) -> None:
        """SE-CASE-03: Hangul text search behaves consistently regardless of case_sensitive flag."""
        (tmp_path / "hangul.txt").write_text("파일파인더 검색 엔진\n파이썬 3.13\n", encoding="utf-8")

        engine = SearchEngine()

        opts_sens = SearchOptions(path=tmp_path, query="검색 엔진", case_sensitive=True)
        res_sens: list[SearchResult] = []
        engine.search(opts_sens, result_callback=res_sens.append)

        opts_insens = SearchOptions(path=tmp_path, query="검색 엔진", case_sensitive=False)
        res_insens: list[SearchResult] = []
        engine.search(opts_insens, result_callback=res_insens.append)

        assert len(res_sens) == 1
        assert len(res_insens) == 1
        assert res_sens[0].matched_line == res_insens[0].matched_line == "파일파인더 검색 엔진"


class TestSearchEngineRegex:
    """Group 3: Regular expression search scenarios."""

    def test_search_regex_phone_pattern_d3_d4(self, tmp_path: Path) -> None:
        """SE-REGEX-01: Regex search matches phone pattern (\\d{3}-\\d{4}) with accurate spans."""
        content = (
            "Customer phone: 010-1234\n"
            "Office line: 02-99-8888\n"
            "Emergency: 031-5678\n"
            "Extension: 12-3456\n"
        )
        (tmp_path / "phones.txt").write_text(content, encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query=r"\d{3}-\d{4}", is_regex=True)
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 2
        # Match 1: 010-1234 on line 1
        assert results[0].line_number == 1
        assert results[0].matched_line[results[0].match_start : results[0].match_end] == "010-1234"

        # Match 2: 031-5678 on line 3
        assert results[1].line_number == 3
        assert results[1].matched_line[results[1].match_start : results[1].match_end] == "031-5678"

    def test_search_regex_complex_ip_and_email_patterns(self, tmp_path: Path) -> None:
        """SE-REGEX-02: Character classes, quantifiers, and word boundary anchors \\b are respected."""
        log_content = (
            "192.168.1.10 - admin@example.com - login success\n"
            "10.0.0.1 - invalid_email - failed\n"
        )
        (tmp_path / "access.log").write_text(log_content, encoding="utf-8")

        engine = SearchEngine()

        # IP address regex
        opts_ip = SearchOptions(
            path=tmp_path,
            query=r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            is_regex=True,
        )
        res_ip: list[SearchResult] = []
        engine.search(opts_ip, result_callback=res_ip.append)
        assert len(res_ip) == 2
        matched_ips = [r.matched_line[r.match_start : r.match_end] for r in res_ip]
        assert matched_ips == ["192.168.1.10", "10.0.0.1"]

        # Email regex
        opts_email = SearchOptions(
            path=tmp_path,
            query=r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
            is_regex=True,
        )
        res_email: list[SearchResult] = []
        engine.search(opts_email, result_callback=res_email.append)
        assert len(res_email) == 1
        assert (
            res_email[0].matched_line[res_email[0].match_start : res_email[0].match_end]
            == "admin@example.com"
        )

    def test_search_regex_case_sensitivity_toggle(self, tmp_path: Path) -> None:
        """SE-REGEX-03: Regex queries respect case_sensitive toggle."""
        (tmp_path / "codes.txt").write_text("ERR_404\nerr_500\nErr_301\n", encoding="utf-8")
        query = r"ERR_\d{3}"

        engine = SearchEngine()

        # Case-sensitive -> matches only ERR_404
        opts_sens = SearchOptions(path=tmp_path, query=query, is_regex=True, case_sensitive=True)
        res_sens: list[SearchResult] = []
        engine.search(opts_sens, result_callback=res_sens.append)
        assert len(res_sens) == 1
        assert res_sens[0].matched_line == "ERR_404"

        # Case-insensitive -> matches all 3
        opts_insens = SearchOptions(path=tmp_path, query=query, is_regex=True, case_sensitive=False)
        res_insens: list[SearchResult] = []
        engine.search(opts_insens, result_callback=res_insens.append)
        assert len(res_insens) == 3

    def test_search_regex_multiple_matches_single_line(self, tmp_path: Path) -> None:
        """SE-REGEX-04: Multiple regex matches on a single line extract all spans correctly."""
        (tmp_path / "tokens.txt").write_text(
            "Token ID_101 and ID_202 and ID_303 detected\n", encoding="utf-8"
        )

        opts = SearchOptions(path=tmp_path, query=r"ID_\d{3}", is_regex=True)
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 3
        matched_tokens = [r.matched_line[r.match_start : r.match_end] for r in results]
        assert matched_tokens == ["ID_101", "ID_202", "ID_303"]
        spans = [(r.match_start, r.match_end) for r in results]
        assert spans == [(6, 12), (17, 23), (28, 34)]


class TestSearchEngineInvalidRegex:
    """Group 4: Invalid regex syntax error trapping."""

    def test_search_invalid_regex_unclosed_parenthesis(self, tmp_path: Path) -> None:
        """SE-INVREG-01: Malformed regex with unclosed parenthesis is logged to stats.errors."""
        (tmp_path / "file.txt").write_text("sample content", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query=r"(unclosed_group", is_regex=True)
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 0
        assert stats.error_count == 1
        assert len(stats.errors) == 1
        assert "Invalid regex pattern" in stats.errors[0][1]

    def test_search_invalid_regex_dangling_quantifier(self, tmp_path: Path) -> None:
        """SE-INVREG-02: Regex starting with dangling quantifier (*dangling) is caught."""
        (tmp_path / "file.txt").write_text("sample content", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query=r"*dangling", is_regex=True)
        engine = SearchEngine()
        stats = engine.search(opts)

        assert stats.error_count == 1
        assert any("Invalid regex pattern" in msg for _, msg in stats.errors)

    def test_search_invalid_regex_unclosed_bracket(self, tmp_path: Path) -> None:
        """SE-INVREG-03: Regex with unclosed character class bracket ([a-z0-9) is caught."""
        (tmp_path / "file.txt").write_text("sample content", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query=r"[a-z0-9", is_regex=True)
        engine = SearchEngine()
        stats = engine.search(opts)

        assert stats.error_count == 1
        assert any("Invalid regex pattern" in msg for _, msg in stats.errors)


class TestSearchEngineCallbacks:
    """Group 5: Callbacks, contracts, and telemetry verification."""

    def test_search_result_callback_contract_and_field_completeness(self, tmp_path: Path) -> None:
        """SE-CALL-01: result_callback receives a complete SearchResult dataclass with all fields."""
        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("Prefix TARGET_KEYWORD Suffix\n", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="TARGET_KEYWORD")
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        res = results[0]
        assert isinstance(res, SearchResult)
        assert res.file_path == doc_file.resolve()
        assert res.file_name == "doc.txt"
        assert res.line_number == 1
        assert res.matched_line == "Prefix TARGET_KEYWORD Suffix"
        assert res.match_start == 7
        assert res.match_end == 21
        assert res.matched_line[res.match_start : res.match_end] == "TARGET_KEYWORD"
        assert res.encoding.lower() == "utf-8"

    def test_search_progress_callback_progression_and_bounds(self, tmp_path: Path) -> None:
        """SE-CALL-02: progress_callback is invoked monotonically from 1 to total."""
        for i in range(4):
            (tmp_path / f"file_{i}.txt").write_text(f"content {i}", encoding="utf-8")

        calls: list[tuple[int, int, Path]] = []
        calls_lock = threading.Lock()

        def on_progress(scanned: int, total: int, current_file: Path) -> None:
            with calls_lock:
                calls.append((scanned, total, current_file))

        opts = SearchOptions(path=tmp_path, query="content")
        engine = SearchEngine(max_workers=1)
        stats = engine.search(opts, progress_callback=on_progress)

        assert stats.total_files == 4
        assert stats.scanned_files == 4
        assert len(calls) == 4

        for scanned, total, path in calls:
            assert total == 4
            assert 1 <= scanned <= 4
            assert path.exists()

        scanned_sequence = [c[0] for c in calls]
        assert scanned_sequence == [1, 2, 3, 4]

    def test_search_headless_without_callbacks(self, tmp_path: Path) -> None:
        """SE-CALL-03: Search executes cleanly when result_callback and progress_callback are None."""
        (tmp_path / "file.txt").write_text("search target line", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="target")
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=None, progress_callback=None)

        assert stats.success_count == 1
        assert stats.scanned_files == 1
        assert stats.error_count == 0

    def test_search_progress_callback_on_empty_directory(self, tmp_path: Path) -> None:
        """SE-CALL-04: When search folder has 0 candidate files, progress_callback(0, 0, path) is called once."""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        calls: list[tuple[int, int, Path]] = []

        opts = SearchOptions(path=empty_dir, query="any_term")
        engine = SearchEngine()
        stats = engine.search(
            opts,
            progress_callback=lambda s, t, p: calls.append((s, t, p)),
        )

        assert stats.total_files == 0
        assert stats.scanned_files == 0
        assert len(calls) == 1
        assert calls[0] == (0, 0, empty_dir.resolve())


class _Phase1SlowScanner(FileScanner):
    def __init__(self, cancel_event: threading.Event) -> None:
        super().__init__()
        self._cancel_event = cancel_event

    def scan_files(
        self,
        base_path: Path,
        recursive: bool = True,
        include_hidden: bool | None = None,
        extensions: Sequence[str] | None = None,
        cancel_event: threading.Event | None = None,
        error_callback: ErrorCallback | None = None,
    ) -> Iterator[Path]:
        for i in range(100):
            if i == 5:
                self._cancel_event.set()
            yield base_path / f"dummy_{i}.txt"


class TestSearchEngineCancellation:
    """Group 6: Cooperative cancellation scenarios."""

    def test_search_cancellation_set_before_start(self, tmp_path: Path) -> None:
        """SE-CANCEL-01: Setting cancel_event before search() terminates immediately without scanning."""
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("some content", encoding="utf-8")

        cancel_event = threading.Event()
        cancel_event.set()

        opts = SearchOptions(path=tmp_path, query="content")
        engine = SearchEngine()
        stats = engine.search(opts, cancel_event=cancel_event)

        assert stats.cancelled is True
        assert stats.scanned_files == 0
        assert stats.total_files == 0
        assert stats.elapsed_seconds < 0.1

    def test_search_cancellation_mid_search_preserves_results(self, tmp_path: Path) -> None:
        """SE-CANCEL-02: Cancelling mid-search stops remaining work while preserving all discovered results."""
        for i in range(30):
            (tmp_path / f"doc_{i:02d}.txt").write_text("TARGET_CANCEL_TOKEN", encoding="utf-8")

        cancel_event = threading.Event()
        results: list[SearchResult] = []
        results_lock = threading.Lock()

        def on_result(res: SearchResult) -> None:
            with results_lock:
                results.append(res)
                if len(results) >= 5:
                    cancel_event.set()

        opts = SearchOptions(path=tmp_path, query="TARGET_CANCEL_TOKEN")
        engine = SearchEngine(max_workers=2)
        stats = engine.search(opts, result_callback=on_result, cancel_event=cancel_event)

        assert stats.cancelled is True
        assert len(results) >= 5
        assert stats.scanned_files < 30
        for r in results:
            assert r.matched_line == "TARGET_CANCEL_TOKEN"

    def test_search_cancellation_during_discovery_phase(self, tmp_path: Path) -> None:
        """SE-CANCEL-03: Traversal loop halts candidate discovery when cancel_event is set."""
        cancel_event = threading.Event()
        mock_scanner = _Phase1SlowScanner(cancel_event=cancel_event)

        opts = SearchOptions(path=tmp_path, query="query")
        engine = SearchEngine(file_scanner=mock_scanner)
        stats = engine.search(opts, cancel_event=cancel_event)

        assert stats.cancelled is True
        assert stats.total_files < 100


class TestSearchEngineConcurrency:
    """Group 7: ThreadPoolExecutor concurrency and thread safety."""

    def test_search_worker_thread_pool_sizing_and_calculation(self) -> None:
        """SE-CONCUR-01: Worker count respects min(32, max(4, os.cpu_count() * 4)) and custom override."""
        engine_default = SearchEngine()
        expected = SearchEngine.calculate_max_workers()
        assert engine_default.max_workers == expected
        assert 4 <= engine_default.max_workers <= 32

        engine_custom = SearchEngine(max_workers=8)
        assert engine_custom.max_workers == 8

    def test_search_multithreaded_parallel_execution(self, tmp_path: Path) -> None:
        """SE-CONCUR-02: Search actively utilizes multiple worker threads concurrently."""
        for i in range(40):
            (tmp_path / f"file_{i:02d}.txt").write_text("CONCURRENCY_TEST", encoding="utf-8")

        thread_ids: set[int] = set()
        thread_ids_lock = threading.Lock()
        results: list[SearchResult] = []

        def on_result(res: SearchResult) -> None:
            with thread_ids_lock:
                thread_ids.add(threading.get_ident())
                results.append(res)

        opts = SearchOptions(path=tmp_path, query="CONCURRENCY_TEST")
        engine = SearchEngine(max_workers=8)
        stats = engine.search(opts, result_callback=on_result)

        assert len(thread_ids) > 1
        assert len(results) == 40
        assert stats.success_count == 40
        assert stats.error_count == 0

    def test_search_thread_safety_high_contention(self, tmp_path: Path) -> None:
        """SE-CONCUR-03: 100 files searched concurrently maintain atomic telemetry invariant."""
        for i in range(100):
            (tmp_path / f"item_{i:03d}.txt").write_text(f"content line {i}", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="content")
        engine = SearchEngine(max_workers=16)
        stats = engine.search(opts)

        assert stats.total_files == 100
        assert stats.scanned_files == 100
        assert stats.scanned_files == stats.success_count + stats.error_count


class _FailingFileScanner(FileScanner):
    def __init__(self, failing_paths: set[str]) -> None:
        super().__init__()
        self._failing_paths = failing_paths

    def stream_lines(
        self,
        path: Path,
        encoding: str = "utf-8",
        errors: str = "replace",
        cancel_event: threading.Event | None = None,
        error_callback: ErrorCallback | None = None,
        raise_on_error: bool = False,
    ) -> Iterator[tuple[int, str]]:
        if path.name in self._failing_paths:
            raise PermissionError(f"Permission denied accessing {path.name}")
        return super().stream_lines(
            path,
            encoding=encoding,
            errors=errors,
            cancel_event=cancel_event,
            error_callback=error_callback,
            raise_on_error=raise_on_error,
        )


class _MidSearchDeletingScanner(FileScanner):
    def __init__(self, delete_target: str) -> None:
        super().__init__()
        self._delete_target = delete_target

    def scan_files(
        self,
        base_path: Path,
        recursive: bool = True,
        include_hidden: bool | None = None,
        extensions: Sequence[str] | None = None,
        cancel_event: threading.Event | None = None,
        error_callback: ErrorCallback | None = None,
    ) -> Iterator[Path]:
        for p in super().scan_files(
            base_path,
            recursive=recursive,
            include_hidden=include_hidden,
            extensions=extensions,
            cancel_event=cancel_event,
            error_callback=error_callback,
        ):
            if p.name == self._delete_target:
                with contextlib.suppress(OSError):
                    p.unlink()
            yield p


class TestSearchEngineStatsAndRobustness:
    """Group 8: ScanStatistics, robustness, error handling, and file filtering."""

    def test_search_stats_fully_accurate_metrics_100_percent_success(self, tmp_path: Path) -> None:
        """SE-STATS-01: All fields of ScanStatistics are accurate in a clean search."""
        for i in range(5):
            (tmp_path / f"doc_{i}.txt").write_text("clean text", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="clean")
        engine = SearchEngine()
        stats = engine.search(opts)

        assert stats.total_files == 5
        assert stats.scanned_files == 5
        assert stats.success_count == 5
        assert stats.error_count == 0
        assert stats.errors == []
        assert stats.cancelled is False
        assert stats.elapsed_seconds > 0.0

    def test_search_stats_mixed_success_and_error_files(self, tmp_path: Path) -> None:
        """SE-STATS-02: Individual file errors increment error_count, valid files increment success_count."""
        for i in range(3):
            (tmp_path / f"good_{i}.txt").write_text("target_token", encoding="utf-8")
        for i in range(2):
            (tmp_path / f"bad_{i}.txt").write_text("target_token", encoding="utf-8")

        custom_scanner = _FailingFileScanner(failing_paths={"bad_0.txt", "bad_1.txt"})
        engine = SearchEngine(file_scanner=custom_scanner)

        opts = SearchOptions(path=tmp_path, query="target_token")
        results: list[SearchResult] = []
        stats = engine.search(opts, result_callback=results.append)

        assert stats.total_files == 5
        assert stats.scanned_files == 5
        assert stats.success_count == 3
        assert stats.error_count == 2
        assert len(stats.errors) == 2
        assert len(results) == 3
        assert stats.scanned_files == stats.success_count + stats.error_count

    def test_search_stats_nonexistent_search_path(self, tmp_path: Path) -> None:
        """SE-STATS-03: Non-existent search path logs error to stats.errors and exits cleanly."""
        missing = tmp_path / "non_existent_folder"

        opts = SearchOptions(path=missing, query="query")
        engine = SearchEngine()
        stats = engine.search(opts)

        assert stats.error_count == 1
        assert len(stats.errors) == 1
        assert "Search folder does not exist" in stats.errors[0][1]
        assert stats.total_files == 0
        assert stats.scanned_files == 0

    def test_search_single_file_target_scope(self, tmp_path: Path) -> None:
        """SE-STATS-04: Target path pointing directly to a file scans only that file."""
        target_file = tmp_path / "single.txt"
        target_file.write_text("target content inside single file", encoding="utf-8")

        opts = SearchOptions(path=target_file, query="content")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert stats.total_files == 1
        assert stats.scanned_files == 1
        assert stats.success_count == 1
        assert len(results) == 1
        assert results[0].file_name == "single.txt"

    def test_search_extension_filter(self, tmp_path: Path) -> None:
        """SE-EXT-01: Extension filtering limits search to whitelisted file extensions."""
        (tmp_path / "script.py").write_text("query_token in python", encoding="utf-8")
        (tmp_path / "doc.txt").write_text("query_token in text", encoding="utf-8")
        (tmp_path / "read.md").write_text("query_token in markdown", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="query_token", extensions=[".py"])
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_name == "script.py"

    def test_search_binary_exclusion_extension(self, tmp_path: Path) -> None:
        """SE-BIN-01: Files with known binary extensions are skipped entirely."""
        (tmp_path / "app.exe").write_bytes(b"target_token in binary executable\x00\x00")
        (tmp_path / "lib.dll").write_bytes(b"target_token in library\x00")
        (tmp_path / "notes.txt").write_text("target_token in notes", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="target_token")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_name == "notes.txt"
        assert stats.total_files == 1
        assert stats.scanned_files == 1

    def test_search_binary_exclusion_null_byte_heuristic(self, tmp_path: Path) -> None:
        """SE-BIN-02: Files with unlisted extensions but containing null bytes are excluded."""
        (tmp_path / "data.custom").write_bytes(b"MAGIC\x00\x01\x02\x03\ntarget_token in custom")
        (tmp_path / "text.custom").write_text("Plain text with target_token", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="target_token", extensions=[".custom"])
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_name == "text.custom"

    def test_search_utf8_korean_content(self, tmp_path: Path) -> None:
        """SE-ENC-01: UTF-8 Korean Hangul text is correctly detected and searched."""
        text = "파일파인더 검색 엔진 테스트입니다.\n한국어 지원 확인."
        (tmp_path / "korean_utf8.txt").write_text(text, encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="검색 엔진")
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].line_number == 1
        assert "검색 엔진" in results[0].matched_line
        assert results[0].encoding.lower() == "utf-8"

    def test_search_cp949_korean_content(self, tmp_path: Path) -> None:
        """SE-ENC-02: CP949 / EUC-KR Korean text is correctly detected and matched."""
        korean_bytes = "보고서 내용 요약 문서\n완료되었습니다.\n".encode("cp949")
        (tmp_path / "legacy_cp949.txt").write_bytes(korean_bytes)

        opts = SearchOptions(path=tmp_path, query="내용 요약")
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].line_number == 1
        assert "내용 요약" in results[0].matched_line
        assert results[0].encoding.lower() in ("cp949", "euc-kr", "euc_kr")

    def test_search_broken_encoding_file_skipped(self, tmp_path: Path) -> None:
        """SE-ENC-03: Broken encoding does not abort search; valid files succeed."""
        (tmp_path / "corrupt.txt").write_bytes(b"\x81\x82\xff\xfe\xfe\x01\x02\x83broken")
        (tmp_path / "valid.txt").write_text("Valid file with target_kw\n", encoding="utf-8")

        opts = SearchOptions(path=tmp_path, query="target_kw")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_name == "valid.txt"
        assert stats.scanned_files >= 2

    def test_search_race_condition_deleted_file(self, tmp_path: Path) -> None:
        """SE-ERR-02: File deleted mid-search does not crash the program and is handled gracefully."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("target_token in file1", encoding="utf-8")
        file2 = tmp_path / "file2.txt"
        file2.write_text("target_token in file2", encoding="utf-8")

        scanner = _MidSearchDeletingScanner(delete_target="file2.txt")
        engine = SearchEngine(file_scanner=scanner)

        opts = SearchOptions(path=tmp_path, query="target_token")
        results: list[SearchResult] = []
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_name == "file1.txt"
        assert stats.error_count >= 1 or stats.scanned_files >= 1

    def test_search_large_file_line_by_line(self, tmp_path: Path) -> None:
        """SE-PERF-01: Large file is processed line-by-line without excessive memory usage."""
        large_file = tmp_path / "large.txt"
        target_line = 15000

        with open(large_file, mode="w", encoding="utf-8") as f:
            for idx in range(1, target_line + 100):
                if idx == target_line:
                    f.write(f"Line {idx}: SPECIAL_DEEP_TARGET_MATCH\n")
                else:
                    f.write(f"Line {idx}: standard filler log entry content\n")

        opts = SearchOptions(path=tmp_path, query="SPECIAL_DEEP_TARGET_MATCH")
        results: list[SearchResult] = []
        engine = SearchEngine()
        stats = engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].line_number == target_line
        assert "SPECIAL_DEEP_TARGET_MATCH" in results[0].matched_line
        assert stats.success_count == 1

    def test_search_hidden_files_toggle(self, tmp_path: Path) -> None:
        """SE-HIDDEN-01: Hidden dotfiles and dotdirs are excluded by default and included when enabled."""
        (tmp_path / ".hidden_file.txt").write_text("secret_keyword", encoding="utf-8")
        hidden_dir = tmp_path / ".hidden_dir"
        hidden_dir.mkdir()
        (hidden_dir / "nested.txt").write_text("secret_keyword", encoding="utf-8")
        (tmp_path / "visible.txt").write_text("secret_keyword", encoding="utf-8")

        engine = SearchEngine()

        # Default: include_hidden=False
        opts_no_hidden = SearchOptions(path=tmp_path, query="secret_keyword", include_hidden=False)
        results_no_hidden: list[SearchResult] = []
        engine.search(opts_no_hidden, result_callback=results_no_hidden.append)

        assert len(results_no_hidden) == 1
        assert results_no_hidden[0].file_name == "visible.txt"

        # Enabled: include_hidden=True
        opts_hidden = SearchOptions(path=tmp_path, query="secret_keyword", include_hidden=True)
        results_hidden: list[SearchResult] = []
        engine.search(opts_hidden, result_callback=results_hidden.append)

        assert len(results_hidden) == 3
        names = {r.file_name for r in results_hidden}
        assert names == {"visible.txt", ".hidden_file.txt", "nested.txt"}

    def test_search_symlink_safety(self, tmp_path: Path) -> None:
        """SE-SYM-01: Symlinks are not followed by default, avoiding duplicate matches and recursion."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "target.txt").write_text("symlink_token_content", encoding="utf-8")

        symlink_dir = tmp_path / "link_dir"
        try:
            symlink_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            return

        opts = SearchOptions(path=tmp_path, query="symlink_token_content")
        results: list[SearchResult] = []
        engine = SearchEngine()
        engine.search(opts, result_callback=results.append)

        assert len(results) == 1
        assert results[0].file_path.resolve() == (real_dir / "target.txt").resolve()
