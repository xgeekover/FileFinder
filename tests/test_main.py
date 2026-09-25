"""Unit test suite for app.main (Phase 6: Main Entry Point & CLI).

Verifies command-line argument parsing, CLI search execution, streaming output formatting,
exit codes, GUI launch lifecycle, and routing logic between CLI and GUI modes.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from app import APP_NAME, APP_SUBTITLE, APP_VERSION
from app.core.models import ScanStatistics
from app.core.search_engine import SearchEngine
from app.gui.main_window import MainWindow
from app.main import main, parse_args, run_cli, run_gui

# ==============================================================================
# 1. Argument Parsing Tests
# ==============================================================================


class TestParseArgs:
    """Tests for parse_args verifying flag handling, defaults, and conversions."""

    def test_parse_args_defaults(self) -> None:
        """Empty arguments list returns all default attributes."""
        args = parse_args([])
        assert args.path is None
        assert args.query is None
        assert args.case_sensitive is False
        assert args.regex is False
        assert args.recursive is True
        assert args.hidden is False
        assert args.extensions is None
        assert args.gui is False
        assert args.max_workers is None
        assert getattr(args, "ignore_case", False) is False

    def test_parse_args_short_flags(self) -> None:
        """Short flags correctly map to target namespace options."""
        args = parse_args([
            "-p",
            "/target/dir",
            "-q",
            "needle",
            "-c",
            "-r",
            "-R",
            "-H",
            "-e",
            ".py,.txt",
            "--max-workers",
            "4",
        ])
        assert args.path == Path("/target/dir")
        assert args.query == "needle"
        assert args.case_sensitive is True
        assert args.regex is True
        assert args.recursive is True
        assert args.hidden is True
        assert args.extensions == ".py,.txt"
        assert args.max_workers == 4

    def test_parse_args_long_flags(self) -> None:
        """Long flags correctly set configuration options."""
        args = parse_args([
            "--path",
            "/project/search",
            "--query",
            "search_term",
            "--case-sensitive",
            "--regex",
            "--no-recursive",
            "--hidden",
            "--extensions",
            "py,json",
            "--gui",
            "--max-workers",
            "8",
        ])
        assert args.path == Path("/project/search")
        assert args.query == "search_term"
        assert args.case_sensitive is True
        assert args.regex is True
        assert args.recursive is False
        assert args.hidden is True
        assert args.extensions == "py,json"
        assert args.gui is True
        assert args.max_workers == 8

    def test_parse_args_case_sensitivity_flags(self) -> None:
        """--case-sensitive enables case sensitivity, while --ignore-case disables it."""
        args_cs = parse_args(["-c"])
        assert args_cs.case_sensitive is True
        assert getattr(args_cs, "ignore_case", False) is False

        args_ic = parse_args(["--ignore-case"])
        assert args_ic.case_sensitive is False
        assert getattr(args_ic, "ignore_case", False) is True

        args_i = parse_args(["-i"])
        assert args_i.case_sensitive is False
        assert getattr(args_i, "ignore_case", False) is True

    def test_parse_args_case_sensitivity_mutually_exclusive(self) -> None:
        """Providing both --case-sensitive and --ignore-case raises SystemExit(2)."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["-c", "-i"])
        assert exc_info.value.code == 2

    def test_parse_args_recursive_toggle(self) -> None:
        """--recursive sets True, --no-recursive sets False."""
        assert parse_args(["--recursive"]).recursive is True
        assert parse_args(["--no-recursive"]).recursive is False

    def test_parse_args_version_flag_short_v(self, capsys: pytest.CaptureFixture[str]) -> None:
        """-v displays APP_NAME and APP_VERSION and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["-v"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert APP_NAME in captured.out
        assert APP_VERSION in captured.out

    def test_parse_args_version_flag_short_upper_v(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """-V displays APP_NAME and APP_VERSION and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["-V"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert APP_NAME in captured.out
        assert APP_VERSION in captured.out

    def test_parse_args_version_flag_long(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--version displays APP_NAME and APP_VERSION and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert APP_NAME in captured.out
        assert APP_VERSION in captured.out

    def test_parse_args_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help displays usage guide and exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "filefinder" in captured.out
        assert "--path" in captured.out
        assert "--query" in captured.out

    def test_parse_args_invalid_option(self) -> None:
        """Unrecognized option raises SystemExit(2)."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--invalid-argument"])
        assert exc_info.value.code == 2

    def test_parse_args_none_reads_sys_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When args is None, parse_args parses sys.argv[1:]."""
        monkeypatch.setattr("sys.argv", ["prog", "--query", "from_sys_argv"])
        args = parse_args(None)
        assert args.query == "from_sys_argv"


# ==============================================================================
# 2. CLI Execution Tests
# ==============================================================================


class TestRunCli:
    """Tests for run_cli verifying file searching, formatting, and exit codes."""

    def test_run_cli_successful_search_with_matches(self, tmp_path: Path) -> None:
        """Search finding multiple matches prints streamed lines, summary, and returns 0."""
        file_a = tmp_path / "file_a.txt"
        file_a.write_text("Alpha match line\nSecond line\n", encoding="utf-8")
        file_b = tmp_path / "file_b.py"
        file_b.write_text("# match in comment\n", encoding="utf-8")

        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "match"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr)
        assert exit_code == 0

        out = stdout.getvalue()
        assert "file_a.txt:1: Alpha match line" in out
        assert "file_b.py:1: # match in comment" in out
        assert "--- Search Summary ---" in out
        assert "Matches found : 2" in out
        assert "Scanned files : 2 / 2" in out
        assert stderr.getvalue() == ""

    def test_run_cli_successful_search_zero_matches(self, tmp_path: Path) -> None:
        """Search with zero matching files prints summary with 0 matches and returns 0."""
        test_file = tmp_path / "sample.txt"
        test_file.write_text("No target word here\n", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "nonexistent_term"])

        exit_code = run_cli(args, stdout=stdout)
        assert exit_code == 0

        out = stdout.getvalue()
        assert "Matches found : 0" in out
        assert "Scanned files : 1 / 1" in out

    def test_run_cli_nonexistent_directory(self, tmp_path: Path) -> None:
        """Non-existent directory prints error to stderr and returns exit code 1."""
        non_existent = tmp_path / "missing_folder"
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(non_existent), "-q", "query"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr)
        assert exit_code == 1
        assert "Search directory does not exist" in stderr.getvalue()
        assert stdout.getvalue() == ""

    def test_run_cli_invalid_regex_pattern(self, tmp_path: Path) -> None:
        """Unparseable regex pattern prints error to stderr and returns exit code 1."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "[unclosed_regex", "--regex"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr)
        assert exit_code == 1
        assert "Invalid regular expression pattern" in stderr.getvalue()

    def test_run_cli_case_sensitive_option(self, tmp_path: Path) -> None:
        """Case-sensitive flag restricts matches to exact casing."""
        test_file = tmp_path / "cases.txt"
        test_file.write_text("Apple\napple\nAPPLE\n", encoding="utf-8")

        # Case-insensitive (default) -> 3 matches
        out_ci = io.StringIO()
        args_ci = parse_args(["-p", str(tmp_path), "-q", "Apple", "--ignore-case"])
        assert run_cli(args_ci, stdout=out_ci) == 0
        assert "Matches found : 3" in out_ci.getvalue()

        # Case-sensitive -> 1 match
        out_cs = io.StringIO()
        args_cs = parse_args(["-p", str(tmp_path), "-q", "Apple", "-c"])
        assert run_cli(args_cs, stdout=out_cs) == 0
        assert "Matches found : 1" in out_cs.getvalue()

    def test_run_cli_regex_search(self, tmp_path: Path) -> None:
        """Regex option matches patterns correctly."""
        test_file = tmp_path / "contacts.txt"
        test_file.write_text("Call 123-4567 for info\nNo phone here\n", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", r"\d{3}-\d{4}", "-r"])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "contacts.txt:1: Call 123-4567 for info" in out
        assert "Matches found : 1" in out

    def test_run_cli_extension_filtering(self, tmp_path: Path) -> None:
        """--extensions restricts search to specified file extensions."""
        (tmp_path / "script.py").write_text("secret_keyword", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("secret_keyword", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "secret_keyword", "-e", ".py"])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "script.py:1: secret_keyword" in out
        assert "notes.txt" not in out
        assert "Matches found : 1" in out

    def test_run_cli_no_recursive_option(self, tmp_path: Path) -> None:
        """--no-recursive limits search to top-level folder."""
        (tmp_path / "root.txt").write_text("find_me", encoding="utf-8")
        nested_dir = tmp_path / "nested"
        nested_dir.mkdir()
        (nested_dir / "child.txt").write_text("find_me", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "find_me", "--no-recursive"])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "root.txt:1: find_me" in out
        assert "child.txt" not in out
        assert "Matches found : 1" in out

    def test_run_cli_hidden_files_toggle(self, tmp_path: Path) -> None:
        """--hidden includes hidden files in scan."""
        (tmp_path / "visible.txt").write_text("hidden_test", encoding="utf-8")
        (tmp_path / ".hidden.txt").write_text("hidden_test", encoding="utf-8")

        # Default excludes hidden
        stdout_default = io.StringIO()
        args_default = parse_args(["-p", str(tmp_path), "-q", "hidden_test"])
        assert run_cli(args_default, stdout=stdout_default) == 0
        assert ".hidden.txt" not in stdout_default.getvalue()
        assert "Matches found : 1" in stdout_default.getvalue()

        # --hidden includes hidden
        stdout_hidden = io.StringIO()
        args_hidden = parse_args(["-p", str(tmp_path), "-q", "hidden_test", "--hidden"])
        assert run_cli(args_hidden, stdout=stdout_hidden) == 0
        assert ".hidden.txt" in stdout_hidden.getvalue()
        assert "Matches found : 2" in stdout_hidden.getvalue()

    def test_run_cli_empty_query(self, tmp_path: Path) -> None:
        """Empty query returns immediately with 0 matches and exit code 0."""
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(tmp_path)])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "Matches found : 0" in out

    def test_run_cli_default_path_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When --path is omitted, defaults to Path.cwd()."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "local.txt").write_text("cwd_needle", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-q", "cwd_needle"])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "local.txt:1: cwd_needle" in out
        assert "Matches found : 1" in out

    def test_run_cli_file_scan_errors_do_not_abort_or_fail_exit_code(
        self, tmp_path: Path
    ) -> None:
        """Permission or decoding errors on individual files are logged but do not return exit code 1."""
        mock_stats = ScanStatistics(
            total_files=2,
            scanned_files=2,
            success_count=1,
            error_count=1,
            errors=[(tmp_path / "locked.txt", "Permission denied")],
            elapsed_seconds=0.05,
        )
        mock_engine = MagicMock(spec=SearchEngine)
        mock_engine.search.return_value = mock_stats

        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "test"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr, engine=mock_engine)
        assert exit_code == 0
        assert "Errors        : 1" in stdout.getvalue()
        assert "Permission denied" in stderr.getvalue()

    def test_run_cli_engine_directory_error_fails_exit_code(self, tmp_path: Path) -> None:
        """Engine-level directory nonexistence error returns exit code 1."""
        mock_stats = ScanStatistics(
            total_files=0,
            scanned_files=0,
            success_count=0,
            error_count=1,
            errors=[(tmp_path, f"Search folder does not exist: {tmp_path}")],
            elapsed_seconds=0.01,
        )
        mock_engine = MagicMock(spec=SearchEngine)
        mock_engine.search.return_value = mock_stats

        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "test"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr, engine=mock_engine)
        assert exit_code == 1

    def test_run_cli_engine_regex_error_fails_exit_code(self, tmp_path: Path) -> None:
        """Engine-level regex compilation error returns exit code 1."""
        mock_stats = ScanStatistics(
            total_files=0,
            scanned_files=0,
            success_count=0,
            error_count=1,
            errors=[(tmp_path, "Invalid regex pattern: bad pattern")],
            elapsed_seconds=0.01,
        )
        mock_engine = MagicMock(spec=SearchEngine)
        mock_engine.search.return_value = mock_stats

        stdout = io.StringIO()
        stderr = io.StringIO()
        args = parse_args(["-p", str(tmp_path), "-q", "test"])

        exit_code = run_cli(args, stdout=stdout, stderr=stderr, engine=mock_engine)
        assert exit_code == 1

    def test_run_cli_single_file_target(self, tmp_path: Path) -> None:
        """Targeting a single file directly scans that file and returns matches."""
        target_file = tmp_path / "single.txt"
        target_file.write_text("Hello single target\nSecond line\n", encoding="utf-8")

        stdout = io.StringIO()
        args = parse_args(["-p", str(target_file), "-q", "single target"])
        assert run_cli(args, stdout=stdout) == 0

        out = stdout.getvalue()
        assert "single.txt:1: Hello single target" in out
        assert "Matches found : 1" in out

    def test_run_cli_custom_max_workers(self, tmp_path: Path) -> None:
        """Passing --max-workers instantiates SearchEngine with the specified thread count."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("worker_test\n", encoding="utf-8")

        with patch("app.main.SearchEngine", wraps=SearchEngine) as mock_engine_cls:
            args = parse_args(["-p", str(tmp_path), "-q", "worker_test", "--max-workers", "3"])
            exit_code = run_cli(args, stdout=io.StringIO())
            assert exit_code == 0
            mock_engine_cls.assert_called_once_with(max_workers=3)


