"""FileFinder - Cross-Platform File Content Search Tool.

This module exposes application-wide metadata constants.
"""

from typing import Final

APP_NAME: Final[str] = "FileFinder"
APP_VERSION: Final[str] = "1.0.0"
APP_SUBTITLE: Final[str] = "Cross-Platform File Content Search Tool"

__all__: list[str] = [
    "APP_NAME",
    "APP_SUBTITLE",
    "APP_VERSION",
]
