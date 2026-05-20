"""Structured logging configuration."""

import structlog
import logging
import sys

from app.core.config import settings


def configure_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.ExtraAdder(),
    ]

    if settings.LOG_FORMAT == "json":
        formatter = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    else:
        formatter = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=shared_processors + [formatter],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
