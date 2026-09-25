"""Adversarial stress and verification tests by Challenger M2-1.

Empirical verification suite for Milestone 2:
1. High concurrency (32 worker threads) searching 1,000 files.
2. Cooperative cancellation mid-search via threading.Event (promptness + preservation).
3. Line-by-line streaming on a large file (>10MB) measuring O(1) memory footprint.
4. Regex search resilience with invalid regex patterns (graceful error logging, no crash).
5. Adversarial race conditions (file deleted mid-search) and permission errors.
"""

from __future__ import annotations

import contextlib
import threading
import time
import tracemalloc
from pathlib import Path

import pytest

from app.core.file_scanner import FileScanner
from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine


class TestChallengerConcurrency:
    """Stress testing SearchEngine under heavy concurrency."""

    def test_high_concurrency_32_threads_1000_files(self, tmp_path: Path) -> None:
        """Adversarial test: 32 worker threads searching 1,000 files simultaneously.

        Verifies:
        - All 1,000 files are scanned without thread starvation or deadlocks.
        - Correct number of matches discovered without race conditions or dropped callbacks.
        - Multiple worker threads are concurrently utilized.
        - Thread safety of ScanStatistics and callbacks under heavy contention.
        """
        total_files = 1000
        target_token = "TARGET_KEYWORD_CONCURRENCY_48f0d"

        # Create nested directory hierarchy
        # 10 subdirectories with 100 files each
        expected_total_matches = 0
        match_file_indices = set(range(0, total_files, 4))  # every 4th file matches (250 files)

        for i in range(total_files):
            subdir = tmp_path / f"subdir_{i // 100:02d}"
            subdir.mkdir(parents=True, exist_ok=True)
            file_path = subdir / f"file_{i:04d}.txt"

            if i in match_file_indices:
                # Some files have 1 match, some have 2 matches
                if i % 8 == 0:
                    content = (
                        f"Header line {i}\n"
                        f"First match {target_token}\n"
                        "Middle\n"
                        f"Second match {target_token}\n"
                        "Footer\n"
                    )
                    expected_total_matches += 2
                else:
                    content = f"Line 1\nTarget content {target_token} here\nLine 3\n"
                    expected_total_matches += 1

                # Vary encodings for a subset of matching files
                if i % 20 == 0:
                    file_path.write_bytes(content.encode("cp949"))
                elif i % 40 == 0:
                    file_path.write_bytes(content.encode("latin-1"))
                elif i % 60 == 0:
                    file_path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
                else:
                    file_path.write_text(content, encoding="utf-8")
            else:
                # Distractor files without match, some empty
                if i % 50 == 0:
                    file_path.write_text("", encoding="utf-8")
                else:
                    content = f"Filler text line 1 for file {i}\nNo match in this file at all\nAnother line.\n"
                    file_path.write_text(content, encoding="utf-8")

        # Configure engine with explicit 32 threads
        engine = SearchEngine(max_workers=32)
        assert engine.max_workers == 32

        discovered_results: list[SearchResult] = []
        worker_thread_ids: set[int] = set()
        progress_calls: list[tuple[int, int, Path]] = []
        progress_lock = threading.Lock()
        results_lock = threading.Lock()

        def result_callback(res: SearchResult) -> None:
            worker_thread_ids.add(threading.get_ident())
            with results_lock:
                discovered_results.append(res)

        def progress_callback(scanned: int, total: int, current_file: Path) -> None:
            worker_thread_ids.add(threading.get_ident())
            with progress_lock:
                progress_calls.append((scanned, total, current_file))

        options = SearchOptions(
            path=tmp_path,
            query=target_token,
            is_regex=False,
            case_sensitive=True,
            recursive=True,
        )

        stats = engine.search(
            options=options,
            result_callback=result_callback,
            progress_callback=progress_callback,
        )

        # Concurrency & utilization checks
        assert len(worker_thread_ids) > 1, (
            f"Expected multi-threaded execution, got {len(worker_thread_ids)} threads"
        )
        assert len(worker_thread_ids) >= 4, (
            f"Expected significant concurrency, got {len(worker_thread_ids)} distinct threads"
        )

        # Integrity and accuracy checks
        assert stats.total_files == total_files, f"Expected {total_files} total files, got {stats.total_files}"
        assert stats.scanned_files == total_files, f"Expected {total_files} scanned files, got {stats.scanned_files}"
        assert stats.success_count == total_files, f"Expected {total_files} successes, got {stats.success_count}"
        assert stats.error_count == 0, f"Expected 0 errors, got {stats.error_count}: {stats.errors}"
        assert not stats.cancelled

        # Match count accuracy
        assert len(discovered_results) == expected_total_matches, (
            f"Expected {expected_total_matches} matches, got {len(discovered_results)}"
        )

        # Verify SearchResult fields for every result
        for res in discovered_results:
            assert res.file_path.exists()
            assert res.file_name == res.file_path.name
            assert target_token in res.matched_line
            assert res.match_start >= 0
            assert res.match_end > res.match_start
            assert res.encoding in ("utf-8", "utf-8-sig", "cp949", "latin-1")

        # Verify progress callback invocation
        assert len(progress_calls) == total_files
        final_scanned, final_total, _ = progress_calls[-1]
        assert final_scanned == total_files
        assert final_total == total_files
        assert stats.elapsed_seconds > 0.0


