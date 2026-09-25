"""File and path utility functions for FileFinder.

Provides formatting, normalization, CSV export, preview extraction,
and path manipulation helpers. Strictly decoupled from PySide6 GUI framework.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.models import SearchResult


def format_file_size(size_in_bytes: int | float) -> str:
    """Format byte integer into a human-readable size string.

    Examples:
        0 -> "0 B"
        512 -> "512 B"
        1024 -> "1.0 KB"
        1536 -> "1.5 KB"
        1048576 -> "1.0 MB"
        1073741824 -> "1.0 GB"
        1099511627776 -> "1.0 TB"

    Args:
        size_in_bytes: File size in bytes.

    Returns:
        Formatted human-readable size string.
    """
    if size_in_bytes < 0:
        return "0 B"

    size = float(size_in_bytes)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0

    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_idx]}"


def get_safe_relative_path(path: Path | str, base: Path | str) -> str:
    """Compute relative path from base to path safely.

    If path is not inside base (or on Windows across different drive letters),
    safely falls back to returning the string representation of path.

    Args:
        path: Target filesystem path.
        base: Reference base directory path.

    Returns:
        Relative path string if possible, or absolute path string.
    """
    try:
        p = Path(path).resolve()
        b = Path(base).resolve()
        return str(p.relative_to(b))
    except (ValueError, OSError):
        return str(Path(path))


def is_subpath(path: Path | str, base: Path | str) -> bool:
    """Determine whether path is located inside base directory hierarchy.

    Args:
        path: Target filesystem path.
        base: Potential ancestor directory.

    Returns:
        True if path is a descendant of base, False otherwise.
    """
    try:
        p = Path(path).resolve()
        b = Path(base).resolve()
        return p == b or b in p.parents
    except (ValueError, OSError):
        return False


def normalize_extension(ext: str) -> str:
    """Normalize a single file extension string.

    Strips whitespace, converts to lowercase, and guarantees a leading dot.

    Examples:
        "py" -> ".py"
        ".TXT" -> ".txt"
        " .json " -> ".json"
        "" -> ""

    Args:
        ext: Raw extension string.

    Returns:
        Normalized lowercase extension with leading dot, or empty string.
    """
    cleaned = ext.strip().lower()
    if not cleaned:
        return ""
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned


def parse_extensions_string(ext_string: str) -> list[str]:
    """Parse a delimiter-separated string of file extensions.

    Supports comma, semicolon, space, or newline delimiters.
    Returns deduplicated list of normalized extensions.

    Examples:
        ".txt, .py; md json" -> [".txt", ".py", ".md", ".json"]
        "*.py, *.rs" -> [".py", ".rs"]

    Args:
        ext_string: User-entered extensions string.

    Returns:
        List of normalized extensions.
    """
    if not ext_string or not ext_string.strip():
        return []

    # Split by comma, semicolon, whitespace
    raw_tokens = re.split(r"[,;\s]+", ext_string.strip())
    seen: set[str] = set()
    result: list[str] = []

    for token in raw_tokens:
        clean_token = token.strip()
        if not clean_token:
            continue
        # Remove wildcard prefix if user typed '*.py'
        if clean_token.startswith("*"):
            clean_token = clean_token[1:]
        normalized = normalize_extension(clean_token)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def export_results_to_csv(
    results: Sequence[SearchResult],
    target_path: Path | str,
) -> int:
    """Export search results to CSV with UTF-8 BOM ('utf-8-sig').

    Columns: file_name, file_path, line_number, matched_line, encoding
    Pre-pends the UTF-8 Byte Order Mark (BOM) so Excel and spreadsheet tools
    render Korean and special characters cleanly.

    Args:
        results: Sequence of SearchResult dataclass instances.
        target_path: Destination filesystem path for CSV.

    Returns:
        Total number of records written (excluding header).
    """
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["file_name", "file_path", "line_number", "matched_line", "encoding"])
        written = 0
        for r in results:
            writer.writerow([
                r.file_name,
                str(r.file_path),
                r.line_number,
                r.matched_line,
                r.encoding,
            ])
            written += 1
    return written


def read_context_lines(
    file_path: Path | str,
    target_line: int,
    context: int = 5,
    encoding: str = "utf-8",
) -> list[tuple[int, str]]:
    """Read a bounded window of lines around target_line from a text file.

    Extracts lines from max(1, target_line - context) to target_line + context.
    Stops reading immediately at end_line, guaranteeing O(1) memory and avoiding
    loading whole files into memory.

    Args:
        file_path: Path to target file.
        target_line: 1-indexed target line number.
        context: Context lines before and after target line (default: 5).
        encoding: Text encoding codec name.

    Returns:
        List of (line_number, line_text) tuples.
    """
    path = Path(file_path)
    if not path.is_file():
        return []

    context = max(0, context)
    start_line = max(1, target_line - context)
    end_line = target_line + context
    if end_line < start_line:
        return []

    lines: list[tuple[int, str]] = []

    try:
        with open(path, encoding=encoding, errors="replace", newline=None) as f:
            for current_line, raw_line in enumerate(f, start=1):
                if current_line > end_line:
                    break
                if current_line >= start_line:
                    lines.append((current_line, raw_line.rstrip("\r\n")))
    except (OSError, UnicodeDecodeError, LookupError, ValueError):
        return []
    return lines
