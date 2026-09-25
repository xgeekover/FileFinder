"""Automated test suite for PySide6 GUI scenarios in FileFinder.

Verifies all 15 authoritative GUI scenarios, input validations, ResultsTableModel
virtualization and sorting, SettingsDialog persistence, ErrorFilesDialog, AboutDialog,
drag-and-drop, context menus, and HTML preview highlighting using pytest-qt and offscreen Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
)
from pytestqt.qtbot import QtBot

from app.core.file_scanner import FileScanner
from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.core.search_engine import SearchEngine
from app.gui.main_window import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    AboutDialog,
    ErrorFilesDialog,
    MainWindow,
    ResultsTableModel,
)
from app.gui.settings_dialog import SettingsDialog
from app.gui.styles import (
    get_application_stylesheet,
    get_preview_html,
    highlight_line_text,
)


@pytest.fixture(autouse=True)
def clean_qsettings() -> Any:
    """Clear QSettings before and after every test to ensure test isolation."""
    settings = QSettings("FileFinder", "FileFinder")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()


@pytest.fixture
def main_window(qtbot: QtBot) -> MainWindow:
    """Instantiate and manage MainWindow fixture with qtbot."""
    window = MainWindow()
    qtbot.addWidget(window)
    return window


# ==============================================================================
# 1. Validation & Input Error Tests
# ==============================================================================


class TestInputValidation:
    """Verify exact Korean error messages for invalid input parameters."""

    def test_validation_empty_path(self, main_window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
        """V1: Empty path returns '검색 폴더를 선택해주세요.'"""
        main_window.path_input.setText("")
        main_window.query_input.setText("hello")

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더를 선택해주세요."

        # Verify QMessageBox interaction
        messages: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, text: messages.append((title, text)),
        )
        main_window.on_start_search()
        assert len(messages) == 1
        assert messages[0][1] == "검색 폴더를 선택해주세요."

    def test_validation_whitespace_path(self, main_window: MainWindow) -> None:
        """V1 Edge: Whitespace-only path is treated as empty."""
        main_window.path_input.setText("   \t  \n ")
        main_window.query_input.setText("hello")
        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더를 선택해주세요."

    def test_validation_non_existent_path(self, main_window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
        """V2: Non-existent directory returns '검색 폴더가 존재하지 않습니다.'"""
        bad_path = "/non_existent_folder_abc_123_xyz"
        main_window.path_input.setText(bad_path)
        main_window.query_input.setText("hello")

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더가 존재하지 않습니다."

        messages: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, text: messages.append((title, text)),
        )
        main_window.on_start_search()
        assert len(messages) == 1
        assert messages[0][1] == "검색 폴더가 존재하지 않습니다."

    def test_validation_empty_query(self, main_window: MainWindow, tmp_path: Path) -> None:
        """V3: Empty query returns '검색어를 입력해주세요.'"""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("")

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색어를 입력해주세요."

    def test_validation_whitespace_query(self, main_window: MainWindow, tmp_path: Path) -> None:
        """V3 Edge: Whitespace-only query is treated as empty."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("     ")

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색어를 입력해주세요."

    def test_validation_invalid_regex(self, main_window: MainWindow, tmp_path: Path) -> None:
        """V4: Malformed regex when regex toggle is ON returns '올바르지 않은 정규식입니다.'"""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("[unclosed_bracket_pattern")
        main_window.cb_regex.setChecked(True)

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "올바르지 않은 정규식입니다."

    def test_validation_special_characters_with_regex_off(
        self, main_window: MainWindow, tmp_path: Path
    ) -> None:
        """V4 Edge: Special regex characters with regex toggle OFF are valid plain text."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("[unclosed_bracket_pattern")
        main_window.cb_regex.setChecked(False)

        valid, err_msg = main_window.validate_inputs()
        assert valid is True
        assert err_msg is None


# ==============================================================================
# 2. The 15 Authoritative GUI Verification Scenarios
# ==============================================================================


class TestAuthoritative15Scenarios:
    """Automated verification of all 15 scenarios specified in R3/R8."""

    def test_scenario_01_hello_case_insensitive_default(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 1: 'hello' search with case-insensitive default matches 'Hello', 'hello', 'HELLO'."""
        f1 = tmp_path / "f1.txt"
        f1.write_text("Hello world\nhello universe\nHELLO GALAXY\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("hello")
        main_window.cb_case.setChecked(False)

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 3
        matched_lines = [main_window.table_model.get_result(i).matched_line for i in range(3)]  # type: ignore[union-attr]
        assert "Hello world" in matched_lines
        assert "hello universe" in matched_lines
        assert "HELLO GALAXY" in matched_lines

    def test_scenario_02_korean_text_search(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 2: Korean text search in UTF-8 file renders correctly without mojibake."""
        korean_file = tmp_path / "korean_doc.txt"
        korean_file.write_text(
            "첫 번째 라인\n파일파인더 한글 검색 테스트 성공\n세 번째 라인\n",
            encoding="utf-8",
        )

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("한글 검색")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert "한글 검색" in res.matched_line
        assert res.file_name == "korean_doc.txt"
        assert res.line_number == 2

        # Verify preview panel displays Korean without corruption
        index = main_window.table_model.index(0, 0)
        main_window.results_table.setCurrentIndex(index)
        assert "한글 검색" in main_window.preview_panel.toHtml()

    def test_scenario_03_long_sentence_search(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 3: Multi-word sentence search preserving exact spaces."""
        doc = tmp_path / "sentence.txt"
        sentence = "This is a test sentence for multi-word search capability."
        doc.write_text(f"Prefix line\n{sentence}\nSuffix line\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("This is a test sentence")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert res.matched_line == sentence

    def test_scenario_04_explicit_case_insensitive_matching(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 4: Explicit case-insensitive matching finds both 'Hello' and 'hello'."""
        f = tmp_path / "case_test.txt"
        f.write_text("Hello line\nhello line\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("hello")
        main_window.cb_case.setChecked(False)

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 2

    def test_scenario_05_case_sensitive_option_filtering(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 5: Case-sensitive ON matches only exact case and excludes lowercase."""
        f = tmp_path / "case_test.txt"
        f.write_text("Hello line\nhello line\nHELLO line\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("Hello")
        main_window.cb_case.setChecked(True)

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert res.matched_line == "Hello line"

    def test_scenario_06_regex_pattern_search(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 6: Regex pattern matching \\d{3}-\\d{4} finds formatted digits."""
        f = tmp_path / "contacts.txt"
        f.write_text("Call 555-0199 now\nNo numbers here\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText(r"\d{3}-\d{4}")
        main_window.cb_regex.setChecked(True)

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert "555-0199" in res.matched_line

    def test_scenario_07_recursive_search_toggle(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 7: Recursive search toggle ON vs OFF behavior."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "root.txt").write_text("target_token in root\n", encoding="utf-8")
        (sub / "nested.txt").write_text("target_token in nested\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("target_token")

        # Test Recursive OFF
        main_window.cb_recursive.setChecked(False)
        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass
        assert main_window.table_model.rowCount() == 1
        assert main_window.table_model.get_result(0).file_name == "root.txt"  # type: ignore[union-attr]

        # Test Recursive ON
        main_window.cb_recursive.setChecked(True)
        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass
        assert main_window.table_model.rowCount() == 2

    def test_scenario_08_multiple_extension_filters(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 8: Whitelist filter '.txt, .py' searches only matching extensions."""
        (tmp_path / "a.txt").write_text("findme in txt\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("# findme in py\n", encoding="utf-8")
        (tmp_path / "c.md").write_text("findme in md\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("findme")
        main_window.ext_input.setText(".txt, .py")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 2
        names = {main_window.table_model.get_result(i).file_name for i in range(2)}  # type: ignore[union-attr]
        assert names == {"a.txt", "b.py"}

    def test_scenario_09_non_existent_path_error(
        self, main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 9: Non-existent path displays Korean warning and halts."""
        main_window.path_input.setText("/path_does_not_exist_99999")
        main_window.query_input.setText("test")

        warning_boxes: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, text: warning_boxes.append(text),
        )

        main_window.on_start_search()
        assert warning_boxes == ["검색 폴더가 존재하지 않습니다."]
        assert main_window.search_worker is None
        assert main_window.table_model.rowCount() == 0

    def test_scenario_10_permission_error_and_error_dialog(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 10: Unreadable files are skipped; error button shows count and opens dialog."""
        good_file = tmp_path / "good.txt"
        good_file.write_text("secret_keyword\n", encoding="utf-8")

        # Mock SearchEngine.search to simulate 1 permission error
        def mock_search(
            self_engine: Any,
            options: SearchOptions,
            result_callback: Any = None,
            progress_callback: Any = None,
            cancel_event: Any = None,
        ) -> ScanStatistics:
            if result_callback is not None:
                res = SearchResult(good_file, "good.txt", 1, "secret_keyword", 0, 14, "utf-8")
                result_callback(res)
            if progress_callback is not None:
                progress_callback(1, 2, good_file)

            bad_file = tmp_path / "locked.txt"
            stats = ScanStatistics(
                total_files=2,
                scanned_files=2,
                success_count=1,
                error_count=1,
                errors=[(bad_file, "Permission denied")],
                elapsed_seconds=0.12,
                cancelled=False,
            )
            return stats

        monkeypatch.setattr(SearchEngine, "search", mock_search)

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("secret_keyword")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        assert main_window.btn_errors.isEnabled() is True
        assert main_window.btn_errors.text() == "[오류 파일 1개]"

        # Test ErrorFilesDialog
        errors_list = [(tmp_path / "locked.txt", "Permission denied")]
        dlg = ErrorFilesDialog(errors_list, parent=main_window)
        qtbot.addWidget(dlg)
        assert dlg.table.rowCount() == 1
        assert dlg.table.item(0, 0).text() == str(tmp_path / "locked.txt")  # type: ignore[union-attr]
        assert dlg.table.item(0, 1).text() == "Permission denied"  # type: ignore[union-attr]

    def test_scenario_11_large_file_streaming(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 11: Large file search without memory explosion."""
        large_file = tmp_path / "large.txt"
        # Write 5,000 lines with match on line 4,999
        lines = ["normal line content\n" for _ in range(4998)]
        lines.append("target_needle_in_large_file\n")
        lines.append("final line\n")
        large_file.write_text("".join(lines), encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("target_needle_in_large_file")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert res.line_number == 4999

    def test_scenario_12_cp949_file_search(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Scenario 12: CP949 Korean legacy encoded file search and preview."""
        cp949_file = tmp_path / "legacy_korean.txt"
        cp949_content = "공지사항\n대한민국 파일 검색 테스트\n끝\n"
        cp949_file.write_bytes(cp949_content.encode("cp949"))

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("대한민국")

        main_window.on_start_search()
        assert main_window.search_worker is not None
        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            pass

        assert main_window.table_model.rowCount() == 1
        res = main_window.table_model.get_result(0)
        assert res is not None
        assert "대한민국" in res.matched_line
        assert res.encoding in ("cp949", "euc-kr")

    def test_scenario_13_cancellation_preserves_results(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 13: Search cancellation preserves already found results and updates status."""
        for i in range(20):
            (tmp_path / f"doc_{i:02d}.txt").write_text(f"match_token in file {i}\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("match_token")
        main_window._worker_batch_size = 1

        orig_stream_lines = FileScanner.stream_lines

        def cooperative_stream_lines(scanner_self: Any, path: Path, *args: Any, **kwargs: Any) -> Any:
            yield from orig_stream_lines(scanner_self, path, *args, **kwargs)
            cancel_evt = kwargs.get("cancel_event")
            if cancel_evt is not None and not cancel_evt.is_set():
                cancel_evt.wait(timeout=0.05)

        monkeypatch.setattr(FileScanner, "stream_lines", cooperative_stream_lines)

        main_window.on_start_search()
        assert main_window.search_worker is not None

        # Wait until at least 1 result arrives, then cancel while search is in-flight
        qtbot.waitUntil(lambda: main_window.table_model.rowCount() >= 1, timeout=3000)
        assert main_window.search_worker.isRunning() is True

        with qtbot.waitSignal(main_window.search_worker.search_completed, timeout=5000):
            main_window.on_cancel_search()

        # Verify results preserved
        assert main_window.table_model.rowCount() >= 1
        assert "검색 취소됨" in main_window.status_bar.currentMessage()
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False

    def test_scenario_14_csv_export_utf8_bom(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 14: CSV export creates UTF-8 BOM file with exact required columns."""
        res1 = SearchResult(tmp_path / "a.py", "a.py", 12, "print('한국어')", 0, 5, "utf-8")
        res2 = SearchResult(tmp_path / "b.txt", "b.txt", 42, "second, match with 'quotes'", 0, 6, "cp949")
        main_window.table_model.append_batch([res1, res2])

        target_csv = tmp_path / "results_exported.csv"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda parent, caption, dir, filter: (str(target_csv), "CSV"),
        )
        monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

        main_window.on_export_csv()
        assert target_csv.exists()

        raw_bytes = target_csv.read_bytes()
        assert raw_bytes.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM

        decoded_text = raw_bytes.decode("utf-8-sig")
        lines = decoded_text.strip().splitlines()
        assert lines[0] == "file_name,file_path,line_number,matched_line,encoding"
        assert len(lines) == 3
        assert "한국어" in decoded_text

    def test_scenario_15_double_click_row_opens_default_app(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 15: Double clicking result row calls platform_utils.open_file_in_default_app."""
        target_file = tmp_path / "target_code.py"
        target_file.write_text("print('test')\n", encoding="utf-8")

        res = SearchResult(target_file, "target_code.py", 1, "print('test')", 0, 5, "utf-8")
        main_window.table_model.append_batch([res])

        opened_paths: list[Path] = []

        def mock_open(p: Any) -> bool:
            opened_paths.append(Path(p))
            return True

        monkeypatch.setattr(
            "app.utils.platform_utils.open_file_in_default_app",
            mock_open,
        )

        index = main_window.table_model.index(0, 1)
        main_window.on_table_double_clicked(index)

        assert len(opened_paths) == 1
        assert opened_paths[0].resolve() == target_file.resolve()


# ==============================================================================
# 3. Model, Sorting & Virtualization Tests
# ==============================================================================


class TestResultsTableModel:
    """Test ResultsTableModel virtualization, columns, data roles, and sorting."""

    def test_table_model_columns_and_data_roles(self, tmp_path: Path) -> None:
        model = ResultsTableModel()
        assert model.columnCount() == 5
        assert [model.headerData(i, Qt.Orientation.Horizontal) for i in range(5)] == [
            "#",
            "Filename",
            "Path",
            "Line",
            "Matched Content",
        ]

        p = tmp_path / "sample.py"
        res = SearchResult(p, "sample.py", 100, "def foo():", 4, 7, "utf-8")
        model.append_batch([res])

        assert model.rowCount() == 1
        idx0 = model.index(0, 0)
        idx1 = model.index(0, 1)
        idx2 = model.index(0, 2)
        idx3 = model.index(0, 3)
        idx4 = model.index(0, 4)

        assert model.data(idx0, Qt.ItemDataRole.DisplayRole) == "1"
        assert model.data(idx1, Qt.ItemDataRole.DisplayRole) == "sample.py"
        assert model.data(idx2, Qt.ItemDataRole.DisplayRole) == str(p)
        assert model.data(idx3, Qt.ItemDataRole.DisplayRole) == "100"
        assert model.data(idx4, Qt.ItemDataRole.DisplayRole) == "def foo():"

        assert model.data(idx0, Qt.ItemDataRole.TextAlignmentRole) == int(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        assert model.data(idx1, Qt.ItemDataRole.TextAlignmentRole) == int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        assert model.data(idx0, Qt.ItemDataRole.UserRole) == res

    def test_table_model_sorting_by_columns(self, tmp_path: Path) -> None:
        model = ResultsTableModel()
        r1 = SearchResult(tmp_path / "b.txt", "b.txt", 50, "beta line", 0, 4, "utf-8")
        r2 = SearchResult(tmp_path / "a.txt", "a.txt", 10, "alpha line", 0, 5, "utf-8")
        r3 = SearchResult(tmp_path / "a.txt", "a.txt", 20, "gamma line", 0, 5, "utf-8")
        model.append_batch([r1, r2, r3])

        # Sort Column 1: Filename ascending
        model.sort(1, Qt.SortOrder.AscendingOrder)
        assert model.get_result(0).file_name == "a.txt"  # type: ignore[union-attr]
        assert model.get_result(1).file_name == "a.txt"  # type: ignore[union-attr]
        assert model.get_result(2).file_name == "b.txt"  # type: ignore[union-attr]

        # Sort Column 3: Line ascending
        model.sort(3, Qt.SortOrder.AscendingOrder)
        assert model.get_result(0).line_number == 10  # type: ignore[union-attr]
        assert model.get_result(1).line_number == 20  # type: ignore[union-attr]
        assert model.get_result(2).line_number == 50  # type: ignore[union-attr]

        # Sort Column 3: Line descending
        model.sort(3, Qt.SortOrder.DescendingOrder)
        assert model.get_result(0).line_number == 50  # type: ignore[union-attr]
        assert model.get_result(2).line_number == 10  # type: ignore[union-attr]

    def test_table_model_clear(self, tmp_path: Path) -> None:
        model = ResultsTableModel()
        model.append_batch([SearchResult(tmp_path / "x.py", "x.py", 1, "test", 0, 4, "utf-8")])
        assert model.rowCount() == 1
        model.clear()
        assert model.rowCount() == 0
        assert model.get_result(0) is None


# ==============================================================================
# 4. Settings Dialog & Persistence Tests
# ==============================================================================


class TestSettingsDialogAndPersistence:
    """Verify SettingsDialog configuration and QSettings persistence."""

    def test_settings_dialog_load_and_save(self, qtbot: QtBot) -> None:
        dlg = SettingsDialog()
        qtbot.addWidget(dlg)

        # Modify values
        dlg.ext_input.setText(".py, .rs, .go")
        dlg.cb_case.setChecked(True)
        dlg.cb_regex.setChecked(True)
        dlg.cb_recursive.setChecked(False)
        dlg.cb_hidden.setChecked(True)
        dlg.spin_workers.setValue(16)
        dlg.spin_context.setValue(8)

        dlg.save_settings()

        # Read back from QSettings
        settings = QSettings("FileFinder", "FileFinder")
        assert settings.value("extensions") == ".py, .rs, .go"
        assert settings.value("case_sensitive") is True
        assert settings.value("is_regex") is True
        assert settings.value("recursive") is False
        assert settings.value("include_hidden") is True
        assert int(str(settings.value("max_workers"))) == 16
        assert int(str(settings.value("context_lines"))) == 8

    def test_settings_dialog_restore_defaults(self, qtbot: QtBot) -> None:
        dlg = SettingsDialog()
        qtbot.addWidget(dlg)

        dlg.ext_input.setText(".custom")
        dlg.cb_case.setChecked(True)
        dlg.spin_context.setValue(15)

        dlg.restore_defaults()

        assert ".txt" in dlg.ext_input.text()
        assert dlg.cb_case.isChecked() is False
        assert dlg.spin_context.value() == 5

    def test_main_window_settings_save_and_restore(self, qtbot: QtBot, tmp_path: Path) -> None:
        win1 = MainWindow()
        qtbot.addWidget(win1)

        win1.path_input.setText(str(tmp_path))
        win1.query_input.setText("saved_query")
        win1.cb_case.setChecked(True)
        win1.cb_regex.setChecked(True)
        win1.save_settings()

        win2 = MainWindow()
        qtbot.addWidget(win2)
        assert win2.path_input.text() == str(tmp_path)
        assert win2.query_input.text() == "saved_query"
        assert win2.cb_case.isChecked() is True
        assert win2.cb_regex.isChecked() is True


# ==============================================================================
# 5. Dialogs: AboutDialog, ErrorFilesDialog, and Drag-and-Drop
# ==============================================================================


class TestDialogsAndInteractions:
    """Verify AboutDialog text, ErrorFilesDialog interactions, and drag & drop."""

    def test_about_dialog_metadata_exact_text(self, qtbot: QtBot) -> None:
        dlg = AboutDialog()
        qtbot.addWidget(dlg)

        labels = dlg.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]

        assert APP_NAME in texts
        assert APP_SUBTITLE in texts
        assert f"Version {APP_VERSION}" in texts
        assert APP_DESCRIPTION in texts

    def test_error_files_dialog_copy(self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        errors = [(tmp_path / "a.txt", "Permission denied"), (tmp_path / "b.bin", "Encoding error")]
        dlg = ErrorFilesDialog(errors)
        qtbot.addWidget(dlg)

        copied: list[str] = []

        def mock_copy(text: str) -> bool:
            copied.append(text)
            return True

        monkeypatch.setattr(
            "app.utils.platform_utils.copy_to_clipboard",
            mock_copy,
        )
        monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

        dlg._copy_all_errors()
        assert len(copied) == 1
        assert "Permission denied" in copied[0]
        assert "Encoding error" in copied[0]

    def test_drag_and_drop_folder_and_file(self, main_window: MainWindow, tmp_path: Path) -> None:
        sub_folder = tmp_path / "my_project"
        sub_folder.mkdir()
        code_file = sub_folder / "script.py"
        code_file.write_text("print(1)\n", encoding="utf-8")

        # Mock drop event with folder URL
        class DummyUrl:
            def __init__(self, path: Path) -> None:
                self._path = str(path)

            def toLocalFile(self) -> str:
                return self._path

        class DummyMime:
            def __init__(self, path: Path) -> None:
                self._path = path

            def hasUrls(self) -> bool:
                return True

            def urls(self) -> list[DummyUrl]:
                return [DummyUrl(self._path)]

        class DummyDropEvent:
            def __init__(self, path: Path) -> None:
                self._mime = DummyMime(path)

            def mimeData(self) -> DummyMime:
                return self._mime

            def acceptProposedAction(self) -> None:
                pass

        # 1. Dropping a folder sets the folder directly
        main_window.dropEvent(DummyDropEvent(sub_folder))  # type: ignore[arg-type]
        assert main_window.path_input.text() == str(sub_folder)

        # 2. Dropping a file sets the file's parent directory
        main_window.dropEvent(DummyDropEvent(code_file))  # type: ignore[arg-type]
        assert main_window.path_input.text() == str(sub_folder)


# ==============================================================================
# 6. Styling, Preview Highlighting, and Context Menu Tests
# ==============================================================================


class TestStylingAndContextPreview:
    """Verify HTML generation, line highlighting, and context menu actions."""

    def test_stylesheet_loading(self) -> None:
        qss = get_application_stylesheet()
        assert "QMainWindow" in qss
        assert "#search_btn" in qss
        assert "#cancel_btn" in qss
        assert "#error_btn" in qss
        assert "QTableView" in qss

    def test_highlight_line_text_plain_and_regex(self) -> None:
        # Plain text match
        res_plain = highlight_line_text("Hello World from Python", "World", is_regex=False)
        assert "<mark style=" in res_plain
        assert "World</mark>" in res_plain

        # Case-insensitive match
        res_ci = highlight_line_text("Hello world from Python", "WORLD", is_regex=False, case_sensitive=False)
        assert "world</mark>" in res_ci

        # Regex match
        res_regex = highlight_line_text("Version 1234 published", r"\d+", is_regex=True)
        assert "1234</mark>" in res_regex

        # HTML characters escaped safely
        res_escape = highlight_line_text("if (x < 10 && y > 20) { match }", "match")
        assert "&lt; 10 &amp;&amp; y &gt; 20" in res_escape

    def test_get_preview_html_with_context_lines(self) -> None:
        context_lines = [
            (10, "line 10"),
            (11, "line 11 with match_target"),
            (12, "line 12"),
        ]
        html_out = get_preview_html(context_lines, target_line=11, search_term="match_target")
        assert "▶" in html_out
        assert "11" in html_out
        assert "<mark style=" in html_out
        assert "match_target</mark>" in html_out

    def test_recent_search_history_limit_and_recall(self, main_window: MainWindow) -> None:
        # Push 12 searches
        for i in range(12):
            main_window._add_to_history(f"/path/{i}", f"query_{i}")

        assert len(main_window._recent_searches) == 10
        assert main_window._recent_searches[0] == ["/path/11", "query_11"]
        assert main_window._recent_searches[9] == ["/path/2", "query_2"]

        # Populate from history
        main_window._populate_history_item("/path/5", "query_5")
        assert main_window.path_input.text() == "/path/5"
        assert main_window.query_input.text() == "query_5"

    def test_context_menu_copy_actions(
        self, main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        test_path = tmp_path / "item.py"
        res = SearchResult(test_path, "item.py", 42, "matched line text", 0, 5, "utf-8")
        main_window.table_model.append_batch([res])

        copied: list[str] = []

        def mock_clipboard(t: str) -> bool:
            copied.append(t)
            return True

        monkeypatch.setattr(
            "app.utils.platform_utils.copy_to_clipboard",
            mock_clipboard,
        )

        captured_menus: list[QMenu] = []

        class MockMenu(QMenu):
            def exec(self, *args: Any, **kwargs: Any) -> Any:
                captured_menus.append(self)
                return None

        monkeypatch.setattr("app.gui.main_window.QMenu", MockMenu)

        # Set current index to row 0
        idx0 = main_window.table_model.index(0, 0)
        main_window.results_table.setCurrentIndex(idx0)

        # Request context menu
        main_window.on_context_menu_requested(QPoint(10, 10))

        assert len(captured_menus) == 1
        menu = captured_menus[0]

        # Trigger each copy action in the menu
        copy_path_act = next(a for a in menu.actions() if "경로" in a.text())
        copy_name_act = next(a for a in menu.actions() if "파일명" in a.text())
        copy_line_act = next(a for a in menu.actions() if "매치" in a.text())

        copy_path_act.trigger()
        copy_name_act.trigger()
        copy_line_act.trigger()

        assert copied == [str(test_path), "item.py", "matched line text"]
