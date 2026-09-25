"""
End-to-End (E2E) Test Suite for FileFinder.

Architecture & Specifications:
- Philosophy: Opaque-box, requirement-driven testing from user & public API perspectives.
- Specifications: ORIGINAL_REQUEST.md, PROJECT.md, docs/ARCHITECTURE.md.
- 4-Tier Test Case Design Hierarchy:
    * Tier 1: Core Feature Coverage (>=5 test cases per core feature category)
    * Tier 2: Boundary & Corner Cases (limits, empty, extreme lengths, symbols)
    * Tier 3: Cross-Feature Combinations (pairwise and multi-option interactions)
    * Tier 4: Real-World Application Scenarios (polyglot repos, mixed encodings, log audits)
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from app.core.models import (
        ScanStatistics,
        SearchOptions,
        SearchResult,
    )
    from app.core.search_engine import SearchEngine


# Progressive Testability: Attempt to import core modules.
# If not yet implemented, tests will be cleanly skipped with explicit reasons.
class _Fallback:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return None


def _fallback_func(*args: Any, **kwargs: Any) -> Any:
    return None


try:
    from app.core.models import (
        ScanStatistics,
        SearchOptions,
        SearchResult,
    )
    from app.core.search_engine import SearchEngine

    CORE_AVAILABLE = True
    _ = (ScanStatistics, SearchResult)  # Explicitly referenced for static analyzers
except (ImportError, ModuleNotFoundError):
    CORE_AVAILABLE = False
    if not TYPE_CHECKING:
        ScanStatistics = _Fallback
        SearchOptions = _Fallback
        SearchResult = _Fallback
        SearchEngine = _Fallback

try:
    from app.main import parse_args, run_cli  # type: ignore[import-untyped]

    CLI_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    CLI_AVAILABLE = False
    parse_args = _fallback_func
    run_cli = _fallback_func

requires_core = pytest.mark.skipif(
    not CORE_AVAILABLE,
    reason="app.core is not yet implemented (Milestone 2 in progress)",
)
requires_cli = pytest.mark.skipif(
    not CLI_AVAILABLE,
    reason="app.main CLI is not yet implemented (Milestone 5 planned)",
)


# ==============================================================================
# Synthetic Test Data Generation Fixture
# ==============================================================================


@dataclass
class SyntheticWorkspace:
    """Helper fixture providing isolated filesystem generation with controlled encodings."""

    root: Path

    def create_text_file(
        self,
        rel_path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> Path:
        """Create a text file with specified encoding."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return target

    def create_bytes_file(self, rel_path: str | Path, raw_bytes: bytes) -> Path:
        """Create a binary or raw byte file."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw_bytes)
        return target

    def create_bom_file(self, rel_path: str | Path, content: str) -> Path:
        """Create a UTF-8 file with Byte Order Mark (BOM: \xef\xbb\xbf)."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        return target

    def create_cp949_file(self, rel_path: str | Path, content: str) -> Path:
        """Create a Korean CP949 / EUC-KR encoded file."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("cp949"))
        return target

    def create_latin1_file(self, rel_path: str | Path, content: str) -> Path:
        """Create an ISO-8859-1 (Latin-1) encoded file."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("latin-1"))
        return target

    def create_binary_file(
        self,
        rel_path: str | Path,
        has_null_bytes: bool = True,
    ) -> Path:
        """Create a binary file with null bytes or executable header."""
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if has_null_bytes:
            data = b"Some initial text \x00 with embedded null bytes\x00\x01\x02"
        else:
            data = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        target.write_bytes(data)
        return target

    def create_symlink(self, rel_link_path: str | Path, rel_target_path: str | Path) -> Path | None:
        """Create a filesystem symlink pointing to another path within or outside the workspace."""
        link_target = self.root / rel_target_path
        link_path = self.root / rel_link_path
        link_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(link_target, link_path)
            return link_path
        except (OSError, NotImplementedError):
            return None


@pytest.fixture
def workspace(tmp_path: Path) -> SyntheticWorkspace:
    """Fixture providing a clean, self-contained synthetic workspace in tmp_path."""
    return SyntheticWorkspace(root=tmp_path)


def run_search(
    options: Any,
    cancel_event: threading.Event | None = None,
) -> tuple[list[Any], Any]:
    """Helper to execute SearchEngine.search and return (results_list, scan_statistics)."""
    assert SearchEngine is not None
    engine = SearchEngine()
    results: list[Any] = []
    stats = engine.search(
        options=options,
        result_callback=results.append,
        cancel_event=cancel_event,
    )
    return results, stats


# ==============================================================================
# TIER 1: Core Feature Coverage
# ==============================================================================