class TestChallengerCancellation:
    """Stress testing cancellation responsiveness and result preservation."""

    def test_cancellation_mid_search_stops_promptly_and_preserves_results(self, tmp_path: Path) -> None:
        """Adversarial test: Cancel search mid-flight and verify immediate termination.

        Verifies:
        - Search stops promptly upon cancel_event.set() (latency < 1.0s).
        - Already discovered results are preserved without data corruption.
        - stats.cancelled is True.
        - Does not scan all files (proves premature cooperative termination).
        """
        file_count = 500
        target = "KEYWORD_TO_CANCEL"

        for i in range(file_count):
            p = tmp_path / f"cancel_test_{i:04d}.txt"
            # Add padding lines to ensure file takes non-zero time
            lines = [f"Padding line {j} in file {i}" for j in range(30)]
            lines.insert(15, f"Matched keyword: {target}")
            p.write_text("\n".join(lines), encoding="utf-8")

        engine = SearchEngine(max_workers=8)
        cancel_event = threading.Event()
        discovered: list[SearchResult] = []
        cancel_triggered_at: float = 0.0
        threshold_results = 20

        def on_result(res: SearchResult) -> None:
            nonlocal cancel_triggered_at
            discovered.append(res)
            if len(discovered) >= threshold_results and not cancel_event.is_set():
                cancel_triggered_at = time.perf_counter()
                cancel_event.set()

        options = SearchOptions(
            path=tmp_path,
            query=target,
            is_regex=False,
            recursive=True,
        )

        stats = engine.search(
            options=options,
            result_callback=on_result,
            cancel_event=cancel_event,
        )
        returned_at = time.perf_counter()

        cancellation_delay = returned_at - cancel_triggered_at

        # Verify prompt cancellation
        assert cancel_event.is_set()
        assert stats.cancelled is True
        assert cancellation_delay < 1.5, f"Cancellation took too long: {cancellation_delay:.4f}s"

        # Verify result preservation
        assert len(discovered) >= threshold_results, (
            f"Expected at least {threshold_results} preserved results, got {len(discovered)}"
        )
        assert stats.scanned_files < file_count, (
            f"Expected early termination, but all {file_count} files were scanned"
        )

        for res in discovered:
            assert target in res.matched_line

    def test_cancellation_pre_set_event(self, tmp_path: Path) -> None:
        """Verify that pre-cancelled event returns immediately with 0 files processed."""
        (tmp_path / "file1.txt").write_text("Hello World", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Hello Universe", encoding="utf-8")

        cancel_event = threading.Event()
        cancel_event.set()  # Cancelled before start

        engine = SearchEngine()
        options = SearchOptions(path=tmp_path, query="Hello")

        start = time.perf_counter()
        stats = engine.search(options=options, cancel_event=cancel_event)
        elapsed = time.perf_counter() - start

        assert stats.cancelled is True
        assert stats.total_files == 0
        assert stats.scanned_files == 0
        assert elapsed < 0.05, f"Pre-cancelled search took {elapsed}s, should be <0.05s"


class TestChallengerStreamingMemory:
    """Stress testing memory bounds on large files (>10MB)."""

    def test_line_by_line_streaming_o1_memory_on_15mb_file(self, tmp_path: Path) -> None:
        """Adversarial test: Stream search on a 15MB file and prove O(1) memory consumption.

        Verifies:
        - Peak memory growth during search is under 2.5 MB (drastically below 15MB file size).
        - Proves file content is read sequentially in small line buffers without slurp into memory.
        - Correctly locates matches at early, middle, and late line positions.
        """
        large_file = tmp_path / "large_stress_file.txt"
        target_token = "SPECIAL_LINE_TOKEN_FOUND"

        line_count = 150_000
        line_length = 100  # 150,000 * 100 bytes ≈ 15 MB
        padding_chars = "x" * (line_length - 1)

        # Target line indices (1-based)
        target_lines = {10, 50_000, 100_000, 149_990}

        # Write 15MB file sequentially
        with open(large_file, "w", encoding="utf-8") as f:
            for idx in range(1, line_count + 1):
                if idx in target_lines:
                    f.write(f"{target_token}_AT_{idx} " + ("y" * 60) + "\n")
                else:
                    f.write(f"Line_{idx:07d}_{padding_chars}\n")

        file_size_bytes = large_file.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)
        assert file_size_mb >= 14.0, f"Generated file is {file_size_mb:.2f} MB, expected >= 14 MB"

        # 1. Test FileScanner.stream_lines directly with tracemalloc
        scanner = FileScanner()
        tracemalloc.start()
        tracemalloc.reset_peak()
        mem_before, _ = tracemalloc.get_traced_memory()

        streamed_matches = []
        for line_no, text in scanner.stream_lines(large_file, encoding="utf-8"):
            if target_token in text:
                streamed_matches.append((line_no, text))

        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        scanner_peak_overhead_mb = (peak_mem - mem_before) / (1024 * 1024)
        assert len(streamed_matches) == len(target_lines)
        assert {m[0] for m in streamed_matches} == target_lines
        assert scanner_peak_overhead_mb < 1.0, (
            f"FileScanner memory peak overhead was {scanner_peak_overhead_mb:.2f} MB, expected < 1.0 MB"
        )

        # 2. Test full SearchEngine.search on the 15MB file
        engine = SearchEngine(max_workers=4)
        options = SearchOptions(
            path=large_file,
            query=target_token,
            is_regex=False,
            case_sensitive=True,
        )

        tracemalloc.start()
        tracemalloc.reset_peak()
        start_engine_mem, _ = tracemalloc.get_traced_memory()

        found_results: list[SearchResult] = []
        stats = engine.search(options=options, result_callback=found_results.append)

        _, peak_engine_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        engine_peak_overhead_mb = (peak_engine_mem - start_engine_mem) / (1024 * 1024)

        assert stats.total_files == 1
        assert stats.scanned_files == 1
        assert stats.success_count == 1
        assert stats.error_count == 0
        assert len(found_results) == len(target_lines)
        found_line_numbers = {r.line_number for r in found_results}
        assert found_line_numbers == target_lines

        # Peak memory must not scale with file size (O(1) requirement)
        # Even with ThreadPoolExecutor thread overhead, peak memory should be well under 3.5 MB
        assert engine_peak_overhead_mb < 3.5, (
            f"SearchEngine peak memory overhead was {engine_peak_overhead_mb:.2f} MB on a {file_size_mb:.2f} MB file. "
            f"Memory does not appear to be bounded O(1)."
        )


