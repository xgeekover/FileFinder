"""Empirical challenger test suite for FileFinder Milestone 2 (Core Search Engine).

Adversarially probes:
1. Symlink Safety:
   - Direct circular directory symlinks (dir/loop -> dir)
   - Mutual circular directory symlinks (dirA/to_b -> dirB, dirB/to_a -> dirA)
   - Deep nested circular directory symlinks (root/a/b/c/back -> root)
   - Symlink chains (file link chains, dir link chains)
   - Broken symlinks (file, dir, chain, circular broken links)
   - Base path itself being a symlink / circular symlink
2. Race Conditions:
   - Concurrent file deletion during multi-threaded SearchEngine search
   - Concurrent directory deletion (rmtree) during FileScanner traversal
   - Zero unhandled FileNotFoundError crashes
3. Korean CP949 vs Big5 Disambiguation:
   - Short Korean strings ('한글', '공지사항', '테스트') where charset-normalizer predicts Big5
   - CP949 tie-breaker rule verification
   - Integration with SearchEngine search
4. Binary Exclusion Heuristic:
   - Embedded null byte (\\x00) at offset 0, offset 1, offset 100, offset 4096, offset 8191
   - Boundary tests at offset 8192 and beyond
   - UTF-16 / UTF-32 BOM preservation despite null bytes
   - End-to-end SearchEngine exclusion verification
"""

from __future__ import annotations

import contextlib
import os
import random
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import charset_normalizer
import pytest

from app.core.encoding_detector import EncodingDetector
from app.core.file_filter import FileFilter
from app.core.file_scanner import FileScanner
from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine

# ============================================================================
# Dimension 1: Symlink Safety
# ============================================================================


