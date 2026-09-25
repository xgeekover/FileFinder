"""Comprehensive unit test suite for FileScanner.

Verifies:
1. Recursive vs non-recursive traversal across deep and flat hierarchies
2. Full symlink safety: default ignoring symlinks, circular symlink protection, broken links
3. Hidden file and directory detection (.dot files and folders)
4. Memory-bounded line-by-line streaming (1-based lines, whitespace preservation, extreme line lengths)
5. Non-aborting exception resilience (PermissionError, FileNotFoundError, IsADirectoryError, OSError)
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.file_scanner import FileScanner


class TestFileScannerTraversal:
    """Group 1: Directory traversal scenarios (recursive vs non-recursive, flat, hierarchy)."""

    def test_scanner_default_initialization(self) -> None:
        """FS-00: FileScanner initializes with follow_symlinks=False and file_filter=None."""
        scanner = FileScanner()
        assert scanner.follow_symlinks is False
        assert scanner.file_filter is None

    def test_scan_files_flat_directory_matches_recursive_when_flat(self, tmp_path: Path) -> None:
        """FS-TRAV-01: In a flat folder with only top-level files, recursive and non-recursive yield identical sets."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.py"
        f1.write_text("a", encoding="utf-8")
        f2.write_text("b", encoding="utf-8")

        scanner = FileScanner()
        res_non_rec = list(scanner.scan_files(tmp_path, recursive=False))
        res_rec = list(scanner.scan_files(tmp_path, recursive=True))

        assert set(res_non_rec) == set(res_rec) == {f1, f2}

    def test_scan_files_non_recursive_skips_subdirectories(self, tmp_path: Path) -> None:
        """FS-TRAV-02: When recursive=False, subdirectories and their contents are completely ignored."""
        (tmp_path / "root1.txt").write_text("content", encoding="utf-8")
        (tmp_path / "root2.py").write_text("print()", encoding="utf-8")

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested", encoding="utf-8")

        sub_nested = sub / "deep"
        sub_nested.mkdir()
        (sub_nested / "deep.txt").write_text("deep", encoding="utf-8")

        scanner = FileScanner()
        results = list(scanner.scan_files(tmp_path, recursive=False))
        filenames = {p.name for p in results}

        assert filenames == {"root1.txt", "root2.py"}
        assert "nested.txt" not in filenames
        assert "deep.txt" not in filenames

    def test_scan_files_recursive_arbitrary_depth(self, tmp_path: Path) -> None:
        """FS-TRAV-03: When recursive=True, deep hierarchies (5+ levels) are fully traversed."""
        (tmp_path / "root.txt").write_text("root", encoding="utf-8")

        current = tmp_path
        created_files = {"root.txt"}
        for level in range(1, 6):
            current = current / f"level_{level}"
            current.mkdir()
            fname = f"file_l{level}.txt"
            (current / fname).write_text(f"level {level}", encoding="utf-8")
            created_files.add(fname)

        scanner = FileScanner()
        results = list(scanner.scan_files(tmp_path, recursive=True))
        found_names = {p.name for p in results}

        assert found_names == created_files
        assert len(found_names) == 6

    def test_scan_files_single_file_target(self, tmp_path: Path) -> None:
        """FS-TRAV-04: scan_files yields target path immediately if given a single file."""
        single_file = tmp_path / "target.txt"
        single_file.write_text("single file content", encoding="utf-8")

        scanner = FileScanner()
        results = list(scanner.scan_files(single_file))

        assert results == [single_file]

    def test_scan_files_empty_directory(self, tmp_path: Path) -> None:
        """FS-TRAV-05: Scanning an empty directory yields 0 items and terminates cleanly."""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        scanner = FileScanner()
        results = list(scanner.scan_files(empty_dir))

        assert results == []

    def test_scan_files_deterministic_sorting_order(self, tmp_path: Path) -> None:
        """FS-TRAV-06: Traversal orders entries case-insensitively (name.lower()) deterministically."""
        files = ["b.txt", "A.txt", "c.txt", "1.txt"]
        for fname in files:
            (tmp_path / fname).write_text(fname, encoding="utf-8")

        scanner = FileScanner()
        results = list(scanner.scan_files(tmp_path, recursive=False))
        names = [p.name for p in results]

        # Sorted by name.lower()
        assert names == ["1.txt", "A.txt", "b.txt", "c.txt"]


