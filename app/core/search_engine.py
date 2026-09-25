"""Core multi-threaded search engine for FileFinder.

Coordinates parallel file content searching across the filesystem using
ThreadPoolExecutor. Completely independent of any GUI framework.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.core.encoding_detector import EncodingDetector
from app.core.file_filter import FileFilter
from app.core.file_scanner import FileScanner
from app.core.models import ScanStatistics, SearchOptions, SearchResult

logger = logging.getLogger("app.core.search_engine")

ResultCallback = Callable[[SearchResult], None]
ProgressCallback = Callable[[int, int, Path], None]  # (scanned_files, total_files, current_path)


class SearchEngine:
    """High-performance multi-threaded search engine.

    Features:
    - ThreadPoolExecutor concurrency scaled to host CPU cores.
    - Plain string search with case-sensitivity toggle.
    - Precompiled regular expression search with error trapping.
    - Cooperative cancellation via threading.Event preserving existing results.
    - Thread-safe result and progress callbacks.
    - ScanStatistics tracking total files, successes, errors, and timing.
    - Zero PySide6 or GUI framework dependencies.
    """

    def __init__(
        self,
        max_workers: int | None = None,
        file_filter: FileFilter | None = None,
        encoding_detector: EncodingDetector | None = None,
        file_scanner: FileScanner | None = None,
    ) -> None:
        """Initialize SearchEngine with optional worker count and collaborators.

        Args:
            max_workers: Maximum number of worker threads. If None, computes
                min(32, max(4, (os.cpu_count() or 1) * 4)).
            file_filter: Optional custom FileFilter instance for dependency injection.
            encoding_detector: Optional custom EncodingDetector instance.
            file_scanner: Optional custom FileScanner instance.
        """
        self.max_workers: int = (
            max_workers if max_workers is not None else self.calculate_max_workers()
        )
        self._custom_filter = file_filter
        self._custom_detector = encoding_detector
        self._custom_scanner = file_scanner

    @staticmethod
    def calculate_max_workers() -> int:
        """Compute optimal thread count: min(32, max(4, (os.cpu_count() or 1) * 4))."""
        cpu_count = os.cpu_count() or 1
        return min(32, max(4, cpu_count * 4))

    def search(
        self,
        options: SearchOptions,
        result_callback: ResultCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ScanStatistics:
        """Execute search across files matching the specified SearchOptions.

        Args:
            options: Search configuration (path, query, regex flag, case sensitivity, etc.).
            result_callback: Invoked when a matching line is discovered.
            progress_callback: Invoked after each file is scanned (scanned, total, current_file).
            cancel_event: Optional threading.Event to cooperatively cancel an in-flight search.

        Returns:
            ScanStatistics containing summary metrics, error logs, and elapsed time.
        """
        start_time = time.perf_counter()
        stats = ScanStatistics()

        # Check early cancellation
        if cancel_event is not None and cancel_event.is_set():
            stats.cancelled = True
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
            return stats

        # Path existence check
        search_path = options.path.resolve()
        if not search_path.exists():
            stats.add_error(options.path, f"Search folder does not exist: {options.path}")
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
            return stats

        # Empty query returns immediately with zero matches
        if not options.query:
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
            return stats

        # Compile pattern upfront
        flags = re.NOFLAG if options.case_sensitive else re.IGNORECASE
        try:
            if options.is_regex:
                pattern = re.compile(options.query, flags)
            else:
                pattern = re.compile(re.escape(options.query), flags)
        except re.error as exc:
            logger.warning("Invalid regex query '%s': %s", options.query, exc)
            stats.add_error(options.path, f"Invalid regex pattern: {exc}")
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
            return stats

        # Initialize collaborators
        file_filter = self._custom_filter or FileFilter(
            extensions=options.extensions,
            include_hidden=options.include_hidden,
        )
        scanner = self._custom_scanner or FileScanner(file_filter=file_filter)
        detector = self._custom_detector or EncodingDetector()

        # Phase 1: Candidate file discovery
        candidate_files: list[Path] = []
        if search_path.is_file():
            if file_filter.should_scan(search_path, check_content=False):
                candidate_files.append(search_path)
        else:
            try:
                for file_path in scanner.scan_files(
                    search_path,
                    recursive=options.recursive,
                    cancel_event=cancel_event,
                ):
                    if cancel_event is not None and cancel_event.is_set():
                        stats.cancelled = True
                        stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
                        return stats
                    candidate_files.append(file_path)
            except (PermissionError, OSError) as exc:
                stats.add_error(search_path, str(exc))

        stats.total_files = len(candidate_files)
        if stats.total_files == 0:
            if progress_callback is not None:
                progress_callback(0, 0, search_path)
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
            return stats

        # Phase 2: Parallel content search
        stats_lock = threading.Lock()
        callback_lock = threading.Lock()

        def _process_single_file(file_path: Path) -> None:
            if cancel_event is not None and cancel_event.is_set():
                return

            try:
                # Fast rejection of binary files
                if file_filter.is_binary_by_extension(file_path) or file_filter.is_binary_content(
                    file_path
                ):
                    with stats_lock:
                        stats.record_success()
                    return

                # Encoding detection
                encoding = detector.detect(file_path)

                # Line-by-line search
                for line_number, line_content in scanner.stream_lines(
                    file_path, encoding, cancel_event=cancel_event, raise_on_error=True
                ):
                    if cancel_event is not None and cancel_event.is_set():
                        break

                    for match in pattern.finditer(line_content):
                        result = SearchResult(
                            file_path=file_path,
                            file_name=file_path.name,
                            line_number=line_number,
                            matched_line=line_content,
                            match_start=match.start(),
                            match_end=match.end(),
                            encoding=encoding,
                        )
                        if result_callback is not None:
                            with callback_lock:
                                result_callback(result)

                with stats_lock:
                    stats.record_success()

            except (PermissionError, FileNotFoundError, IsADirectoryError, OSError) as exc:
                with stats_lock:
                    stats.add_error(file_path, str(exc))
            except Exception as exc:
                logger.warning("Unexpected error scanning '%s': %s", file_path, exc, exc_info=True)
                with stats_lock:
                    stats.add_error(file_path, f"Unexpected error: {exc}")
            finally:
                with stats_lock:
                    stats.scanned_files += 1
                    current_scanned = stats.scanned_files

                if progress_callback is not None:
                    with callback_lock:
                        progress_callback(current_scanned, stats.total_files, file_path)

        # ThreadPoolExecutor execution with responsive cancellation
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(_process_single_file, path) for path in candidate_files]
            remaining_futures = set(futures)

            while remaining_futures:
                if cancel_event is not None and cancel_event.is_set():
                    stats.cancelled = True
                    for f in remaining_futures:
                        f.cancel()
                    break

                done, remaining_futures = concurrent.futures.wait(
                    remaining_futures,
                    timeout=0.05,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for f in done:
                    try:
                        f.result()
                    except Exception as exc:
                        logger.error("Worker thread task error: %s", exc, exc_info=True)

        if cancel_event is not None and cancel_event.is_set():
            stats.cancelled = True

        stats.elapsed_seconds = round(time.perf_counter() - start_time, 4)
        return stats
