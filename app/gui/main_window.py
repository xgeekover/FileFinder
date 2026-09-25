"""PySide6 main window and results table model for FileFinder.

Implements high-performance table virtualization (100k+ rows), drag-and-drop folder selection,
syntax-highlighted context preview, non-blocking background search worker integration,
and comprehensive menus and dialogs.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSettings,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.file_filter import FileFilter
from app.core.models import ScanStatistics, SearchOptions, SearchResult
from app.core.search_engine import SearchEngine
from app.gui.search_worker import SearchWorker
from app.gui.settings_dialog import SettingsDialog
from app.gui.styles import (
    get_application_stylesheet,
    get_preview_html,
)
from app.utils import file_utils, platform_utils

logger = logging.getLogger("app.gui.main_window")

APP_NAME = "FileFinder"
APP_SUBTITLE = "Cross-Platform File Content Search Tool"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "Search files quickly across Windows, macOS and Linux."
DEFAULT_EXTENSIONS_STRING = ", ".join(FileFilter.DEFAULT_TEXT_EXTENSIONS)


class ResultsTableModel(QAbstractTableModel):
    """Virtualized table model capable of smoothly rendering 100k+ SearchResult rows."""

    COLUMNS: ClassVar[list[str]] = ["#", "Filename", "Path", "Line", "Matched Content"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: list[SearchResult] = []
        self._sort_column: int = 2
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._results)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._results)):
            return None

        result = self._results[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return f"{index.row() + 1:,}"
            elif col == 1:
                return result.file_name
            elif col == 2:
                return str(result.file_path)
            elif col == 3:
                return f"{result.line_number:,}"
            elif col == 4:
                return result.matched_line

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 3):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 2:
                return str(result.file_path)
            elif col == 4:
                return result.matched_line

        elif role == Qt.ItemDataRole.UserRole:
            return result

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def sort(
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Sort model results by selected column with stable secondary ordering."""
        if not self._results:
            return

        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        reverse = order == Qt.SortOrder.DescendingOrder

        if column == 0:
            pass  # preserve original order or reverse
        elif column == 1:
            self._results.sort(
                key=lambda r: (r.file_name.lower(), str(r.file_path), r.line_number),
                reverse=reverse,
            )
        elif column == 2:
            self._results.sort(
                key=lambda r: (str(r.file_path), r.line_number),
                reverse=reverse,
            )
        elif column == 3:
            self._results.sort(
                key=lambda r: (r.line_number, str(r.file_path)),
                reverse=reverse,
            )
        elif column == 4:
            self._results.sort(
                key=lambda r: (r.matched_line.lower(), str(r.file_path), r.line_number),
                reverse=reverse,
            )

        self.layoutChanged.emit()

    def add_results(self, batch: Sequence[SearchResult]) -> None:
        """Atomically insert a batch of SearchResults into the table model."""
        if not batch:
            return
        first = len(self._results)
        last = first + len(batch) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._results.extend(batch)
        self.endInsertRows()

    def append_batch(self, batch: Sequence[SearchResult]) -> None:
        """Alias for add_results for compatibility with SearchWorker signal naming."""
        self.add_results(batch)

    def clear(self) -> None:
        """Clear all results from the model."""
        self.beginResetModel()
        self._results.clear()
        self.endResetModel()

    def get_result(self, row: int) -> SearchResult | None:
        """Retrieve SearchResult dataclass instance for the given row index."""
        if 0 <= row < len(self._results):
            return self._results[row]
        return None

    def get_all_results(self) -> list[SearchResult]:
        """Return shallow copy of all SearchResult instances."""
        return list(self._results)