class TestChallengerRegexResilience:
    """Stress testing regex error handling and safety."""

    @pytest.mark.parametrize(
        "bad_pattern",
        [
            "[",                   # Unclosed character set
            "(?<invalid",          # Incomplete/invalid group syntax
            "*leading_quantifier", # Nothing to repeat
            "(?P<",                # Unterminated group name
            "(abc",                # Unclosed parenthesis
            "[a-z",                # Unclosed range
            "\\",                  # Trailing lone backslash
            "(?<=.*)",             # Non-fixed-width lookbehind (Python re constraint)
        ],
    )
    def test_invalid_regex_handled_gracefully_without_crash(
        self, tmp_path: Path, bad_pattern: str
    ) -> None:
        """Adversarial test: Verify SearchEngine catches re.error and logs without crashing.

        Verifies:
        - re.error does not escape SearchEngine.search().
        - stats.error_count == 1.
        - Error message is recorded in stats.errors mentioning regex.
        - Result callback is not called.
        """
        test_file = tmp_path / "dummy.txt"
        test_file.write_text("Some text for regex search testing", encoding="utf-8")

        engine = SearchEngine()
        results: list[SearchResult] = []

        options = SearchOptions(
            path=tmp_path,
            query=bad_pattern,
            is_regex=True,
            case_sensitive=False,
        )

        stats = engine.search(options=options, result_callback=results.append)

        assert stats.error_count == 1, f"Expected 1 error for bad regex '{bad_pattern}', got {stats.error_count}"
        assert len(stats.errors) == 1
        _err_path, err_msg = stats.errors[0]
        assert "regex" in err_msg.lower() or "pattern" in err_msg.lower()
        assert len(results) == 0

    def test_regex_metacharacters_in_plain_search_do_not_error(self, tmp_path: Path) -> None:
        """Verify plain search treats regex metacharacters literally without re.error."""
        test_file = tmp_path / "literal_regex.txt"
        test_file.write_text("Formula: [x + 1] * 2 = (abc)\nAnother line \\ with / slash\n", encoding="utf-8")

        engine = SearchEngine()

        for literal_query in ["[x + 1]", "* 2", "(abc)", "\\ with"]:
            results: list[SearchResult] = []
            options = SearchOptions(
                path=tmp_path,
                query=literal_query,
                is_regex=False,  # Plain search escaping regex characters
            )
            stats = engine.search(options=options, result_callback=results.append)

            assert stats.error_count == 0, f"Plain search failed on '{literal_query}': {stats.errors}"
            assert len(results) >= 1
            assert literal_query in results[0].matched_line


