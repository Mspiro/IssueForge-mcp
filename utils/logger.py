"""
Centralised logging setup for IssueForge.

Call `setup_logging()` once at each script entry-point.
All sub-modules use `logging.getLogger("IssueForge.<Module>")` and
automatically inherit the handlers configured here.
"""

import logging
import logging.handlers
import os
import sys


def setup_logging(log_file: str = None, console_level: str = None, file_level: str = None):
    """
    Configure the root "IssueForge" logger with a console handler and an
    optional rotating file handler.

    Args:
        log_file:      Path to log file. Defaults to config.LOG_FILE.
        console_level: Console log level string. Defaults to config.LOG_LEVEL_CONSOLE.
        file_level:    File log level string. Defaults to config.LOG_LEVEL_FILE.
    """
    from config import LOG_FILE, LOG_LEVEL_CONSOLE, LOG_LEVEL_FILE, LOG_ROTATION_DAYS

    log_file = log_file or LOG_FILE
    console_level = console_level or LOG_LEVEL_CONSOLE
    file_level = file_level or LOG_LEVEL_FILE

    root = logging.getLogger("IssueForge")
    # Guard: don't add duplicate handlers if called more than once.
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file handler — silently skip if the log directory is not writable.
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=LOG_ROTATION_DAYS,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        root.warning(f"Could not open log file '{log_file}': {e}. File logging disabled.")


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper — returns IssueForge.<name> logger."""
    return logging.getLogger(f"IssueForge.{name}")