@requires_core
class TestTier1CoreFeatures:
    """Tier 1: Comprehensive coverage for all fundamental search engine features."""

    # --- F1: Plain String Search ---

    def test_tier1_f1_plain_single_word(self, workspace: SyntheticWorkspace) -> None:
        """F1.1: Verify single word match in standard text file."""
        workspace.create_text_file("doc1.txt", "The quick brown fox jumps over the lazy dog.")
        opts = SearchOptions(path=workspace.root, query="brown")
        results, stats = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "doc1.txt"
        assert results[0].line_number == 1
        assert "quick brown fox" in results[0].matched_line
        assert results[0].match_start == 10
        assert results[0].match_end == 15
        assert stats.success_count >= 1

    def test_tier1_f1_plain_multi_word_phrase(self, workspace: SyntheticWorkspace) -> None:
        """F1.2: Verify multi-word phrase with spaces."""
        workspace.create_text_file("phrase.txt", "alpha beta gamma\nhello search world\nfinal line")
        opts = SearchOptions(path=workspace.root, query="hello search world")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].line_number == 2
        assert results[0].matched_line == "hello search world"

    def test_tier1_f1_plain_punctuation_in_query(self, workspace: SyntheticWorkspace) -> None:
        """F1.3: Verify query containing punctuation and brackets without regex interpretation."""
        workspace.create_text_file("code.py", "items = [1, 2, 3]; val = dict['key'];")
        opts = SearchOptions(path=workspace.root, query="dict['key']", is_regex=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "dict['key']" in results[0].matched_line

    def test_tier1_f1_plain_multiple_matches_same_line(self, workspace: SyntheticWorkspace) -> None:
        """F1.4: Verify multiple matches on the same line produce distinct SearchResult entries."""
        workspace.create_text_file("repeat.txt", "echo test and echo again and echo once more")
        opts = SearchOptions(path=workspace.root, query="echo")
        results, _ = run_search(opts)

        assert len(results) == 3
        offsets = [(r.match_start, r.match_end) for r in results]
        assert offsets == [(0, 4), (14, 18), (29, 33)]
        for r in results:
            assert r.line_number == 1

    def test_tier1_f1_plain_matches_across_multiple_files(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F1.5: Verify search aggregates matches across multiple distinct files."""
        workspace.create_text_file("file_a.txt", "target keyword in file A")
        workspace.create_text_file("file_b.txt", "no match here")
        workspace.create_text_file("file_c.txt", "target keyword in file C")
        opts = SearchOptions(path=workspace.root, query="target keyword")
        results, stats = run_search(opts)

        matched_files = {r.file_name for r in results}
        assert matched_files == {"file_a.txt", "file_c.txt"}
        assert stats.scanned_files == 3

    # --- F2: Case Sensitivity Toggle ---

    def test_tier1_f2_case_insensitive_default_lowercase_query(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F2.1: Default case-insensitive matches uppercase text when query is lowercase."""
        workspace.create_text_file("case.txt", "FILEFINDER is fast")
        opts = SearchOptions(path=workspace.root, query="filefinder", case_sensitive=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].matched_line == "FILEFINDER is fast"

    def test_tier1_f2_case_insensitive_default_uppercase_query(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F2.2: Default case-insensitive matches lowercase text when query is uppercase."""
        workspace.create_text_file("case.txt", "filefinder is fast")
        opts = SearchOptions(path=workspace.root, query="FILEFINDER", case_sensitive=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].matched_line == "filefinder is fast"

    def test_tier1_f2_case_insensitive_default_mixed_case(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F2.3: Default case-insensitive matches varied casing."""
        workspace.create_text_file("case.txt", "FileFinder\nFILEFINDER\nfilefinder\nFiLeFiNdEr")
        opts = SearchOptions(path=workspace.root, query="FileFinder", case_sensitive=False)
        results, _ = run_search(opts)

        assert len(results) == 4

    def test_tier1_f2_case_sensitive_enabled_exact_match(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F2.4: Case-sensitive search matches exact case."""
        workspace.create_text_file("exact.txt", "Token\ntoken\nTOKEN")
        opts = SearchOptions(path=workspace.root, query="Token", case_sensitive=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].line_number == 1
        assert results[0].matched_line == "Token"

    def test_tier1_f2_case_sensitive_enabled_rejects_mismatched_case(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F2.5: Case-sensitive search returns zero results when case differs."""
        workspace.create_text_file("mismatch.txt", "hello world\nHELLO WORLD")
        opts = SearchOptions(path=workspace.root, query="Hello", case_sensitive=True)
        results, _ = run_search(opts)

        assert len(results) == 0

    # --- F3: Regular Expression Search ---

    def test_tier1_f3_regex_character_classes(self, workspace: SyntheticWorkspace) -> None:
        """F3.1: Regex matching character classes [a-z]+."""
        workspace.create_text_file("regex1.txt", "item1: 456\nitem2: 789\nitem3: abc")
        opts = SearchOptions(path=workspace.root, query=r"item\d+:\s+\d+", is_regex=True)
        results, _ = run_search(opts)

        assert len(results) == 2
        lines = [r.line_number for r in results]
        assert lines == [1, 2]

    def test_tier1_f3_regex_digit_pattern_phone(self, workspace: SyntheticWorkspace) -> None:
        """F3.2: Regex matching phone-like pattern `\\d{3}-\\d{4}` (spec requirement)."""
        workspace.create_text_file("contacts.txt", "Call me at 010-1234-5678 or office 02-987-6543")
        opts = SearchOptions(path=workspace.root, query=r"\d{3}-\d{4}", is_regex=True)
        results, _ = run_search(opts)

        assert len(results) >= 1
        assert any("010-1234-5678" in r.matched_line for r in results)

    def test_tier1_f3_regex_anchors_start_and_end(self, workspace: SyntheticWorkspace) -> None:
        """F3.3: Regex matching line start (^) and end ($) anchors."""
        workspace.create_text_file(
            "anchors.txt", "START data\nmid START mid\ndata END\nSTART only END"
        )
        opts = SearchOptions(path=workspace.root, query=r"^START.*END$", is_regex=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].matched_line == "START only END"

    def test_tier1_f3_regex_alternation(self, workspace: SyntheticWorkspace) -> None:
        """F3.4: Regex matching alternation (foo|bar)."""
        workspace.create_text_file("alter.txt", "apple banana cherry date")
        opts = SearchOptions(path=workspace.root, query=r"banana|date", is_regex=True)
        results, _ = run_search(opts)

        assert len(results) == 2
        matched_texts = [r.matched_line[r.match_start : r.match_end] for r in results]
        assert "banana" in matched_texts
        assert "date" in matched_texts

    def test_tier1_f3_regex_escaped_metacharacters(self, workspace: SyntheticWorkspace) -> None:
        """F3.5: Regex matching escaped dots, brackets, and stars."""
        workspace.create_text_file("meta.txt", "pointer->value\narray[0] = *ptr;\nnormal text")
        opts = SearchOptions(path=workspace.root, query=r"array\[0\] = \*ptr;", is_regex=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].line_number == 2

    # --- F4: Traversal Modes (Recursive / Non-Recursive) ---

    def test_tier1_f4_recursive_finds_in_root(self, workspace: SyntheticWorkspace) -> None:
        """F4.1: Recursive mode finds files in the root folder."""
        workspace.create_text_file("root.txt", "needle in root")
        opts = SearchOptions(path=workspace.root, query="needle", recursive=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "root.txt"

    def test_tier1_f4_recursive_finds_in_subdirs(self, workspace: SyntheticWorkspace) -> None:
        """F4.2: Recursive mode finds files in immediate subdirectories."""
        workspace.create_text_file("sub/level1.txt", "needle in level 1")
        opts = SearchOptions(path=workspace.root, query="needle", recursive=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "level1.txt"

    def test_tier1_f4_recursive_finds_in_deeply_nested(self, workspace: SyntheticWorkspace) -> None:
        """F4.3: Recursive mode finds files in deeply nested subdirectories."""
        workspace.create_text_file("a/b/c/d/deep.txt", "needle in deep ocean")
        opts = SearchOptions(path=workspace.root, query="needle", recursive=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "deep.txt"

    def test_tier1_f4_non_recursive_finds_root_only(self, workspace: SyntheticWorkspace) -> None:
        """F4.4: Non-recursive mode finds files residing strictly in root."""
        workspace.create_text_file("root.txt", "needle in root")
        workspace.create_text_file("sub/sub.txt", "needle in sub")
        opts = SearchOptions(path=workspace.root, query="needle", recursive=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "root.txt"

    def test_tier1_f4_non_recursive_ignores_subdirs(self, workspace: SyntheticWorkspace) -> None:
        """F4.5: Non-recursive mode does not descend into subdirectories."""
        workspace.create_text_file("child1/file.txt", "needle here")
        workspace.create_text_file("child2/file.txt", "needle here")
        opts = SearchOptions(path=workspace.root, query="needle", recursive=False)
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.scanned_files == 0

    # --- F5: Extension Whitelist Filtering ---

    def test_tier1_f5_ext_filter_single_with_dot(self, workspace: SyntheticWorkspace) -> None:
        """F5.1: Extension filter with leading dot restricts search to matching files."""
        workspace.create_text_file("doc.txt", "needle in txt")
        workspace.create_text_file("doc.py", "needle in py")
        opts = SearchOptions(path=workspace.root, query="needle", extensions=[".py"])
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "doc.py"

    def test_tier1_f5_ext_filter_single_without_dot(self, workspace: SyntheticWorkspace) -> None:
        """F5.2: Extension filter without leading dot normalized and matched correctly."""
        workspace.create_text_file("doc.txt", "needle in txt")
        workspace.create_text_file("doc.md", "needle in md")
        opts = SearchOptions(path=workspace.root, query="needle", extensions=["md"])
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "doc.md"

    def test_tier1_f5_ext_filter_multiple_extensions(self, workspace: SyntheticWorkspace) -> None:
        """F5.3: Multiple extension filters match union of specified extensions."""
        workspace.create_text_file("a.py", "needle in py")
        workspace.create_text_file("b.json", "needle in json")
        workspace.create_text_file("c.xml", "needle in xml")
        opts = SearchOptions(path=workspace.root, query="needle", extensions=[".py", ".json"])
        results, _ = run_search(opts)

        matched_names = {r.file_name for r in results}
        assert matched_names == {"a.py", "b.json"}

    def test_tier1_f5_ext_filter_case_insensitive_extensions(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F5.4: Extension filtering is case-insensitive (.TXT finds .txt and .TXT)."""
        workspace.create_text_file("lower.txt", "needle in lower")
        workspace.create_text_file("upper.TXT", "needle in upper")
        opts = SearchOptions(path=workspace.root, query="needle", extensions=[".TXT"])
        results, _ = run_search(opts)

        assert len(results) == 2

    def test_tier1_f5_ext_filter_unmatched_extensions_excluded(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F5.5: Files with non-matching extensions are completely skipped."""
        workspace.create_text_file("skip.log", "needle in log")
        workspace.create_text_file("skip.ini", "needle in ini")
        opts = SearchOptions(path=workspace.root, query="needle", extensions=[".txt"])
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.scanned_files == 0

    # --- F6: Binary File Exclusion ---

    def test_tier1_f6_binary_exclusion_known_exe_dll_zip(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F6.1: Files with known binary extensions (.exe, .zip) excluded even if content is text."""
        workspace.create_text_file("program.exe", "fake text containing needle")
        workspace.create_text_file("archive.zip", "fake text containing needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 0

    def test_tier1_f6_binary_exclusion_image_files(self, workspace: SyntheticWorkspace) -> None:
        """F6.2: Media extensions (.png, .jpg) excluded from content scanning."""
        workspace.create_text_file("photo.png", "needle")
        workspace.create_text_file("icon.ico", "needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 0

    def test_tier1_f6_binary_exclusion_null_byte_heuristic_8kb(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F6.3: Unknown extension containing null bytes rejected via 8KB null-byte heuristic."""
        raw_data = b"Some header info\x00\x00\x00" + b"needle in binary payload"
        workspace.create_bytes_file("custom.dat_blob", raw_data)
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 0

    def test_tier1_f6_binary_pure_text_files_searched(self, workspace: SyntheticWorkspace) -> None:
        """F6.4: Pure text files without null bytes are searched properly."""
        workspace.create_text_file("notes.txt", "valid text line with needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 1

    def test_tier1_f6_binary_mixed_tree_only_text_matched(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F6.5: Mixed tree containing binaries and text files yields only text file matches."""
        workspace.create_text_file("code.py", "needle in python")
        workspace.create_binary_file("module.pyc")
        workspace.create_binary_file("data.bin")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "code.py"

    # --- F7: Symlink Safety ---

    def test_tier1_f7_symlink_file_skipped_by_default(self, workspace: SyntheticWorkspace) -> None:
        """F7.1: Symlinked file is skipped by default (follow_symlinks=False)."""
        real_file = workspace.create_text_file("real.txt", "needle in real")
        link = workspace.create_symlink("symlink.txt", "real.txt")
        if link is None:
            pytest.skip("Symlink creation not supported in current test environment")

        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        # Only the real file should be found, not the symlink
        matched_paths = [r.file_path for r in results]
        assert real_file in matched_paths
        assert link not in matched_paths

    def test_tier1_f7_symlink_dir_skipped_by_default(self, workspace: SyntheticWorkspace) -> None:
        """F7.2: Symlinked directory is not traversed by default."""
        workspace.create_text_file("real_dir/file.txt", "needle in real dir")
        link_dir = workspace.create_symlink("link_dir", "real_dir")
        if link_dir is None:
            pytest.skip("Symlink creation not supported in current test environment")

        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "real_dir" in str(results[0].file_path)

    def test_tier1_f7_symlink_circular_loop_safe(self, workspace: SyntheticWorkspace) -> None:
        """F7.3: Recursive symlink cycle does not cause infinite recursion."""
        workspace.create_text_file("dir_a/file.txt", "needle in dir_a")
        link = workspace.create_symlink("dir_a/loop_back", "dir_a")
        if link is None:
            pytest.skip("Symlink creation not supported in current test environment")

        opts = SearchOptions(path=workspace.root, query="needle", recursive=True)
        results, stats = run_search(opts)

        assert len(results) == 1
        assert stats.error_count == 0

    def test_tier1_f7_symlink_original_file_searched_once(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F7.4: When symlink points to original, original is searched once without duplication."""
        workspace.create_text_file("target.txt", "unique_keyword_123")
        workspace.create_symlink("alias.txt", "target.txt")

        opts = SearchOptions(path=workspace.root, query="unique_keyword_123")
        results, _ = run_search(opts)

        assert len(results) == 1

    def test_tier1_f7_symlink_broken_link_handled_without_crash(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F7.5: Broken symlink pointing to non-existent target does not crash search."""
        workspace.create_symlink("broken_link.txt", "does_not_exist.txt")
        workspace.create_text_file("valid.txt", "needle")

        opts = SearchOptions(path=workspace.root, query="needle")
        results, stats = run_search(opts)

        assert len(results) == 1
        assert stats.error_count == 0

    # --- F8: Hidden File Filtering ---

    def test_tier1_f8_hidden_dot_file_excluded_by_default(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F8.1: Dot-prefixed file (.env) is excluded when include_hidden=False."""
        workspace.create_text_file(".env", "SECRET_KEY = needle")
        workspace.create_text_file("visible.env", "SECRET_KEY = needle")
        opts = SearchOptions(path=workspace.root, query="needle", include_hidden=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "visible.env"

    def test_tier1_f8_hidden_dot_dir_excluded_by_default(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F8.2: Dot-prefixed directory (.git/) is excluded when include_hidden=False."""
        workspace.create_text_file(".git/config", "needle in git config")
        workspace.create_text_file("src/app.py", "needle in app")
        opts = SearchOptions(path=workspace.root, query="needle", include_hidden=False)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "app.py"

    def test_tier1_f8_hidden_dot_file_included_when_enabled(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F8.3: Dot-prefixed file is searched when include_hidden=True."""
        workspace.create_text_file(".env", "SECRET_KEY = needle")
        opts = SearchOptions(path=workspace.root, query="needle", include_hidden=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == ".env"

    def test_tier1_f8_hidden_dot_dir_included_when_enabled(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F8.4: Dot-prefixed directory files are searched when include_hidden=True."""
        workspace.create_text_file(".config/app.conf", "needle in hidden dir")
        opts = SearchOptions(path=workspace.root, query="needle", include_hidden=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "app.conf"

    def test_tier1_f8_hidden_nested_file_in_visible_dir(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F8.5: Hidden file nested deep in visible directory is filtered properly."""
        workspace.create_text_file("public/assets/.secret.txt", "needle")
        opts = SearchOptions(path=workspace.root, query="needle", include_hidden=False)
        results, _ = run_search(opts)

        assert len(results) == 0

    # --- F9: Encoding Auto-Detection Fallback Chain ---

    def test_tier1_f9_encoding_utf8_standard(self, workspace: SyntheticWorkspace) -> None:
        """F9.1: Standard UTF-8 file detected and searched correctly."""
        workspace.create_text_file("utf8.txt", "FileFinder UTF-8 검색 테스트", encoding="utf-8")
        opts = SearchOptions(path=workspace.root, query="검색")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "검색" in results[0].matched_line
        assert results[0].encoding.lower() in {"utf-8", "utf_8"}

    def test_tier1_f9_encoding_utf8_bom(self, workspace: SyntheticWorkspace) -> None:
        """F9.2: UTF-8 with BOM file detected as utf-8-sig."""
        workspace.create_bom_file("bom.txt", "BOM Header Text with needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "needle" in results[0].matched_line
        assert "utf-8" in results[0].encoding.lower()

    def test_tier1_f9_encoding_cp949_korean(self, workspace: SyntheticWorkspace) -> None:
        """F9.3: Korean legacy CP949 / EUC-KR encoded file correctly detected and searched."""
        korean_text = "안녕하세요 파일파인더 한글 검색 테스트 문서입니다.\n두 번째 줄 내용."
        workspace.create_cp949_file("korean_cp949.txt", korean_text)
        opts = SearchOptions(path=workspace.root, query="파일파인더")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "파일파인더" in results[0].matched_line
        assert results[0].encoding.lower() in {"cp949", "euc-kr", "euc_kr"}

    def test_tier1_f9_encoding_latin1_european(self, workspace: SyntheticWorkspace) -> None:
        """F9.4: Latin-1 European text file with high bytes detected and searched."""
        latin_text = "Résumé of François: naïve café façade\nSecond line."
        workspace.create_latin1_file("french.txt", latin_text)
        opts = SearchOptions(path=workspace.root, query="naïve")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "naïve" in results[0].matched_line

    def test_tier1_f9_encoding_mixed_directory_common_query(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F9.5: Mixed encoding directory searching for a common ASCII term."""
        workspace.create_text_file("file_utf8.txt", "COMMON_TOKEN in utf-8", encoding="utf-8")
        workspace.create_cp949_file("file_cp949.txt", "COMMON_TOKEN in cp949 한글")
        workspace.create_latin1_file("file_latin1.txt", "COMMON_TOKEN in latin-1 café")

        opts = SearchOptions(path=workspace.root, query="COMMON_TOKEN")
        results, stats = run_search(opts)

        assert len(results) == 3
        assert stats.scanned_files == 3
        assert stats.error_count == 0

    # --- F10: Callbacks and Statistics Reporting ---

    def test_tier1_f10_callbacks_result_fields_populated(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F10.1: SearchResult contains all mandatory dataclass fields populated accurately."""
        workspace.create_text_file("info.txt", "line one\nline two target line\nline three")
        opts = SearchOptions(path=workspace.root, query="target")
        results, _ = run_search(opts)

        assert len(results) == 1
        res = results[0]
        assert isinstance(res.file_path, Path)
        assert res.file_name == "info.txt"
        assert res.line_number == 2
        assert res.matched_line == "line two target line"
        assert res.match_start == 9
        assert res.match_end == 15
        assert isinstance(res.encoding, str)

    def test_tier1_f10_callbacks_progress_scanned_count(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F10.2: progress_callback is called and updates scanned_files count incrementally."""
        assert SearchEngine is not None
        for i in range(5):
            workspace.create_text_file(f"file_{i}.txt", f"content {i}")

        progress_calls: list[tuple[int, int, Path]] = []
        engine = SearchEngine()
        opts = SearchOptions(path=workspace.root, query="content")
        stats = engine.search(
            options=opts,
            progress_callback=lambda s, t, p: progress_calls.append((s, t, p)),
        )

        assert len(progress_calls) == 5
        assert stats.scanned_files == 5
        assert stats.total_files == 5

    def test_tier1_f10_callbacks_progress_path_type(self, workspace: SyntheticWorkspace) -> None:
        """F10.3: progress_callback passes valid Path instances."""
        assert SearchEngine is not None
        workspace.create_text_file("sample.txt", "content")
        recorded_paths: list[Path] = []
        engine = SearchEngine()
        opts = SearchOptions(path=workspace.root, query="content")
        engine.search(
            options=opts,
            progress_callback=lambda s, t, p: recorded_paths.append(p),
        )

        assert len(recorded_paths) == 1
        assert isinstance(recorded_paths[0], Path)
        assert recorded_paths[0].name == "sample.txt"

    def test_tier1_f10_callbacks_statistics_counts_match_results(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F10.4: ScanStatistics totals match callback counts and scanned file counts."""
        for i in range(3):
            workspace.create_text_file(f"match_{i}.txt", "needle here")
        workspace.create_text_file("other.txt", "no match")

        opts = SearchOptions(path=workspace.root, query="needle")
        results, stats = run_search(opts)

        assert len(results) == 3
        assert stats.total_files == 4
        assert stats.scanned_files == 4
        assert stats.success_count >= 3
        assert stats.error_count == 0

    def test_tier1_f10_callbacks_elapsed_time_positive(self, workspace: SyntheticWorkspace) -> None:
        """F10.5: ScanStatistics.elapsed_seconds is a positive float."""
        workspace.create_text_file("file.txt", "needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        _, stats = run_search(opts)

        assert stats.elapsed_seconds >= 0.0
        assert isinstance(stats.elapsed_seconds, float)

    # --- F11: Cooperative Cancellation ---

    def test_tier1_f11_cancellation_pre_set_stops_immediately(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F11.1: If cancel_event is already set, search terminates immediately with 0 results."""
        for i in range(10):
            workspace.create_text_file(f"f_{i}.txt", "needle")

        cancel_event = threading.Event()
        cancel_event.set()

        opts = SearchOptions(path=workspace.root, query="needle")
        results, stats = run_search(opts, cancel_event=cancel_event)

        assert len(results) == 0
        assert getattr(stats, "cancelled", False) is True

    def test_tier1_f11_cancellation_mid_search_preserves_results(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F11.2: Cancelling mid-search preserves already-accumulated results."""
        assert SearchEngine is not None
        for i in range(20):
            workspace.create_text_file(f"file_{i:02d}.txt", f"needle in file {i}")

        cancel_event = threading.Event()
        results: list[Any] = []

        def cancel_on_match(res: Any) -> None:
            results.append(res)
            if len(results) >= 3:
                cancel_event.set()

        engine = SearchEngine(max_workers=1)
        opts = SearchOptions(path=workspace.root, query="needle")
        stats = engine.search(
            options=opts,
            result_callback=cancel_on_match,
            cancel_event=cancel_event,
        )

        assert len(results) >= 3
        assert len(results) < 20
        assert getattr(stats, "cancelled", False) is True

    def test_tier1_f11_cancellation_stats_cancelled_flag_true(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F11.3: ScanStatistics accurately reflects cancelled=True upon cancellation."""
        workspace.create_text_file("test.txt", "needle")
        cancel_event = threading.Event()
        cancel_event.set()

        opts = SearchOptions(path=workspace.root, query="needle")
        _, stats = run_search(opts, cancel_event=cancel_event)

        assert getattr(stats, "cancelled", False) is True

    def test_tier1_f11_cancellation_no_unhandled_exceptions(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F11.4: Cancellation does not raise exceptions or crash background threads."""
        workspace.create_text_file("f1.txt", "data")
        cancel_event = threading.Event()
        cancel_event.set()
        opts = SearchOptions(path=workspace.root, query="data")

        # Must not raise any exception
        _, stats = run_search(opts, cancel_event=cancel_event)
        assert stats.error_count == 0

    def test_tier1_f11_cancellation_pool_remains_usable(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """F11.5: Subsequent searches work cleanly after a cancelled search."""
        assert SearchEngine is not None
        workspace.create_text_file("first.txt", "needle")
        workspace.create_text_file("second.txt", "needle")

        engine = SearchEngine()

        # Run 1: Cancelled
        cancel_event = threading.Event()
        cancel_event.set()
        opts1 = SearchOptions(path=workspace.root, query="needle")
        engine.search(options=opts1, cancel_event=cancel_event)

        # Run 2: Clean search without cancel
        opts2 = SearchOptions(path=workspace.root, query="needle")
        results: list[Any] = []
        stats2 = engine.search(options=opts2, result_callback=results.append)

        assert len(results) == 2
        assert stats2.scanned_files == 2


# ==============================================================================
# TIER 2: Boundary & Corner Cases
# ==============================================================================


@requires_core
class TestTier2BoundaryCornerCases:
    """Tier 2: Verification of system boundaries, empty inputs, extreme lengths, and special chars."""

    def test_tier2_empty_directory_zero_files(self, workspace: SyntheticWorkspace) -> None:
        """B1: Searching an entirely empty directory yields 0 results without error."""
        opts = SearchOptions(path=workspace.root, query="anything")
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.total_files == 0
        assert stats.scanned_files == 0
        assert stats.error_count == 0

    def test_tier2_empty_files_zero_bytes(self, workspace: SyntheticWorkspace) -> None:
        """B2: Zero-byte files handled gracefully without error."""
        workspace.create_bytes_file("empty1.txt", b"")
        workspace.create_bytes_file("empty2.txt", b"")
        opts = SearchOptions(path=workspace.root, query="target")
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.scanned_files == 2
        assert stats.error_count == 0

    def test_tier2_blank_lines_only_file(self, workspace: SyntheticWorkspace) -> None:
        """B3: File containing only blank newlines (\\n\\n\\n) handled correctly."""
        workspace.create_text_file("blank.txt", "\n\n\n\n\n")
        opts = SearchOptions(path=workspace.root, query="text")
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.scanned_files == 1

    def test_tier2_extreme_long_single_line(self, workspace: SyntheticWorkspace) -> None:
        """B4: Extremely long line (64KB text) matched without memory or offset crash."""
        prefix = "a" * 32000
        suffix = "b" * 32000
        content = f"{prefix}TARGET_TOKEN{suffix}"
        workspace.create_text_file("long_line.txt", content)

        opts = SearchOptions(path=workspace.root, query="TARGET_TOKEN")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].match_start == 32000
        assert results[0].match_end == 32000 + len("TARGET_TOKEN")
        assert results[0].line_number == 1

    def test_tier2_large_file_line_streaming(self, workspace: SyntheticWorkspace) -> None:
        """B5: Multi-thousand line file processed line-by-line with exact line number matching."""
        lines = [f"line number {i} padding text" for i in range(1, 5001)]
        lines[4241] = "line number 4242 SPECIAL_NEEDLE target"
        workspace.create_text_file("big_log.txt", "\n".join(lines))

        opts = SearchOptions(path=workspace.root, query="SPECIAL_NEEDLE")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].line_number == 4242
        assert "SPECIAL_NEEDLE" in results[0].matched_line

    def test_tier2_match_at_exact_boundaries_start_and_end_of_line(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """B6: Matches located at index 0 and end-of-line without newline."""
        content = "NEEDLE middle NEEDLE"
        workspace.create_text_file("bounds.txt", content)

        opts = SearchOptions(path=workspace.root, query="NEEDLE")
        results, _ = run_search(opts)

        assert len(results) == 2
        assert results[0].match_start == 0
        assert results[0].match_end == 6
        assert results[1].match_start == 14
        assert results[1].match_end == 20

    def test_tier2_zero_matches_query_not_found(self, workspace: SyntheticWorkspace) -> None:
        """B7: Non-existent query across multiple files returns 0 results cleanly."""
        for i in range(5):
            workspace.create_text_file(f"doc_{i}.txt", f"content block {i}")
        opts = SearchOptions(path=workspace.root, query="NON_EXISTENT_STRING_XYZ")
        results, stats = run_search(opts)

        assert len(results) == 0
        assert stats.scanned_files == 5
        assert stats.error_count == 0

    def test_tier2_single_character_query(self, workspace: SyntheticWorkspace) -> None:
        """B8: Single character query correctly finds occurrences."""
        workspace.create_text_file("single_char.txt", "x y z\nx a b")
        opts = SearchOptions(path=workspace.root, query="x")
        results, _ = run_search(opts)

        assert len(results) == 2
        lines = [r.line_number for r in results]
        assert lines == [1, 2]

    def test_tier2_astral_plane_unicode_emojis_and_symbols(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """B9: 4-byte UTF-8 emojis (🔍, 🚀) and symbols searched and matched accurately."""
        workspace.create_text_file("emojis.txt", "Search engine 🔍 is fast 🚀!\nAnother line.")
        opts = SearchOptions(path=workspace.root, query="🔍")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "🔍" in results[0].matched_line

    def test_tier2_special_filenames_spaces_brackets_korean(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """B10: Special filenames containing spaces, Korean Hangul, and brackets."""
        name = "데이터 검색 [보고서] (최종) 2026.txt"
        workspace.create_text_file(name, "내부 데이터 내용: keyword_found")
        opts = SearchOptions(path=workspace.root, query="keyword_found")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == name

    def test_tier2_filenames_with_leading_dashes(self, workspace: SyntheticWorkspace) -> None:
        """B11: Filenames starting with dashes (--config.txt) handled safely."""
        workspace.create_text_file("--special-file.txt", "content with needle")
        opts = SearchOptions(path=workspace.root, query="needle")
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "--special-file.txt"

    def test_tier2_deeply_nested_directory_tree_12_levels(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """B12: Traversal through 12+ directory levels deep."""
        deep_path = Path("a/b/c/d/e/f/g/h/i/j/k/l/deep_target.txt")
        workspace.create_text_file(deep_path, "deep needle found")
        opts = SearchOptions(path=workspace.root, query="deep needle", recursive=True)
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "deep_target.txt"


# ==============================================================================
# TIER 3: Cross-Feature Combinations (Pairwise & Multi-Way Interactions)
# ==============================================================================


@requires_core
class TestTier3CrossFeatureCombinations:
    """Tier 3: Testing interactions between multiple orthogonal search parameters."""

    def test_tier3_combo_regex_non_recursive_hidden_enabled(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C1: Regex + Non-recursive + Hidden files enabled."""
        workspace.create_text_file(".env", "DB_PORT=5432\nDB_HOST=localhost")
        workspace.create_text_file(".secret.txt", "API_KEY=abcd-1234")
        workspace.create_text_file("sub/.env.sub", "DB_PORT=9999")  # Subdir should be ignored

        opts = SearchOptions(
            path=workspace.root,
            query=r"[A-Z_]+=\d+",
            is_regex=True,
            recursive=False,
            include_hidden=True,
        )
        results, _ = run_search(opts)

        # Only root .env should match
        assert len(results) == 1
        assert results[0].file_name == ".env"
        assert results[0].matched_line == "DB_PORT=5432"

    def test_tier3_combo_case_sensitive_multi_ext_mixed_encodings(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C2: Case-sensitive + Multi-extension filter + Mixed encodings."""
        workspace.create_text_file("config.py", "AUTH_TOKEN = 'secret'", encoding="utf-8")
        workspace.create_cp949_file("memo.txt", "AUTH_TOKEN 설정 완료")
        workspace.create_text_file("lower.py", "auth_token = 'skip'")
        workspace.create_text_file("ignore.doc", "AUTH_TOKEN = 'skip'")

        opts = SearchOptions(
            path=workspace.root,
            query="AUTH_TOKEN",
            case_sensitive=True,
            extensions=[".py", ".txt"],
        )
        results, _ = run_search(opts)

        matched_names = {r.file_name for r in results}
        assert matched_names == {"config.py", "memo.txt"}

    def test_tier3_combo_binary_exclusion_overrides_ext_filter(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C3: User specifies [".bin", ".txt"] -> binary file with .bin is still excluded."""
        workspace.create_binary_file("firmware.bin", has_null_bytes=True)
        workspace.create_text_file("notes.txt", "needle in text")

        opts = SearchOptions(
            path=workspace.root,
            query="needle",
            extensions=[".bin", ".txt"],
        )
        results, _ = run_search(opts)

        assert len(results) == 1
        assert results[0].file_name == "notes.txt"

    def test_tier3_combo_regex_case_insensitive_deep_nesting_cancellation(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C4: Regex + Case-Insensitive + Nested directories + Cancellation event."""
        for i in range(15):
            workspace.create_text_file(f"dir_{i}/file_{i}.txt", f"Item UUID: {i:04d}-ABCD")

        cancel_event = threading.Event()
        results: list[Any] = []

        def cancel_after_two(res: Any) -> None:
            results.append(res)
            if len(results) >= 2:
                cancel_event.set()

        assert SearchEngine is not None
        engine = SearchEngine(max_workers=1)
        opts = SearchOptions(
            path=workspace.root,
            query=r"uuid:\s+\d{4}-[a-z]+",
            is_regex=True,
            case_sensitive=False,
            recursive=True,
        )
        stats = engine.search(
            options=opts,
            result_callback=cancel_after_two,
            cancel_event=cancel_event,
        )

        assert len(results) >= 2
        assert getattr(stats, "cancelled", False) is True

    def test_tier3_combo_korean_cp949_multi_word_exact_case(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C5: Korean CP949 + Multi-word query + Case-sensitive."""
        workspace.create_cp949_file("korean_report.txt", "2026년 상반기 FILEFINDER 개발 계획서")
        opts = SearchOptions(
            path=workspace.root,
            query="상반기 FILEFINDER",
            case_sensitive=True,
        )
        results, _ = run_search(opts)

        assert len(results) == 1
        assert "상반기 FILEFINDER" in results[0].matched_line

    def test_tier3_combo_symlink_dir_and_hidden_files_recursive(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """C6: Symlinked directory + Hidden files toggle."""
        workspace.create_text_file("real/.secret.txt", "hidden needle")
        workspace.create_symlink("symlink_dir", "real")

        opts = SearchOptions(
            path=workspace.root,
            query="hidden needle",
            include_hidden=True,
            recursive=True,
        )
        results, _ = run_search(opts)

        # Real hidden file is found; symlinked directory is skipped
        assert len(results) == 1
        assert "real" in str(results[0].file_path)


# ==============================================================================
# TIER 4: Real-World Application Scenarios
# ==============================================================================


@requires_core
class TestTier4RealWorldScenarios:
    """Tier 4: Realistic developer and sysadmin workflows simulating real workspaces."""

    def test_tier4_polyglot_repository_search(self, workspace: SyntheticWorkspace) -> None:
        """
        Scenario 1: Polyglot Full-Stack Repository.
        Simulates searching for API_BASE_URL across Python, TypeScript, Markdown, JSON,
        while safely ignoring .git internals and binary assets.
        """
        workspace.create_text_file("backend/server.py", "API_BASE_URL = 'https://api.domain.com'")
        workspace.create_text_file(
            "frontend/src/api.ts", "const API_BASE_URL = 'https://api.domain.com';"
        )
        workspace.create_text_file("docs/api.md", "Configure `API_BASE_URL` in your environment.")
        workspace.create_text_file("config/env.json", '{"API_BASE_URL": "https://api.domain.com"}')
        workspace.create_text_file(
            ".git/config", "API_BASE_URL in hidden git config (should be ignored)"
        )
        workspace.create_binary_file("assets/logo.png")
        workspace.create_binary_file("backend/__pycache__/server.cpython-313.pyc")

        opts = SearchOptions(
            path=workspace.root,
            query="API_BASE_URL",
            include_hidden=False,
            recursive=True,
        )
        results, stats = run_search(opts)

        matched_files = {r.file_name for r in results}
        assert matched_files == {"server.py", "api.ts", "api.md", "env.json"}
        assert ".git" not in str([r.file_path for r in results])
        assert stats.error_count == 0

    def test_tier4_legacy_corporate_archive_mixed_encodings(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """
        Scenario 2: Legacy Corporate Archive with Mixed Encodings.
        Simulates an archive containing CP949 Korean memos, UTF-8 BOM config, Latin-1 CSV,
        and standard UTF-8 files all searched for a common project tag.
        """
        workspace.create_cp949_file("archive/2018_보고서.txt", "프로젝트_알파 관련 회의록")
        workspace.create_bom_file("archive/config_bom.ini", "project = 프로젝트_알파")
        workspace.create_text_file("archive/notes_utf8.txt", "진행중인 작업: 프로젝트_알파")
        workspace.create_latin1_file("archive/legacy_eu.csv", "ID;NAME\n1;Project_Alpha_EU_café")

        opts = SearchOptions(
            path=workspace.root,
            query="프로젝트_알파",
            recursive=True,
        )
        results, stats = run_search(opts)

        # CP949, BOM, and UTF-8 files should all cleanly match
        assert len(results) >= 3
        assert stats.error_count == 0

    def test_tier4_server_log_audit_http_status_regex(self, workspace: SyntheticWorkspace) -> None:
        """
        Scenario 3: Server Log Audit & Incident Investigation.
        Simulates analyzing Apache/Nginx web server access logs for HTTP 500 errors
        using regular expressions to extract timestamped incident records.
        """
        log_content = (
            '192.168.1.10 - - [20/Sep/2026:10:15:32 +0000] "GET /index.html HTTP/1.1" 200 4523\n'
            '192.168.1.15 - - [20/Sep/2026:10:16:01 +0000] "POST /api/checkout HTTP/1.1" 500 120\n'
            '192.168.1.20 - - [20/Sep/2026:10:16:45 +0000] "GET /images/logo.png HTTP/1.1" 304 0\n'
            '192.168.1.25 - - [20/Sep/2026:10:17:12 +0000] "POST /api/payment HTTP/1.1" 503 89\n'
        )
        workspace.create_text_file("access.log", log_content)

        opts = SearchOptions(
            path=workspace.root,
            query=r'HTTP/1\.1"\s+5\d{2}',
            is_regex=True,
        )
        results, _ = run_search(opts)

        assert len(results) == 2
        lines = [r.line_number for r in results]
        assert lines == [2, 4]
        assert "500" in results[0].matched_line
        assert "503" in results[1].matched_line

    def test_tier4_error_resilience_unreadable_file_and_corrupt_bytes(
        self, workspace: SyntheticWorkspace
    ) -> None:
        """
        Scenario 4: Error Resilience & Fault Tolerance.
        Simulates filesystem with inaccessible files or corrupt byte streams.
        Verifies that search never crashes, processes valid files, and logs errors in ScanStatistics.
        """
        workspace.create_text_file("valid1.txt", "target in valid 1")
        workspace.create_text_file("valid2.txt", "target in valid 2")

        # Create a file with arbitrary mixed corrupt bytes
        corrupt_bytes = b"\xff\xfe\xff\xff\x00\x12\x34\xaa\xbb" + (
            "target in corrupt".encode("latin-1")
        )
        workspace.create_bytes_file("corrupt.dat", corrupt_bytes)

        opts = SearchOptions(path=workspace.root, query="target")
        results, stats = run_search(opts)

        # Search must complete without crashing
        assert len(results) >= 2
        assert stats.scanned_files >= 2
        assert isinstance(stats.errors, list)

    @requires_cli
    def test_tier4_cli_end_to_end_execution(
        self, workspace: SyntheticWorkspace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Scenario 5: Command-Line Interface (CLI) End-to-End Execution.
        Invokes parse_args and run_cli to verify argument parsing, stdout result streaming,
        and zero exit status code.
        """
        assert parse_args is not None and run_cli is not None
        workspace.create_text_file("cli_test.txt", "FileFinder CLI verification line")

        args = parse_args(
            [
                "--path",
                str(workspace.root),
                "--query",
                "verification",
                "--ignore-case",
            ]
        )
        exit_code = run_cli(args)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "cli_test.txt" in captured.out
        assert "verification" in captured.out


# ==============================================================================
# CLI Argument Parser Contract Unit/E2E Verification
# ==============================================================================


@requires_cli
class TestCliArgumentParserContract:
    """Verifies CLI argument parsing interface contract defined in R4."""

    def test_cli_parse_path_and_query(self) -> None:
        """Verify standard --path and --query parsing."""
        assert parse_args is not None
        args = parse_args(["--path", "/tmp/test", "--query", "find_me"])
        assert str(args.path) == "/tmp/test"
        assert args.query == "find_me"
        assert args.regex is False

    def test_cli_parse_flags(self) -> None:
        """Verify --regex and --ignore-case flags."""
        assert parse_args is not None
        args = parse_args(
            [
                "--path",
                "/tmp/test",
                "--query",
                "pattern",
                "--regex",
                "--ignore-case",
            ]
        )
        assert args.regex is True
        assert getattr(args, "ignore_case", False) is True
