"""Cross-platform system utilities for FileFinder.

Isolates all operating-system specific calls for macOS, Windows, and Linux.
Strictly decoupled from PySide6 GUI framework.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("app.utils.platform_utils")


def open_file_in_default_app(file_path: Path | str) -> bool:
    """Open a file using the host operating system's default associated application.

    Platform implementation:
    - Windows: Uses os.startfile()
    - macOS: Uses /usr/bin/open
    - Linux: Uses xdg-open

    Args:
        file_path: Absolute or relative path to the target file.

    Returns:
        True if the OS process was successfully dispatched, False otherwise.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        logger.warning("Cannot open non-existent file: %s", path)
        return False

    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True, capture_output=True)
            return True
        else:
            # Linux and BSD
            subprocess.run(["xdg-open", str(path)], check=True, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.error("Failed to open file '%s' with default app: %s", path, exc)
        return False


def reveal_in_file_manager(file_path: Path | str) -> bool:
    """Open the host desktop file manager with the target file highlighted.

    Platform implementation:
    - Windows: Uses explorer.exe /select,"path"
    - macOS: Uses /usr/bin/open -R "path"
    - Linux: Uses D-Bus org.freedesktop.FileManager1.ShowItems if available,
      or falls back to opening the containing directory via xdg-open.

    Args:
        file_path: Path to the target file or directory.

    Returns:
        True if the file manager was successfully invoked, False otherwise.
    """
    path = Path(file_path).resolve()
    target_path = path if path.exists() else path.parent
    if not target_path.exists():
        logger.warning("Cannot reveal non-existent path: %s", path)
        return False

    try:
        if sys.platform == "win32":
            # Explorer /select selects the item within its parent directory
            subprocess.run(["explorer.exe", f"/select,{path}"], check=False)
            return True
        elif sys.platform == "darwin":
            # open -R reveals the file selected in Finder
            subprocess.run(["open", "-R", str(path)], check=True, capture_output=True)
            return True
        else:
            # Linux: Check for dbus-send FileManager1 first
            if shutil.which("dbus-send"):
                uri = path.as_uri()
                cmd = [
                    "dbus-send",
                    "--session",
                    "--print-reply",
                    "--dest=org.freedesktop.FileManager1",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{uri}",
                    'string:""',
                ]
                res = subprocess.run(cmd, check=False, capture_output=True)
                if res.returncode == 0:
                    return True

            # Linux fallback: open parent directory with xdg-open
            folder_to_open = path.parent if path.is_file() else path
            subprocess.run(["xdg-open", str(folder_to_open)], check=True, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.error("Failed to reveal file '%s' in file manager: %s", path, exc)
        return False


def open_folder_in_file_manager(folder_path: Path | str) -> bool:
    """Open folder directory view in host desktop file manager.

    Platform implementation:
    - Windows: Uses os.startfile(folder)
    - macOS: Uses /usr/bin/open "folder"
    - Linux: Uses xdg-open "folder"

    Args:
        folder_path: Path to the directory (or file whose containing directory will be opened).

    Returns:
        True if the file manager was successfully invoked, False otherwise.
    """
    path = Path(folder_path).resolve()
    if not path.exists():
        logger.warning("Cannot open non-existent directory: %s", path)
        return False
    target = path if path.is_dir() else path.parent

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=True, capture_output=True)
            return True
        else:
            subprocess.run(["xdg-open", str(target)], check=True, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.error("Failed to open directory '%s': %s", target, exc)
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy plaintext string to system clipboard without PySide6 dependencies.

    Uses native platform CLI utilities:
    - macOS: pbcopy
    - Windows: clip.exe
    - Linux: wl-copy (Wayland) -> xclip -> xsel

    Args:
        text: The string to place on the clipboard.

    Returns:
        True if text was placed on the clipboard, False otherwise.
    """
    text = str(text)

    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )
            return True
        elif sys.platform == "win32":
            subprocess.run(
                ["clip"],
                input=text.encode("utf-16le"),
                check=True,
                capture_output=True,
            )
            return True
        else:
            # Linux: try Wayland first, then X11 tools
            if shutil.which("wl-copy"):
                subprocess.run(
                    ["wl-copy"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                )
                return True
            elif shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                )
                return True
            elif shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                )
                return True
            else:
                logger.warning(
                    "No clipboard utility found on Linux (checked wl-copy, xclip, xsel)."
                )
                return False
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.error("Failed to copy text to clipboard: %s", exc)
        return False
