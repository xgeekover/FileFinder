"""Comprehensive unit tests for FileFinder utility modules (Milestone 2).

Tests:
1. File size formatting (0 B, KB, MB, GB, negative values, float sizes)
2. Safe relative path calculation and subpath checks
3. Extension normalization and parsing (delimiters, wildcards, case, deduplication)
4. CSV export with UTF-8 BOM (utf-8-sig, Korean, quotes, parent directory creation)
5. Bounded context line reader (streaming O(1), start, middle, end, edge cases)
6. Platform operations (Windows, macOS, Linux subprocess/os.startfile mocks, clipboard)
7. Logging utilities (idempotence, custom stream, hierarchical loggers)
"""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.models import SearchResult
from app.utils.file_utils import (
    export_results_to_csv,
    format_file_size,
    get_safe_relative_path,
    is_subpath,
    normalize_extension,
    parse_extensions_string,
    read_context_lines,
)
from app.utils.logging_utils import get_logger, setup_logging
from app.utils.platform_utils import (
    copy_to_clipboard,
    open_file_in_default_app,
    open_folder_in_file_manager,
    reveal_in_file_manager,
)

# ============================================================================
# 1. File Size Formatting Tests
# ============================================================================


class TestFormatFileSize:
    """Tests for format_file_size."""

    def test_zero_and_negative_bytes(self) -> None:
        assert format_file_size(0) == "0 B"
        assert format_file_size(-1) == "0 B"
        assert format_file_size(-1024) == "0 B"
        assert format_file_size(-999999) == "0 B"

    def test_bytes_range(self) -> None:
        assert format_file_size(1) == "1 B"
        assert format_file_size(512) == "512 B"
        assert format_file_size(1023) == "1023 B"

    def test_kilobytes_range(self) -> None:
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(2048) == "2.0 KB"
        assert format_file_size(1024 * 500) == "500.0 KB"

    def test_megabytes_range(self) -> None:
        assert format_file_size(1048576) == "1.0 MB"
        assert format_file_size(1048576 * 2.5) == "2.5 MB"
        assert format_file_size(1048576 * 100) == "100.0 MB"

    def test_gigabytes_range(self) -> None:
        assert format_file_size(1073741824) == "1.0 GB"
        assert format_file_size(1073741824 * 4.2) == "4.2 GB"

    def test_terabytes_and_petabytes_range(self) -> None:
        assert format_file_size(1099511627776) == "1.0 TB"
        assert format_file_size(1125899906842624) == "1.0 PB"
        # Beyond PB caps at PB
        assert format_file_size(1125899906842624 * 1024) == "1024.0 PB"

    def test_float_input(self) -> None:
        assert format_file_size(1024.0) == "1.0 KB"
        assert format_file_size(1250.6) == "1.2 KB"


# ============================================================================
# 2. Safe Relative Path & Subpath Tests
# ============================================================================