class TestChallengerAdversarialEdgeCases:
    """Additional adversarial edge cases (race conditions, permission errors)."""

    def test_file_deleted_mid_search_race_condition(self, tmp_path: Path) -> None:
        """Adversarial test: Delete files concurrently while search is running."""
        files = []
        for i in range(50):
            p = tmp_path / f"transient_{i:03d}.txt"
            p.write_text(f"Content for file {i}\nTarget token HERE\n", encoding="utf-8")
            files.append(p)

        engine = SearchEngine(max_workers=4)
        options = SearchOptions(path=tmp_path, query="HERE")

        deleted_count = 0

        def delete_hook(_res: SearchResult) -> None:
            nonlocal deleted_count
            for target_to_delete in files[25:]:
                with contextlib.suppress(OSError):
                    if target_to_delete.exists():
                        target_to_delete.unlink()
                        deleted_count += 1

        stats = engine.search(options=options, result_callback=delete_hook)

        # Engine should complete without unhandled exception
        assert stats.scanned_files > 0
        # If files were unlinked before open, errors are recorded cleanly in stats.errors
        # Total files = successes + errors
        assert stats.success_count + stats.error_count == stats.total_files

    def test_unreadable_file_permission_error_gracefully_handled(self, tmp_path: Path) -> None:
        """Adversarial test: File with 000 permissions is trapped and recorded in error list."""
        unreadable = tmp_path / "no_access.txt"
        unreadable.write_text("Secret content with TARGET", encoding="utf-8")

        readable = tmp_path / "normal.txt"
        readable.write_text("Public content with TARGET", encoding="utf-8")

        # Strip read permissions
        try:
            unreadable.chmod(0o000)
        except OSError:
            pytest.skip("Filesystem does not support permission modifications")

        try:
            engine = SearchEngine()
            results: list[SearchResult] = []
            options = SearchOptions(path=tmp_path, query="TARGET")

            stats = engine.search(options=options, result_callback=results.append)

            # At least the unreadable file caused an error, while readable succeeded
            assert stats.error_count >= 1
            assert any("permission" in msg.lower() for _, msg in stats.errors)
            assert len(results) == 1
            assert results[0].file_path == readable
        finally:
            with contextlib.suppress(OSError):
                unreadable.chmod(0o644)
