"""FileFinder GUI presentation package.

Exports main window, table model, dialogs, styling helpers, and background worker.
"""

from __future__ import annotations

from app.gui.main_window import (
    AboutDialog,
    ErrorFilesDialog,
    MainWindow,
    ResultsTableModel,
)
from app.gui.search_worker import SearchWorker
from app.gui.settings_dialog import SettingsDialog
from app.gui.styles import (
    get_application_stylesheet,
    get_preview_html,
    highlight_line_text,
)

__all__ = [
    "AboutDialog",
    "ErrorFilesDialog",
    "MainWindow",
    "ResultsTableModel",
    "SearchWorker",
    "SettingsDialog",
    "get_application_stylesheet",
    "get_preview_html",
    "highlight_line_text",
]