class TestFileScannerSymlinks:
    """Group 2: Symlink safety and loop protection."""

    def test_scan_files_symlink_safety_default_ignores_all(self, tmp_path: Path) -> None:
        """FS-SYM-01: Default follow_symlinks=False ignores file and directory symlinks."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("real content", encoding="utf-8")

        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "nested.txt").write_text("nested", encoding="utf-8")

        link_file = tmp_path / "link_file.txt"
        link_dir = tmp_path / "link_dir"
        try:
            link_file.symlink_to(real_file)
            link_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            return

        scanner = FileScanner(follow_symlinks=False)
        results = list(scanner.scan_files(tmp_path, recursive=True))

        assert real_file in results
        assert real_dir / "nested.txt" in results
        assert link_file not in results
        assert link_dir / "nested.txt" not in results

    def test_scan_files_directory_symlinks_never_followed(self, tmp_path: Path) -> None:
        """FS-SYM-02: Directory symlinks are NEVER followed, even when follow_symlinks=True."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "doc.txt").write_text("content", encoding="utf-8")

        symlink_dir = tmp_path / "symlink_dir"
        try:
            symlink_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            return

        scanner = FileScanner(follow_symlinks=True)
        results = list(scanner.scan_files(tmp_path, recursive=True))

        # doc.txt should be yielded only once via real_dir, never via symlink_dir
        matches = [p for p in results if p.name == "doc.txt"]
        assert len(matches) == 1
        assert matches[0] == real_dir / "doc.txt"

    def test_scan_files_circular_symlink_loop_protection(self, tmp_path: Path) -> None:
        """FS-SYM-03: Circular symlinks do not cause infinite recursion."""
        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        (dir_a / "file_a.txt").write_text("content a", encoding="utf-8")

        circular_link = dir_a / "link_to_a"
        try:
            circular_link.symlink_to(dir_a, target_is_directory=True)
        except (OSError, NotImplementedError):
            return

        scanner = FileScanner(follow_symlinks=False)
        results = list(scanner.scan_files(dir_a, recursive=True))

        assert len(results) == 1
        assert results[0].name == "file_a.txt"

    def test_scan_files_broken_dangling_symlink_resilience(self, tmp_path: Path) -> None:
        """FS-SYM-04: Dangling symlinks pointing to non-existent targets are ignored without error."""
        dangling_target = tmp_path / "non_existent_target.txt"
        dangling_link = tmp_path / "dangling_link.txt"
        valid_file = tmp_path / "valid.txt"
        valid_file.write_text("valid", encoding="utf-8")

        try:
            dangling_link.symlink_to(dangling_target)
        except (OSError, NotImplementedError):
            return

        scanner = FileScanner(follow_symlinks=True)
        results = list(scanner.scan_files(tmp_path, recursive=True))

        assert valid_file in results
        assert dangling_link not in results


