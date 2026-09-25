"""Adversarial stress and edge-case verification tests for Milestone 1.

Empirical validation by challenger_m1 targeting:
1. Deeply nested directory trees (25+ levels) with target files at leaf and intermediate depths.
2. Large files with match on the exact final line, validating bounded memory consumption (O(1) streaming).
3. Concurrency cancellation races:
   - Pre-emptive cancellation (cancel before start).
   - Mid-flight cancellation triggered during high-frequency parallel processing.
   - Late cancellation right as search completes.
   - Result preservation under all cancellation timing windows.
4. Mixed corrupt byte sequences across UTF-8, CP949, and Latin-1:
   - Truncated multi-byte UTF-8 sequences.
   - Orphaned CP949 lead bytes.
   - Fuzzed binary bytes surrounding valid search tokens.
5. Circular symlinks and unreadable permission-denied directories/files.
6. Extreme boundary conditions: files without newlines, huge line length, multiple matches per line.
"""

from __future__ import annotations

import contextlib
import os
import random
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import pytest

from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine


class TestDeepNesting:
    """Stress tests for deep directory hierarchies."""

    def test_deep_nesting_25_levels_with_leaf_and_intermediate_matches(
        self, tmp_path: Path
    ) -> None:
        """Verify traversal through 25 levels of directory hierarchy without recursion overflow."""
        current = tmp_path
        levels = 25
        created_files: list[Path] = []

        for level in range(1, levels + 1):
            current = current / f"level_{level:02d}"
            current.mkdir()
            # Drop a file every 5 levels
            if level % 5 == 0:
                fpath = current / f"checkpoint_lvl_{level}.txt"
                fpath.write_text(f"Token_At_Level_{level}\n", encoding="utf-8")
                created_files.append(fpath)

        # Leaf file at level 25
        leaf_file = current / "deepest_leaf.txt"
        leaf_file.write_text("Deepest_Secret_Token_Found_Here\n", encoding="utf-8")
        created_files.append(leaf_file)

        # 1. Search for leaf match
        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="Deepest_Secret_Token", recursive=True),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert len(results) == 1
        assert results[0].file_name == "deepest_leaf.txt"
        assert results[0].line_number == 1
        assert "Deepest_Secret_Token_Found_Here" in results[0].matched_line

        # 2. Search for intermediate tokens
        intermediate_results: list[SearchResult] = []
        stats_inter = engine.search(
            SearchOptions(path=tmp_path, query="Token_At_Level_", recursive=True),
            result_callback=intermediate_results.append,
        )

        assert not stats_inter.cancelled
        assert len(intermediate_results) == 5  # Levels 5, 10, 15, 20, 25 (checkpoint files)
        assert stats_inter.total_files >= 6

    def test_non_recursive_on_deep_structure_ignores_nested_files(
        self, tmp_path: Path
    ) -> None:
        """Verify recursive=False does not traverse into deep subdirectories."""
        (tmp_path / "top_level.txt").write_text("target_token here\n", encoding="utf-8")
        nested_dir = tmp_path / "sub1" / "sub2" / "sub3"
        nested_dir.mkdir(parents=True)
        (nested_dir / "nested.txt").write_text("target_token nested\n", encoding="utf-8")

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="target_token", recursive=False),
            result_callback=results.append,
        )

        assert len(results) == 1
        assert results[0].file_name == "top_level.txt"
        assert stats.total_files == 1


