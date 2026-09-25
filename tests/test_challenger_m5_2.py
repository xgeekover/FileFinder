"""Adversarial challenger test suite for FileFinder Phase 5 PySide6 GUI.

Focuses on corner cases, error boundaries, and defensive programming invariants:
1. Korean Validation Invariants: empty/whitespace path, nonexistent path, empty/whitespace query,
   invalid regex patterns (e.g. `[a-z(`), verifying exact Korean dialog text and ensuring no worker thread starts.
2. Drag-and-drop edge cases: folder dragging, file dragging (parent directory resolution),
   non-existent paths, non-URL mime data, web URLs, symlinks, special character filenames.
3. Rapid UI interactions: rapid search triggers, search -> immediate cancel -> restart search,
   clear results while worker is actively running, cancellation race conditions.
4. Settings persistence resilience: corrupted QSettings keys (malformed JSON, corrupted geometry,
   corrupted booleans, out-of-range worker/context values), missing settings fallback.
5. Rich text preview formatting: HTML escaping verification on files containing `<script>`,
   `&amp;`, quotes, embedded null bytes, extremely long lines (50k+ chars), and regex edge cases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QByteArray, QMimeData, QSettings, QUrl
from PySide6.QtWidgets import QMessageBox, QTextEdit
from pytestqt.qtbot import QtBot

from app.core.search_engine import SearchEngine
from app.gui.main_window import MainWindow
from app.gui.settings_dialog import SettingsDialog
from app.gui.styles import (
    MATCH_HIGHLIGHT_STYLE,
    get_preview_html,
    highlight_line_text,
)


@pytest.fixture(autouse=True)
def isolated_qsettings() -> Any:
    """Ensure clean QSettings environment for each test."""
    settings = QSettings("FileFinder", "FileFinder")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()


@pytest.fixture
def main_window(qtbot: QtBot) -> MainWindow:
    """Instantiate and manage a clean MainWindow instance."""
    window = MainWindow()
    qtbot.addWidget(window)
    return window


# ==============================================================================
# Helper Mock Drop Events
# ==============================================================================


class MockDropEvent:
    """Mock drop event for testing drag-and-drop handler."""

    def __init__(self, mime: QMimeData) -> None:
        self._mime = mime
        self._accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        self._accepted = True

    def isAccepted(self) -> bool:
        return self._accepted


class MockDragEnterEvent:
    """Mock drag enter event for testing drag enter handler."""

    def __init__(self, mime: QMimeData) -> None:
        self._mime = mime
        self._accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        self._accepted = True

    def ignore(self) -> None:
        self._accepted = False

    def isAccepted(self) -> bool:
        return self._accepted


# ==============================================================================
# 1. Korean Validation Invariants
# ==============================================================================


class TestKoreanValidationInvariants:
    """Adversarial testing of input validation rules and exact Korean dialog messages."""

    def test_validation_empty_path_worker_not_started(
        self, main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty path must display exact Korean warning and must NOT start a search worker."""
        main_window.path_input.setText("")
        main_window.query_input.setText("keyword")

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더를 선택해주세요."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "검색 폴더를 선택해주세요.")
        assert main_window.search_worker is None
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False

    @pytest.mark.parametrize(
        "whitespace_path",
        [
            " ",
            "   ",
            "\t",
            "\n",
            " \t \r\n  ",
        ],
    )
    def test_validation_whitespace_path_worker_not_started(
        self, main_window: MainWindow, whitespace_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only paths must be treated as empty, showing exact Korean warning."""
        main_window.path_input.setText(whitespace_path)
        main_window.query_input.setText("keyword")

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더를 선택해주세요."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "검색 폴더를 선택해주세요.")
        assert main_window.search_worker is None

    def test_validation_nonexistent_path_worker_not_started(
        self, main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent path must display exact Korean warning and must NOT start worker."""
        nonexistent = "/path/that/does/not/exist/definitely_not_12345"
        main_window.path_input.setText(nonexistent)
        main_window.query_input.setText("keyword")

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더가 존재하지 않습니다."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "검색 폴더가 존재하지 않습니다.")
        assert main_window.search_worker is None
        assert main_window.btn_search.isEnabled() is True

    def test_validation_empty_query_worker_not_started(
        self, main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty query must display exact Korean warning and must NOT start a search worker."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("")

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색어를 입력해주세요."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "검색어를 입력해주세요.")
        assert main_window.search_worker is None

    @pytest.mark.parametrize(
        "whitespace_query",
        [
            " ",
            "   ",
            "\t",
            "\n",
            " \r\n \t ",
        ],
    )
    def test_validation_whitespace_query_worker_not_started(
        self, main_window: MainWindow, tmp_path: Path, whitespace_query: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whitespace-only query must be treated as empty, showing exact Korean warning."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText(whitespace_query)

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색어를 입력해주세요."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "검색어를 입력해주세요.")
        assert main_window.search_worker is None

    @pytest.mark.parametrize(
        "malformed_regex",
        [
            "[a-z(",  # The exact case specified in the objective
            "([a-z]",
            "*abc",
            "?",
            "++",
            "(?<",
            "\\",
            "[가-힣(",  # Korean regex syntax error
        ],
    )
    def test_validation_invalid_regex_worker_not_started(
        self, main_window: MainWindow, tmp_path: Path, malformed_regex: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid regex pattern when regex toggle is ON must display exact Korean warning."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText(malformed_regex)
        main_window.cb_regex.setChecked(True)

        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda parent, title, msg: warnings.append((title, msg)),
        )

        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "올바르지 않은 정규식입니다."

        main_window.on_start_search()

        assert len(warnings) == 1
        assert warnings[0] == ("입력 오류", "올바르지 않은 정규식입니다.")
        assert main_window.search_worker is None

    def test_validation_invalid_regex_syntax_is_valid_when_regex_disabled(
        self, main_window: MainWindow, tmp_path: Path
    ) -> None:
        """Special regex characters like `[a-z(` must be treated as valid plain strings when regex is OFF."""
        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("[a-z(")
        main_window.cb_regex.setChecked(False)

        valid, err_msg = main_window.validate_inputs()
        assert valid is True
        assert err_msg is None

    def test_validation_korean_paths_and_queries(
        self, main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Korean directory path and Korean query string validation behavior."""
        korean_dir = tmp_path / "테스트폴더_프로젝트"
        korean_dir.mkdir()

        # Valid Korean path and query
        main_window.path_input.setText(str(korean_dir))
        main_window.query_input.setText("한글검색어")
        main_window.cb_regex.setChecked(False)
        valid, err_msg = main_window.validate_inputs()
        assert valid is True
        assert err_msg is None

        # Nonexistent Korean path
        nonexistent_korean = tmp_path / "존재하지않는폴더_123"
        main_window.path_input.setText(str(nonexistent_korean))
        valid, err_msg = main_window.validate_inputs()
        assert valid is False
        assert err_msg == "검색 폴더가 존재하지 않습니다."

        # Valid Korean regex
        main_window.path_input.setText(str(korean_dir))
        main_window.query_input.setText("[가-힣]+")
        main_window.cb_regex.setChecked(True)
        valid, err_msg = main_window.validate_inputs()
        assert valid is True
        assert err_msg is None


# ==============================================================================
# 2. Drag-and-Drop Edge Cases
# ==============================================================================


class TestDragAndDropEdgeCases:
    """Adversarial stress-testing of drag-and-drop operations on MainWindow."""

    def test_drag_and_drop_folder_sets_directory(self, main_window: MainWindow, tmp_path: Path) -> None:
        """Dragging a directory folder directly updates path_input to that folder."""
        folder = tmp_path / "project_root"
        folder.mkdir()

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(folder))])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert drop_event.isAccepted() is True
        assert main_window.path_input.text() == str(folder.resolve())

    def test_drag_and_drop_file_resolves_parent_directory(self, main_window: MainWindow, tmp_path: Path) -> None:
        """Dragging an individual file sets path_input to its parent directory."""
        parent_dir = tmp_path / "src"
        parent_dir.mkdir()
        file_path = parent_dir / "app.py"
        file_path.write_text("print('hello')", encoding="utf-8")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(file_path))])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert drop_event.isAccepted() is True
        assert main_window.path_input.text() == str(parent_dir.resolve())

    def test_drag_and_drop_korean_path_and_spaces(self, main_window: MainWindow, tmp_path: Path) -> None:
        """Dragging folders/files with spaces and Korean names resolves accurately."""
        korean_folder = tmp_path / "문서 보관함 (중요)"
        korean_folder.mkdir()
        korean_file = korean_folder / "보고서 (최종).txt"
        korean_file.write_text("내용", encoding="utf-8")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(korean_file))])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert drop_event.isAccepted() is True
        assert main_window.path_input.text() == str(korean_folder.resolve())

    def test_drag_and_drop_nonexistent_path(self, main_window: MainWindow, tmp_path: Path) -> None:
        """Dragging a non-existent filesystem path must be safely ignored without crash or corruption."""
        initial_path = "/initial/valid/folder"
        main_window.path_input.setText(initial_path)

        ghost_path = tmp_path / "ghost_dir" / "nonexistent.txt"
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(ghost_path))])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        # path_input should remain unchanged because neither is_file() nor is_dir() is true
        assert main_window.path_input.text() == initial_path

    def test_drag_enter_and_drop_non_url_mime_data(self, main_window: MainWindow) -> None:
        """Dragging non-URL mime data (e.g. text/plain or binary) must be ignored."""
        initial_path = "/keep/this/path"
        main_window.path_input.setText(initial_path)

        # 1. Text/plain mime
        mime_text = QMimeData()
        mime_text.setText("Just some random text, not a URL")

        enter_event = MockDragEnterEvent(mime_text)
        main_window.dragEnterEvent(enter_event)  # type: ignore[arg-type]
        assert enter_event.isAccepted() is False

        drop_event = MockDropEvent(mime_text)
        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert main_window.path_input.text() == initial_path

        # 2. Binary payload mime
        mime_bin = QMimeData()
        mime_bin.setData("application/octet-stream", QByteArray(b"\x00\x01\x02\x03"))

        enter_bin = MockDragEnterEvent(mime_bin)
        main_window.dragEnterEvent(enter_bin)  # type: ignore[arg-type]
        assert enter_bin.isAccepted() is False

        drop_bin = MockDropEvent(mime_bin)
        main_window.dropEvent(drop_bin)  # type: ignore[arg-type]
        assert main_window.path_input.text() == initial_path

    def test_drag_web_url_without_local_file(self, main_window: MainWindow) -> None:
        """Dragging a web URL (http://...) without a local file representation is safely ignored."""
        initial_path = "/unchanged/path"
        main_window.path_input.setText(initial_path)

        mime = QMimeData()
        mime.setUrls([QUrl("https://github.com/geekover/FileFinder")])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert main_window.path_input.text() == initial_path

    def test_drag_multiple_urls_picks_first(self, main_window: MainWindow, tmp_path: Path) -> None:
        """When multiple URLs are dropped, the first URL is safely used."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(dir1)), QUrl.fromLocalFile(str(dir2))])
        drop_event = MockDropEvent(mime)

        main_window.dropEvent(drop_event)  # type: ignore[arg-type]
        assert main_window.path_input.text() == str(dir1.resolve())


# ==============================================================================
# 3. Rapid UI Interactions & Race Conditions
# ==============================================================================


class TestRapidUIInteractions:
    """Stress-test rapid user triggers, cancellation races, and re-entrant actions."""

    def test_rapid_search_reentrance_defense(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Verify behavior when on_start_search is repeatedly called in rapid succession.

        Tests whether the UI guards against spawning conflicting concurrent workers.
        """
        for i in range(50):
            p = tmp_path / f"test_{i}.txt"
            p.write_text(f"line content with match keyword {i}\n" * 10, encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("match keyword")
        main_window._worker_batch_size = 5

        # First trigger
        main_window.on_start_search()
        worker1 = main_window.search_worker
        assert worker1 is not None

        # Immediate rapid second trigger (e.g. key repeat or duplicate signal)
        main_window.on_start_search()
        worker2 = main_window.search_worker
        assert worker2 is not None

        # Wait for all workers to settle
        if worker1.isRunning():
            qtbot.waitUntil(lambda: not worker1.isRunning(), timeout=5000)
        if worker2.isRunning():
            qtbot.waitUntil(lambda: not worker2.isRunning(), timeout=5000)

        # Ensure Qt event loop processes the queued search_completed signal
        qtbot.waitUntil(lambda: main_window.btn_search.isEnabled(), timeout=5000)
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False

    def test_search_immediate_cancel_and_restart(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Search -> immediate cancel -> restart search sequence without deadlock or crash."""
        for i in range(20):
            p = tmp_path / f"race_{i}.txt"
            p.write_text(f"target text in file {i}\n" * 20, encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("target text")
        main_window._worker_batch_size = 2

        # 1. Start search
        main_window.on_start_search()
        worker_initial = main_window.search_worker
        assert worker_initial is not None

        # 2. Immediately cancel search
        main_window.on_cancel_search()
        assert worker_initial.is_cancelled() is True

        # Wait for initial worker to finish
        qtbot.waitUntil(lambda: not worker_initial.isRunning(), timeout=5000)

        # 3. Restart search immediately
        main_window.on_start_search()
        worker_restarted = main_window.search_worker
        assert worker_restarted is not None
        assert worker_restarted is not worker_initial
        assert worker_restarted.is_cancelled() is False

        # Wait for restarted search to complete normally and UI to re-enable
        qtbot.waitUntil(lambda: main_window.btn_search.isEnabled(), timeout=5000)
        assert main_window.table_model.rowCount() > 0
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False

    def test_clear_results_while_worker_running(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Clearing results while worker is actively running must not crash and cleanly resets model."""
        for i in range(40):
            p = tmp_path / f"stream_{i}.txt"
            p.write_text(f"streaming query pattern {i}\n" * 15, encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("streaming query")
        main_window._worker_batch_size = 2
        main_window._worker_flush_interval_sec = 0.02

        main_window.on_start_search()
        worker = main_window.search_worker
        assert worker is not None

        # Wait until some results arrive in the model
        qtbot.waitUntil(lambda: main_window.table_model.rowCount() > 0 or not worker.isRunning(), timeout=5000)

        # Invoke clear results mid-flight
        main_window.on_clear_results()
        assert main_window.table_model.rowCount() == 0
        assert main_window.lbl_results_count.text() == "결과: 0건"

        # Wait for worker to finish
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

        # UI state remains intact
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False

    def test_cancel_when_no_worker_active(self, main_window: MainWindow) -> None:
        """Calling on_cancel_search when no worker is running is a safe no-op."""
        assert main_window.search_worker is None
        main_window.on_cancel_search()
        assert main_window.btn_cancel.isEnabled() is False

    def test_query_input_enter_pressed_during_active_search(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """User pressing Enter on query_input while search is in-flight must not crash or deadlock."""
        for i in range(30):
            p = tmp_path / f"enter_{i}.txt"
            p.write_text(f"constant content {i}\n" * 15, encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("constant content")
        main_window._worker_batch_size = 2

        # 1. Start initial search
        main_window.on_start_search()
        worker1 = main_window.search_worker
        assert worker1 is not None

        # 2. Simulate user hitting Enter on query_input while worker is running
        main_window.query_input.returnPressed.emit()
        worker2 = main_window.search_worker
        assert worker2 is not None

        # Wait for completion
        qtbot.waitUntil(lambda: main_window.btn_search.isEnabled(), timeout=5000)
        assert main_window.btn_search.isEnabled() is True
        assert main_window.btn_cancel.isEnabled() is False


# ==============================================================================
# 4. Settings Persistence Resilience
# ==============================================================================


class TestSettingsPersistenceResilience:
    """Adversarial testing of QSettings recovery against malformed, corrupted, or missing data."""

    def test_missing_settings_fallbacks(self, main_window: MainWindow) -> None:
        """Clean QSettings with missing keys must cleanly load default settings without errors."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.clear()
        settings.sync()

        main_window.load_settings()

        assert main_window.path_input.text() == ""
        assert main_window.query_input.text() == ""
        assert ".txt" in main_window.ext_input.text()
        assert main_window.cb_case.isChecked() is False
        assert main_window.cb_regex.isChecked() is False
        assert main_window.cb_recursive.isChecked() is True
        assert main_window.cb_hidden.isChecked() is False
        assert main_window._recent_searches == []

    @pytest.mark.parametrize(
        "corrupted_history",
        [
            "{not valid json",
            "12345",
            "null",
            "true",
            '"just a plain string"',
            '{"key": "value"}',
            "[1, 2, 3]",
            '["a", "b", "c"]',
            '[["only_one_element"]]',
            '[["too", "many", "elements", "here"]]',
        ],
    )
    def test_corrupted_recent_searches_recovery(
        self, main_window: MainWindow, corrupted_history: str
    ) -> None:
        """Malformed or schema-violating recent_searches JSON falls back gracefully to empty list."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("recent_searches", corrupted_history)
        settings.sync()

        main_window.load_settings()
        assert main_window._recent_searches == []
        # History menu has 1 disabled placeholder action
        assert len(main_window.menu_history.actions()) == 1
        assert main_window.menu_history.actions()[0].text() == "최근 검색 기록 없음"

    def test_recent_searches_non_string_types_typeerror(
        self, main_window: MainWindow
    ) -> None:
        """Adversarial probe: When recent_searches contains non-string elements (e.g. [[123, 456]]),

        clicking the action triggers TypeError in QLineEdit.setText because types were not verified.
        """
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("recent_searches", "[[123, 456]]")
        settings.sync()

        main_window.load_settings()
        assert len(main_window.menu_history.actions()) == 1
        act = main_window.menu_history.actions()[0]
        assert act.text() == "[456] in 123"

        # Triggering the action calls _populate_history_item(123, 456)
        with pytest.raises(TypeError, match="wrong argument types"):
            main_window._populate_history_item(123, 456)  # type: ignore[arg-type]

    def test_corrupted_window_geometry_and_state(self, main_window: MainWindow) -> None:
        """Corrupted or random bytes in window_geometry / window_state must not crash MainWindow."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("window_geometry", "not_a_qbytearray_string")
        settings.setValue("window_state", 98765)
        settings.setValue("splitter_state", QByteArray(b"invalid_corrupted_bytes_12345"))
        settings.sync()

        # Must not raise an exception
        main_window.load_settings()
        assert main_window.isVisible() is not None

    @pytest.mark.parametrize(
        ("case_raw", "expected_bool"),
        [
            ("true", True),
            ("True", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("corrupted_value", False),
            ("", False),
            (None, False),
        ],
    )
    def test_corrupted_boolean_settings_normalization(
        self, main_window: MainWindow, case_raw: Any, expected_bool: bool
    ) -> None:
        """String, numeric, and invalid representations of booleans are safely normalized."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("case_sensitive", case_raw)
        settings.sync()

        main_window.load_settings()
        assert main_window.cb_case.isChecked() == expected_bool

    def test_settings_dialog_corrupted_workers_and_context(self, qtbot: QtBot) -> None:
        """SettingsDialog safely clamps and falls back when max_workers or context_lines are corrupted."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("max_workers", "invalid_non_numeric")
        settings.setValue("context_lines", "also_invalid")
        settings.sync()

        dlg = SettingsDialog()
        qtbot.addWidget(dlg)

        # Fallbacks: recommended worker count and default context lines 5
        recommended = SearchEngine.calculate_max_workers()
        assert dlg.spin_workers.value() == recommended
        assert dlg.spin_context.value() == 5

    def test_settings_save_and_reload_roundtrip(self, main_window: MainWindow) -> None:
        """Full roundtrip save and load preserves options accurately."""
        main_window.path_input.setText("/custom/test/dir")
        main_window.query_input.setText("sample_query")
        main_window.ext_input.setText(".py, .rs")
        main_window.cb_case.setChecked(True)
        main_window.cb_regex.setChecked(True)
        main_window.cb_recursive.setChecked(False)
        main_window.cb_hidden.setChecked(True)
        main_window._recent_searches = [["/dir1", "query1"], ["/dir2", "query2"]]

        main_window.save_settings()

        # Create another window to verify restored state
        another_window = MainWindow()
        assert another_window.path_input.text() == "/custom/test/dir"
        assert another_window.query_input.text() == "sample_query"
        assert another_window.ext_input.text() == ".py, .rs"
        assert another_window.cb_case.isChecked() is True
        assert another_window.cb_regex.isChecked() is True
        assert another_window.cb_recursive.isChecked() is False
        assert another_window.cb_hidden.isChecked() is True
        assert another_window._recent_searches == [["/dir1", "query1"], ["/dir2", "query2"]]

    def test_negative_workers_in_settings_handled_without_unhandled_crash(
        self, main_window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative max_workers in settings does not crash main window and reports error."""
        settings = QSettings("FileFinder", "FileFinder")
        settings.setValue("max_workers", -5)
        settings.sync()

        p = tmp_path / "dummy.txt"
        p.write_text("sample content\n", encoding="utf-8")

        main_window.path_input.setText(str(tmp_path))
        main_window.query_input.setText("sample")

        errors: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda parent, title, msg: errors.append(msg),
        )

        main_window.on_start_search()
        worker = main_window.search_worker
        assert worker is not None

        # Wait for worker to finish and Qt event loop to dispatch error_occurred signal
        qtbot.waitUntil(lambda: len(errors) > 0, timeout=5000)

        # Critical error dialog should have been caught gracefully via on_search_error
        assert len(errors) == 1
        assert "max_workers must be greater than 0" in errors[0]
        assert main_window.btn_search.isEnabled() is True


# ==============================================================================
# 5. Rich Text Preview Formatting & HTML Escaping
# ==============================================================================


class TestRichTextPreviewFormatting:
    """Adversarial testing of HTML escaping, XSS safety, null byte resilience, and long lines."""

    def test_preview_html_escaping_script_tag_in_content(self) -> None:
        """Content containing <script>alert('xss')</script> must be safely HTML escaped."""
        raw_line = '<script type="text/javascript">alert("xss attack & breach");</script>'
        lines = [(10, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=10,
            search_term="alert",
            is_regex=False,
            case_sensitive=False,
        )

        # Raw <script> tag must NOT be present
        assert "<script" not in rendered_html
        assert "</script>" not in rendered_html

        # Escaped entities must be present
        assert "&lt;script" in rendered_html
        assert "&lt;/script&gt;" in rendered_html
        assert "&quot;xss attack &amp; breach&quot;" in rendered_html

        # Highlight tag <mark> must properly wrap matched term 'alert'
        assert f'<mark style="{MATCH_HIGHLIGHT_STYLE}">alert</mark>' in rendered_html

    def test_preview_html_escaping_when_search_query_is_html_tag(self) -> None:
        """When user searches specifically for `<script>`, the highlight itself must be safely escaped."""
        raw_line = "Include <script> tag here and </script> tag there."
        lines = [(1, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=1,
            search_term="<script>",
            is_regex=False,
            case_sensitive=False,
        )

        assert "<script>" not in rendered_html
        assert f'<mark style="{MATCH_HIGHLIGHT_STYLE}">&lt;script&gt;</mark>' in rendered_html

    def test_preview_html_escaping_ampersands_and_entities(self) -> None:
        """Lines containing raw ampersands and existing HTML entities must not suffer double-unescaping."""
        raw_line = "Tom & Jerry && Rick &amp; Morty &lt;special&gt;"
        lines = [(5, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=5,
            search_term="Rick &amp; Morty",
            is_regex=False,
            case_sensitive=False,
        )

        # &amp; in raw text becomes &amp;amp;
        assert "&amp;amp;" in rendered_html
        # Raw & becomes &amp;
        assert "Tom &amp; Jerry &amp;&amp;" in rendered_html

    def test_preview_html_quotes_escaping(self) -> None:
        """Quotes (double and single) in content must be escaped to prevent attribute breakage."""
        raw_line = 'var val = "hello" + \'world\' + `template`;'
        lines = [(3, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=3,
            search_term="hello",
        )

        assert "&quot;hello&quot;" in rendered_html or f'<mark style="{MATCH_HIGHLIGHT_STYLE}">hello</mark>' in rendered_html
        assert "&#x27;world&#x27;" in rendered_html

    def test_preview_html_xss_vectors(self) -> None:
        """Various XSS payload vectors must not result in unescaped HTML elements."""
        payloads = [
            '<img src=x onerror="alert(1)">',
            '<a href="javascript:alert(1)">click me</a>',
            "<svg/onload=alert(1)>",
            '<iframe src="about:blank"></iframe>',
            "<!-- HTML comment -->",
            "<style>body { display: none; }</style>",
        ]

        for idx, payload in enumerate(payloads, start=1):
            rendered_html = get_preview_html(
                lines=[(idx, payload)],
                target_line=idx,
                search_term="alert",
            )
            # Ensure no raw unescaped opening tags remain
            for dangerous in ["<img", "<a href", "<svg", "<iframe", "<!--", "<style"]:
                assert dangerous not in rendered_html

    def test_preview_html_embedded_null_byte_resilience(self, qtbot: QtBot) -> None:
        """Embedded null bytes in preview text must not crash or trigger segmentation fault in QTextEdit."""
        raw_line = "alpha\x00beta\x00gamma target null bytes \x00 omega"
        lines = [(1, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=1,
            search_term="target",
        )

        editor = QTextEdit()
        qtbot.addWidget(editor)
        # Passing HTML with null bytes to QTextEdit should be handled gracefully without exception
        editor.setHtml(rendered_html)
        assert editor.toPlainText() is not None

    def test_preview_html_extremely_long_line_performance(self, qtbot: QtBot) -> None:
        """Lines exceeding 50,000 characters with multiple matches must be processed without freezing."""
        repeated_chunk = "word1 word2 MATCH_TARGET word3 word4 "
        raw_line = repeated_chunk * 1500  # ~57,000 characters
        assert len(raw_line) > 50000

        lines = [(1, raw_line)]
        rendered_html = get_preview_html(
            lines=lines,
            target_line=1,
            search_term="MATCH_TARGET",
        )

        assert "MATCH_TARGET" in rendered_html
        assert f'<mark style="{MATCH_HIGHLIGHT_STYLE}">MATCH_TARGET</mark>' in rendered_html

        editor = QTextEdit()
        qtbot.addWidget(editor)
        editor.setHtml(rendered_html)
        assert editor.toPlainText() is not None

    def test_preview_html_zero_width_regex_matches_no_infinite_loop(self) -> None:
        """Zero-width regex patterns (like ^, $, \\b) must not trigger infinite loop."""
        raw_line = "hello world from boundary test"
        lines = [(1, raw_line)]

        # Testing zero width regex patterns
        for zero_width in ["^", "$", r"\b"]:
            rendered_html = get_preview_html(
                lines=lines,
                target_line=1,
                search_term=zero_width,
                is_regex=True,
            )
            assert "hello world" in rendered_html

    def test_preview_html_malformed_regex_fallback(self) -> None:
        """Malformed regex in preview highlighting falls back safely to plain escaped line."""
        raw_line = "regular line with (unmatched parenthesis"
        lines = [(1, raw_line)]

        rendered_html = get_preview_html(
            lines=lines,
            target_line=1,
            search_term="([a-z",  # unclosed regex group
            is_regex=True,
        )

        assert "regular line with (unmatched parenthesis" in rendered_html

    def test_preview_html_empty_lines_and_formatting(self) -> None:
        """Empty lines sequence displays placeholder message."""
        rendered = get_preview_html(lines=[], target_line=0)
        assert "선택된 매치 미리보기가 없습니다." in rendered

    def test_highlight_line_text_plain_and_regex(self) -> None:
        """Unit test highlight_line_text helper directly with various queries."""
        # Plain text
        res1 = highlight_line_text("Find the needle in the haystack", "needle")
        assert f'<mark style="{MATCH_HIGHLIGHT_STYLE}">needle</mark>' in res1

        # Case insensitive default
        res2 = highlight_line_text("Needle and needle and NEEDLE", "needle", case_sensitive=False)
        assert res2.count("<mark") == 3

        # Case sensitive
        res3 = highlight_line_text("Needle and needle and NEEDLE", "needle", case_sensitive=True)
        assert res3.count("<mark") == 1

        # Empty query
        res4 = highlight_line_text("No search query", "")
        assert res4 == "No search query"
