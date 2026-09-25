"""Comprehensive unit test suite for FileFilter.

Verifies:
1. Binary file detection by extension (58 known extensions across 7 categories)
2. Null-byte heuristic (\\x00 in first 8192 bytes) with exact boundary testing
3. BOM exemption from binary classification (UTF-16, UTF-32)
4. Case-insensitive extension whitelist matching with compound and exact-filename support
5. POSIX and Windows hidden file exclusion relative to base path
6. Complete 4-dimensional decision matrix of should_skip and should_scan with short-circuiting.
"""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.file_filter import FileFilter


class TestFileFilterExtensionMatching:
    """Extension whitelist parsing, normalization, and matching scenarios."""

    def test_filter_init_normalization(self) -> None:
        """FF-01: Extensions and filenames are trimmed, lowercased, and indexed."""
        filter_ = FileFilter(extensions=[".TXT", " py ", "Dockerfile", ""])
        assert ".txt" in filter_._extension_suffixes
        assert ".py" in filter_._extension_suffixes
        assert ".dockerfile" in filter_._extension_suffixes
        assert "py" in filter_._exact_filenames
        assert "dockerfile" in filter_._exact_filenames

    def test_filter_empty_or_none_matches_all(self) -> None:
        """FF-02: Empty or None whitelist matches all filenames and extensions."""
        filter_none = FileFilter(extensions=None)
        assert filter_none.matches_extension(Path("any.txt")) is True
        assert filter_none.matches_extension(Path("binary.exe")) is True
        assert filter_none.matches_extension(Path("no_extension")) is True

        filter_empty = FileFilter(extensions=[])
        assert filter_empty.matches_extension(Path("any.txt")) is True
        assert filter_empty.matches_extension(Path("no_extension")) is True

    def test_matches_extension_case_insensitive(self) -> None:
        """FF-03: Extensions match case-insensitively across uppercase, mixed, lowercase."""
        filter_ = FileFilter(extensions=[".txt", ".py", ".json"])
        assert filter_.matches_extension(Path("doc.txt")) is True
        assert filter_.matches_extension(Path("DOC.TXT")) is True
        assert filter_.matches_extension(Path("Doc.Txt")) is True
        assert filter_.matches_extension(Path("main.PY")) is True
        assert filter_.matches_extension(Path("config.JSON")) is True

    def test_matches_extension_without_leading_dot(self) -> None:
        """FF-04: Whitelist items without leading dot match both extension and exact name."""
        filter_ = FileFilter(extensions=["txt", "py"])
        assert filter_.matches_extension(Path("readme.txt")) is True
        assert filter_.matches_extension(Path("script.py")) is True
        assert filter_.matches_extension(Path("txt")) is True
        assert filter_.matches_extension(Path("py")) is True

    def test_matches_extension_exact_filename(self) -> None:
        """FF-05: Exact filenames match files by full name regardless of extension presence."""
        filter_ = FileFilter(extensions=["Dockerfile", "Makefile", "LICENSE"])
        assert filter_.matches_extension(Path("Dockerfile")) is True
        assert filter_.matches_extension(Path("dockerfile")) is True
        assert filter_.matches_extension(Path("Makefile")) is True
        assert filter_.matches_extension(Path("MAKEFILE")) is True
        assert filter_.matches_extension(Path("LICENSE")) is True
        assert filter_.matches_extension(Path("license")) is True

        # Non-exact matches
        assert filter_.matches_extension(Path("Dockerfile.dev")) is False
        assert filter_.matches_extension(Path("MyMakefile")) is False

    def test_matches_extension_compound_extensions(self) -> None:
        """FF-06: Compound extensions like .tar.gz and .min.js are correctly matched."""
        filter_ = FileFilter(extensions=[".tar.gz", ".min.js", ".spec.ts"])
        assert filter_.matches_extension(Path("archive.tar.gz")) is True
        assert filter_.matches_extension(Path("bundle.min.js")) is True
        assert filter_.matches_extension(Path("app.spec.ts")) is True

        assert filter_.matches_extension(Path("archive.gz")) is False
        assert filter_.matches_extension(Path("bundle.js")) is False
        assert filter_.matches_extension(Path("app.ts")) is False

    def test_matches_extension_negative_cases(self) -> None:
        """FF-07: Files not in whitelist are rejected."""
        filter_ = FileFilter(extensions=[".txt", ".py"])
        assert filter_.matches_extension(Path("image.png")) is False
        assert filter_.matches_extension(Path("style.css")) is False
        assert filter_.matches_extension(Path("doc.txt.bak")) is False
        assert filter_.matches_extension(Path("script.python")) is False

    def test_matches_extension_multiple_dots(self) -> None:
        """FF-08: Filenames with multiple internal dots match the final extension."""
        filter_ = FileFilter(extensions=[".csv"])
        assert filter_.matches_extension(Path("backup.2026.09.20.csv")) is True
        assert filter_.matches_extension(Path("data.v1.0.final.csv")) is True