class TestSymlinkSafety:
    """Adversarial tests for symlink safety and cycle prevention."""

    def test_direct_circular_directory_symlink_does_not_loop(
        self, tmp_path: Path
    ) -> None:
        """Self-referential directory symlink (dir/loop -> dir) must never cause infinite loops."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "real.txt").write_text("search_target_text")

        # Create self loop: sub/loop -> sub
        os.symlink(sub, sub / "loop")

        # Test follow_symlinks=False (default)
        scanner_default = FileScanner(follow_symlinks=False)
        files_default = list(scanner_default.scan_files(tmp_path))
        assert len(files_default) == 1
        assert files_default[0].name == "real.txt"

        # Test follow_symlinks=True (directory symlinks must NEVER be followed)
        scanner_follow = FileScanner(follow_symlinks=True)
        files_follow = list(scanner_follow.scan_files(tmp_path))
        assert len(files_follow) == 1
        assert files_follow[0].name == "real.txt"

        # Test SearchEngine end-to-end
        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="search_target_text"),
            result_callback=results.append,
        )
        assert len(results) == 1
        assert results[0].file_name == "real.txt"
        assert stats.error_count == 0

    def test_mutual_circular_directory_symlinks(self, tmp_path: Path) -> None:
        """Mutual circular directory symlinks (dirA/link_b -> dirB, dirB/link_a -> dirA)."""
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "file_a.txt").write_text("find_me_in_a")
        (dir_b / "file_b.txt").write_text("find_me_in_b")

        os.symlink(dir_b, dir_a / "link_to_b")
        os.symlink(dir_a, dir_b / "link_to_a")

        scanner = FileScanner()
        found = {p.name for p in scanner.scan_files(tmp_path)}
        assert found == {"file_a.txt", "file_b.txt"}

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="find_me"),
            result_callback=results.append,
        )
        assert len(results) == 2
        assert {r.file_name for r in results} == {"file_a.txt", "file_b.txt"}
        assert stats.error_count == 0

    def test_deep_nested_circular_directory_symlink(self, tmp_path: Path) -> None:
        """Deep hierarchy where a leaf points back to the root and an ancestor."""
        level1 = tmp_path / "l1"
        level2 = level1 / "l2"
        level3 = level2 / "l3"
        level3.mkdir(parents=True)

        (level3 / "deep.txt").write_text("deep_content_needle")

        os.symlink(tmp_path, level3 / "back_to_root")
        os.symlink(level1, level3 / "back_to_l1")

        scanner = FileScanner()
        scanned = list(scanner.scan_files(tmp_path))
        assert len(scanned) == 1
        assert scanned[0].name == "deep.txt"

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="deep_content_needle"),
            result_callback=results.append,
        )
        assert len(results) == 1
        assert stats.error_count == 0

    def test_nested_symlink_chains(self, tmp_path: Path) -> None:
        """Chains of symlinks (link1 -> link2 -> real target)."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("chain_target_content")

        link1 = tmp_path / "link1.txt"
        link2 = tmp_path / "link2.txt"
        os.symlink(real_file, link1)
        os.symlink(link1, link2)

        # Directory link chain
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "sub_file.txt").write_text("chain_target_content")
        dlink1 = tmp_path / "dlink1"
        dlink2 = tmp_path / "dlink2"
        os.symlink(sub, dlink1)
        os.symlink(dlink1, dlink2)

        # With follow_symlinks=False (default): symlinks ignored
        scanner_false = FileScanner(follow_symlinks=False)
        names_false = {p.name for p in scanner_false.scan_files(tmp_path)}
        assert names_false == {"real.txt", "sub_file.txt"}

        # With follow_symlinks=True: file symlinks followed, dir symlinks ignored
        scanner_true = FileScanner(follow_symlinks=True)
        names_true = {p.name for p in scanner_true.scan_files(tmp_path)}
        assert names_true == {"real.txt", "sub_file.txt", "link1.txt", "link2.txt"}

    def test_broken_symlinks_do_not_crash(self, tmp_path: Path) -> None:
        """Broken file symlinks, broken dir symlinks, and broken chains must be ignored cleanly."""
        missing = tmp_path / "non_existent_target"

        broken_file = tmp_path / "broken_file.txt"
        broken_dir = tmp_path / "broken_dir"
        broken_chain1 = tmp_path / "broken_chain1"
        broken_chain2 = tmp_path / "broken_chain2"

        os.symlink(missing, broken_file)
        os.symlink(missing, broken_dir)
        os.symlink(missing, broken_chain1)
        os.symlink(broken_chain1, broken_chain2)

        # Circular broken symlinks
        circ1 = tmp_path / "circ1"
        circ2 = tmp_path / "circ2"
        os.symlink(circ2, circ1)
        os.symlink(circ1, circ2)

        (tmp_path / "valid.txt").write_text("valid_needle")

        scanner = FileScanner(follow_symlinks=False)
        found = list(scanner.scan_files(tmp_path))
        assert len(found) == 1
        assert found[0].name == "valid.txt"

        scanner_follow = FileScanner(follow_symlinks=True)
        found_follow = list(scanner_follow.scan_files(tmp_path))
        assert len(found_follow) == 1
        assert found_follow[0].name == "valid.txt"

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query="valid_needle"),
            result_callback=results.append,
        )
        assert len(results) == 1
        assert stats.error_count == 0

    def test_base_path_itself_is_symlink_or_broken(self, tmp_path: Path) -> None:
        """Check behavior when base_path passed to SearchEngine or FileScanner is a symlink."""
        target_dir = tmp_path / "real_dir"
        target_dir.mkdir()
        (target_dir / "item.txt").write_text("item_content")

        dir_link = tmp_path / "dir_link"
        os.symlink(target_dir, dir_link)

        # SearchEngine resolves base_path
        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=dir_link, query="item_content"),
            result_callback=results.append,
        )
        assert len(results) == 1
        assert stats.error_count == 0

        # Broken base_path
        broken_base = tmp_path / "broken_base"
        os.symlink(tmp_path / "missing", broken_base)
        stats_broken = engine.search(SearchOptions(path=broken_base, query="test"))
        assert stats_broken.error_count == 1
        assert "does not exist" in stats_broken.errors[0][1]


# ============================================================================
# Dimension 2: Race Conditions & Concurrent Deletion
# ============================================================================


