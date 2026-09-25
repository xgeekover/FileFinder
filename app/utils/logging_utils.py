"""Thread-safe logging configuration for FileFinder.

Provides standardized logging handlers, formatters, and loggers.
Strictly decoupled from PySide6 GUI framework.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

_DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    stream: TextIO | None = None,
    log_format: str = _DEFAULT_LOG_FORMAT,
    date_format: str = _DEFAULT_DATE_FORMAT,
) -> logging.Logger:
    """Configure structured, clean application logging.

    Idempotent: If handlers are already registered on the 'app' logger,
    they will not be duplicated.

    Args:
        level: Logging level (e.g. logging.INFO, logging.DEBUG).
        stream: Output stream (defaults to sys.stderr).
        log_format: Format string for log records.
        date_format: Date/time format string.

    Returns:
        The configured root or package logger for 'app'.
    """
    logger = logging.getLogger("app")
    logger.setLevel(level)

    # Prevent duplicate StreamHandlers
    has_stream_handler = any(
        isinstance(handler, logging.StreamHandler) for handler in logger.handlers
    )

    if not has_stream_handler:
        target_stream = stream if stream is not None else sys.stderr
        handler = logging.StreamHandler(target_stream)
        handler.setLevel(level)
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Retrieve a hierarchical logger under the 'app' namespace.

    Args:
        name: Sub-logger name (e.g. 'core.search_engine', 'utils.platform_utils').

    Returns:
        logging.Logger instance.
    """
    if name is None or name == "app":
        return logging.getLogger("app")
    if name.startswith("app."):
        return logging.getLogger(name)
    return logging.getLogger(f"app.{name}")
