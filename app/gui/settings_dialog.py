"""Preferences and configuration dialog for FileFinder using QSettings.

Configures default search options, extension whitelists, thread concurrency limits,
and context preview lines.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.file_filter import FileFilter
from app.core.search_engine import SearchEngine
from app.utils.file_utils import parse_extensions_string

DEFAULT_EXTENSIONS_STRING = ", ".join(FileFilter.DEFAULT_TEXT_EXTENSIONS)


class SettingsDialog(QDialog):
    """Modal dialog managing FileFinder persistent settings via QSettings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("환경 설정 (Settings)")
        self.setModal(True)
        self.resize(520, 380)

        self._settings = QSettings("FileFinder", "FileFinder")
        self._setup_ui()
        self.load_settings()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Tabs container
        self.tabs = QTabWidget(self)

        # Tab 1: Search Defaults
        tab_search = QWidget()
        layout_search = QVBoxLayout(tab_search)
        layout_search.setSpacing(12)

        group_ext = QGroupBox("기본 파일 확장자 (Default Extensions)")
        layout_ext = QVBoxLayout(group_ext)
        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText(".txt, .log, .py, ... (비워두면 모든 파일 검색)")
        layout_ext.addWidget(self.ext_input)

        btn_reset_ext = QPushButton("기본 확장자 목록으로 재설정")
        btn_reset_ext.clicked.connect(self._reset_extensions_only)
        layout_ext.addWidget(btn_reset_ext)
        layout_search.addWidget(group_ext)

        group_flags = QGroupBox("기본 검색 옵션 (Default Search Options)")
        layout_flags = QVBoxLayout(group_flags)
        self.cb_case = QCheckBox("대소문자 구분 (Case Sensitive)")
        self.cb_regex = QCheckBox("정규 표현식 검색 (Regular Expression)")
        self.cb_recursive = QCheckBox("하위 폴더 재귀 검색 (Recursive Search)")
        self.cb_hidden = QCheckBox("숨김 파일 및 폴더 포함 (Include Hidden Files)")
        layout_flags.addWidget(self.cb_case)
        layout_flags.addWidget(self.cb_regex)
        layout_flags.addWidget(self.cb_recursive)
        layout_flags.addWidget(self.cb_hidden)
        layout_search.addWidget(group_flags)
        layout_search.addStretch()

        self.tabs.addTab(tab_search, "검색 기본값")

        # Tab 2: Engine Performance
        tab_perf = QWidget()
        layout_perf = QFormLayout(tab_perf)
        layout_perf.setContentsMargins(16, 16, 16, 16)
        layout_perf.setSpacing(12)

        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 64)
        recommended = SearchEngine.calculate_max_workers()
        self.spin_workers.setValue(recommended)

        lbl_workers_hint = QLabel(
            f"시스템 권장 스레드 수: {recommended}개 (CPU 코어 기반 자동 계산)\n"
            "병렬 검색 시 사용할 최대 백그라운드 작업자 스레드 수를 설정합니다."
        )
        lbl_workers_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")

        layout_perf.addRow("최대 스레드 수 (Max Workers):", self.spin_workers)
        layout_perf.addRow("", lbl_workers_hint)

        self.tabs.addTab(tab_perf, "성능 및 스레드")

        # Tab 3: Preview Panel
        tab_preview = QWidget()
        layout_preview = QFormLayout(tab_preview)
        layout_preview.setContentsMargins(16, 16, 16, 16)
        layout_preview.setSpacing(12)

        self.spin_context = QSpinBox()
        self.spin_context.setRange(1, 20)
        self.spin_context.setValue(5)

        lbl_context_hint = QLabel(
            "선택된 검색 결과 매치 라인의 전후 컨텍스트 줄 수를 지정합니다.\n"
            "(기본값: ±5줄, 범위: 1~20줄)"
        )
        lbl_context_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")

        layout_preview.addRow("미리보기 컨텍스트 줄 수:", self.spin_context)
        layout_preview.addRow("", lbl_context_hint)

        self.tabs.addTab(tab_preview, "미리보기")

        main_layout.addWidget(self.tabs)

        # Dialog Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        btn_restore = self.button_box.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if btn_restore is not None:
            btn_restore.clicked.connect(self.restore_defaults)

        main_layout.addWidget(self.button_box)

    def _reset_extensions_only(self) -> None:
        """Reset extension input field to the 38 default extensions."""
        self.ext_input.setText(DEFAULT_EXTENSIONS_STRING)

    def load_settings(self) -> None:
        """Load values from QSettings into dialog widgets."""
        exts_val = self._settings.value("extensions", DEFAULT_EXTENSIONS_STRING)
        self.ext_input.setText(str(exts_val) if exts_val else DEFAULT_EXTENSIONS_STRING)

        case_val = self._settings.value("case_sensitive", False)
        self.cb_case.setChecked(str(case_val).lower() in ("true", "1") if not isinstance(case_val, bool) else case_val)

        regex_val = self._settings.value("is_regex", False)
        self.cb_regex.setChecked(str(regex_val).lower() in ("true", "1") if not isinstance(regex_val, bool) else regex_val)

        rec_val = self._settings.value("recursive", True)
        self.cb_recursive.setChecked(str(rec_val).lower() in ("true", "1") if not isinstance(rec_val, bool) else rec_val)

        hidden_val = self._settings.value("include_hidden", False)
        self.cb_hidden.setChecked(str(hidden_val).lower() in ("true", "1") if not isinstance(hidden_val, bool) else hidden_val)

        default_workers = SearchEngine.calculate_max_workers()
        try:
            workers = int(str(self._settings.value("max_workers", default_workers)))
        except (ValueError, TypeError):
            workers = default_workers
        self.spin_workers.setValue(workers)

        try:
            context = int(str(self._settings.value("context_lines", 5)))
        except (ValueError, TypeError):
            context = 5
        self.spin_context.setValue(context)

    def save_settings(self) -> None:
        """Write dialog widget values into QSettings."""
        raw_ext = self.ext_input.text().strip()
        if raw_ext:
            parsed = parse_extensions_string(raw_ext)
            normalized_str = ", ".join(parsed) if parsed else ""
        else:
            normalized_str = ""
        self._settings.setValue("extensions", normalized_str)

        self._settings.setValue("case_sensitive", self.cb_case.isChecked())
        self._settings.setValue("is_regex", self.cb_regex.isChecked())
        self._settings.setValue("recursive", self.cb_recursive.isChecked())
        self._settings.setValue("include_hidden", self.cb_hidden.isChecked())
        self._settings.setValue("max_workers", self.spin_workers.value())
        self._settings.setValue("context_lines", self.spin_context.value())
        self._settings.sync()

    def restore_defaults(self) -> None:
        """Restore all dialog fields to system factory defaults."""
        self.ext_input.setText(DEFAULT_EXTENSIONS_STRING)
        self.cb_case.setChecked(False)
        self.cb_regex.setChecked(False)
        self.cb_recursive.setChecked(True)
        self.cb_hidden.setChecked(False)
        self.spin_workers.setValue(SearchEngine.calculate_max_workers())
        self.spin_context.setValue(5)

    def accept(self) -> None:
        """Save settings and accept dialog."""
        self.save_settings()
        super().accept()