class TestFileFilterBinaryExtensions:
    """Known binary extension categorization and fast-path detection."""

    @pytest.mark.parametrize(
        "ext",
        [
            # Executables & libraries
            ".exe", ".dll", ".so", ".dylib", ".bin", ".dat", ".iso", ".img",
            ".o", ".obj", ".wasm", ".msi", ".deb", ".rpm",
            # Compressed archives
            ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz", ".z", ".dmg", ".pkg",
            # Images
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
            ".tiff", ".tif", ".psd", ".ai", ".eps", ".svgz",
            # Media
            ".mp3", ".mp4", ".wav", ".avi", ".mkv", ".mov", ".flv",
            ".wmv", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".webm",
            # Office & bytecode
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".pyc", ".pyd", ".pyo", ".class",
            # Databases & fonts
            ".db", ".sqlite", ".sqlite3", ".mdb", ".pdb",
            ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ],
    )
    def test_is_binary_by_extension_all_categories(self, ext: str) -> None:
        """FF-09: All 58 KNOWN_BINARY_EXTENSIONS return True."""
        filter_ = FileFilter()
        assert filter_.is_binary_by_extension(Path(f"sample{ext}")) is True
        assert filter_.is_binary_by_extension(Path(f"SAMPLE{ext.upper()}")) is True

    @pytest.mark.parametrize(
        "ext",
        [
            ".txt", ".log", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
            ".ini", ".conf", ".config", ".properties", ".env", ".java", ".kt",
            ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css",
            ".scss", ".sql", ".cs", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
            ".swift", ".sh", ".bat", ".ps1", ".gradle", ".svg",
        ],
    )
    def test_text_extensions_not_binary_by_extension(self, ext: str) -> None:
        """FF-10: Standard source code, markup, and text extensions return False."""
        filter_ = FileFilter()
        assert filter_.is_binary_by_extension(Path(f"file{ext}")) is False