class TestRaceConditions:
    """Stress tests verifying resilience against mid-search file deletions."""

    def test_concurrent_file_deletion_during_active_search(
        self, tmp_path: Path
    ) -> None:
        """Create 400 files and concurrently delete them while SearchEngine is searching."""
        all_files: list[Path] = []
        for d_idx in range(20):
            d = tmp_path / f"dir_{d_idx}"
            d.mkdir()
            for f_idx in range(20):
                f = d / f"file_{f_idx}.txt"
                f.write_text(f"Line 1: match_needle_{d_idx}_{f_idx}\nLine 2: data\n")
                all_files.append(f)

        stop_deleter = threading.Event()

        def deleter_worker() -> None:
            time.sleep(0.002)
            shuffled = list(all_files)
            random.shuffle(shuffled)
            for f in shuffled:
                if stop_deleter.is_set():
                    break
                try:
                    if f.exists():
                        f.unlink()
                except Exception:
                    pass
                time.sleep(0.001)

        deleter_thread = threading.Thread(target=deleter_worker)
        deleter_thread.start()

        engine = SearchEngine(max_workers=8)
        results: list[SearchResult] = []
        try:
            stats = engine.search(
                SearchOptions(path=tmp_path, query="match_needle"),
                result_callback=results.append,
            )
        finally:
            stop_deleter.set()
            deleter_thread.join()

        # Invariants that must hold under concurrent deletion:
        # 1. Total discovered files must be between 1 and 400 (some deleted before traversal)
        assert 0 < stats.total_files <= 400
        # 2. Every discovered file must be accounted for in scanned_files
        assert stats.scanned_files == stats.total_files
        # 3. All scanned files must partition exactly into successes and errors
        assert stats.success_count + stats.error_count == stats.total_files
        # 4. Results matched correspond to successes
        assert len(results) == stats.success_count
        # 5. At least some files were deleted mid-search, triggering trapped errors
        assert stats.error_count > 0

        # Errors should be FileNotFoundError / [Errno 2]
        for _err_path, err_msg in stats.errors:
            assert any(
                term in err_msg.lower()
                for term in ["no such file", "filenotfounderror", "errno 2"]
            )

    def test_concurrent_rmtree_during_filescanner_traversal(
        self, tmp_path: Path
    ) -> None:
        """Concurrently delete whole subdirectories while FileScanner.scan_files is iterating."""
        dirs: list[Path] = []
        for d_idx in range(40):
            d = tmp_path / f"batch_{d_idx}"
            d.mkdir()
            dirs.append(d)
            for f_idx in range(15):
                (d / f"doc_{f_idx}.txt").write_text("traversal_data")

        stop_event = threading.Event()

        def rmtree_worker() -> None:
            time.sleep(0.003)
            for d in dirs:
                if stop_event.is_set():
                    break
                with contextlib.suppress(Exception):
                    shutil.rmtree(d)
                time.sleep(0.002)

        t = threading.Thread(target=rmtree_worker)
        t.start()

        scanner = FileScanner()
        errors: list[tuple[Path, Exception]] = []

        def error_cb(path: Path, exc: Exception) -> None:
            errors.append((path, exc))

        try:
            found_files = list(scanner.scan_files(tmp_path, error_callback=error_cb))
        finally:
            stop_event.set()
            t.join()

        # The generator must complete cleanly without an unhandled exception
        assert isinstance(found_files, list)
        for _err_path, exc in errors:
            assert isinstance(exc, (FileNotFoundError, OSError))

    def test_file_deleted_between_binary_check_and_stream(self, tmp_path: Path) -> None:
        """Specifically simulate file disappearing between discovery and stream_lines."""
        f = tmp_path / "vanish.txt"
        f.write_text("hello vanish needle")

        # Custom mock scanner that deletes file on stream_lines entry
        original_scanner = FileScanner()

        class EvaporatingScanner(FileScanner):
            def stream_lines(
                self,
                path: Path,
                encoding: str = "utf-8",
                errors: str = "replace",
                cancel_event: threading.Event | None = None,
                error_callback: Any = None,
                raise_on_error: bool = False,
            ) -> Iterator[tuple[int, str]]:
                if path.exists():
                    path.unlink()
                return original_scanner.stream_lines(
                    path,
                    encoding=encoding,
                    errors=errors,
                    cancel_event=cancel_event,
                    error_callback=error_callback,
                    raise_on_error=raise_on_error,
                )

        engine_evaporating = SearchEngine(file_scanner=EvaporatingScanner())
        results: list[SearchResult] = []
        stats = engine_evaporating.search(
            SearchOptions(path=tmp_path, query="vanish"),
            result_callback=results.append,
        )

        assert len(results) == 0
        assert stats.error_count == 1
        assert "No such file" in stats.errors[0][1]