# ==============================================================================
# 3. GUI Launching Tests
# ==============================================================================


class TestRunGui:
    """Tests for run_gui verifying QApplication configuration and lifecycle."""

    def test_run_gui_initialization_and_metadata(self) -> None:
        """run_gui configures QApplication metadata and stylesheet, shows MainWindow, and returns exec code."""
        with (
            patch.object(QApplication, "exec", return_value=0),
            patch.object(MainWindow, "show", return_value=None),
        ):
            exit_code = run_gui([])
            assert exit_code == 0

            app = QApplication.instance()
            assert isinstance(app, QApplication)
            assert app.applicationName() == APP_NAME
            assert app.applicationVersion() == APP_VERSION
            assert app.applicationDisplayName() == f"{APP_NAME} - {APP_SUBTITLE}"

    def test_run_gui_singleton_reuse_without_crash(self) -> None:
        """run_gui safely reuses existing QApplication without libshiboken singleton collision."""
        assert QApplication.instance() is not None
        with (
            patch.object(QApplication, "exec", return_value=42),
            patch.object(MainWindow, "show", return_value=None),
        ):
            assert run_gui([]) == 42

    def test_run_gui_custom_argv(self) -> None:
        """run_gui accepts custom argv list."""
        with (
            patch.object(QApplication, "exec", return_value=0),
            patch.object(MainWindow, "show", return_value=None),
        ):
            assert run_gui(["custom_arg"]) == 0


