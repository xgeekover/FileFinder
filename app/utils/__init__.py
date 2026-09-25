"""FileFinder utilities package.

Provides cross-platform OS helpers, logging configuration, and file utilities.
"""

from __future__ import annotations

from app.utils.file_utils import (
    export_results_to_csv,
    format_file_size,
    get_safe_relative_path,
    is_subpath,
    normalize_extension,
    parse_extensions_string,
    read_context_lines,
)
from app.utils.logging_utils import get_logger, setup_logging
from app.utils.platform_utils import (
    copy_to_clipboard,
    open_file_in_default_app,
    open_folder_in_file_manager,
    reveal_in_file_manager,
)

__all__ = [
    "copy_to_clipboard",
    "export_results_to_csv",
    "format_file_size",
    "get_logger",
    "get_safe_relative_path",
    "is_subpath",
    "normalize_extension",
    "open_file_in_default_app",
    "open_folder_in_file_manager",
    "parse_extensions_string",
    "read_context_lines",
    "reveal_in_file_manager",
    "setup_logging",
]