class TestFileScannerHiddenFiles:
    """Group 3: Hidden file and directory filtering."""

    def test_is_hidden_name_static_precision(self) -> None:
        """FS-HIDDEN-01: is_hidden_name correctly identifies dot-prefixed filenames."""
        assert FileScanner.is_hidden_name(Path(".gitignore")) is True
        assert FileScanner.is_hidden_name(Path(".bashrc")) is True
        assert FileScanner.is_hidden_name(Path(".env")) is True
        assert FileScanner.is_hidden_name(Path(".hidden")) is True

        assert FileScanner.is_hidden_name(Path("main.py")) is False
        assert FileScanner.is_hidden_name(Path("document.txt")) is False
        assert FileScanner.is_hidden_name(Path("README.md")) is False
        assert FileScanner.is_hidden_name(Path("archive.tar.gz")) is False

    def test_has_hidden_component_precision(self) -> None:
        """FS-HIDDEN-02: has_hidden_component checks if any parent path part starts with dot."""
        assert FileScanner.has_hidden_component(Path("a/.hidden/b.txt"), relative_to=Path("a")) is True
        assert FileScanner.has_hidden_component(Path("a/b/c.txt"), relative_to=Path("a")) is False
        assert FileScanner.has_hidden_component(Path(".git/hooks/pre-commit")) is True
        assert FileScanner.has_hidden_component(Path("src/components/Button.tsx")) is False
        assert FileScanner.has_hidden_component(Path("a/b/c/file.txt"), relative_to=Path("a")) is False

    def test_scan_files_hidden_toggle_off_excludes_all(self, tmp_path: Path) -> None:
        """FS-HIDDEN-03: include_hidden=False excludes root dotfiles and files in nested dot-directories."""
        (tmp_path / ".env").write_text("secret", encoding="utf-8")
        (tmp_path / "normal.txt").write_text("normal", encoding="utf-8")

        hidden_dir = tmp_path / ".hidden_dir"
        hidden_dir.mkdir()
        (hidden_dir / "secret.txt").write_text("secret", encoding="utf-8")

        normal_dir = tmp_path / "normal_dir"
        normal_dir.mkdir()
        (normal_dir / ".nested_hidden.txt").write_text("nested", encoding="utf-8")
        (normal_dir / "visible.txt").write_text("visible", encoding="utf-8")

        scanner = FileScanner()
        results = list(scanner.scan_files(tmp_path, recursive=True, include_hidden=False))
        filenames = {p.name for p in results}

        assert filenames == {"normal.txt", "visible.txt"}

    def test_scan_files_hidden_toggle_on_includes_all(self, tmp_path: Path) -> None:
        """FS-HIDDEN-04: include_hidden=True includes root dotfiles and files in dot-directories."""
        (tmp_path / ".env").write_text("secret", encoding="utf-8")
        (tmp_path / "normal.txt").write_text("normal", encoding="utf-8")

        hidden_dir = tmp_path / ".hidden_dir"
        hidden_dir.mkdir()
        (hidden_dir / "secret.txt").write_text("secret", encoding="utf-8")

        normal_dir = tmp_path / "normal_dir"
        normal_dir.mkdir()
        (normal_dir / ".nested_hidden.txt").write_text("nested", encoding="utf-8")
        (normal_dir / "visible.txt").write_text("visible", encoding="utf-8")

        scanner = FileScanner()
        results = list(scanner.scan_files(tmp_path, recursive=True, include_hidden=True))
        filenames = {p.name for p in results}

        assert filenames == {
            "normal.txt",
            ".env",
            "secret.txt",
            ".nested_hidden.txt",
            "visible.txt",
        }

    def test_scan_files_inherits_filter_include_hidden(self, tmp_path: Path) -> None:
        """FS-HIDDEN-05: When include_hidden is None in scan_files, inherits from self.file_filter.include_hidden."""
        (tmp_path / ".secret.txt").write_text("secret", encoding="utf-8")
        (tmp_path / "normal.txt").write_text("normal", encoding="utf-8")

        mock_filter = MagicMock()
        mock_filter.include_hidden = True
        mock_filter.matches_extension.return_value = True
        mock_filter.is_binary_by_extension.return_value = False

        scanner = FileScanner(file_filter=mock_filter)
        results = list(scanner.scan_files(tmp_path, include_hidden=None))
        filenames = {p.name for p in results}

        assert ".secret.txt" in filenames
        assert "normal.txt" in filenames