class TestLargeFileMemoryBound:
    """Verify O(1) memory consumption and match discovery on large files."""

    def test_large_file_match_on_exact_final_line_bounded_memory(
        self, tmp_path: Path
    ) -> None:
        """Stream a 100,000-line file (~10MB) where target token only appears on line 100,000."""
        large_file = tmp_path / "large_dataset.txt"
        total_lines = 100_000
        target_token = "NEEDLE_AT_THE_VERY_END"

        # Generate file in chunks to keep test setup fast and low memory
        with open(large_file, "w", encoding="utf-8") as f:
            chunk = "Ordinary filler log line with numbers 123456789 and letters abcdef\n" * 1000
            for _ in range(total_lines // 1000 - 1):
                f.write(chunk)
            # Write 999 more filler lines
            for i in range(999):
                f.write(f"Filler line near end {i}\n")
            # Exact 100,000th line is the needle
            f.write(f"Final summary: {target_token} [SUCCESS]\n")

        file_size_bytes = large_file.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)
        assert file_size_mb >= 5.0  # At least 5MB-10MB

        tracemalloc.start()
        engine = SearchEngine(max_workers=2)
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query=target_token),
            result_callback=results.append,
        )
        _current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Check peak memory usage during search (bounded streaming, well below 5MB)
        assert peak_mem < file_size_bytes // 2

        assert not stats.cancelled
        assert len(results) == 1
        assert results[0].line_number == total_lines
        assert target_token in results[0].matched_line
        assert results[0].file_name == "large_dataset.txt"


class TestCancellationStress:
    """Stress test cancellation under various timing windows."""

    def test_preemptive_cancellation_before_start(self, tmp_path: Path) -> None:
        """Cancel event already set when search is initiated."""
        for i in range(20):
            (tmp_path / f"file_{i}.txt").write_text("target_token\n", encoding="utf-8")

        cancel_event = threading.Event()
        cancel_event.set()

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="target_token"),
            result_callback=results.append,
            cancel_event=cancel_event,
        )

        assert stats.cancelled is True
        assert len(results) == 0
        assert stats.scanned_files == 0

    def test_mid_flight_cancellation_preserves_results(self, tmp_path: Path) -> None:
        """Cancel after discovering N results and verify existing results remain intact."""
        total_files = 100
        for i in range(total_files):
            (tmp_path / f"doc_{i:03d}.txt").write_text(
                f"Line 1: filler\nLine 2: target_token match #{i}\n", encoding="utf-8"
            )

        cancel_event = threading.Event()
        results: list[SearchResult] = []
        lock = threading.Lock()

        def on_result(result: SearchResult) -> None:
            with lock:
                results.append(result)
                if len(results) >= 15:
                    cancel_event.set()

        engine = SearchEngine(max_workers=4)
        stats = engine.search(
            SearchOptions(path=tmp_path, query="target_token"),
            result_callback=on_result,
            cancel_event=cancel_event,
        )

        assert stats.cancelled is True
        # Must have preserved at least the 15 results that triggered cancellation
        assert len(results) >= 15
        # Total scanned files should be less than or equal to total files
        assert stats.scanned_files <= total_files
        for r in results:
            assert "target_token" in r.matched_line

    def test_high_frequency_cancellation_jitter_stress(self, tmp_path: Path) -> None:
        """Rapidly trigger random cancellation timings across multiple searches."""
        for i in range(40):
            (tmp_path / f"jitter_{i}.txt").write_text("token " * 200 + "\n", encoding="utf-8")

        engine = SearchEngine(max_workers=4)
        opts = SearchOptions(path=tmp_path, query="token")

        for trial in range(5):
            cancel_event = threading.Event()
            delay = (trial + 1) * 0.002  # 2ms, 4ms, 6ms, 8ms, 10ms

            timer = threading.Timer(delay, cancel_event.set)
            timer.start()

            results: list[SearchResult] = []
            stats = engine.search(
                opts,
                result_callback=results.append,
                cancel_event=cancel_event,
            )
            timer.cancel()

            # The engine must return valid statistics without deadlocking or crashing
            assert stats.scanned_files >= 0
            assert stats.error_count == 0
            if stats.cancelled:
                assert cancel_event.is_set()