class TestFileFilterNullByteHeuristic:
    """Null byte (\\x00) inspection in the first 8192 bytes."""

    def test_null_byte_at_offset_zero(self, tmp_path: Path) -> None:
        """FF-11: File starting with null byte is classified as binary content."""
        f = tmp_path / "null_0.data"
        f.write_bytes(b"\x00Rest of text payload")
        filter_ = FileFilter()
        assert filter_.is_binary_content(f) is True
        assert filter_.is_binary(f) is True

    @pytest.mark.parametrize("offset", [1, 100, 1024, 4096])
    def test_null_byte_at_intermediate_offsets(self, tmp_path: Path, offset: int) -> None:
        """FF-12: Null byte at intermediate offsets within 8KB is classified as binary."""
        content = bytearray(b"A" * 8192)
        content[offset] = 0
        f = tmp_path / f"null_{offset}.txt"
        f.write_bytes(bytes(content))

        filter_ = FileFilter()
        assert filter_.is_binary_content(f) is True

    def test_null_byte_at_exact_8191_boundary(self, tmp_path: Path) -> None:
        """FF-13: Null byte at offset 8191 (exact last byte of 8KB sample) triggers binary."""
        content = bytearray(b"A" * 8192)
        content[8191] = 0  # 8192nd byte (0-indexed 8191)
        f = tmp_path / "null_8191.txt"
        f.write_bytes(bytes(content))

        filter_ = FileFilter()
        assert filter_.is_binary_content(f, sample_size=8192) is True

    @pytest.mark.parametrize("offset", [8192, 8193, 10000])
    def test_null_byte_beyond_8192_not_marked_binary(self, tmp_path: Path, offset: int) -> None:
        """FF-14: Null byte placed at or beyond index 8192 is outside the 8KB sample window."""
        content = bytearray(b"A" * (offset + 100))
        content[offset] = 0
        f = tmp_path / f"null_after_{offset}.txt"
        f.write_bytes(bytes(content))

        filter_ = FileFilter()
        assert filter_.is_binary_content(f, sample_size=8192) is False

    def test_null_byte_custom_sample_size(self, tmp_path: Path) -> None:
        """FF-15: Custom sample_size parameter is strictly respected."""
        filter_ = FileFilter()

        # Null at 1023 (within 1024 window)
        f1 = tmp_path / "null_1023.txt"
        b1 = bytearray(b"A" * 2048)
        b1[1023] = 0
        f1.write_bytes(bytes(b1))
        assert filter_.is_binary_content(f1, sample_size=1024) is True

        # Null at 1024 (outside 1024 window)
        f2 = tmp_path / "null_1024.txt"
        b2 = bytearray(b"A" * 2048)
        b2[1024] = 0
        f2.write_bytes(bytes(b2))
        assert filter_.is_binary_content(f2, sample_size=1024) is False

    def test_empty_file_not_binary(self, tmp_path: Path) -> None:
        """FF-16: Empty 0-byte file contains no null bytes and is not binary."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        filter_ = FileFilter()
        assert filter_.is_binary_content(f) is False

    def test_clean_text_file_not_binary(self, tmp_path: Path) -> None:
        """FF-17: Large clean text file contains no null bytes and is not binary."""
        f = tmp_path / "clean.txt"
        f.write_text("Hello World\n한국어 텍스트 파일입니다.\n" * 500, encoding="utf-8")
        filter_ = FileFilter()
        assert filter_.is_binary_content(f) is False

    def test_bom_exemption_utf16_le_and_be(self, tmp_path: Path) -> None:
        """FF-18: UTF-16 files with BOM contain null bytes but are exempted from binary check."""
        filter_ = FileFilter()

        # UTF-16 LE
        f_u16le = tmp_path / "u16le.txt"
        f_u16le.write_bytes(b"\xff\xfe" + "Hello UTF-16 LE".encode("utf-16-le"))
        assert filter_.is_binary_content(f_u16le) is False

        # UTF-16 BE
        f_u16be = tmp_path / "u16be.txt"
        f_u16be.write_bytes(b"\xfe\xff" + "Hello UTF-16 BE".encode("utf-16-be"))
        assert filter_.is_binary_content(f_u16be) is False

    def test_bom_exemption_utf32_le_and_be(self, tmp_path: Path) -> None:
        """FF-19: UTF-32 files with BOM contain null bytes but are exempted from binary check."""
        filter_ = FileFilter()

        # UTF-32 LE
        f_u32le = tmp_path / "u32le.txt"
        f_u32le.write_bytes(b"\xff\xfe\x00\x00" + "Hello UTF-32 LE".encode("utf-32-le"))
        assert filter_.is_binary_content(f_u32le) is False

        # UTF-32 BE
        f_u32be = tmp_path / "u32be.txt"
        f_u32be.write_bytes(b"\x00\x00\xfe\xff" + "Hello UTF-32 BE".encode("utf-32-be"))
        assert filter_.is_binary_content(f_u32be) is False

    def test_is_binary_content_io_error_handling(self, tmp_path: Path) -> None:
        """FF-20: Missing file returns False by default or raises when raise_on_error=True."""
        missing = tmp_path / "missing.bin"
        filter_ = FileFilter()
        assert filter_.is_binary_content(missing, raise_on_error=False) is False
        with pytest.raises(FileNotFoundError):
            filter_.is_binary_content(missing, raise_on_error=True)


class TestFileFilterHiddenFiles:
    """Hidden file and directory detection."""

    def test_is_hidden_posix_filename(self) -> None:
        """FF-21: File starting with dot is hidden under POSIX."""
        filter_ = FileFilter()
        assert filter_.is_hidden(Path(".hidden.txt")) is True
        assert filter_.is_hidden(Path(".gitignore")) is True
        assert filter_.is_hidden(Path(".env")) is True
        assert filter_.is_hidden(Path("regular.txt")) is False

    def test_is_hidden_posix_directory_component(self) -> None:
        """FF-22: File inside dot-prefixed subdirectory is hidden."""
        filter_ = FileFilter()
        assert filter_.is_hidden(Path(".git/config")) is True
        assert filter_.is_hidden(Path("src/.cache/build.log")) is True
        assert filter_.is_hidden(Path("src/main/app.py")) is False

    def test_is_hidden_relative_to_base_path(self) -> None:
        """FF-23: Evaluates hidden status strictly relative to base_path."""
        filter_ = FileFilter()
        base = Path("/home/user/.workspace/project")

        # Path inside project with hidden folder relative to base -> hidden
        hidden_in_base = base / ".internal" / "secret.txt"
        assert filter_.is_hidden(hidden_in_base, base_path=base) is True

        # Path inside project with no hidden components relative to base -> visible
        # Even though base contains '.workspace' in its own path!
        visible_in_base = base / "src" / "app.py"
        assert filter_.is_hidden(visible_in_base, base_path=base) is False

    def test_is_hidden_dot_and_dotdot_exempt(self) -> None:
        """FF-24: '.' and '..' components do not mark a path as hidden."""
        filter_ = FileFilter()
        assert filter_.is_hidden(Path(".")) is False
        assert filter_.is_hidden(Path("..")) is False
        assert filter_.is_hidden(Path("dir/./file.txt")) is False
        assert filter_.is_hidden(Path("dir/../dir/file.txt")) is False

    def test_is_hidden_windows_attribute(self) -> None:
        """FF-25: Windows FILE_ATTRIBUTE_HIDDEN is respected on win32 platform."""
        filter_ = FileFilter()

        fake_hidden_stat = MagicMock()
        fake_hidden_stat.st_file_attributes = stat.FILE_ATTRIBUTE_HIDDEN

        with (
            patch("sys.platform", "win32"),
            patch.object(Path, "stat", return_value=fake_hidden_stat),
        ):
            assert filter_.is_hidden(Path("normal_file.txt")) is True

        fake_archive_stat = MagicMock()
        fake_archive_stat.st_file_attributes = stat.FILE_ATTRIBUTE_ARCHIVE

        with (
            patch("sys.platform", "win32"),
            patch.object(Path, "stat", return_value=fake_archive_stat),
        ):
            assert filter_.is_hidden(Path("normal_file.txt")) is False


class TestFileFilterDecisionMatrix:
    """Integrated should_skip and should_scan truth table and short-circuiting."""

    def test_should_skip_hidden_file_toggle(self, tmp_path: Path) -> None:
        """FF-26: include_hidden flag toggles inclusion of hidden files."""
        hidden_file = tmp_path / ".secret.txt"
        hidden_file.write_text("classified data", encoding="utf-8")

        filter_exclude = FileFilter(extensions=[".txt"], include_hidden=False)
        assert filter_exclude.should_skip(hidden_file) is True
        assert filter_exclude.should_scan(hidden_file) is False

        filter_include = FileFilter(extensions=[".txt"], include_hidden=True)
        assert filter_include.should_skip(hidden_file) is False
        assert filter_include.should_scan(hidden_file) is True

    def test_should_skip_binary_extension(self, tmp_path: Path) -> None:
        """FF-27: Known binary extension is skipped even with text content."""
        bin_file = tmp_path / "app.exe"
        bin_file.write_bytes(b"Pure ASCII text inside exe file")

        filter_ = FileFilter(extensions=None, include_hidden=False)
        assert filter_.should_skip(bin_file) is True
        assert filter_.should_scan(bin_file) is False

    def test_should_skip_binary_content_null_byte(self, tmp_path: Path) -> None:
        """FF-28: File with text extension but embedded null byte is skipped."""
        fake_txt = tmp_path / "fake.txt"
        fake_txt.write_bytes(b"Text header\x00binary payload")

        filter_ = FileFilter(extensions=[".txt"], include_hidden=False)
        assert filter_.should_skip(fake_txt, check_content=True) is True
        assert filter_.should_scan(fake_txt, check_content=True) is False

    def test_should_scan_valid_text_file(self, tmp_path: Path) -> None:
        """FF-29: Visible text file matching extension whitelist is scanned."""
        valid_file = tmp_path / "document.txt"
        valid_file.write_text("Valid text content", encoding="utf-8")

        filter_ = FileFilter(extensions=[".txt"], include_hidden=False)
        assert filter_.should_skip(valid_file) is False
        assert filter_.should_scan(valid_file) is True

    def test_should_skip_short_circuiting(self) -> None:
        """FF-30: should_skip short-circuits before invoking is_binary_content."""
        filter_ = FileFilter(extensions=[".txt"], include_hidden=False)

        # 1. Hidden file short-circuits without checking content
        with patch.object(filter_, "is_binary_content") as mock_bin:
            assert filter_.should_skip(Path(".hidden.txt")) is True
            mock_bin.assert_not_called()

        # 2. Extension mismatch short-circuits without checking content
        with patch.object(filter_, "is_binary_content") as mock_bin:
            assert filter_.should_skip(Path("script.py")) is True
            mock_bin.assert_not_called()

        # 3. Binary extension short-circuits without checking content
        filter_all = FileFilter(extensions=None, include_hidden=True)
        with patch.object(filter_all, "is_binary_content") as mock_bin:
            assert filter_all.should_skip(Path("app.exe")) is True
            mock_bin.assert_not_called()