# ============================================================================
# Dimension 3: Korean CP949 vs Big5 Tie-Breaker on Short Strings
# ============================================================================


class TestKoreanCp949Big5Disambiguation:
    """Probes Korean CP949 detection and Big5 tie-breaker rules on short strings."""

    @pytest.mark.parametrize("word", ["한글", "공지사항", "테스트"])
    def test_charset_normalizer_raw_misclassifies_short_cp949_as_big5(
        self, word: str
    ) -> None:
        """Confirm empirical baseline: charset-normalizer alone predicts Big5 on these words."""
        raw_bytes = word.encode("cp949")
        matches = charset_normalizer.from_bytes(raw_bytes)
        best = matches.best()
        assert best is not None
        # This confirms why our tiebreaker rule is essential
        assert best.encoding.lower() == "big5"

    @pytest.mark.parametrize("word", ["한글", "공지사항", "테스트"])
    def test_encoding_detector_tiebreaker_corrects_to_cp949(self, word: str) -> None:
        """EncodingDetector tiebreaker rule 3.1 must override Big5 to CP949."""
        raw_bytes = word.encode("cp949")
        detector = EncodingDetector()
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected == "cp949"

    @pytest.mark.parametrize(
        "word",
        [
            "안녕하세요",
            "파일",
            "검색",
            "결과",
            "오류",
            "안녕",
            "가",
            "값",
            "한국어",
            "문서",
        ],
    )
    def test_encoding_detector_other_korean_words(self, word: str) -> None:
        """Additional common Korean words in CP949 must all resolve to CP949."""
        raw_bytes = word.encode("cp949")
        detector = EncodingDetector()
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected == "cp949"

    def test_cp949_search_engine_integration(self, tmp_path: Path) -> None:
        """Verify SearchEngine correctly identifies and matches CP949 files with short strings."""
        test_cases = [
            ("hangul.txt", "한글", "한글 파일 내용입니다."),
            ("notice.txt", "공지사항", "시스템 점검 공지사항 안내"),
            ("test.txt", "테스트", "기능 단위 테스트 완료"),
        ]

        for fname, _, content in test_cases:
            f = tmp_path / fname
            f.write_bytes(content.encode("cp949"))

        engine = SearchEngine()

        for fname, query, _ in test_cases:
            results: list[SearchResult] = []
            stats = engine.search(
                SearchOptions(path=tmp_path, query=query),
                result_callback=results.append,
            )
            matched_files = {r.file_name for r in results}
            assert fname in matched_files
            assert all(r.encoding == "cp949" for r in results if r.file_name == fname)
            assert stats.error_count == 0


# ============================================================================
# Dimension 4: Binary Exclusion on Embedded Null Bytes in First 8KB
# ============================================================================