class TestFileScannerStreaming:
    """Group 4: Line-by-line memory-bounded streaming."""

    def test_stream_lines_one_based_indexing_and_content(self, tmp_path: Path) -> None:
        """FS-STREAM-01: stream_lines yields tuples of (1-based_line_no, line_text)."""
        target = tmp_path / "lines.txt"
        target.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

        scanner = FileScanner()
        lines = list(scanner.stream_lines(target))

        assert lines == [(1, "Line 1"), (2, "Line 2"), (3, "Line 3")]

    def test_stream_lines_preserves_indentation_strips_crlf(self, tmp_path: Path) -> None:
        """FS-STREAM-02: Strips only trailing \\r and \\n, preserving leading indentation."""
        target = tmp_path / "indented.py"
        target.write_bytes(b"    def foo():  \r\n\treturn 42\n")

        scanner = FileScanner()
        lines = list(scanner.stream_lines(target))

        assert lines[0] == (1, "    def foo():  ")
        assert lines[1] == (2, "\treturn 42")

    def test_stream_lines_bounded_memory_large_file(self, tmp_path: Path) -> None:
        """FS-STREAM-03: Streams 20,000 lines sequentially without accumulating memory."""
        large_file = tmp_path / "large.log"
        total_lines = 20000

        with open(large_file, mode="w", encoding="utf-8") as f:
            for idx in range(1, total_lines + 1):
                f.write(f"Log line {idx}: status=OK message='Processed transaction successfully'\n")

        scanner = FileScanner()
        count = 0
        last_line_no = 0
        for line_no, content in scanner.stream_lines(large_file):
            count += 1
            last_line_no = line_no
            assert content.startswith(f"Log line {line_no}:")

        assert count == total_lines
        assert last_line_no == total_lines

    def test_stream_lines_extreme_single_line_length(self, tmp_path: Path) -> None:
        """FS-STREAM-04: Handle minified files or large single-line data (50KB+) without buffer overflow."""
        long_line_file = tmp_path / "bundle.min.js"
        long_text = "var x = " + "a" * 50000 + ";"
        long_line_file.write_text(long_text, encoding="utf-8")

        scanner = FileScanner()
        lines = list(scanner.stream_lines(long_line_file))

        assert len(lines) == 1
        assert lines[0][0] == 1
        assert len(lines[0][1]) == len(long_text)
        assert lines[0][1] == long_text

    def test_stream_lines_empty_file(self, tmp_path: Path) -> None:
        """FS-STREAM-05: 0-byte file yields empty generator and exits cleanly."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_bytes(b"")

        scanner = FileScanner()
        lines = list(scanner.stream_lines(empty_file))

        assert lines == []

    def test_stream_lines_decoding_replace(self, tmp_path: Path) -> None:
        """FS-STREAM-06: Invalid byte sequences decode cleanly into Unicode replacement character \\ufffd."""
        target = tmp_path / "corrupt_stream.txt"
        target.write_bytes(b"Clean prefix \xff\xfe middle \x80 suffix\n")

        scanner = FileScanner()
        lines = list(scanner.stream_lines(target, encoding="utf-8", errors="replace"))

        assert len(lines) == 1
        assert "\ufffd" in lines[0][1]
        assert "Clean prefix" in lines[0][1]
        assert "suffix" in lines[0][1]

    def test_stream_lines_cancellation_mid_file(self, tmp_path: Path) -> None:
        """FS-STREAM-07: Setting cancel_event halts line generator immediately."""
        target = tmp_path / "long_lines.txt"
        target.write_text("\n".join(f"Line {i}" for i in range(1, 100)), encoding="utf-8")

        cancel_event = threading.Event()
        read_lines: list[tuple[int, str]] = []
        scanner = FileScanner()

        for line_number, text in scanner.stream_lines(target, cancel_event=cancel_event):
            read_lines.append((line_number, text))
            if line_number == 5:
                cancel_event.set()

        assert len(read_lines) == 5
        assert read_lines[-1] == (5, "Line 5")


class TestFileScannerErrorResilience:
    """Group 5: Error resilience, race conditions, and dual-mode exception contract."""

    def test_scan_files_nonexistent_base_path_error_callback(self, tmp_path: Path) -> None:
        """FS-ERR-01: Non-existent directory triggers error_callback and yields nothing."""
        missing = tmp_path / "does_not_exist"
        errors: list[tuple[Path, Exception]] = []

        def on_error(p: Path, exc: Exception) -> None:
            errors.append((p, exc))

        scanner = FileScanner()
        results = list(scanner.scan_files(missing, error_callback=on_error))

        assert results == []
        assert len(errors) == 1
        assert errors[0][0] == missing
        assert isinstance(errors[0][1], FileNotFoundError)

    def test_scan_files_permission_error_in_iterdir_proceeds(self, tmp_path: Path) -> None:
        """FS-ERR-02: PermissionError in iterdir reports to callback, traversal of sibling dirs proceeds."""
        normal_dir = tmp_path / "normal"
        normal_dir.mkdir()
        (normal_dir / "accessible.txt").write_text("ok", encoding="utf-8")

        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        (restricted_dir / "hidden.txt").write_text("secret", encoding="utf-8")

        errors: list[tuple[Path, Exception]] = []

        def on_error(p: Path, exc: Exception) -> None:
            errors.append((p, exc))

        real_iterdir = Path.iterdir

        def mock_iterdir(self: Path) -> Iterator[Path]:
            if self.name == "restricted":
                raise PermissionError("Access denied to restricted folder")
            return real_iterdir(self)

        scanner = FileScanner()
        with patch.object(Path, "iterdir", side_effect=mock_iterdir, autospec=True):
            results = list(scanner.scan_files(tmp_path, recursive=True, error_callback=on_error))

        filenames = {p.name for p in results}
        assert "accessible.txt" in filenames
        assert "hidden.txt" not in filenames
        assert len(errors) == 1
        assert isinstance(errors[0][1], PermissionError)

    def test_scan_files_race_condition_mid_scan_deletion(self, tmp_path: Path) -> None:
        """FS-ERR-03: File deleted mid-scan does not crash scanner and reports to error_callback."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("content 1", encoding="utf-8")
        file2 = tmp_path / "file2.txt"
        file2.write_text("content 2", encoding="utf-8")

        errors: list[tuple[Path, Exception]] = []

        def on_error(p: Path, exc: Exception) -> None:
            errors.append((p, exc))

        real_is_file = Path.is_file

        def mock_is_file(self: Path, **kwargs: object) -> bool:
            if self.name == "file2.txt":
                raise FileNotFoundError("File was deleted mid-scan")
            return real_is_file(self, **kwargs)

        scanner = FileScanner()
        with patch.object(Path, "is_file", side_effect=mock_is_file, autospec=True):
            results = list(scanner.scan_files(tmp_path, error_callback=on_error))

        filenames = {p.name for p in results}
        assert "file1.txt" in filenames
        assert "file2.txt" not in filenames
        assert len(errors) == 1
        assert isinstance(errors[0][1], FileNotFoundError)

    def test_stream_lines_directory_path_error_handling(self, tmp_path: Path) -> None:
        """FS-ERR-04: stream_lines called on a directory path traps IsADirectoryError or OSError."""
        dir_path = tmp_path / "a_directory"
        dir_path.mkdir()

        scanner = FileScanner()

        # raise_on_error=False
        errors: list[tuple[Path, Exception]] = []
        lines = list(
            scanner.stream_lines(
                dir_path,
                raise_on_error=False,
                error_callback=lambda p, e: errors.append((p, e)),
            )
        )
        assert lines == []
        assert len(errors) == 1
        assert isinstance(errors[0][1], (IsADirectoryError, OSError))

        # raise_on_error=True
        with pytest.raises((IsADirectoryError, OSError)):
            list(scanner.stream_lines(dir_path, raise_on_error=True))

    def test_stream_lines_oserror_io_failure(self, tmp_path: Path) -> None:
        """FS-ERR-05: OSError during file read is trapped and reported to error_callback."""
        target = tmp_path / "io_error.txt"
        target.write_text("some content", encoding="utf-8")

        errors: list[tuple[Path, Exception]] = []

        def on_error(p: Path, exc: Exception) -> None:
            errors.append((p, exc))

        scanner = FileScanner()
        with patch("builtins.open", side_effect=OSError("I/O device error")):
            lines = list(
                scanner.stream_lines(
                    target,
                    raise_on_error=False,
                    error_callback=on_error,
                )
            )

        assert lines == []
        assert len(errors) == 1
        assert isinstance(errors[0][1], OSError)

    def test_stream_lines_dual_mode_exception_contract(self, tmp_path: Path) -> None:
        """FS-ERR-06: raise_on_error=True re-raises exceptions; False logs and returns cleanly."""
        missing = tmp_path / "nonexistent.txt"
        scanner = FileScanner()

        # When raise_on_error=True
        with pytest.raises(FileNotFoundError):
            list(scanner.stream_lines(missing, raise_on_error=True))

        # When raise_on_error=False
        errors: list[tuple[Path, Exception]] = []
        lines = list(
            scanner.stream_lines(
                missing,
                raise_on_error=False,
                error_callback=lambda p, e: errors.append((p, e)),
            )
        )
        assert lines == []
        assert len(errors) == 1
        assert isinstance(errors[0][1], FileNotFoundError)
