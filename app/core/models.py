"""Core data models and dataclasses for FileFinder.

Defines SearchResult, SearchOptions, and ScanStatistics.
Zero external dependencies outside the Python standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Represents an individual text match found within a scanned file."""

    file_path: Path
    file_name: str
    line_number: int
    matched_line: str
    match_start: int
    match_end: int
    encoding: str

    def __post_init__(self) -> None:
        """Ensure file_name is populated from file_path if not explicitly provided."""
        if not self.file_name and self.file_path:
            object.__setattr__(self, "file_name", self.file_path.name)


@dataclass(slots=True)
class SearchOptions:
    """Configuration parameters specifying search scope, patterns, and filters."""

    path: Path
    query: str
    is_regex: bool = False
    case_sensitive: bool = False
    recursive: bool = True
    include_hidden: bool = False
    extensions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScanStatistics:
    """Aggregated telemetry and execution metrics for a search operation."""

    total_files: int = 0
    scanned_files: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    cancelled: bool = False

    def add_error(self, file_path: Path, message: str) -> None:
        """Record an error encounter for a specific filesystem path."""
        self.error_count += 1
        self.errors.append((file_path, message))

    def record_success(self) -> None:
        """Increment count of successfully scanned files."""
        self.success_count += 1