class TestBinaryExclusionHeuristic:
    """Probes binary file exclusion via embedded null bytes in the first 8KB."""

    @pytest.mark.parametrize("offset", [0, 1, 10, 100, 1024, 4096, 8190, 8191])
    def test_null_byte_within_first_8kb_marked_as_binary(
        self, tmp_path: Path, offset: int
    ) -> None:
        """Any null byte placed at index 0 <= offset < 8192 must trigger is_binary_content=True."""
        content = bytearray(b"A" * 8192)
        content[offset] = 0  # embedded \x00

        f = tmp_path / f"null_{offset}.txt"
        f.write_bytes(bytes(content))

        ff = FileFilter()
        assert ff.is_binary_content(f) is True
        assert ff.is_binary(f) is True
        assert ff.should_skip(f) is True

    @pytest.mark.parametrize("offset", [8192, 8193, 10000])
    def test_null_byte_at_or_beyond_8192_not_marked_binary(
        self, tmp_path: Path, offset: int
    ) -> None:
        """Null byte placed strictly at or after byte 8192 is beyond 8KB sample window."""
        content = bytearray(b"A" * (offset + 100))
        content[offset] = 0

        f = tmp_path / f"null_after_{offset}.txt"
        f.write_bytes(bytes(content))

        ff = FileFilter()
        # First 8192 bytes contain only 'A', no null byte
        assert ff.is_binary_content(f, sample_size=8192) is False

    def test_empty_and_pure_text_files_not_binary(self, tmp_path: Path) -> None:
        """Empty files and pure ASCII/UTF-8 files must never be marked binary."""
        f_empty = tmp_path / "empty.txt"
        f_empty.write_bytes(b"")

        f_8kb_clean = tmp_path / "clean_8kb.txt"
        f_8kb_clean.write_bytes(b"Hello World\n" * 700)  # ~8.4KB

        ff = FileFilter()
        assert ff.is_binary_content(f_empty) is False
        assert ff.is_binary_content(f_8kb_clean) is False

    def test_utf16_utf32_bom_preservation(self, tmp_path: Path) -> None:
        """UTF-16 and UTF-32 files with valid BOMs contain null bytes but must NOT be skipped."""
        ff = FileFilter()

        # UTF-16 LE
        f_u16le = tmp_path / "u16le.txt"
        f_u16le.write_bytes(b"\xff\xfe" + "Hello UTF-16 LE".encode("utf-16-le"))
        assert ff.is_binary_content(f_u16le) is False

        # UTF-16 BE
        f_u16be = tmp_path / "u16be.txt"
        f_u16be.write_bytes(b"\xfe\xff" + "Hello UTF-16 BE".encode("utf-16-be"))
        assert ff.is_binary_content(f_u16be) is False

        # UTF-32 LE
        f_u32le = tmp_path / "u32le.txt"
        f_u32le.write_bytes(b"\xff\xfe\x00\x00" + "Hello UTF-32 LE".encode("utf-32-le"))
        assert ff.is_binary_content(f_u32le) is False

        # UTF-32 BE
        f_u32be = tmp_path / "u32be.txt"
        f_u32be.write_bytes(b"\x00\x00\xfe\xff" + "Hello UTF-32 BE".encode("utf-32-be"))
        assert ff.is_binary_content(f_u32be) is False

    def test_search_engine_binary_exclusion_end_to_end(self, tmp_path: Path) -> None:
        """SearchEngine must exclude files with null bytes in first 8KB from match results."""
        needle = "UNIQUE_TARGET_STRING_XYZ"

        # 1. Null at pos 0 with needle
        f_null0 = tmp_path / "null_at_0.txt"
        f_null0.write_bytes(b"\x00" + f"Text with {needle}\n".encode())

        # 2. Null at pos 500 with needle
        f_null500 = tmp_path / "null_at_500.txt"
        f_null500.write_bytes(b"A" * 500 + b"\x00" + f"{needle}\n".encode())

        # 3. Null at pos 8191 with needle
        f_null8191 = tmp_path / "null_at_8191.txt"
        f_null8191.write_bytes(b"B" * 8191 + b"\x00" + f"{needle}\n".encode())

        # 4. Clean text with needle
        f_clean = tmp_path / "clean_text.txt"
        f_clean.write_text(f"This is clean text containing {needle}\n")

        # 5. UTF-16 LE text with needle (has BOM)
        f_utf16 = tmp_path / "encoded_u16.txt"
        f_utf16.write_bytes(f"UTF-16 text with {needle}\n".encode("utf-16"))

        engine = SearchEngine()
        results: list[SearchResult] = []
        stats = engine.search(
            SearchOptions(path=tmp_path, query=needle),
            result_callback=results.append,
        )

        matched_filenames = {r.file_name for r in results}

        # Clean text and UTF-16 must match
        assert "clean_text.txt" in matched_filenames
        assert "encoded_u16.txt" in matched_filenames

        # Files with null bytes in first 8KB must NOT match
        assert "null_at_0.txt" not in matched_filenames
        assert "null_at_500.txt" not in matched_filenames
        assert "null_at_8191.txt" not in matched_filenames

        # All 5 files were discovered and safely processed
        assert stats.total_files == 5
        assert stats.scanned_files == 5
        assert stats.error_count == 0