# ==============================================================================
# 4. Main Entry Point Routing Tests
# ==============================================================================


class TestMainRouting:
    """Tests for main() entry point verifying routing between GUI and CLI modes."""

    def test_main_routes_to_gui_when_no_args(self) -> None:
        """Invoking main() with no search arguments launches the GUI."""
        with (
            patch("app.main.run_gui", return_value=0) as mock_gui,
            patch("app.main.run_cli") as mock_cli,
        ):
            exit_code = main([])
            assert exit_code == 0
            mock_gui.assert_called_once_with([])
            mock_cli.assert_not_called()

    def test_main_routes_to_gui_when_gui_flag(self) -> None:
        """Invoking main() with --gui explicitly launches the GUI."""
        with (
            patch("app.main.run_gui", return_value=0) as mock_gui,
            patch("app.main.run_cli") as mock_cli,
        ):
            exit_code = main(["--gui"])
            assert exit_code == 0
            mock_gui.assert_called_once_with(["--gui"])
            mock_cli.assert_not_called()

    def test_main_routes_to_gui_when_gui_flag_with_path_and_query(self) -> None:
        """--gui overrides provided path and query to launch GUI mode."""
        with (
            patch("app.main.run_gui", return_value=0) as mock_gui,
            patch("app.main.run_cli") as mock_cli,
        ):
            exit_code = main(["--gui", "-p", "/some/path", "-q", "search_term"])
            assert exit_code == 0
            mock_gui.assert_called_once_with(["--gui", "-p", "/some/path", "-q", "search_term"])
            mock_cli.assert_not_called()

    def test_main_routes_to_cli_when_path_provided(self, tmp_path: Path) -> None:
        """Providing --path routes to run_cli."""
        with (
            patch("app.main.run_gui") as mock_gui,
            patch("app.main.run_cli", return_value=0) as mock_cli,
        ):
            exit_code = main(["--path", str(tmp_path)])
            assert exit_code == 0
            mock_cli.assert_called_once()
            mock_gui.assert_not_called()

    def test_main_routes_to_cli_when_query_provided(self) -> None:
        """Providing --query routes to run_cli."""
        with (
            patch("app.main.run_gui") as mock_gui,
            patch("app.main.run_cli", return_value=0) as mock_cli,
        ):
            exit_code = main(["--query", "search_keyword"])
            assert exit_code == 0
            mock_cli.assert_called_once()
            mock_gui.assert_not_called()

    def test_main_routes_to_cli_when_both_provided(self, tmp_path: Path) -> None:
        """Providing both --path and --query routes to run_cli."""
        with (
            patch("app.main.run_gui") as mock_gui,
            patch("app.main.run_cli", return_value=0) as mock_cli,
        ):
            exit_code = main(["-p", str(tmp_path), "-q", "search_keyword"])
            assert exit_code == 0
            mock_cli.assert_called_once()
            mock_gui.assert_not_called()

    def test_main_propagates_cli_exit_code_zero(self, tmp_path: Path) -> None:
        """main() propagates exit code 0 returned from run_cli."""
        with patch("app.main.run_cli", return_value=0):
            exit_code = main(["-p", str(tmp_path), "-q", "test"])
            assert exit_code == 0

    def test_main_propagates_cli_exit_code_error(self, tmp_path: Path) -> None:
        """main() propagates exit code 1 returned from run_cli."""
        with patch("app.main.run_cli", return_value=1):
            exit_code = main(["-p", str(tmp_path), "-q", "test"])
            assert exit_code == 1

    def test_main_propagates_gui_exit_code(self) -> None:
        """main() propagates exit code returned from run_gui."""
        with patch("app.main.run_gui", return_value=42):
            exit_code = main(["--gui"])
            assert exit_code == 42

    def test_main_default_argv_none_uses_sys_argv(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main(None) parses sys.argv."""
        monkeypatch.setattr("sys.argv", ["filefinder", "--help"])
        with pytest.raises(SystemExit) as exc_info:
            main(None)
        assert exc_info.value.code == 0
