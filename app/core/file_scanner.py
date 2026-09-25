"""Filesystem traversal and line-by-line file streaming module for FileFinder.

Provides high-performance directory scanning with symlink safety, hidden file
filtering, race-condition resilience, and memory-bounded streaming.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.core.file_filter import FileFilter

logger = logging.getLogger("app.core.file_scanner")

ErrorCallback = Callable[[Path, Exception], None]


@runtime_checkable
class FileFilterProtocol(Protocol):
    """Structural interface expected from a FileFilter collaborator."""

    include_hidden: bool

    def is_hidden(self, path: Path) -> bool: ...

    def matches_extension(self, path: Path) -> bool: ...

    def is_binary_by_extension(self, path: Path) -> bool: ...

    def should_scan(self, path: Path) -> bool: ...


class FileScanner:
    """High-performance, symlink-safe filesystem scanner and line-by-line streamer.

    Features:
    - Recursive and non-recursive directory traversal using pathlib.Path.
    - Full symlink safety: ignores symlinks by default (follow_symlinks=False),
      never follows directory symlinks, and detects circular directory graphs.
    - Hidden file and directory filtering (names starting with dot '.').
    - Non-aborting exception trapping for PermissionError, FileNotFoundError,
      IsADirectoryError, OSError, and race conditions (deleted files mid-scan).
    - O(1) memory line-by-line streaming generator with decoding error resilience.
    - Cooperative cancellation via threading.Event.
    - Zero PySide6 dependencies.
    """

    def __init__(
        self,
        file_filter: FileFilter | FileFilterProtocol | None = None,
        follow_symlinks: bool = False,
    ) -> None:
        """Initialize FileScanner.

        Args:
            file_filter: Optional FileFilter instance to evaluate candidate files.
            follow_symlinks: Whether to follow file symlinks. Directory symlinks
                are NEVER followed regardless of this setting.
        """
        self.file_filter = file_filter
        self.follow_symlinks = follow_symlinks

    @staticmethod
    def is_hidden_name(path: Path) -> bool:
        """Check if the path name indicates a hidden file or directory (starts with '.')."""
        return path.name.startswith(".")

    @staticmethod
    def has_hidden_component(path: Path, relative_to: Path | None = None) -> bool:
        """Check if any component of path (optionally relative to relative_to) starts with '.'."""
        try:
            target = path.relative_to(relative_to) if relative_to else path
        except ValueError:
            target = path
        return any(part.startswith(".") for part in target.parts)

    def scan_files(
        self,
        base_path: Path,
        recursive: bool = True,
        include_hidden: bool | None = None,
        extensions: Sequence[str] | None = None,
        cancel_event: threading.Event | None = None,
        error_callback: ErrorCallback | None = None,
    ) -> Iterator[Path]:
        """Scan base_path and yield candidate file paths matching all filter criteria.

        Args:
            base_path: The directory (or single file) to scan.
            recursive: If True, recursively traverse subdirectories.
            include_hidden: Override for hidden file inclusion. If None, derives from
                self.file_filter.include_hidden if available, else False.
            extensions: Optional list of extensions to filter (e.g. ['.py', '.txt']).
            cancel_event: threading.Event for cooperative cancellation.
            error_callback: Optional callback invoked as (path, exception) on errors.

        Yields:
            Path objects representing valid candidate files to search.
        """
        # Resolve effective hidden flag
        effective_include_hidden: bool
        if include_hidden is not None:
            effective_include_hidden = include_hidden
        elif self.file_filter is not None and hasattr(self.file_filter, "include_hidden"):
            effective_include_hidden = bool(self.file_filter.include_hidden)
        else:
            effective_include_hidden = False

        # Normalize extension whitelist if provided
        normalized_exts: set[str] | None = None
        exact_names: set[str] | None = None
        if extensions is not None:
            normalized_exts = {
                ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                for ext in extensions
                if ext.strip()
            }
            exact_names = {
                ext.strip().lower()
                for ext in extensions
                if ext.strip() and not ext.strip().startswith(".")
            }

        # Check early cancellation
        if cancel_event is not None and cancel_event.is_set():
            return

        # Check if base_path exists and handle single file case
        try:
            if not self.follow_symlinks and base_path.is_symlink():
                return

            if not base_path.exists():
                if error_callback is not None:
                    error_callback(base_path, FileNotFoundError(f"Path does not exist: {base_path}"))
                return

            if base_path.is_file():
                if self._should_yield_file(
                    base_path,
                    base_path=base_path.parent,
                    include_hidden=effective_include_hidden,
                    extensions=normalized_exts,
                    exact_names=exact_names,
                ):
                    yield base_path
                return

            if not base_path.is_dir():
                return
        except (PermissionError, FileNotFoundError, OSError) as exc:
            if error_callback is not None:
                error_callback(base_path, exc)
            return

        # Traversal setup: Iterative stack-based directory traversal (LIFO)
        stack: deque[Path] = deque([base_path])

        # Track visited directory real paths to prevent circular symlinks/hardlinks
        visited_dirs: set[Path] = set()
        try:
            visited_dirs.add(base_path.resolve())
        except (PermissionError, FileNotFoundError, OSError):
            visited_dirs.add(base_path)

        while stack:
            if cancel_event is not None and cancel_event.is_set():
                break

            current_dir = stack.pop()

            # Retrieve directory entries with full exception protection
            try:
                entries = list(current_dir.iterdir())
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError) as exc:
                if error_callback is not None:
                    error_callback(current_dir, exc)
                continue

            # Sort entries for deterministic, reproducible traversal order
            entries.sort(key=lambda p: p.name.lower())

            for entry in entries:
                if cancel_event is not None and cancel_event.is_set():
                    break

                try:
                    # 1. Symlink check
                    is_sym = entry.is_symlink()
                    if is_sym:
                        if not self.follow_symlinks:
                            continue
                        # Even if follow_symlinks=True, NEVER follow directory symlinks
                        if entry.is_dir():
                            continue

                    # 2. Hidden check (names starting with '.')
                    is_hidden = self.is_hidden_name(entry)
                    if is_hidden and not effective_include_hidden:
                        continue

                    # 3. Directory handling
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            try:
                                real_dir = entry.resolve()
                            except (PermissionError, FileNotFoundError, OSError):
                                real_dir = entry

                            if real_dir not in visited_dirs:
                                visited_dirs.add(real_dir)
                                stack.append(entry)
                        continue

                    # 4. Regular file handling
                    if entry.is_file(
                        follow_symlinks=self.follow_symlinks
                    ) and self._should_yield_file(
                        entry,
                        base_path=base_path,
                        include_hidden=effective_include_hidden,
                        extensions=normalized_exts,
                        exact_names=exact_names,
                    ):
                        yield entry

                except (PermissionError, FileNotFoundError, OSError) as exc:
                    # Race condition: file deleted or permission revoked mid-scan
                    if error_callback is not None:
                        error_callback(entry, exc)
                    continue

    def _should_yield_file(
        self,
        path: Path,
        base_path: Path,
        include_hidden: bool,
        extensions: set[str] | None,
        exact_names: set[str] | None = None,
    ) -> bool:
        """Internal helper to test if a file meets extension and hidden criteria."""
        # Check hidden status
        if not include_hidden:
            if self.is_hidden_name(path):
                return False
            if self.has_hidden_component(path, relative_to=base_path):
                return False

        # If file_filter provides specialized extension/binary filtering
        if self.file_filter is not None:
            if hasattr(
                self.file_filter, "matches_extension"
            ) and not self.file_filter.matches_extension(path):
                return False
            if hasattr(
                self.file_filter, "is_binary_by_extension"
            ) and self.file_filter.is_binary_by_extension(path):
                return False
        elif extensions is not None and len(extensions) > 0:
            filename_lower = path.name.lower()
            ext_matched = path.suffix.lower() in extensions
            name_matched = bool(exact_names and filename_lower in exact_names)
            if not (ext_matched or name_matched):
                return False

        return True

    def stream_lines(
        self,
        path: Path,
        encoding: str = "utf-8",
        errors: str = "replace",
        cancel_event: threading.Event | None = None,
        error_callback: ErrorCallback | None = None,
        raise_on_error: bool = False,
    ) -> Iterator[tuple[int, str]]:
        """Stream lines from a file sequentially without loading the full file into memory.

        Guarantees O(1) memory footprint relative to file size, bounded only by the
        longest line in the file.

        Args:
            path: Target file path to stream.
            encoding: Text encoding codec name (e.g. 'utf-8', 'cp949', 'latin-1').
            errors: Decoding error handling strategy (default 'replace' for resilience).
            cancel_event: threading.Event for cooperative cancellation.
            error_callback: Optional callback invoked as (path, exception) on errors.
            raise_on_error: If True, re-raises caught exceptions. If False (default),
                reports to error_callback and exits generator cleanly.

        Yields:
            Tuples of (line_number, line_text) where line_number is 1-indexed and
            line_text has trailing '\\r' and '\\n' stripped.
        """
        try:
            with open(path, encoding=encoding, errors=errors, newline=None) as f:
                for line_number, raw_line in enumerate(f, start=1):
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    yield line_number, raw_line.rstrip("\r\n")
        except (
            PermissionError,
            FileNotFoundError,
            IsADirectoryError,
            OSError,
            UnicodeDecodeError,
            LookupError,
        ) as exc:
            if error_callback is not None:
                error_callback(path, exc)
            if raise_on_error:
                raise
            return
