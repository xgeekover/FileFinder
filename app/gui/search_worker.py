"""Background search worker thread for FileFinder.

Wraps SearchEngine execution inside a PySide6 QThread to ensure non-blocking UI.
Batches search matches in groups of 100-500 items (default 250) or every 100ms
to maintain 60 FPS table rendering. Supports cooperative cancellation and robust
error reporting.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine

logger = logging.getLogger("app.gui.search_worker")


class SearchWorker(QThread):
    """QThread worker executing SearchEngine in a background thread.

    Signals:
        progress_updated(int, int, str): (scanned_files, total_files, current_file_path)
        result_found(object): Individual SearchResult
        results_batch_found(list): list[SearchResult] for chunked table updates
        search_completed(object): ScanStatistics on normal or cancelled completion
        error_occurred(str): Error message string on fatal exception
        search_finished(object): Backward-compatible alias for search_completed
        search_error(str): Backward-compatible alias for error_occurred
    """

    # Primary Qt Signals
    progress_updated = Signal(int, int, str)
    result_found = Signal(object)
    results_batch_found = Signal(list)
    search_completed = Signal(object)
    error_occurred = Signal(str)

    # Compatibility Aliases
    search_finished = search_completed
    search_error = error_occurred

    def __init__(
        self,
        first_arg: SearchEngine | SearchOptions | None = None,
        second_arg: SearchOptions | SearchEngine | None = None,
        batch_size: int = 250,
        flush_interval_sec: float = 0.1,
        parent: QObject | None = None,
        *,
        engine: SearchEngine | None = None,
        options: SearchOptions | None = None,
    ) -> None:
        """Initialize SearchWorker with flexible parameter ordering.

        Supports:
            SearchWorker(options, engine=None, ...)
            SearchWorker(engine, options, ...)
            SearchWorker(options=options, engine=engine, ...)

        Args:
            first_arg: Either SearchEngine or SearchOptions instance.
            second_arg: The complementary SearchOptions or SearchEngine instance.
            batch_size: Maximum row count before emitting results_batch_found.
            flush_interval_sec: Maximum latency in seconds before emitting partial batch.
            parent: Optional parent QObject.
            engine: Optional keyword-provided SearchEngine instance.
            options: Optional keyword-provided SearchOptions instance.
        """
        super().__init__(parent)

        resolved_engine = engine
        resolved_options = options

        if isinstance(first_arg, SearchEngine):
            resolved_engine = first_arg
            if isinstance(second_arg, SearchOptions):
                resolved_options = second_arg
        elif isinstance(first_arg, SearchOptions):
            resolved_options = first_arg
            if isinstance(second_arg, SearchEngine):
                resolved_engine = second_arg

        if resolved_options is None:
            raise TypeError("SearchWorker requires a valid SearchOptions instance")

        self.options: SearchOptions = resolved_options
        self.engine: SearchEngine = resolved_engine if resolved_engine is not None else SearchEngine()

        self.batch_size: int = max(1, batch_size)
        self.flush_interval_sec: float = max(0.01, flush_interval_sec)

        self._cancel_event = threading.Event()
        self._batch_lock = threading.Lock()
        self._batch: list[SearchResult] = []
        self._last_flush_time: float = 0.0

    def cancel(self) -> None:
        """Signal cooperative cancellation to worker thread."""
        logger.info("SearchWorker cancellation requested.")
        self._cancel_event.set()
        with self._batch_lock:
            if self._batch:
                batch_to_emit = self._batch
                self._batch = []
                self.results_batch_found.emit(batch_to_emit)

    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._cancel_event.is_set()

    def request_interruption(self) -> None:
        """Qt-idiomatic cancellation triggering cooperative event."""
        self.cancel()

    def run(self) -> None:
        """Worker thread entry point executed in background OS thread."""
        logger.debug("SearchWorker thread started (thread ID: %s)", threading.get_ident())
        self._cancel_event.clear()
        with self._batch_lock:
            self._batch = []
        self._last_flush_time = time.perf_counter()

        def _on_result(res: SearchResult) -> None:
            """Callback invoked by SearchEngine worker threads on every match."""
            batch_to_emit: list[SearchResult] | None = None
            now = time.perf_counter()

            with self._batch_lock:
                self._batch.append(res)
                if len(self._batch) >= self.batch_size or (now - self._last_flush_time >= self.flush_interval_sec):
                    batch_to_emit = self._batch
                    self._batch = []
                    self._last_flush_time = now

            if batch_to_emit is not None:
                self.results_batch_found.emit(batch_to_emit)
            self.result_found.emit(res)

        def _on_progress(scanned: int, total: int, current_path: Path) -> None:
            """Callback invoked by SearchEngine worker threads on each scanned file."""
            self.progress_updated.emit(scanned, total, str(current_path))

            batch_to_emit: list[SearchResult] | None = None
            now = time.perf_counter()

            with self._batch_lock:
                if self._batch and (now - self._last_flush_time >= self.flush_interval_sec):
                    batch_to_emit = self._batch
                    self._batch = []
                    self._last_flush_time = now

            if batch_to_emit is not None:
                self.results_batch_found.emit(batch_to_emit)

        try:
            stats = self.engine.search(
                options=self.options,
                result_callback=_on_result,
                progress_callback=_on_progress,
                cancel_event=self._cancel_event,
            )

            # Mandatory flush: Emit any remaining results in buffer prior to search_completed
            remaining_batch: list[SearchResult] | None = None
            with self._batch_lock:
                if self._batch:
                    remaining_batch = self._batch
                    self._batch = []

            if remaining_batch is not None:
                self.results_batch_found.emit(remaining_batch)

            logger.info(
                "SearchWorker finished: scanned=%d/%d, successes=%d, errors=%d, cancelled=%s, elapsed=%.2fs",
                stats.scanned_files,
                stats.total_files,
                stats.success_count,
                stats.error_count,
                stats.cancelled,
                stats.elapsed_seconds,
            )
            self.search_completed.emit(stats)

        except Exception as exc:
            logger.error("SearchWorker encountered unhandled error: %s", exc, exc_info=True)

            # Flush any results found prior to exception
            remaining_batch = None
            with self._batch_lock:
                if self._batch:
                    remaining_batch = self._batch
                    self._batch = []
            if remaining_batch is not None:
                self.results_batch_found.emit(remaining_batch)

            self.error_occurred.emit(str(exc))
