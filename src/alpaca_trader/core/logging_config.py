"""Structured JSON logging configuration for alpaca-trader.

Provides a JSON formatter and setup function for consistent, machine-parseable
log output across all modules. Falls back to human-readable format when
LOG_FORMAT=text or when running interactively.

Usage:
    from alpaca_trader.core.logging_config import setup_logging
    setup_logging()  # Call once at app startup
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Output fields:
        timestamp: ISO 8601 UTC timestamp
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        logger: Logger name (module path)
        message: Formatted log message
        module: Source module name
        function: Source function name
        line: Source line number
        exc_info: Exception traceback (if present)
        extra: Any extra fields passed via extra={} on the log call
    """

    _BUILTIN_ATTRS = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_entry["stack_info"] = record.stack_info

        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in self._BUILTIN_ATTRS and not k.startswith("_")
        }
        if extra:
            log_entry["extra"] = extra

        return json.dumps(log_entry, default=str)


class HumanFormatter(logging.Formatter):
    """Clean human-readable formatter for interactive use."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging(
    level: Optional[str] = None,
    format_type: Optional[str] = None,
) -> None:
    """Configure root logger for the alpaca-trader application.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR). Defaults to
               LOG_LEVEL env var, then INFO.
        format_type: 'json' or 'text'. Defaults to LOG_FORMAT env var,
                     then 'json' if not a TTY, 'text' if interactive.
    """
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    fmt = format_type or os.environ.get("LOG_FORMAT", "")

    if not fmt:
        fmt = "text" if sys.stderr.isatty() else "json"

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(HumanFormatter())

    root.addHandler(handler)

    for noisy in ("urllib3", "httpcore", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