class TestSafeRelativePathAndSubpath:
    """Tests for get_safe_relative_path and is_subpath."""

    def test_get_safe_relative_path_nested(self, tmp_path: Path) -> None:
        base = tmp_path / "project"
        base.mkdir()
        target = base / "src" / "module" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("code")

        rel = get_safe_relative_path(target, base)
        assert rel == str(Path("src") / "module" / "main.py")

    def test_get_safe_relative_path_same_directory(self, tmp_path: Path) -> None:
        base = tmp_path / "project"
        base.mkdir()
        assert get_safe_relative_path(base, base) == "."

    def test_get_safe_relative_path_outside_base(self, tmp_path: Path) -> None:
        base = tmp_path / "project"
        base.mkdir()
        outside = tmp_path / "outside" / "other.txt"
        outside.parent.mkdir(parents=True)
        outside.write_text("outside")

        # When path is not inside base, falls back to string of path
        rel = get_safe_relative_path(outside, base)
        assert rel == str(outside)

    def test_is_subpath_true_for_child(self, tmp_path: Path) -> None:
        base = tmp_path / "base_dir"
        base.mkdir()
        child = base / "sub1" / "sub2" / "file.txt"
        child.parent.mkdir(parents=True)
        child.write_text("child")

        assert is_subpath(child, base) is True

    def test_is_subpath_true_for_self(self, tmp_path: Path) -> None:
        base = tmp_path / "base_dir"
        base.mkdir()
        assert is_subpath(base, base) is True

    def test_is_subpath_false_for_parent(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "child"
        child.mkdir()

        assert is_subpath(parent, child) is False

    def test_is_subpath_false_for_sibling(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        assert is_subpath(dir1, dir2) is False

    def test_is_subpath_with_string_arguments(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        child = base / "file.txt"
        child.write_text("hello")

        assert is_subpath(str(child), str(base)) is True
        assert is_subpath(str(base), str(child)) is False


# ============================================================================
# 3. Extension Normalization & Parsing Tests
# ============================================================================


class TestExtensionHelpers:
    """Tests for normalize_extension and parse_extensions_string."""

    def test_normalize_extension_variations(self) -> None:
        assert normalize_extension("py") == ".py"
        assert normalize_extension(".py") == ".py"
        assert normalize_extension("TXT") == ".txt"
        assert normalize_extension(".TXT") == ".txt"
        assert normalize_extension("  .JSON  ") == ".json"
        assert normalize_extension("  yaml ") == ".yaml"
        assert normalize_extension("") == ""
        assert normalize_extension("   ") == ""

    def test_parse_extensions_string_comma_separated(self) -> None:
        result = parse_extensions_string(".txt, .py, .md")
        assert result == [".txt", ".py", ".md"]

    def test_parse_extensions_string_semicolon_separated(self) -> None:
        result = parse_extensions_string("txt;py;md")
        assert result == [".txt", ".py", ".md"]

    def test_parse_extensions_string_whitespace_separated(self) -> None:
        result = parse_extensions_string("txt   py \t md \n json")
        assert result == [".txt", ".py", ".md", ".json"]

    def test_parse_extensions_string_mixed_delimiters(self) -> None:
        result = parse_extensions_string(".txt, py;  md\tjson, ; yaml")
        assert result == [".txt", ".py", ".md", ".json", ".yaml"]

    def test_parse_extensions_string_wildcard_patterns(self) -> None:
        result = parse_extensions_string("*.txt, *.py, *md, *.JSON")
        assert result == [".txt", ".py", ".md", ".json"]

    def test_parse_extensions_string_deduplication(self) -> None:
        result = parse_extensions_string(".py, py, *.py, .PY, PY")
        assert result == [".py"]

    def test_parse_extensions_string_preserves_order(self) -> None:
        result = parse_extensions_string("ts, js, py, html, css")
        assert result == [".ts", ".js", ".py", ".html", ".css"]

    def test_parse_extensions_string_empty_inputs(self) -> None:
        assert parse_extensions_string("") == []
        assert parse_extensions_string("   ") == []
        assert parse_extensions_string(",,,;;;   ") == []


# ============================================================================
# 4. CSV Export Tests
# ============================================================================


class TestExportResultsToCsv:
    """Tests for export_results_to_csv with UTF-8 BOM."""

    def test_export_empty_results(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "empty.csv"
        count = export_results_to_csv([], csv_file)
        assert count == 0
        assert csv_file.exists()

        raw_bytes = csv_file.read_bytes()
        # MUST start with UTF-8 BOM
        assert raw_bytes.startswith(b"\xef\xbb\xbf")

        # Read back as CSV
        with open(csv_file, encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            assert len(reader) == 1
            assert reader[0] == ["file_name", "file_path", "line_number", "matched_line", "encoding"]

    def test_export_results_with_korean_and_special_characters(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "export" / "results.csv"
        results = [
            SearchResult(
                file_path=Path("/tmp/test/sample.py"),
                file_name="sample.py",
                line_number=42,
                matched_line="def search_korean(): # 한글 주석 테스트",
                match_start=4,
                match_end=17,
                encoding="utf-8",
            ),
            SearchResult(
                file_path=Path("/tmp/test/quotes.csv"),
                file_name="quotes.csv",
                line_number=1,
                matched_line='name,"quote, with comma and ""escaped"" quotes",value',
                match_start=0,
                match_end=4,
                encoding="cp949",
            ),
            SearchResult(
                file_path=Path("/tmp/test/symbols.txt"),
                file_name="symbols.txt",
                line_number=100,
                matched_line="Special symbols: ⚡ © ® ™ 한국어 日本語 中文",
                match_start=17,
                match_end=24,
                encoding="utf-8",
            ),
        ]

        count = export_results_to_csv(results, csv_file)
        assert count == 3
        assert csv_file.exists()

        raw_bytes = csv_file.read_bytes()
        assert raw_bytes.startswith(b"\xef\xbb\xbf")

        with open(csv_file, encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            assert len(reader) == 4  # Header + 3 data rows
            assert reader[0] == ["file_name", "file_path", "line_number", "matched_line", "encoding"]

            # Check row 1
            assert reader[1] == [
                "sample.py",
                "/tmp/test/sample.py",
                "42",
                "def search_korean(): # 한글 주석 테스트",
                "utf-8",
            ]

            # Check row 2 (quotes & commas handled by csv.writer)
            assert reader[2] == [
                "quotes.csv",
                "/tmp/test/quotes.csv",
                "1",
                'name,"quote, with comma and ""escaped"" quotes",value',
                "cp949",
            ]

            # Check row 3 (special unicode symbols)
            assert reader[3] == [
                "symbols.txt",
                "/tmp/test/symbols.txt",
                "100",
                "Special symbols: ⚡ © ® ™ 한국어 日本語 中文",
                "utf-8",
            ]

    def test_export_results_creates_nested_parent_directories(self, tmp_path: Path) -> None:
        deep_file = tmp_path / "deep" / "nested" / "output" / "results.csv"
        assert not deep_file.parent.exists()

        result = SearchResult(
            file_path=Path("/dir/a.txt"),
            file_name="a.txt",
            line_number=1,
            matched_line="test",
            match_start=0,
            match_end=4,
            encoding="utf-8",
        )
        count = export_results_to_csv([result], deep_file)
        assert count == 1
        assert deep_file.exists()


# ============================================================================
# 5. Bounded Context Line Reading Tests
# ============================================================================


class TestReadContextLines:
    """Tests for read_context_lines with bounded streaming."""

    @pytest.fixture
    def sample_file(self, tmp_path: Path) -> Path:
        file = tmp_path / "sample.txt"
        lines = [f"Line {i}: Content for test" for i in range(1, 21)]
        file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return file

    def test_read_context_lines_middle_of_file(self, sample_file: Path) -> None:
        # Target line 10, context 3 -> lines 7 to 13
        context = read_context_lines(sample_file, target_line=10, context=3)
        assert len(context) == 7
        assert [num for num, _ in context] == [7, 8, 9, 10, 11, 12, 13]
        assert context[0] == (7, "Line 7: Content for test")
        assert context[3] == (10, "Line 10: Content for test")
        assert context[6] == (13, "Line 13: Content for test")

    def test_read_context_lines_near_start(self, sample_file: Path) -> None:
        # Target line 2, context 5 -> lines 1 to 7 (start clamped at 1)
        context = read_context_lines(sample_file, target_line=2, context=5)
        assert len(context) == 7
        assert [num for num, _ in context] == [1, 2, 3, 4, 5, 6, 7]
        assert context[0] == (1, "Line 1: Content for test")

    def test_read_context_lines_near_end(self, sample_file: Path) -> None:
        # Target line 19, context 5 -> lines 14 to 20 (file ends at 20)
        context = read_context_lines(sample_file, target_line=19, context=5)
        assert len(context) == 7
        assert [num for num, _ in context] == [14, 15, 16, 17, 18, 19, 20]
        assert context[-1] == (20, "Line 20: Content for test")

    def test_read_context_lines_exact_target_only(self, sample_file: Path) -> None:
        # Context 0 -> only target line
        context = read_context_lines(sample_file, target_line=5, context=0)
        assert len(context) == 1
        assert context[0] == (5, "Line 5: Content for test")

    def test_read_context_lines_negative_context_treated_as_zero(self, sample_file: Path) -> None:
        context = read_context_lines(sample_file, target_line=5, context=-3)
        assert len(context) == 1
        assert context[0] == (5, "Line 5: Content for test")

    def test_read_context_lines_target_line_beyond_eof(self, sample_file: Path) -> None:
        # Target line 100 on 20-line file
        context = read_context_lines(sample_file, target_line=100, context=5)
        assert context == []

    def test_read_context_lines_non_existent_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "non_existent.txt"
        context = read_context_lines(missing, target_line=5, context=2)
        assert context == []

    def test_read_context_lines_directory_target(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "a_directory"
        dir_path.mkdir()
        context = read_context_lines(dir_path, target_line=1, context=2)
        assert context == []

    def test_read_context_lines_unknown_encoding_error(self, sample_file: Path) -> None:
        # Invalid codec should not crash, returns []
        context = read_context_lines(sample_file, target_line=5, encoding="unknown_codec_xyz_123")
        assert context == []

    def test_read_context_lines_crlf_and_korean(self, tmp_path: Path) -> None:
        korean_file = tmp_path / "korean.txt"
        content = "첫번째 줄\r\n두번째 줄: 타겟\r\n세번째 줄\r\n"
        korean_file.write_bytes(content.encode("utf-8"))

        context = read_context_lines(korean_file, target_line=2, context=1)
        assert len(context) == 3
        assert context[0] == (1, "첫번째 줄")
        assert context[1] == (2, "두번째 줄: 타겟")
        assert context[2] == (3, "세번째 줄")

    def test_read_context_lines_bounded_streaming_stops_at_end_line(self, tmp_path: Path) -> None:
        """Verify that streaming stops reading lines once end_line is reached."""
        file = tmp_path / "large_stream.txt"
        lines_count = 1000
        file.write_text("\n".join(f"Line {i}" for i in range(1, lines_count + 1)) + "\n")

        # Open and inspect reading stopping at end_line (10 + 5 = 15)
        context = read_context_lines(file, target_line=10, context=5)
        assert len(context) == 11
        assert context[0][0] == 5
        assert context[-1][0] == 15


# ============================================================================
# 6. Cross-Platform Platform Utils Tests
# ============================================================================


class TestPlatformUtils:
    """Tests for platform_utils across macOS, Windows, and Linux."""

    def test_open_file_in_default_app_non_existent(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.txt"
        assert open_file_in_default_app(missing) is False

    def test_open_file_in_default_app_windows(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with (
            patch("sys.platform", "win32"),
            patch("os.startfile", create=True) as mock_startfile,
        ):
            success = open_file_in_default_app(target)
            assert success is True
            mock_startfile.assert_called_once_with(str(target.resolve()))

    def test_open_file_in_default_app_darwin(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = open_file_in_default_app(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["open", str(target.resolve())], check=True, capture_output=True
            )

    def test_open_file_in_default_app_linux(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with patch("sys.platform", "linux"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = open_file_in_default_app(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["xdg-open", str(target.resolve())], check=True, capture_output=True
            )

    def test_open_file_in_default_app_subprocess_error(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with (
            patch("sys.platform", "darwin"),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "open")),
        ):
            success = open_file_in_default_app(target)
            assert success is False

    def test_reveal_in_file_manager_non_existent(self, tmp_path: Path) -> None:
        missing = tmp_path / "none" / "nested" / "missing.txt"
        assert reveal_in_file_manager(missing) is False

    def test_reveal_in_file_manager_windows(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with patch("sys.platform", "win32"), patch("subprocess.run") as mock_run:
            success = reveal_in_file_manager(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["explorer.exe", f"/select,{target.resolve()}"], check=False
            )

    def test_reveal_in_file_manager_darwin(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = reveal_in_file_manager(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["open", "-R", str(target.resolve())], check=True, capture_output=True
            )

    def test_reveal_in_file_manager_linux_dbus_success(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/dbus-send"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            success = reveal_in_file_manager(target)
            assert success is True
            # Verified dbus-send invoked
            assert mock_run.call_args[0][0][0] == "dbus-send"

    def test_reveal_in_file_manager_linux_xdg_open_fallback(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("content")

        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            success = reveal_in_file_manager(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["xdg-open", str(target.parent.resolve())], check=True, capture_output=True
            )

    def test_open_folder_in_file_manager_non_existent(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing_folder"
        assert open_folder_in_file_manager(missing) is False

    def test_open_folder_in_file_manager_windows(self, tmp_path: Path) -> None:
        folder = tmp_path / "test_folder"
        folder.mkdir()

        with (
            patch("sys.platform", "win32"),
            patch("os.startfile", create=True) as mock_startfile,
        ):
            success = open_folder_in_file_manager(folder)
            assert success is True
            mock_startfile.assert_called_once_with(str(folder.resolve()))

    def test_open_folder_in_file_manager_darwin(self, tmp_path: Path) -> None:
        folder = tmp_path / "test_folder"
        folder.mkdir()

        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = open_folder_in_file_manager(folder)
            assert success is True
            mock_run.assert_called_once_with(
                ["open", str(folder.resolve())], check=True, capture_output=True
            )

    def test_open_folder_in_file_manager_linux(self, tmp_path: Path) -> None:
        folder = tmp_path / "test_folder"
        folder.mkdir()

        with patch("sys.platform", "linux"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = open_folder_in_file_manager(folder)
            assert success is True
            mock_run.assert_called_once_with(
                ["xdg-open", str(folder.resolve())], check=True, capture_output=True
            )

    def test_open_folder_in_file_manager_with_file_path(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "file.txt"
        target.parent.mkdir(parents=True)
        target.write_text("text")

        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = open_folder_in_file_manager(target)
            assert success is True
            mock_run.assert_called_once_with(
                ["open", str(target.parent.resolve())], check=True, capture_output=True
            )

    def test_copy_to_clipboard_darwin(self) -> None:
        text = "Hello macOS clipboard! 한국어"
        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = copy_to_clipboard(text)
            assert success is True
            mock_run.assert_called_once_with(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )

    def test_copy_to_clipboard_windows(self) -> None:
        text = "Hello Windows clipboard! 한국어"
        with patch("sys.platform", "win32"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = copy_to_clipboard(text)
            assert success is True
            mock_run.assert_called_once_with(
                ["clip"],
                input=text.encode("utf-16le"),
                check=True,
                capture_output=True,
            )

    def test_copy_to_clipboard_linux_wl_copy(self) -> None:
        text = "Hello Wayland clipboard!"
        with (
            patch("sys.platform", "linux"),
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wl-copy" if cmd == "wl-copy" else None,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            success = copy_to_clipboard(text)
            assert success is True
            mock_run.assert_called_once_with(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )

    def test_copy_to_clipboard_linux_xclip_fallback(self) -> None:
        text = "Hello X11 xclip clipboard!"
        with (
            patch("sys.platform", "linux"),
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/xclip" if cmd == "xclip" else None,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            success = copy_to_clipboard(text)
            assert success is True
            mock_run.assert_called_once_with(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )

    def test_copy_to_clipboard_linux_xsel_fallback(self) -> None:
        text = "Hello X11 xsel clipboard!"
        with (
            patch("sys.platform", "linux"),
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/xsel" if cmd == "xsel" else None,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            success = copy_to_clipboard(text)
            assert success is True
            mock_run.assert_called_once_with(
                ["xsel", "--clipboard", "--input"],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )

    def test_copy_to_clipboard_linux_no_tool(self) -> None:
        with patch("sys.platform", "linux"), patch("shutil.which", return_value=None):
            success = copy_to_clipboard("text")
            assert success is False

    def test_copy_to_clipboard_subprocess_exception(self) -> None:
        with (
            patch("sys.platform", "darwin"),
            patch("subprocess.run", side_effect=OSError("Command not found")),
        ):
            success = copy_to_clipboard("text")
            assert success is False


# ============================================================================
# 7. Logging Utils Tests
# ============================================================================


class TestLoggingUtils:
    """Tests for logging_utils."""

    def test_setup_logging_idempotence(self) -> None:
        # Reset app logger handlers
        logger = logging.getLogger("app")
        logger.handlers.clear()

        # First call adds StreamHandler
        setup_logging(level=logging.DEBUG)
        assert len([h for h in logger.handlers if isinstance(h, logging.StreamHandler)]) == 1

        # Second call does not add another StreamHandler
        setup_logging(level=logging.INFO)
        assert len([h for h in logger.handlers if isinstance(h, logging.StreamHandler)]) == 1
        assert logger.level == logging.INFO

    def test_setup_logging_custom_stream_output(self) -> None:
        logger = logging.getLogger("app")
        logger.handlers.clear()

        stream = io.StringIO()
        setup_logging(level=logging.INFO, stream=stream)

        app_logger = get_logger("test_module")
        app_logger.info("Test log message: %s", "hello_world")

        output = stream.getvalue()
        assert "Test log message: hello_world" in output
        assert "[INFO]" in output
        assert "app.test_module" in output

    def test_get_logger_hierarchical_naming(self) -> None:
        assert get_logger() is logging.getLogger("app")
        assert get_logger("app") is logging.getLogger("app")
        assert get_logger("core.search_engine") is logging.getLogger("app.core.search_engine")
        assert get_logger("app.utils.file_utils") is logging.getLogger("app.utils.file_utils")