class TestCorruptDataAndEncodingFuzz:
    """Stress tests with corrupt, truncated, and mixed byte data."""

    def test_corrupt_utf8_continuation_bytes(self, tmp_path: Path) -> None:
        """File with invalid UTF-8 byte sequences mixed with valid search target."""
        # 0xC3 followed by 0x28 is invalid UTF-8; 0xFF is invalid UTF-8
        bad_bytes = (
            b"Line 1: Valid text start\n"
            b"Line 2: \xc3\x28 bad utf8 sequence \xff\xfe\n"
            b"Line 3: Target_Token_Survives here\n"
            b"Line 4: \xe2\x28\xa1 another truncated multibyte\n"
        )
        (tmp_path / "corrupt_utf8.txt").write_bytes(bad_bytes)

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="Target_Token_Survives"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert stats.total_files == 1
        # The engine must either match Target_Token_Survives (via replace or latin-1) or skip cleanly
        # Because detector falls back to latin-1 or scanner uses errors="replace", line 3 text is preserved!
        assert len(results) == 1
        assert "Target_Token_Survives" in results[0].matched_line
        assert results[0].line_number == 3

    def test_orphan_cp949_lead_bytes(self, tmp_path: Path) -> None:
        """File with orphan CP949 lead byte at line boundaries."""
        # 0xB0 is a CP949 2-byte lead byte. Followed by newline 0x0A, it is an orphan lead byte.
        # When CP949 decoding fails, engine falls back to Latin-1.
        # ASCII tokens embedded in the file must survive Latin-1 decoding.
        cp949_bad = (
            "첫 번째 정상 라인\n".encode("cp949")
            + b"\xb0\n"
            + "두 번째 라인: TOKEN_ASCII_SURVIVES\n".encode("cp949")
        )
        (tmp_path / "corrupt_cp949.txt").write_bytes(cp949_bad)

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="TOKEN_ASCII_SURVIVES"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert stats.scanned_files == 1
        # Engine falls back to Latin-1 safely without crash and discovers ASCII tokens
        assert len(results) == 1
        assert "TOKEN_ASCII_SURVIVES" in results[0].matched_line
        assert results[0].line_number == 3

    def test_binary_null_bytes_at_critical_offsets(self, tmp_path: Path) -> None:
        """Verify binary exclusion heuristic when null bytes appear at various offsets."""
        # Null byte at offset 0
        (tmp_path / "null_at_0.txt").write_bytes(b"\x00hello world target_token")
        # Null byte at offset 8191 (last byte of 8KB inspection buffer)
        (tmp_path / "null_at_8191.txt").write_bytes(b"A" * 8191 + b"\x00target_token")
        # Null byte at offset 8192 (just beyond 8KB inspection buffer)
        # Note: By default, 8192 sample size inspects [0:8192]. If null byte is at offset 8192,
        # it is not in the first 8192 bytes, so it might be treated as text.
        (tmp_path / "null_at_8192.txt").write_bytes(b"A" * 8192 + b"\x00target_token")
        # Clean text
        (tmp_path / "clean.txt").write_text("A" * 100 + " target_token", encoding="utf-8")

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="target_token"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        # null_at_0 and null_at_8191 MUST be excluded as binary
        result_filenames = {r.file_name for r in results}
        assert "null_at_0.txt" not in result_filenames
        assert "null_at_8191.txt" not in result_filenames
        assert "clean.txt" in result_filenames


