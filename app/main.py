"""Main entry point for FileFinder application.

Provides dual-mode execution:
- Headless CLI search mode when search arguments (--path, --query) are specified
- PySide6 desktop GUI when launched without search arguments or with --gui
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from PySide6.QtWidgets import QApplication

from app import APP_NAME, APP_SUBTITLE, APP_VERSION
from app.core.models import SearchOptions, SearchResult
from app.core.search_engine import SearchEngine
from app.gui.main_window import MainWindow
from app.gui.styles import get_application_stylesheet
from app.utils import file_utils


class _IgnoreCaseAction(argparse.Action):
    """Custom action for --ignore-case setting case_sensitive=False and ignore_case=True."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, False)
        namespace.ignore_case = True


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for CLI and GUI modes.

    Args:
        args: Sequence of command-line argument strings, or None to read sys.argv[1:].

    Returns:
        Populated argparse.Namespace instance.
    """
    parser = argparse.ArgumentParser(
        prog="filefinder",
        description=f"{APP_NAME} - {APP_SUBTITLE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        default=None,
        help="Target directory or file path to search",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="Search text or regular expression pattern",
    )

    case_group = parser.add_mutually_exclusive_group()
    case_group.add_argument(
        "-c",
        "--case-sensitive",
        dest="case_sensitive",
        action="store_true",
        default=False,
        help="Enable case-sensitive matching (default: case-insensitive)",
    )
    case_group.add_argument(
        "-i",
        "--ignore-case",
        dest="case_sensitive",
        action=_IgnoreCaseAction,
        nargs=0,
        help="Explicitly disable case sensitivity (default behavior)",
    )
    parser.set_defaults(ignore_case=False)

    parser.add_argument(
        "-r",
        "--regex",
        action="store_true",
        default=False,
        help="Treat query as a regular expression pattern",
    )
    parser.add_argument(
        "-R",
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recursively search subdirectories (default: True, use --no-recursive to disable)",
    )
    parser.add_argument(
        "-H",
        "--hidden",
        action="store_true",
        default=False,
        help="Include hidden files and folders in search (default: False)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        type=str,
        default=None,
        help="Comma-separated list of file extensions to include (e.g. '.py,.txt')",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="Explicitly launch PySide6 graphical user interface",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of parallel worker threads (default: auto-computed)",
    )
    parser.add_argument(
        "-v",
        "-V",
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
    )

    return parser.parse_args(args)


def run_cli(
    args: argparse.Namespace,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    engine: SearchEngine | None = None,
) -> int:
    """Execute search in headless command-line interface mode.

    Args:
        args: Parsed command-line arguments.
        stdout: Destination text stream for matching output (defaults to sys.stdout).
        stderr: Destination text stream for error output (defaults to sys.stderr).
        engine: Optional custom SearchEngine instance for dependency injection.

    Returns:
        0 on clean execution, 1 on non-existent directory or invalid regex.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    # 1. Path resolution & existence validation
    raw_path: Path | None = getattr(args, "path", None)
    search_path = (raw_path or Path.cwd()).resolve()

    if raw_path is not None and not search_path.exists():
        err.write(f"Error: Search directory does not exist: {raw_path}\n")
        err.flush()
        return 1

    # 2. Query preparation & regex pre-compilation validation
    query: str = getattr(args, "query", None) or ""
    is_regex: bool = bool(getattr(args, "regex", False))
    case_sensitive: bool = bool(getattr(args, "case_sensitive", False))

    if is_regex and query:
        flags = re.NOFLAG if case_sensitive else re.IGNORECASE
        try:
            re.compile(query, flags)
        except re.error as exc:
            err.write(f"Error: Invalid regular expression pattern '{query}': {exc}\n")
            err.flush()
            return 1

    # 3. Extensions normalization
    raw_extensions: str | None = getattr(args, "extensions", None)
    extensions: list[str] = (
        file_utils.parse_extensions_string(raw_extensions)
        if raw_extensions
        else []
    )

    # 4. Search configuration assembly
    options = SearchOptions(
        path=search_path,
        query=query,
        is_regex=is_regex,
        case_sensitive=case_sensitive,
        recursive=bool(getattr(args, "recursive", True)),
        include_hidden=bool(getattr(args, "hidden", False)),
        extensions=extensions,
    )

    # 5. SearchEngine execution
    max_workers: int | None = getattr(args, "max_workers", None)
    search_engine = engine or SearchEngine(max_workers=max_workers)

    matches_found = 0

    def on_result(result: SearchResult) -> None:
        nonlocal matches_found
        matches_found += 1
        out.write(f"{result.file_path}:{result.line_number}: {result.matched_line}\n")
        out.flush()

    stats = search_engine.search(options, result_callback=on_result)

    # 6. Summary reporting
    out.write("\n--- Search Summary ---\n")
    out.write(f"Scanned files : {stats.scanned_files} / {stats.total_files}\n")
    out.write(f"Matches found : {matches_found}\n")
    out.write(f"Elapsed time  : {stats.elapsed_seconds:.3f}s\n")
    out.write(f"Errors        : {stats.error_count}\n")
    out.flush()

    if stats.errors:
        for err_path, err_msg in stats.errors:
            err.write(f"  - {err_path}: {err_msg}\n")
        err.flush()

    # 7. Check for engine-level directory/regex failure
    for _, err_msg in stats.errors:
        if "does not exist" in err_msg.lower() or "invalid regex" in err_msg.lower():
            return 1

    return 0


def run_gui(argv: Sequence[str] | None = None) -> int:
    """Launch the PySide6 graphical user interface.

    Initializes or reuses QApplication, sets application metadata,
    applies stylesheet, instantiates MainWindow, and enters Qt event loop.

    Args:
        argv: Optional command-line arguments sequence for QApplication.

    Returns:
        Integer exit code returned by QApplication.exec().
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(list(argv) if argv is not None else sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setApplicationDisplayName(f"{APP_NAME} - {APP_SUBTITLE}")
    app.setStyleSheet(get_application_stylesheet())

    window = MainWindow()
    window.show()
    return int(app.exec())


def main(argv: Sequence[str] | None = None) -> int:
    """Main program entry point.

    Parses command-line arguments and routes execution to either:
    - Headless CLI search mode if --path or --query is specified
    - PySide6 graphical user interface if no CLI search arguments are given

    Args:
        argv: Optional sequence of argument strings (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, 1 for runtime/configuration error).
    """
    args = parse_args(argv)

    if getattr(args, "gui", False) or (args.path is None and args.query is None):
        return run_gui(argv)

    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
