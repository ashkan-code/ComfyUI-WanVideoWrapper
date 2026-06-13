"""Logging configuration for the XT MCP server.

Call configure_logging() exactly once at server startup.
"""

from __future__ import annotations

import logging
import logging.handlers
import pathlib


def configure_logging() -> None:
    """Set up root logger with rotating file handler and stderr handler."""
    from xt_mcp.config import settings  # late import to avoid circular init

    log_path = pathlib.Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # stderr handler: only WARNING+ to avoid polluting MCP stdio transport stdout
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level))
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)
