"""Filesystem path filtering, binary detection, and extension whitelisting for FileFinder.

Zero PySide6 imports. Strictly typed and self-contained.
"""

from __future__ import annotations

import stat
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar


class FileFilter:
    """Filters filesystem candidate files based on extension, binary content, and hidden status."""

    KNOWN_BINARY_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {
            # Executables and shared libraries
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".dat",
            ".iso",
            ".img",
            ".o",
            ".obj",
            ".wasm",
            ".msi",
            ".deb",
            ".rpm",
            # Compressed archives and packages
            ".zip",
            ".tar",
            ".gz",
            ".7z",
            ".rar",
            ".bz2",
            ".xz",
            ".z",
            ".dmg",
            ".pkg",
            # Image formats (excluding SVG which is XML text)
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".webp",
            ".tiff",
            ".tif",
            ".psd",
            ".ai",
            ".eps",
            ".svgz",
            # Audio and video media
            ".mp3",
            ".mp4",
            ".wav",
            ".avi",
            ".mkv",
            ".mov",
            ".flv",
            ".wmv",
            ".m4a",
            ".aac",
            ".ogg",
            ".oga",
            ".flac",
            ".webm",
            # Proprietary office documents and compiled bytecode
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".pyc",
            ".pyd",
            ".pyo",
            ".class",
            # Databases, persistent stores, debug symbols
            ".db",
            ".sqlite",
            ".sqlite3",
            ".mdb",
            ".pdb",
            # Font binaries
            ".ttf",
            ".otf",
            ".woff",
            ".woff2",
            ".eot",
        }
    )

    DEFAULT_TEXT_EXTENSIONS: ClassVar[tuple[str, ...]] = (
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
        "dockerfile",
    )

    def __init__(
        self,
        extensions: Iterable[str] | None = None,
        include_hidden: bool = False,
    ) -> None:
        """Initialize the file filter.

        Args:
            extensions: Sequence of allowed file extensions or filenames
                        (e.g. ['.txt', 'py', 'Dockerfile']). Case-insensitive,
                        leading dot optional. Empty/None matches all files.
            include_hidden: If False (default), hidden files and folders are excluded.
        """
        self.include_hidden: bool = include_hidden
        self._extension_suffixes: set[str] = set()
        self._exact_filenames: set[str] = set()

        if extensions is not None:
            for ext in extensions:
                cleaned = ext.strip().lower()
                if not cleaned:
                    continue
                if cleaned.startswith("."):
                    self._extension_suffixes.add(cleaned)
                else:
                    self._extension_suffixes.add(f".{cleaned}")
                    self._exact_filenames.add(cleaned)

        self.extensions: frozenset[str] = frozenset(
            self._extension_suffixes | self._exact_filenames
        )

    def is_hidden(self, path: Path, base_path: Path | None = None) -> bool:
        """Check if path or any of its directory components is hidden.

        POSIX: Any component beginning with '.' (excluding '.' and '..').
        Windows: Checks FILE_ATTRIBUTE_HIDDEN and leading dot.

        Args:
            path: Target filesystem path to check.
            base_path: Optional reference base directory. If provided, only
                components relative to base_path are evaluated.
        """
        if base_path is not None:
            try:
                rel_parts = path.relative_to(base_path).parts
                if any(part.startswith(".") and part not in (".", "..") for part in rel_parts):
                    return True
            except ValueError:
                pass

        # Check immediate filename
        if path.name.startswith(".") and path.name not in (".", ".."):
            return True

        # Check relative path parts if not absolute
        if not path.is_absolute() and any(
            part.startswith(".") and part not in (".", "..") for part in path.parts
        ):
            return True

        # Windows attribute query
        if sys.platform == "win32":
            try:
                attrs = path.stat().st_file_attributes
                if attrs & stat.FILE_ATTRIBUTE_HIDDEN:
                    return True
            except (AttributeError, OSError, ValueError):
                pass

        return False

    def matches_extension(self, path: Path) -> bool:
        """Check if path matches user-specified extension whitelist.

        If no extensions were configured, all files match.
        """
        if not self._extension_suffixes and not self._exact_filenames:
            return True

        filename = path.name.lower()
        if filename in self._exact_filenames:
            return True

        suffix = path.suffix.lower()
        if suffix in self._extension_suffixes:
            return True

        # Check compound extensions (e.g. .tar.gz)
        return any(filename.endswith(ext) for ext in self._extension_suffixes)

    def is_binary_by_extension(self, path: Path) -> bool:
        """Fast-path check: returns True if path has a known binary suffix."""
        return path.suffix.lower() in self.KNOWN_BINARY_EXTENSIONS

    def is_binary_content(
        self,
        path: Path,
        sample_size: int = 8192,
        raise_on_error: bool = False,
    ) -> bool:
        """Inspect the first sample_size bytes for null bytes (\\x00).

        Files with UTF-16 or UTF-32 BOMs are exempted (treated as encoded text).
        """
        try:
            with open(path, mode="rb") as f:
                chunk = f.read(sample_size)
        except (PermissionError, FileNotFoundError, IsADirectoryError, OSError):
            if raise_on_error:
                raise
            return False

        if not chunk:
            return False

        # UTF-16 and UTF-32 BOM signatures legitimately contain null bytes
        if chunk.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")):
            return False

        return b"\x00" in chunk

    def is_binary(
        self,
        path: Path,
        sample_size: int = 8192,
        check_content: bool = True,
    ) -> bool:
        """Determine if a file is binary by extension or content inspection."""
        if self.is_binary_by_extension(path):
            return True
        if check_content:
            return self.is_binary_content(path, sample_size=sample_size)
        return False

    def should_skip(self, path: Path, check_content: bool = True) -> bool:
        """Determine if a candidate path should be skipped during search.

        Returns True if:
        - Path is hidden and include_hidden is False
        - Extension does not match whitelist
        - Extension is a known binary type
        - File content contains null bytes (when check_content is True)
        """
        if not self.include_hidden and self.is_hidden(path):
            return True
        if not self.matches_extension(path):
            return True
        if self.is_binary_by_extension(path):
            return True
        return bool(check_content and self.is_binary_content(path, raise_on_error=True))

    def should_scan(self, path: Path, check_content: bool = True) -> bool:
        """Convenience inverse of should_skip."""
        return not self.should_skip(path, check_content=check_content)
