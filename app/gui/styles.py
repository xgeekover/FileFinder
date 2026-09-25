"""Application stylesheet, color tokens, and preview HTML rendering for FileFinder.

Provides a polished, professional developer-utility dark theme with clean borders,
high-contrast typography, and syntax-like preview highlighting.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from typing import Any

# Font configurations
FONT_FAMILY_UI = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", '
    'Arial, sans-serif'
)
FONT_FAMILY_MONO = (
    '"JetBrains Mono", "Cascadia Code", "Fira Code", Consolas, Menlo, Monaco, '
    '"Courier New", monospace'
)

# High-contrast match highlight styles
MATCH_HIGHLIGHT_STYLE = (
    "background-color: #ffd700; color: #000000; font-weight: bold; "
    "border-radius: 2px; padding: 0 2px;"
)


def get_application_stylesheet() -> str:
    """Return the complete PySide6 application QSS stylesheet string."""
    return f"""
    /* Global Window and Base Widget Defaults */
    QMainWindow, QDialog, QWidget {{
        background-color: #1e1e24;
        color: #f8fafc;
        font-family: {FONT_FAMILY_UI};
        font-size: 13px;
    }}

    /* Group Boxes */
    QGroupBox {{
        font-weight: bold;
        border: 1px solid #3a3a48;
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 10px;
        background-color: #22222c;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 5px;
        color: #94a3b8;
    }}

    /* Text Inputs */
    QLineEdit {{
        background-color: #2b2b36;
        color: #f8fafc;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        padding: 6px 10px;
        selection-background-color: #2563eb;
        selection-color: #ffffff;
    }}
    QLineEdit:focus {{
        border: 1px solid #3b82f6;
        background-color: #31313e;
    }}
    QLineEdit:disabled {{
        background-color: #1a1a20;
        color: #64748b;
        border: 1px solid #2d2d38;
    }}

    /* Buttons */
    QPushButton {{
        background-color: #333342;
        color: #f1f5f9;
        border: 1px solid #474758;
        border-radius: 4px;
        padding: 6px 14px;
        font-weight: 500;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background-color: #3e3e50;
        border-color: #64748b;
    }}
    QPushButton:pressed {{
        background-color: #282834;
    }}
    QPushButton:disabled {{
        background-color: #1a1a20;
        color: #64748b;
        border: 1px solid #2d2d38;
    }}

    /* Primary Accent Button (Search) */
    QPushButton#search_btn {{
        background-color: #2563eb;
        color: #ffffff;
        border: 1px solid #1d4ed8;
        font-weight: bold;
    }}
    QPushButton#search_btn:hover {{
        background-color: #1d4ed8;
        border-color: #3b82f6;
    }}
    QPushButton#search_btn:pressed {{
        background-color: #1e40af;
    }}

    /* Danger Button (Cancel) */
    QPushButton#cancel_btn {{
        background-color: #dc2626;
        color: #ffffff;
        border: 1px solid #b91c1c;
        font-weight: bold;
    }}
    QPushButton#cancel_btn:hover {{
        background-color: #b91c1c;
    }}
    QPushButton#cancel_btn:pressed {{
        background-color: #991b1b;
    }}
    QPushButton#cancel_btn:disabled {{
        background-color: #1a1a20;
        color: #64748b;
        border: 1px solid #2d2d38;
    }}

    /* Warning Button (Error Files Dialog Trigger) */
    QPushButton#error_btn {{
        background-color: #d97706;
        color: #ffffff;
        border: 1px solid #b45309;
        font-weight: bold;
    }}
    QPushButton#error_btn:hover {{
        background-color: #b45309;
    }}
    QPushButton#error_btn:disabled {{
        background-color: #282834;
        color: #64748b;
        border: 1px solid #3a3a48;
    }}

    /* Checkboxes & Radio Buttons */
    QCheckBox, QRadioButton {{
        spacing: 6px;
        color: #e2e8f0;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid #4a4a5c;
        border-radius: 3px;
        background-color: #2b2b36;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: #3b82f6;
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: #2563eb;
        border-color: #3b82f6;
    }}

    /* Results Table View */
    QTableView {{
        background-color: #1a1a20;
        alternate-background-color: #22222a;
        color: #f8fafc;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        gridline-color: #2d2d38;
        selection-background-color: #1e40af;
        selection-color: #ffffff;
        font-family: {FONT_FAMILY_MONO};
        font-size: 12px;
    }}
    QTableView::item {{
        padding: 4px 6px;
        border: none;
    }}
    QTableView::item:selected {{
        background-color: #1e40af;
        color: #ffffff;
    }}

    /* Table Headers */
    QHeaderView::section {{
        background-color: #282834;
        color: #cbd5e1;
        padding: 6px 8px;
        border: none;
        border-right: 1px solid #3a3a48;
        border-bottom: 1px solid #3a3a48;
        font-family: {FONT_FAMILY_UI};
        font-weight: 600;
        font-size: 12px;
    }}
    QHeaderView::section:hover {{
        background-color: #323242;
    }}

    /* File Preview Panel (QTextEdit) */
    QTextEdit#preview_panel {{
        background-color: #141419;
        color: #f8fafc;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        font-family: {FONT_FAMILY_MONO};
        font-size: 12px;
        padding: 4px;
    }}

    /* Splitter */
    QSplitter::handle {{
        background-color: #2d2d38;
    }}
    QSplitter::handle:hover {{
        background-color: #3b82f6;
    }}
    QSplitter::handle:horizontal {{
        width: 4px;
    }}
    QSplitter::handle:vertical {{
        height: 4px;
    }}

    /* Progress Bar */
    QProgressBar {{
        background-color: #2b2b36;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        text-align: center;
        color: #ffffff;
        font-weight: bold;
        font-size: 11px;
        height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: #2563eb;
        border-radius: 3px;
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        background-color: #1a1a20;
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: #444456;
        min-height: 24px;
        border-radius: 4px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: #55556c;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background-color: #1a1a20;
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background-color: #444456;
        min-width: 24px;
        border-radius: 4px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: #55556c;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* Menu Bar & Menus */
    QMenuBar {{
        background-color: #18181e;
        color: #e2e8f0;
        border-bottom: 1px solid #2d2d38;
        padding: 2px 4px;
    }}
    QMenuBar::item {{
        background-color: transparent;
        padding: 4px 10px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: #2a2a36;
        color: #ffffff;
    }}
    QMenu {{
        background-color: #22222c;
        color: #f8fafc;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 20px;
        border-radius: 3px;
    }}
    QMenu::item:selected {{
        background-color: #2563eb;
        color: #ffffff;
    }}
    QMenu::separator {{
        height: 1px;
        background-color: #3a3a48;
        margin: 4px 6px;
    }}

    /* Status Bar */
    QStatusBar {{
        background-color: #18181e;
        color: #94a3b8;
        border-top: 1px solid #2d2d38;
        font-size: 12px;
    }}

    /* Tab Widget (Settings Dialog) */
    QTabWidget::pane {{
        border: 1px solid #3a3a48;
        background-color: #22222c;
        border-radius: 4px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: #1a1a22;
        color: #94a3b8;
        padding: 8px 16px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        border: 1px solid #3a3a48;
        border-bottom: none;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: #22222c;
        color: #f8fafc;
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: #2a2a36;
        color: #cbd5e1;
    }}

    /* SpinBoxes & ComboBoxes */
    QSpinBox, QComboBox {{
        background-color: #2b2b36;
        color: #f8fafc;
        border: 1px solid #3a3a48;
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QSpinBox:focus, QComboBox:focus {{
        border: 1px solid #3b82f6;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #22222c;
        color: #f8fafc;
        selection-background-color: #2563eb;
        border: 1px solid #3a3a48;
    }}
    """


def highlight_line_text(
    line: str,
    query: str,
    is_regex: bool = False,
    case_sensitive: bool = False,
) -> str:
    """Highlight matched query instances within a single raw line string using HTML.

    Args:
        line: Raw line text from file.
        query: Search term or regex string.
        is_regex: Whether query is a compiled regex pattern.
        case_sensitive: Whether match evaluation is case sensitive.

    Returns:
        HTML-escaped and highlight-wrapped string.
    """
    if not query:
        return html.escape(line)

    flags = re.NOFLAG if case_sensitive else re.IGNORECASE
    try:
        if is_regex:
            pattern = re.compile(f"({query})", flags)
        else:
            pattern = re.compile(f"({re.escape(query)})", flags)
    except re.error:
        return html.escape(line)

    parts: list[str] = []
    last_idx = 0
    for match in pattern.finditer(line):
        start, end = match.span()
        if start == end:
            continue
        if start > last_idx:
            parts.append(html.escape(line[last_idx:start]))
        matched_str = html.escape(line[start:end])
        parts.append(f'<mark style="{MATCH_HIGHLIGHT_STYLE}">{matched_str}</mark>')
        last_idx = end

    if last_idx < len(line):
        parts.append(html.escape(line[last_idx:]))

    return "".join(parts)


def get_preview_html(
    lines: Sequence[tuple[int, str] | str],
    target_line: int,
    search_term: str = "",
    is_regex: bool = False,
    case_sensitive: bool = False,
    **kwargs: Any,
) -> str:
    """Build syntax-styled HTML table for displaying bounded context lines in QTextEdit.

    Supports lines as Sequence of (line_number, line_text) tuples or plain strings.
    Accepts search_term or query as keyword argument.

    Args:
        lines: Sequence of (line_number, line_text) tuples or strings.
        target_line: The exact line number containing the primary match.
        search_term: The search pattern to highlight (alias: query).
        is_regex: Whether search_term should be treated as regex.
        case_sensitive: Whether match evaluation is case sensitive.
        **kwargs: Optional fallback arguments (e.g. query=...).

    Returns:
        Full HTML string ready for QTextEdit.setHtml().
    """
    if "query" in kwargs and not search_term:
        search_term = kwargs["query"]

    if not lines:
        return '<div style="color: #64748b; padding: 12px;">선택된 매치 미리보기가 없습니다.</div>'

    # Normalize lines into (line_number, raw_content) tuples
    normalized_lines: list[tuple[int, str]] = []
    for idx, item in enumerate(lines):
        if isinstance(item, tuple) and len(item) == 2:
            normalized_lines.append((int(item[0]), str(item[1])))
        else:
            # item is plain string, calculate line number based on target_line context
            line_num = (target_line - len(lines) // 2 + idx) if len(lines) > 1 else target_line
            normalized_lines.append((max(1, line_num), str(item)))

    rows_html: list[str] = []
    for line_num, raw_content in normalized_lines:
        is_target = line_num == target_line
        highlighted_text = highlight_line_text(
            raw_content,
            search_term,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
        )

        if is_target:
            row_style = (
                "background-color: rgba(255, 215, 0, 0.12); "
                "border-left: 3px solid #ffd700;"
            )
            num_style = (
                "color: #fbbf24; font-weight: bold; text-align: right; "
                "padding: 2px 10px 2px 4px; user-select: none; width: 45px;"
            )
            marker = '<span style="color: #ffd700; margin-right: 4px;">▶</span>'
        else:
            row_style = "background-color: transparent;"
            num_style = (
                "color: #64748b; text-align: right; "
                "padding: 2px 10px 2px 4px; user-select: none; width: 45px;"
            )
            marker = ""

        row = (
            f'<tr style="{row_style}">'
            f'<td style="{num_style}">{marker}{line_num}</td>'
            f'<td style="padding: 2px 8px; color: #f8fafc; white-space: pre-wrap; word-break: break-all;">'
            f"{highlighted_text}</td>"
            f"</tr>"
        )
        rows_html.append(row)

    table_body = "\n".join(rows_html)
    return (
        f'<div style="font-family: {FONT_FAMILY_MONO}; font-size: 12px; line-height: 1.4;">'
        f'<table style="width: 100%; border-collapse: collapse; margin: 0;">'
        f"{table_body}"
        f"</table>"
        f"</div>"
    )
