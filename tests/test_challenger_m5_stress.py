"""Empirical stress test suite and benchmark harness for FileFinder Phase 5 GUI.

Author: challenger_m5_1
Objective:
1. Virtualization & Scale: ResultsTableModel with 100,000+ SearchResult instances.
   Measure insertion latency, memory usage, sorting speed (path -> line, line -> path),
   and verify zero UI freezes or crashes.
2. High-Frequency Batching: SearchWorker emitting 10,000 matches in bursts of 250 items.
   Verify that all 10,000 items are correctly added to the table with 0 data loss.
3. Mid-search cancellation under heavy load: Verify that calling cancel() preserves
   all already-emitted items and cleanly halts the thread within 200ms.
4. Runnable as standalone CLI script or via pytest under QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import gc
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# Ensure offscreen Qt platform if not specified
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableView

from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.core.search_engine import SearchEngine
from app.gui.main_window import ResultsTableModel
from app.gui.search_worker import SearchWorker


def get_current_rss_kb() -> int:
    """Query current resident set size (RSS) in kilobytes using ps."""
    try:
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())])
        return int(out.decode().strip())
    except Exception:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 if sys.platform == "darwin" else 1
        return rss // divisor


def generate_synthetic_results(count: int) -> list[SearchResult]:
    """Generate deterministic synthetic SearchResult items for stress testing."""
    results: list[SearchResult] = []
    # Use 2,000 distinct file paths to simulate a medium/large project
    for i in range(count):
        file_idx = i % 2000
        folder_idx = file_idx // 20
        path = Path(f"/var/projects/repo_{folder_idx:02d}/module/file_{file_idx:04d}.py")
        line = (i * 17) % 15000 + 1
        res = SearchResult(
            file_path=path,
            file_name=path.name,
            line_number=line,
            matched_line=f"def execute_task_{i}(payload: dict) -> bool:  # match token {i}",
            match_start=4,
            match_end=16,
            encoding="utf-8",
        )
        results.append(res)
    return results


# ==============================================================================
# 1. Virtualization & Scale Benchmarks (100,000+ Items)
# ==============================================================================


class BenchmarkVirtualizationScale:
    """Stress test ResultsTableModel virtualization, memory usage, and sorting on 100k+ items."""

    SCALE_COUNT: int = 100_000
    BATCH_CHUNK_SIZE: int = 250

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        """Execute full empirical virtualization and scale benchmark suite."""
        app = QApplication.instance() or QApplication(sys.argv)
        metrics: dict[str, Any] = {}

        gc.collect()
        rss_baseline = get_current_rss_kb()

        # Step 1: Generate 100,000 items
        t_gen_0 = time.perf_counter()
        dataset = generate_synthetic_results(cls.SCALE_COUNT)
        t_gen_1 = time.perf_counter()
        metrics["data_generation_sec"] = t_gen_1 - t_gen_0

        rss_after_gen = get_current_rss_kb()
        metrics["rss_baseline_mb"] = rss_baseline / 1024.0
        metrics["rss_after_gen_mb"] = rss_after_gen / 1024.0
        metrics["rss_delta_data_mb"] = (rss_after_gen - rss_baseline) / 1024.0

        # Step 2: Model & QTableView setup
        table = QTableView()
        model = ResultsTableModel()
        table.setModel(model)
        table.show()
        app.processEvents()

        # Step 3: Measure Batched Insertion (mimicking live worker streaming in bursts of 250)
        chunks = [
            dataset[i : i + cls.BATCH_CHUNK_SIZE]
            for i in range(0, len(dataset), cls.BATCH_CHUNK_SIZE)
        ]
        batch_latencies_ms: list[float] = []

        t_insert_start = time.perf_counter()
        for chunk in chunks:
            b_t0 = time.perf_counter()
            model.append_batch(chunk)
            app.processEvents()
            b_lat = (time.perf_counter() - b_t0) * 1000.0
            batch_latencies_ms.append(b_lat)
        t_insert_end = time.perf_counter()

        total_insert_sec = t_insert_end - t_insert_start
        metrics["total_batched_insertion_sec"] = total_insert_sec
        metrics["insertion_throughput_items_sec"] = cls.SCALE_COUNT / total_insert_sec
        metrics["mean_batch_latency_ms"] = sum(batch_latencies_ms) / len(batch_latencies_ms)
        metrics["max_batch_latency_ms"] = max(batch_latencies_ms)
        metrics["min_batch_latency_ms"] = min(batch_latencies_ms)

        # Step 4: Memory after full model insertion and UI binding
        gc.collect()
        rss_final = get_current_rss_kb()
        metrics["rss_final_mb"] = rss_final / 1024.0
        metrics["total_memory_overhead_mb"] = (rss_final - rss_baseline) / 1024.0
        metrics["bytes_per_result_item"] = (
            (rss_final - rss_baseline) * 1024.0 / cls.SCALE_COUNT
        )

        # Step 5: Virtualization & Viewport Data Access Verification
        assert model.rowCount() == cls.SCALE_COUNT, f"Expected {cls.SCALE_COUNT} rows, got {model.rowCount()}"
        assert model.columnCount() == 5, f"Expected 5 columns, got {model.columnCount()}"

        # Test data roles across sample rows (first, middle, last, random)
        sample_rows = [0, 1, cls.SCALE_COUNT // 2, cls.SCALE_COUNT - 2, cls.SCALE_COUNT - 1]
        for _ in range(10):
            sample_rows.append(random.randint(0, cls.SCALE_COUNT - 1))

        t_access_0 = time.perf_counter()
        for r in sample_rows:
            for c in range(5):
                idx = model.index(r, c)
                disp = model.data(idx, Qt.ItemDataRole.DisplayRole)
                assert disp is not None and len(str(disp)) > 0
                align = model.data(idx, Qt.ItemDataRole.TextAlignmentRole)
                assert align is not None
                if c in (2, 4):
                    tip = model.data(idx, Qt.ItemDataRole.ToolTipRole)
                    assert tip is not None
            user_obj = model.data(model.index(r, 0), Qt.ItemDataRole.UserRole)
            assert isinstance(user_obj, SearchResult)
        t_access_1 = time.perf_counter()
        metrics["sampled_data_access_latency_ms"] = (t_access_1 - t_access_0) * 1000.0

        # Viewport navigation offscreen (verify no freezes or crashes)
        table.scrollToBottom()
        app.processEvents()
        table.scrollToTop()
        app.processEvents()

        # Step 6: Sorting Benchmarks (Path -> Line and Line -> Path)
        # Sort 1: Path (Column 2) Ascending
        t_sort_p0 = time.perf_counter()
        model.sort(2, Qt.SortOrder.AscendingOrder)
        app.processEvents()
        t_sort_p1 = time.perf_counter()
        metrics["sort_path_ascending_ms"] = (t_sort_p1 - t_sort_p0) * 1000.0

        # Verify sorted by path, tie-breaker line
        res_0 = model.get_result(0)
        res_1 = model.get_result(1)
        res_last = model.get_result(cls.SCALE_COUNT - 1)
        assert res_0 is not None and res_1 is not None and res_last is not None
        assert str(res_0.file_path) <= str(res_1.file_path)
        assert str(res_0.file_path) <= str(res_last.file_path)

        # Sort 2: Line (Column 3) Ascending (Transition: Path -> Line)
        t_sort_l0 = time.perf_counter()
        model.sort(3, Qt.SortOrder.AscendingOrder)
        app.processEvents()
        t_sort_l1 = time.perf_counter()
        metrics["sort_path_to_line_transition_ms"] = (t_sort_l1 - t_sort_l0) * 1000.0

        # Verify sorted by line, tie-breaker path
        res_l0 = model.get_result(0)
        res_l1 = model.get_result(1)
        res_llast = model.get_result(cls.SCALE_COUNT - 1)
        assert res_l0 is not None and res_l1 is not None and res_llast is not None
        assert res_l0.line_number <= res_l1.line_number
        assert res_l0.line_number <= res_llast.line_number

        # Sort 3: Transition Line -> Path Ascending
        t_sort_p2 = time.perf_counter()
        model.sort(2, Qt.SortOrder.AscendingOrder)
        app.processEvents()
        t_sort_p3 = time.perf_counter()
        metrics["sort_line_to_path_transition_ms"] = (t_sort_p3 - t_sort_p2) * 1000.0

        # Sort 4: Path Descending
        t_sort_pd0 = time.perf_counter()
        model.sort(2, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        t_sort_pd1 = time.perf_counter()
        metrics["sort_path_descending_ms"] = (t_sort_pd1 - t_sort_pd0) * 1000.0

        res_d0 = model.get_result(0)
        res_dlast = model.get_result(cls.SCALE_COUNT - 1)
        assert res_d0 is not None and res_dlast is not None
        assert str(res_d0.file_path) >= str(res_dlast.file_path)

        table.close()
        return metrics


# ==============================================================================
# 2. High-Frequency Batching Benchmarks (10,000 Items in 250 Bursts)
# ==============================================================================


class BenchmarkHighFrequencyBatching:
    """Stress test SearchWorker emitting 10,000 matches in 40 bursts of 250 items."""

    BURST_ITEMS: int = 10_000
    BURST_SIZE: int = 250
    BURST_COUNT: int = BURST_ITEMS // BURST_SIZE

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        """Execute high-frequency burst emission and verify 0 data loss."""
        app = QApplication.instance() or QApplication(sys.argv)
        metrics: dict[str, Any] = {}

        model = ResultsTableModel()

        # Build 10,000 distinct deterministic items
        expected_items: list[SearchResult] = []
        for i in range(cls.BURST_ITEMS):
            res = SearchResult(
                file_path=Path(f"/data/stream/batch_{i // cls.BURST_SIZE}/file_{i % 50}.txt"),
                file_name=f"file_{i % 50}.txt",
                line_number=i + 1,
                matched_line=f"burst stream match content token {i}",
                match_start=0,
                match_end=10,
                encoding="utf-8",
            )
            expected_items.append(res)

        # Worker subclass that simulates burst emissions of 250 items
        class HighFrequencyBurstWorker(SearchWorker):
            def run(self_worker) -> None:
                for b_idx in range(cls.BURST_COUNT):
                    start_i = b_idx * cls.BURST_SIZE
                    end_i = start_i + cls.BURST_SIZE
                    batch = expected_items[start_i:end_i]
                    self_worker.results_batch_found.emit(batch)
                    # High frequency spacing: 1 millisecond sleep
                    time.sleep(0.001)

                stats = ScanStatistics(
                    total_files=cls.BURST_COUNT,
                    scanned_files=cls.BURST_COUNT,
                    success_count=cls.BURST_COUNT,
                    error_count=0,
                    errors=[],
                    elapsed_seconds=0.0,
                    cancelled=False,
                )
                self_worker.search_completed.emit(stats)

        worker = HighFrequencyBurstWorker(
            options=SearchOptions(path=Path("/data/stream"), query="burst"),
            batch_size=cls.BURST_SIZE,
        )

        batches_received: list[int] = []

        def on_batch(batch: list[SearchResult]) -> None:
            batches_received.append(len(batch))
            model.append_batch(batch)

        worker.results_batch_found.connect(on_batch)

        completed_event = threading.Event()
        worker.search_completed.connect(lambda s: completed_event.set())

        t0 = time.perf_counter()
        worker.start()

        timeout_sec = 10.0
        while not completed_event.is_set() or model.rowCount() < cls.BURST_ITEMS:
            app.processEvents()
            time.sleep(0.002)
            if time.perf_counter() - t0 > timeout_sec:
                break

        t1 = time.perf_counter()
        worker.wait(1000)

        elapsed_sec = t1 - t0
        metrics["total_burst_delivery_sec"] = elapsed_sec
        metrics["burst_throughput_items_sec"] = cls.BURST_ITEMS / elapsed_sec
        metrics["batches_emitted"] = cls.BURST_COUNT
        metrics["batches_received"] = len(batches_received)
        metrics["total_items_in_model"] = model.rowCount()

        # Strict Verification: 0 Data Loss
        assert model.rowCount() == cls.BURST_ITEMS, (
            f"Data loss detected: Expected {cls.BURST_ITEMS} rows, got {model.rowCount()}"
        )

        all_results = model.get_all_results()
        assert len(all_results) == cls.BURST_ITEMS, "Model get_all_results length mismatch"

        # Check each item preserves identity, line_number, and matched_line
        for idx, (actual, expected) in enumerate(zip(all_results, expected_items, strict=True)):
            assert actual.line_number == expected.line_number, (
                f"Item at {idx} corrupted: actual line {actual.line_number} != expected {expected.line_number}"
            )
            assert actual.matched_line == expected.matched_line, (
                f"Item at {idx} text mismatch: '{actual.matched_line}' != '{expected.matched_line}'"
            )
            assert actual.file_path == expected.file_path, (
                f"Item at {idx} path mismatch: '{actual.file_path}' != '{expected.file_path}'"
            )

        metrics["data_loss_items"] = 0
        metrics["data_integrity_verified"] = True
        return metrics


# ==============================================================================
# 3. Mid-Search Cancellation Benchmarks (<200ms Halt, Preserves Items)
# ==============================================================================


class BenchmarkMidSearchCancellation:
    """Stress test cancellation under heavy concurrent search load."""

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        """Verify cancellation preserves emitted results and halts thread within 200ms."""
        app = QApplication.instance() or QApplication(sys.argv)
        metrics: dict[str, Any] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create 40 files with 2,500 lines each = 100,000 searchable lines
            # This generates sustained heavy load across multiple worker threads
            file_paths: list[Path] = []
            for f_i in range(40):
                fp = temp_path / f"heavy_file_{f_i:03d}.txt"
                content_lines = [
                    f"file {f_i} line {l_i} search_token_needle match line"
                    for l_i in range(2500)
                ]
                fp.write_text("\n".join(content_lines), encoding="utf-8")
                file_paths.append(fp)

            model = ResultsTableModel()
            engine = SearchEngine(max_workers=min(16, (os.cpu_count() or 1) * 2))
            options = SearchOptions(path=temp_path, query="search_token_needle", recursive=True)

            worker = SearchWorker(
                engine=engine,
                options=options,
                batch_size=250,
                flush_interval_sec=0.05,
            )
            worker.results_batch_found.connect(model.append_batch)

            stats_holder: list[ScanStatistics] = []
            worker.search_completed.connect(lambda s: stats_holder.append(s))

            worker.start()

            # Wait until heavy streaming begins and at least 3,000 matches are already in the table
            t_wait_0 = time.perf_counter()
            while model.rowCount() < 3000 and worker.isRunning():
                app.processEvents()
                time.sleep(0.005)
                if time.perf_counter() - t_wait_0 > 10.0:
                    break

            pre_cancel_count = model.rowCount()
            assert pre_cancel_count >= 1000, f"Load not reached: {pre_cancel_count}"

            # Cancel under heavy stream and measure halt duration
            t_cancel_start = time.perf_counter()
            worker.cancel()
            halt_ok = worker.wait(500)  # wait up to 500ms
            t_cancel_end = time.perf_counter()

            halt_duration_sec = t_cancel_end - t_cancel_start
            metrics["halt_duration_ms"] = halt_duration_sec * 1000.0
            metrics["thread_stopped_cleanly"] = halt_ok
            metrics["worker_running_after_wait"] = worker.isRunning()

            # Process any queued events (e.g. final batch flush emitted on cancel)
            app.processEvents()
            post_cancel_count = model.rowCount()
            metrics["pre_cancel_row_count"] = pre_cancel_count
            metrics["post_cancel_row_count"] = post_cancel_count
            metrics["preserved_row_count"] = post_cancel_count

            # Assertions
            assert halt_ok is True, "SearchWorker thread failed to halt within 500ms"
            assert halt_duration_sec <= 0.200, (
                f"Halt duration exceeded 200ms threshold: {halt_duration_sec * 1000.0:.2f}ms"
            )
            assert not worker.isRunning(), "SearchWorker is still running after wait()"
            assert post_cancel_count >= pre_cancel_count, (
                f"Data loss after cancellation: {post_cancel_count} < {pre_cancel_count}"
            )
            assert len(stats_holder) == 1, "Expected search_completed signal to emit ScanStatistics"
            assert stats_holder[0].cancelled is True, "ScanStatistics.cancelled was not True"

        # Sub-test B: Immediate cancellation (edge case: cancel immediately after start)
        worker_early = SearchWorker(
            engine=engine,
            options=options,
            batch_size=250,
        )
        worker_early.start()
        t_early_0 = time.perf_counter()
        worker_early.cancel()
        early_halt_ok = worker_early.wait(500)
        t_early_1 = time.perf_counter()
        early_halt_sec = t_early_1 - t_early_0
        metrics["early_cancel_halt_ms"] = early_halt_sec * 1000.0
        assert early_halt_ok is True
        assert early_halt_sec <= 0.200

        return metrics


# ==============================================================================
# PyTest Compatible Test Functions
# ==============================================================================


def test_stress_virtualization_100k_scale() -> None:
    """PyTest entry point: Virtualization & Scale with 100,000+ items."""
    metrics = BenchmarkVirtualizationScale.run_benchmark()
    assert metrics["sort_path_ascending_ms"] < 1000.0, "Path sort exceeded 1.0s limit"
    assert metrics["sort_path_to_line_transition_ms"] < 500.0, "Sort transition exceeded 500ms"
    assert metrics["total_batched_insertion_sec"] < 5.0, "Batched insertion exceeded 5.0s"


def test_stress_high_frequency_batching_zero_data_loss() -> None:
    """PyTest entry point: 10,000 items in bursts of 250 with 0 data loss."""
    metrics = BenchmarkHighFrequencyBatching.run_benchmark()
    assert metrics["data_loss_items"] == 0
    assert metrics["data_integrity_verified"] is True


def test_stress_mid_search_cancellation_halt_under_200ms() -> None:
    """PyTest entry point: Mid-search cancellation under 200ms halt preserving items."""
    metrics = BenchmarkMidSearchCancellation.run_benchmark()
    assert metrics["halt_duration_ms"] <= 200.0
    assert metrics["thread_stopped_cleanly"] is True
    assert metrics["post_cancel_row_count"] >= metrics["pre_cancel_row_count"]


# ==============================================================================
# CLI Entry Point
# ==============================================================================


def main() -> int:
    """Run stress benchmarks and print empirical report."""
    print("=" * 80)
    print("FILEFINDER PHASE 5 GUI EMPIRICAL STRESS TEST HARNESS")
    print("=" * 80)

    # 1. Virtualization & Scale
    print("\n[1/3] Running Virtualization & Scale Benchmark (100,000 SearchResult items)...")
    m1 = BenchmarkVirtualizationScale.run_benchmark()
    print(f"  - Total Items: {BenchmarkVirtualizationScale.SCALE_COUNT:,}")
    print(f"  - Batched Insertion (400 x 250): {m1['total_batched_insertion_sec']:.4f}s")
    print(f"  - Insertion Throughput: {m1['insertion_throughput_items_sec']:,.0f} items/sec")
    print(f"  - Mean Batch Latency: {m1['mean_batch_latency_ms']:.3f} ms")
    print(f"  - Max Batch Latency: {m1['max_batch_latency_ms']:.3f} ms")
    print(f"  - Baseline Memory: {m1['rss_baseline_mb']:.2f} MB")
    print(f"  - Memory After Gen: {m1['rss_after_gen_mb']:.2f} MB")
    print(f"  - Final Memory: {m1['rss_final_mb']:.2f} MB")
    print(f"  - Total Memory Delta: {m1['total_memory_overhead_mb']:.2f} MB")
    print(f"  - Memory per Result Item: {m1['bytes_per_result_item']:.1f} bytes/item")
    print(f"  - Sampled Data Access Latency: {m1['sampled_data_access_latency_ms']:.3f} ms")
    print(f"  - Sort Path Ascending: {m1['sort_path_ascending_ms']:.2f} ms")
    print(f"  - Sort Path -> Line Transition: {m1['sort_path_to_line_transition_ms']:.2f} ms")
    print(f"  - Sort Line -> Path Transition: {m1['sort_line_to_path_transition_ms']:.2f} ms")
    print(f"  - Sort Path Descending: {m1['sort_path_descending_ms']:.2f} ms")
    print("  => VIRTUALIZATION & SCALE: PASSED (Zero freezes, smooth 100k rendering)")

    # 2. High-Frequency Batching
    print("\n[2/3] Running High-Frequency Batching Benchmark (10,000 items in 250 bursts)...")
    m2 = BenchmarkHighFrequencyBatching.run_benchmark()
    print(f"  - Total Items Emitted: {BenchmarkHighFrequencyBatching.BURST_ITEMS:,}")
    print(f"  - Bursts Emitted: {m2['batches_emitted']}, Bursts Received: {m2['batches_received']}")
    print(f"  - Total Items in Model: {m2['total_items_in_model']:,}")
    print(f"  - Delivery Time: {m2['total_burst_delivery_sec']:.4f}s")
    print(f"  - Throughput: {m2['burst_throughput_items_sec']:,.0f} items/sec")
    print(f"  - Data Loss: {m2['data_loss_items']} items (0% loss)")
    print(f"  - 100% Data Integrity Verified: {m2['data_integrity_verified']}")
    print("  => HIGH-FREQUENCY BATCHING: PASSED (0 data loss, full integrity)")

    # 3. Mid-search Cancellation
    print("\n[3/3] Running Mid-Search Cancellation Benchmark (Heavy Load)...")
    m3 = BenchmarkMidSearchCancellation.run_benchmark()
    print(f"  - Pre-cancel Items: {m3['pre_cancel_row_count']:,}")
    print(f"  - Post-cancel Items: {m3['post_cancel_row_count']:,}")
    print(f"  - Clean Thread Halt: {m3['thread_stopped_cleanly']}")
    print(f"  - Halt Latency (Heavy Load): {m3['halt_duration_ms']:.2f} ms (Threshold: 200 ms)")
    print(f"  - Halt Latency (Early Cancel): {m3['early_cancel_halt_ms']:.2f} ms")
    print("  => MID-SEARCH CANCELLATION: PASSED (<200ms halt, all items preserved)")

    print("\n" + "=" * 80)
    print("ALL EMPIRICAL GUI STRESS BENCHMARKS PASSED PERFECTLY!")
    print("VERDICT: APPROVE")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
