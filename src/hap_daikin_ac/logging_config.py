"""Logging setup for the CLI."""

from __future__ import annotations

import logging
import os
import sys


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[31;1m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = self.COLORS.get(record.levelno)
        if not color:
            return message
        return f"{color}{message}{self.RESET}"


def configure_logging(level_name: str | None = None, *, color: bool = True) -> None:
    """Configure root logging with optional colorized console output."""
    level_name = level_name or os.getenv("HAP_DAIKIN_LOG_LEVEL", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    use_color = color and sys.stderr.isatty() and "NO_COLOR" not in os.environ
    if use_color:
        try:
            import colorlogs  # noqa: F401
            from colorama import init

            init(autoreset=True)
        except Exception:
            use_color = False

    formatter_cls = _ColorFormatter if use_color else logging.Formatter
    formatter = formatter_cls(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        "%H:%M:%S",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

