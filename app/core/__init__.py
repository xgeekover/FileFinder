"""FileFinder core search engine package.

Provides high-performance, GUI-independent file searching, encoding detection,
filtering, and scanning modules.
"""

from __future__ import annotations

from app.core.encoding_detector import EncodingDetector
from app.core.file_filter import FileFilter
from app.core.file_scanner import FileScanner
from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.core.search_engine import SearchEngine

__all__ = [
    "EncodingDetector",
    "FileFilter",
    "FileScanner",
    "ScanStatistics",
    "SearchEngine",
    "SearchOptions",
    "SearchResult",
]