class ErrorFilesDialog(QDialog):
    """Modal dialog displaying filesystem scan errors and skipped files."""

    def __init__(
        self,
        errors: Sequence[tuple[Path, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"오류 파일 목록 ({len(errors)}개)")
        self.resize(700, 420)
        self._errors = list(errors)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        lbl = QLabel(f"검색 중 접근할 수 없거나 오류가 발생하여 건너뛴 파일 목록입니다 ({len(errors)}개):")
        layout.addWidget(lbl)

        self.table = QTableWidget(len(errors), 2)
        self.table.setHorizontalHeaderLabels(["파일 경로", "오류 원인"])
        header = self.table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 360)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for row, (err_path, err_msg) in enumerate(errors):
            item_path = QTableWidgetItem(str(err_path))
            item_msg = QTableWidgetItem(str(err_msg))
            item_path.setToolTip(str(err_path))
            item_msg.setToolTip(str(err_msg))
            self.table.setItem(row, 0, item_path)
            self.table.setItem(row, 1, item_msg)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_copy = QPushButton("오류 목록 복사 (Copy All)")
        btn_copy.clicked.connect(self._copy_all_errors)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _copy_all_errors(self) -> None:
        lines = [f"{p}\t{e}" for p, e in self._errors]
        platform_utils.copy_to_clipboard("\n".join(lines))
        QMessageBox.information(self, "복사 완료", "오류 목록이 클립보드에 복사되었습니다.")


class AboutDialog(QDialog):
    """Standard about dialog displaying application metadata and version."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedSize(420, 260)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        lbl_title = QLabel(APP_NAME)
        lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #3b82f6;")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(APP_SUBTITLE)
        lbl_sub.setStyleSheet("font-size: 13px; font-style: italic; color: #94a3b8;")
        layout.addWidget(lbl_sub)

        lbl_ver = QLabel(f"Version {APP_VERSION}")
        lbl_ver.setStyleSheet("font-size: 12px; font-weight: bold;")
        layout.addWidget(lbl_ver)

        lbl_desc = QLabel(APP_DESCRIPTION)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 12px; color: #cbd5e1; margin-top: 6px;")
        layout.addWidget(lbl_desc)

        layout.addStretch()

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)


class MainWindow(QMainWindow):
    """FileFinder main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - {APP_SUBTITLE}")
        self.resize(1100, 750)
        self.setMinimumSize(800, 500)
        self.setAcceptDrops(True)

        # Set application icon if available
        icon_path = Path(__file__).resolve().parent.parent.parent / "resources" / "icons" / "icon_64x64.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._settings = QSettings("FileFinder", "FileFinder")
        self._search_worker: SearchWorker | None = None
        self._last_stats: ScanStatistics | None = None
        self._last_query: str = ""
        self._last_is_regex: bool = False
        self._last_case_sensitive: bool = False
        self._recent_searches: list[list[str]] = []
        self._worker_batch_size: int = 250
        self._worker_flush_interval_sec: float = 0.1
        self._context_menu: QMenu | None = None

        self._setup_ui()
        self._setup_menu_bar()
        self.load_settings()

    @property
    def search_worker(self) -> SearchWorker | None:
        """Public accessor for the active or last SearchWorker instance."""
        return self._search_worker

    def _setup_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Top Control Panel
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        # Row 1: Folder Selection
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        lbl_folder = QLabel("검색 폴더:")
        lbl_folder.setFixedWidth(75)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("검색할 폴더 경로를 선택하거나 드래그 앤 드롭하세요...")

        self.btn_browse = QPushButton("찾아보기...")
        self.btn_browse.clicked.connect(self.on_browse_folder)

        # Recent searches history dropdown button
        self.btn_history = QPushButton("최근 검색 ▾")
        self.menu_history = QMenu(self)
        self.btn_history.setMenu(self.menu_history)

        folder_row.addWidget(lbl_folder)
        folder_row.addWidget(self.path_input)
        folder_row.addWidget(self.btn_browse)
        folder_row.addWidget(self.btn_history)
        control_layout.addLayout(folder_row)

        # Row 2: Search Query Input
        query_row = QHBoxLayout()
        query_row.setSpacing(8)
        lbl_query = QLabel("검색어:")
        lbl_query.setFixedWidth(75)
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("검색할 문자열 또는 정규표현식을 입력하세요 (Enter 키로 검색)")
        self.query_input.returnPressed.connect(self.on_start_search)

        self.btn_search = QPushButton("검색")
        self.btn_search.setObjectName("search_btn")
        self.btn_search.setFixedWidth(90)
        self.btn_search.clicked.connect(self.on_start_search)

        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setObjectName("cancel_btn")
        self.btn_cancel.setFixedWidth(90)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.on_cancel_search)

        query_row.addWidget(lbl_query)
        query_row.addWidget(self.query_input)
        query_row.addWidget(self.btn_search)
        query_row.addWidget(self.btn_cancel)
        control_layout.addLayout(query_row)

        # Row 3: Search Options and Extension Whitelist
        options_row = QHBoxLayout()
        options_row.setSpacing(14)

        self.cb_case = QCheckBox("대소문자 구분")
        self.cb_regex = QCheckBox("정규식 사용")
        self.cb_recursive = QCheckBox("하위 폴더 포함")
        self.cb_recursive.setChecked(True)
        self.cb_hidden = QCheckBox("숨김 파일 포함")

        lbl_ext = QLabel("확장자:")
        self.ext_input = QLineEdit()
        self.ext_input.setText(DEFAULT_EXTENSIONS_STRING)
        self.ext_input.setPlaceholderText(".txt, .py, .md (비워두면 모든 파일)")

        options_row.addWidget(self.cb_case)
        options_row.addWidget(self.cb_regex)
        options_row.addWidget(self.cb_recursive)
        options_row.addWidget(self.cb_hidden)
        options_row.addWidget(lbl_ext)
        options_row.addWidget(self.ext_input)
        control_layout.addLayout(options_row)

        main_layout.addWidget(control_panel)

        # Center: Vertical Splitter (Results Table + Preview Panel)
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        # Results Table
        self.table_model = ResultsTableModel(self)
        self.results_table = QTableView()
        self.results_table.setModel(self.table_model)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.results_table.setSortingEnabled(True)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.on_context_menu_requested)
        self.results_table.doubleClicked.connect(self.on_table_double_clicked)

        # Table Column Widths
        header = self.results_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.results_table.setColumnWidth(1, 180)
        self.results_table.setColumnWidth(2, 340)

        # Wire selection to preview panel
        sel_model = self.results_table.selectionModel()
        if sel_model is not None:
            sel_model.currentRowChanged.connect(self.on_current_row_changed)

        self.splitter.addWidget(self.results_table)

        # Preview Panel Container
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        self.lbl_preview_header = QLabel("파일 미리보기 (±5 Context Lines):")
        self.lbl_preview_header.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 11px;")
        preview_layout.addWidget(self.lbl_preview_header)

        self.preview_panel = QTextEdit()
        self.preview_panel.setObjectName("preview_panel")
        self.preview_panel.setReadOnly(True)
        self.preview_panel.setPlaceholderText("검색 결과를 선택하면 일치 항목 전후 ±5줄이 하이라이트 표시됩니다.")
        preview_layout.addWidget(self.preview_panel)

        self.splitter.addWidget(preview_container)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        main_layout.addWidget(self.splitter)

        # Bottom Telemetry & Progress
        bottom_bar = QWidget()
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(0, 4, 0, 0)
        bottom_layout.setSpacing(10)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)

        self.lbl_stats = QLabel("대기 중")
        self.lbl_stats.setStyleSheet("font-weight: 500;")

        self.lbl_results_count = QLabel("결과: 0건")
        self.lbl_results_count.setStyleSheet("font-weight: bold; color: #3b82f6;")

        self.btn_errors = QPushButton("[오류 파일 0개]")
        self.btn_errors.setObjectName("error_btn")
        self.btn_errors.setEnabled(False)
        self.btn_errors.clicked.connect(self.on_show_errors_dialog)

        bottom_layout.addWidget(self.progress_bar, 2)
        bottom_layout.addWidget(self.lbl_stats, 2)
        bottom_layout.addWidget(self.lbl_results_count, 1)
        bottom_layout.addWidget(self.btn_errors)
        main_layout.addWidget(bottom_bar)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("준비 완료")

        # Apply global application stylesheet
        self.setStyleSheet(get_application_stylesheet())

    def _setup_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        # File Menu
        menu_file = menu_bar.addMenu("&File")

        act_open = QAction("검색 폴더 열기... (Open Folder)", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.on_browse_folder)
        menu_file.addAction(act_open)

        self.act_export = QAction("결과 내보내기... (Export CSV)", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self.on_export_csv)
        menu_file.addAction(self.act_export)

        menu_file.addSeparator()

        act_exit = QAction("종료 (Exit)", self)
        act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        act_exit.triggered.connect(self.close)
        menu_file.addAction(act_exit)

        # Search Menu
        menu_search = menu_bar.addMenu("&Search")

        self.act_start_search = QAction("검색 시작 (Start Search)", self)
        self.act_start_search.setShortcut(QKeySequence("F5"))
        self.act_start_search.triggered.connect(self.on_start_search)
        menu_search.addAction(self.act_start_search)

        self.act_cancel_search = QAction("검색 취소 (Cancel Search)", self)
        self.act_cancel_search.setShortcut(QKeySequence("Escape"))
        self.act_cancel_search.setEnabled(False)
        self.act_cancel_search.triggered.connect(self.on_cancel_search)
        menu_search.addAction(self.act_cancel_search)

        act_clear = QAction("결과 지우기 (Clear Results)", self)
        act_clear.setShortcut(QKeySequence("Ctrl+L"))
        act_clear.triggered.connect(self.on_clear_results)
        menu_search.addAction(act_clear)

        # Tools Menu
        menu_tools = menu_bar.addMenu("&Tools")
        act_settings = QAction("환경 설정... (Settings)", self)
        act_settings.setShortcut(QKeySequence.StandardKey.Preferences)
        act_settings.triggered.connect(self.on_open_settings)
        menu_tools.addAction(act_settings)

        # Help Menu
        menu_help = menu_bar.addMenu("&Help")
        act_about = QAction("FileFinder 정보 (About)", self)
        act_about.setShortcut(QKeySequence.StandardKey.HelpContents)
        act_about.triggered.connect(self.on_about)
        menu_help.addAction(act_about)

        act_readme = QAction("README 보기 (Open README)", self)
        act_readme.triggered.connect(self.on_open_readme)
        menu_help.addAction(act_readme)

    # --------------------------------------------------------------------------
    # Drag and Drop Events
    # --------------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return

        local_file = urls[0].toLocalFile()
        if not local_file:
            return

        target_path = Path(local_file).resolve()
        if target_path.is_file():
            self.path_input.setText(str(target_path.parent))
        elif target_path.is_dir():
            self.path_input.setText(str(target_path))

        event.acceptProposedAction()

    # --------------------------------------------------------------------------
    # Settings & Persistence
    # --------------------------------------------------------------------------
    def load_settings(self) -> None:
        """Restore window state, geometry, search flags, and history from QSettings."""
        geom = self._settings.value("window_geometry")
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            self.restoreGeometry(geom)

        state = self._settings.value("window_state")
        if isinstance(state, QByteArray) and not state.isEmpty():
            self.restoreState(state)

        splitter_state = self._settings.value("splitter_state")
        if isinstance(splitter_state, QByteArray) and not splitter_state.isEmpty():
            self.splitter.restoreState(splitter_state)

        path_val = self._settings.value("last_path", "")
        self.path_input.setText(str(path_val) if path_val else "")

        query_val = self._settings.value("last_query", "")
        self.query_input.setText(str(query_val) if query_val else "")

        ext_val = self._settings.value("extensions", DEFAULT_EXTENSIONS_STRING)
        self.ext_input.setText(str(ext_val) if ext_val else DEFAULT_EXTENSIONS_STRING)

        case_val = self._settings.value("case_sensitive", False)
        self.cb_case.setChecked(str(case_val).lower() in ("true", "1") if not isinstance(case_val, bool) else case_val)

        regex_val = self._settings.value("is_regex", False)
        self.cb_regex.setChecked(str(regex_val).lower() in ("true", "1") if not isinstance(regex_val, bool) else regex_val)

        rec_val = self._settings.value("recursive", True)
        self.cb_recursive.setChecked(str(rec_val).lower() in ("true", "1") if not isinstance(rec_val, bool) else rec_val)

        hidden_val = self._settings.value("include_hidden", False)
        self.cb_hidden.setChecked(str(hidden_val).lower() in ("true", "1") if not isinstance(hidden_val, bool) else hidden_val)

        # Restore recent searches history
        history_raw = self._settings.value("recent_searches", "[]")
        try:
            parsed = json.loads(str(history_raw))
            if isinstance(parsed, list):
                self._recent_searches = [item for item in parsed if isinstance(item, list) and len(item) == 2]
            else:
                self._recent_searches = []
        except (ValueError, TypeError):
            self._recent_searches = []
        self._update_history_menu()

    def save_settings(self) -> None:
        """Persist window state, geometry, options, and history into QSettings."""
        self._settings.setValue("window_geometry", self.saveGeometry())
        self._settings.setValue("window_state", self.saveState())
        self._settings.setValue("splitter_state", self.splitter.saveState())
        self._settings.setValue("last_path", self.path_input.text().strip())
        self._settings.setValue("last_query", self.query_input.text().strip())
        self._settings.setValue("extensions", self.ext_input.text().strip())
        self._settings.setValue("case_sensitive", self.cb_case.isChecked())
        self._settings.setValue("is_regex", self.cb_regex.isChecked())
        self._settings.setValue("recursive", self.cb_recursive.isChecked())
        self._settings.setValue("include_hidden", self.cb_hidden.isChecked())
        self._settings.setValue("recent_searches", json.dumps(self._recent_searches))
        self._settings.sync()

    def closeEvent(self, event: Any) -> None:
        """Handle window close event: cancel active search and save settings."""
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_worker.cancel()
            self._search_worker.wait(2000)
        self.save_settings()
        event.accept()

    # --------------------------------------------------------------------------
    # Input Validation
    # --------------------------------------------------------------------------
    def validate_inputs(self) -> tuple[bool, str | None]:
        """Validate search parameters against specifications.

        Returns:
            Tuple of (is_valid, error_message).
        """
        path_text = self.path_input.text().strip()
        query_text = self.query_input.text().strip()

        if not path_text:
            return False, "검색 폴더를 선택해주세요."

        resolved_path = Path(path_text).expanduser()
        if not resolved_path.exists():
            return False, "검색 폴더가 존재하지 않습니다."

        if not query_text:
            return False, "검색어를 입력해주세요."

        if self.cb_regex.isChecked():
            flags = re.NOFLAG if self.cb_case.isChecked() else re.IGNORECASE
            try:
                re.compile(query_text, flags)
            except re.error:
                return False, "올바르지 않은 정규식입니다."

        return True, None

    # --------------------------------------------------------------------------
    # Search Execution Flow
    # --------------------------------------------------------------------------
    def on_start_search(self) -> None:
        """Validate inputs and launch background SearchWorker."""
        valid, err_msg = self.validate_inputs()
        if not valid and err_msg:
            QMessageBox.warning(self, "입력 오류", err_msg)
            return

        path_text = self.path_input.text().strip()
        query_text = self.query_input.text().strip()

        # Add to recent search history
        self._add_to_history(path_text, query_text)

        # Clear previous results and error indicators
        self.table_model.clear()
        self.preview_panel.clear()
        self.lbl_results_count.setText("결과: 0건")
        self.btn_errors.setText("[오류 파일 0개]")
        self.btn_errors.setEnabled(False)
        self._last_stats = None

        # Build options
        parsed_exts = file_utils.parse_extensions_string(self.ext_input.text())
        options = SearchOptions(
            path=Path(path_text).expanduser().resolve(),
            query=query_text,
            is_regex=self.cb_regex.isChecked(),
            case_sensitive=self.cb_case.isChecked(),
            recursive=self.cb_recursive.isChecked(),
            include_hidden=self.cb_hidden.isChecked(),
            extensions=parsed_exts,
        )

        self._last_query = query_text
        self._last_is_regex = options.is_regex
        self._last_case_sensitive = options.case_sensitive

        # Retrieve thread worker count from QSettings
        default_workers = SearchEngine.calculate_max_workers()
        try:
            max_workers = int(str(self._settings.value("max_workers", default_workers)))
        except (ValueError, TypeError):
            max_workers = default_workers

        engine = SearchEngine(max_workers=max_workers)

        # UI state transitions
        self.btn_search.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.act_start_search.setEnabled(False)
        self.act_cancel_search.setEnabled(True)
        self.progress_bar.setMaximum(0)  # indeterminate until total files discovered
        self.progress_bar.setValue(0)
        self.lbl_stats.setText("파일 탐색 중...")
        self.status_bar.showMessage("검색이 시작되었습니다...")

        # Spawn background worker
        self._search_worker = SearchWorker(
            engine=engine,
            options=options,
            batch_size=self._worker_batch_size,
            flush_interval_sec=self._worker_flush_interval_sec,
            parent=self,
        )
        self._search_worker.results_batch_found.connect(self.on_results_batch_found)
        self._search_worker.progress_updated.connect(self.on_progress_updated)
        self._search_worker.search_completed.connect(self.on_search_completed)
        self._search_worker.error_occurred.connect(self.on_search_error)
        self._search_worker.start()

    def on_cancel_search(self) -> None:
        """Cancel the in-flight search while preserving already discovered matches."""
        if self._search_worker is not None and self._search_worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("취소 중...")
            self.status_bar.showMessage("검색 취소 중... 이미 찾은 결과는 보존됩니다.")
            self._search_worker.cancel()

    def on_results_batch_found(self, batch: list[SearchResult]) -> None:
        """Slot receiving batched SearchResult instances from SearchWorker."""
        self.table_model.append_batch(batch)
        self.lbl_results_count.setText(f"결과: {self.table_model.rowCount():,}건")

    def on_progress_updated(self, scanned: int, total: int, current_file: str) -> None:
        """Slot receiving progress metrics from SearchWorker."""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(scanned)
            percent = int((scanned / total) * 100)
            self.lbl_stats.setText(f"{scanned:,} / {total:,} ({percent}%)")
        else:
            self.progress_bar.setMaximum(0)
            self.lbl_stats.setText(f"{scanned:,} 파일 스캔 중...")

        filename = Path(current_file).name if current_file else ""
        self.status_bar.showMessage(f"검색 중: {filename}")

    def on_search_completed(self, stats: ScanStatistics) -> None:
        """Slot invoked upon SearchWorker completion or cancellation."""
        self._last_stats = stats
        self.btn_search.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("취소")
        self.act_start_search.setEnabled(True)
        self.act_cancel_search.setEnabled(False)

        total_results = self.table_model.rowCount()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)

        # Update Error button
        if stats.error_count > 0:
            self.btn_errors.setText(f"[오류 파일 {stats.error_count}개]")
            self.btn_errors.setEnabled(True)
        else:
            self.btn_errors.setText("[오류 파일 0개]")
            self.btn_errors.setEnabled(False)

        # Format completion metrics
        if stats.cancelled:
            msg = (
                f"검색 취소됨: 총 {stats.total_files:,}개 중 {stats.scanned_files:,}개 스캔 "
                f"(성공 {stats.success_count:,}개, 오류 {stats.error_count:,}개) | "
                f"결과 {total_results:,}건 | 소요 시간: {stats.elapsed_seconds:.2f}초"
            )
        else:
            msg = (
                f"검색 완료: 총 {stats.total_files:,}개 파일 "
                f"(성공 {stats.success_count:,}개, 오류 {stats.error_count:,}개) | "
                f"결과 {total_results:,}건 | 소요 시간: {stats.elapsed_seconds:.2f}초"
            )

        self.status_bar.showMessage(msg)
        self.lbl_stats.setText(f"완료 ({stats.elapsed_seconds:.2f}초)")

    def on_search_error(self, message: str) -> None:
        """Slot invoked if SearchWorker encounters an unhandled fatal error."""
        self.btn_search.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("취소")
        self.act_start_search.setEnabled(True)
        self.act_cancel_search.setEnabled(False)
        QMessageBox.critical(self, "검색 오류", f"검색 중 오류가 발생했습니다:\n{message}")

    # --------------------------------------------------------------------------
    # Preview and Table Events
    # --------------------------------------------------------------------------
    def on_current_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Update file preview panel when selected row changes."""
        if not current.isValid():
            self.preview_panel.clear()
            return

        result = self.table_model.get_result(current.row())
        if result is None:
            self.preview_panel.clear()
            return

        try:
            context_lines_count = int(str(self._settings.value("context_lines", 5)))
        except (ValueError, TypeError):
            context_lines_count = 5

        context_lines = file_utils.read_context_lines(
            result.file_path,
            result.line_number,
            context=context_lines_count,
            encoding=result.encoding,
        )

        preview_html = get_preview_html(
            context_lines,
            result.line_number,
            self._last_query,
            is_regex=self._last_is_regex,
            case_sensitive=self._last_case_sensitive,
        )
        self.preview_panel.setHtml(preview_html)
        self.lbl_preview_header.setText(
            f"파일 미리보기: {result.file_name} (Line {result.line_number:,}, {result.encoding})"
        )

    def on_table_double_clicked(self, index: QModelIndex) -> None:
        """Double clicking a result row opens file with OS default application."""
        if not index.isValid():
            return
        result = self.table_model.get_result(index.row())
        if result is not None:
            platform_utils.open_file_in_default_app(result.file_path)

    def on_row_double_clicked(self, index: QModelIndex) -> None:
        """Alias for on_table_double_clicked."""
        self.on_table_double_clicked(index)

    def on_context_menu_requested(self, pos: QPoint) -> None:
        """Construct and display right-click context menu for results table."""
        viewport = self.results_table.viewport()
        index = self.results_table.indexAt(pos)
        if not index.isValid():
            index = self.results_table.currentIndex()
        if not index.isValid():
            return

        result = self.table_model.get_result(index.row())
        if result is None:
            return

        menu = QMenu(self)
        self._context_menu = menu

        act_open = menu.addAction("파일 열기 (Open File)")
        act_open.triggered.connect(
            lambda: platform_utils.open_file_in_default_app(result.file_path)
        )

        act_reveal = menu.addAction("파일 위치 열기 (Reveal in File Manager)")
        act_reveal.triggered.connect(
            lambda: platform_utils.reveal_in_file_manager(result.file_path)
        )

        menu.addSeparator()

        act_copy_path = menu.addAction("파일 경로 복사 (Copy Path)")
        act_copy_path.triggered.connect(
            lambda: platform_utils.copy_to_clipboard(str(result.file_path))
        )

        act_copy_name = menu.addAction("파일명 복사 (Copy Filename)")
        act_copy_name.triggered.connect(
            lambda: platform_utils.copy_to_clipboard(result.file_name)
        )

        act_copy_line = menu.addAction("매치 라인 복사 (Copy Matched Line)")
        act_copy_line.triggered.connect(
            lambda: platform_utils.copy_to_clipboard(result.matched_line)
        )

        menu.exec(viewport.mapToGlobal(pos))

    # --------------------------------------------------------------------------
    # History and Dialog Handlers
    # --------------------------------------------------------------------------
    def _add_to_history(self, path: str, query: str) -> None:
        """Add (path, query) pair to recent search history, preserving max 10 entries."""
        item = [path, query]
        if item in self._recent_searches:
            self._recent_searches.remove(item)
        self._recent_searches.insert(0, item)
        if len(self._recent_searches) > 10:
            self._recent_searches = self._recent_searches[:10]
        self._update_history_menu()

    def _update_history_menu(self) -> None:
        """Refresh the recent search history dropdown menu."""
        self.menu_history.clear()
        if not self._recent_searches:
            act = self.menu_history.addAction("최근 검색 기록 없음")
            act.setEnabled(False)
            return

        for path, query in self._recent_searches:
            display_text = f"[{query}] in {path}"
            act = self.menu_history.addAction(display_text)
            act.triggered.connect(
                lambda checked=False, p=path, q=query: self._populate_history_item(p, q)
            )

    def _populate_history_item(self, path: str, query: str) -> None:
        """Populate input controls when history item is selected."""
        self.path_input.setText(path)
        self.query_input.setText(query)

    def on_browse_folder(self) -> None:
        """Launch directory picker dialog."""
        current = self.path_input.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "검색할 폴더 선택", current, QFileDialog.Option.ShowDirsOnly
        )
        if selected:
            self.path_input.setText(selected)

    def on_export_csv(self) -> None:
        """Export current results to CSV with UTF-8 BOM."""
        all_results = self.table_model.get_all_results()
        if not all_results:
            QMessageBox.information(self, "안내", "내보낼 검색 결과가 없습니다.")
            return

        default_target = str(Path.home() / "filefinder_results.csv")
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "검색 결과 CSV 내보내기",
            default_target,
            "CSV 파일 (*.csv);;모든 파일 (*.*)",
        )
        if not save_path:
            return

        try:
            count = file_utils.export_results_to_csv(all_results, save_path)
            QMessageBox.information(
                self,
                "내보내기 완료",
                f"{count:,}개의 검색 결과가 성공적으로 저장되었습니다:\n{save_path}",
            )
        except OSError as exc:
            logger.error("Failed to export CSV to '%s': %s", save_path, exc)
            QMessageBox.critical(self, "내보내기 실패", f"CSV 파일 저장 중 오류가 발생했습니다:\n{exc}")

    def on_clear_results(self) -> None:
        """Clear current results table and preview panel."""
        self.table_model.clear()
        self.preview_panel.clear()
        self.lbl_results_count.setText("결과: 0건")
        self.btn_errors.setText("[오류 파일 0개]")
        self.btn_errors.setEnabled(False)
        self.status_bar.showMessage("검색 결과가 초기화되었습니다.")

    def on_open_settings(self) -> None:
        """Open modal settings dialog and apply any updated options."""
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.load_settings()

    def on_show_errors_dialog(self) -> None:
        """Display modal skipped/error files dialog."""
        if self._last_stats and self._last_stats.errors:
            dlg = ErrorFilesDialog(self._last_stats.errors, parent=self)
            dlg.exec()

    def on_about(self) -> None:
        """Show About FileFinder dialog."""
        dlg = AboutDialog(self)
        dlg.exec()

    def on_open_readme(self) -> None:
        """Open project README.md using host operating system default application."""
        readme_path = Path(__file__).resolve().parent.parent.parent / "README.md"
        if readme_path.exists():
            platform_utils.open_file_in_default_app(readme_path)
        else:
            QMessageBox.information(self, "안내", "README.md 파일을 찾을 수 없습니다.")