class TestSymlinksAndPermissionResilience:
    """Stress test circular symlinks and unreadable permission errors."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink and chmod semantics")
    def test_complex_circular_symlink_graph(self, tmp_path: Path) -> None:
        """Circular symlinks: a -> b -> c -> a and nested self-loops."""
        dir_a = tmp_path / "dir_a"
        dir_b = dir_a / "dir_b"
        dir_c = dir_b / "dir_c"
        dir_c.mkdir(parents=True)

        (dir_a / "file_a.txt").write_text("token_in_a\n", encoding="utf-8")
        (dir_c / "file_c.txt").write_text("token_in_c\n", encoding="utf-8")

        # Symlink c -> a (circular loop)
        link_to_a = dir_c / "link_back_to_a"
        try:
            link_to_a.symlink_to(dir_a, target_is_directory=True)
        except OSError:
            pytest.skip("Symlink creation not permitted in this environment")

        # Self-referencing link in dir_b
        link_self = dir_b / "link_to_b"
        with contextlib.suppress(OSError):
            link_self.symlink_to(dir_b, target_is_directory=True)

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="token_in_"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        # Should find file_a.txt and file_c.txt exactly once without looping infinitely
        assert len(results) == 2
        file_names = [r.file_name for r in results]
        assert "file_a.txt" in file_names
        assert "file_c.txt" in file_names

    @pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX non-root chmod")
    def test_permission_denied_file_and_directory(self, tmp_path: Path) -> None:
        """Traverse when a subfolder or file has mode 000 (access denied)."""
        # Normal folder with readable file
        normal_dir = tmp_path / "normal"
        normal_dir.mkdir()
        (normal_dir / "accessible.txt").write_text("secret_search_token\n", encoding="utf-8")

        # Unreadable file
        locked_file = normal_dir / "locked.txt"
        locked_file.write_text("secret_search_token in locked\n", encoding="utf-8")
        locked_file.chmod(0o000)

        # Unreadable directory
        locked_dir = tmp_path / "locked_dir"
        locked_dir.mkdir()
        (locked_dir / "hidden.txt").write_text("secret_search_token inside locked dir\n", encoding="utf-8")
        locked_dir.chmod(0o000)

        try:
            engine = SearchEngine()
            results: list[SearchResult] = []
            stats = engine.search(
                SearchOptions(path=tmp_path, query="secret_search_token"),
                result_callback=results.append,
            )

            # Accessible file must be found
            assert len(results) == 1
            assert results[0].file_name == "accessible.txt"
            # Errors must be logged for locked items, but search must succeed overall
            assert stats.error_count >= 1
            error_paths = [str(err_path) for err_path, _ in stats.errors]
            assert any("locked" in p for p in error_paths)
        finally:
            # Restore permissions for cleanup
            locked_file.chmod(0o644)
            locked_dir.chmod(0o755)


class TestExtremeBoundaryConditions:
    """Extreme corner cases: no trailing newline, carriage returns, multiple regex matches."""

    def test_file_without_trailing_newline(self, tmp_path: Path) -> None:
        """Match on the last line of a file that has no final newline character."""
        (tmp_path / "no_newline.txt").write_bytes(b"Line 1\nLine 2 without newline: TARGET_HERE")

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="TARGET_HERE"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert len(results) == 1
        assert results[0].line_number == 2
        assert results[0].matched_line == "Line 2 without newline: TARGET_HERE"
        assert results[0].match_start == len("Line 2 without newline: ")
        assert results[0].match_end == len("Line 2 without newline: TARGET_HERE")

    def test_multiple_regex_matches_in_single_line(self, tmp_path: Path) -> None:
        """Single line with 10 occurrences of a pattern yields 10 separate SearchResult entries."""
        tokens = [f"token_{i}" for i in range(10)]
        line = " ".join(tokens) + "\n"
        (tmp_path / "dense.txt").write_text(line, encoding="utf-8")

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query=r"token_\d+", is_regex=True),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert len(results) == 10
        for i, res in enumerate(results):
            assert res.line_number == 1
            assert res.match_start == line.find(f"token_{i}")
            assert res.match_end == res.match_start + len(f"token_{i}")

    def test_search_direct_single_file_target(self, tmp_path: Path) -> None:
        """SearchOptions.path pointing directly to a single file rather than a directory."""
        single_file = tmp_path / "target.txt"
        single_file.write_text("alpha beta gamma\n", encoding="utf-8")

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=single_file, query="beta"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert stats.total_files == 1
        assert len(results) == 1
        assert results[0].file_name == "target.txt"
        assert results[0].matched_line == "alpha beta gamma"


class TestConcurrencyRacesAndReentrancy:
    """Stress testing active filesystem mutation races and multi-threaded search invocation."""

    def test_concurrent_file_deletion_race_condition(self, tmp_path: Path) -> None:
        """Files deleted by an external process while ThreadPoolExecutor is actively processing."""
        total_files = 150
        created_files: list[Path] = []
        for i in range(total_files):
            fpath = tmp_path / f"race_file_{i:03d}.txt"
            # Make half of them match
            content = f"Line 1: filler\nLine 2: target_token match #{i}\n" if i % 2 == 0 else "filler\n"
            fpath.write_text(content, encoding="utf-8")
            created_files.append(fpath)

        def chaos_deleter() -> None:
            time.sleep(0.005)
            # Delete 40 files at random
            sample_to_delete = random.sample(created_files, 40)
            for f in sample_to_delete:
                with contextlib.suppress(OSError):
                    f.unlink(missing_ok=True)
                time.sleep(0.0005)

        deleter_thread = threading.Thread(target=chaos_deleter)
        deleter_thread.start()

        engine = SearchEngine(max_workers=8)
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="target_token"),
            result_callback=results.append,
        )

        deleter_thread.join()

        # Must not crash; errors from deleted files must be caught and logged
        assert not stats.cancelled
        assert stats.scanned_files > 0
        assert stats.success_count + stats.error_count == stats.scanned_files
        for r in results:
            assert "target_token" in r.matched_line

    def test_reentrant_concurrent_searches_same_engine_instance(self, tmp_path: Path) -> None:
        """Invoke search() concurrently from 5 caller threads using the same SearchEngine instance."""
        # Setup 5 distinct subdirectories
        subdirs: list[Path] = []
        for i in range(5):
            sdir = tmp_path / f"subdir_{i}"
            sdir.mkdir()
            for j in range(20):
                (sdir / f"f_{j}.txt").write_text(f"thread_{i}_token in file {j}\n", encoding="utf-8")
            subdirs.append(sdir)

        engine = SearchEngine(max_workers=4)
        errors: list[Exception] = []
        results_per_thread: dict[int, list[SearchResult]] = {i: [] for i in range(5)}

        def runner(idx: int) -> None:
            try:
                stats = engine.search(
                    SearchOptions(path=subdirs[idx], query=f"thread_{idx}_token"),
                    result_callback=results_per_thread[idx].append,
                )
                assert stats.success_count == 20
                assert stats.error_count == 0
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=runner, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        for i in range(5):
            assert len(results_per_thread[i]) == 20


class TestEncodingBOMVariants:
    """Stress tests for multi-byte Unicode encodings with Byte Order Marks (BOM)."""

    def test_utf16_le_and_be_korean_search_with_bom(self, tmp_path: Path) -> None:
        """Search Hangul text in UTF-16 LE and UTF-16 BE encoded files with valid BOM."""
        text = "안녕하세요. 파일파인더 유니코드 테스트입니다.\n"
        (tmp_path / "korean_utf16_le.txt").write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
        (tmp_path / "korean_utf16_be.txt").write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="파일파인더"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert len(results) == 2
        encodings = {r.encoding.lower() for r in results}
        assert any("utf-16" in enc or "utf_16" in enc for enc in encodings)

    def test_utf32_le_and_be_search_with_bom(self, tmp_path: Path) -> None:
        """Search text in UTF-32 LE and UTF-32 BE encoded files with valid BOM."""
        text = "Header line\nTarget_Token in UTF32\nFooter line\n"
        (tmp_path / "file_utf32_le.txt").write_bytes(b"\xff\xfe\x00\x00" + text.encode("utf-32-le"))
        (tmp_path / "file_utf32_be.txt").write_bytes(b"\x00\x00\xfe\xff" + text.encode("utf-32-be"))

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="Target_Token"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        assert len(results) == 2
        for r in results:
            assert "Target_Token" in r.matched_line

    def test_utf16_without_bom_treated_as_binary_via_null_bytes(self, tmp_path: Path) -> None:
        """UTF-16 text without BOM contains null bytes and is safely excluded as binary."""
        text = "Target_Token without BOM\n"
        # utf-16-le without BOM has b'T\x00a\x00r\x00...'
        (tmp_path / "no_bom_utf16.txt").write_bytes(text.encode("utf-16-le"))

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="Target_Token"),
            result_callback=results.append,
        )

        assert not stats.cancelled
        # Excluded by null byte heuristic, no crash
        assert len(results) == 0
        assert stats.scanned_files == 1
        assert stats.success_count == 1
