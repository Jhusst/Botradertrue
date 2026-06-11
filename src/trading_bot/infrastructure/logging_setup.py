"""Logging rotativo a archivo para operación 24/7 desatendida."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from trading_bot.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """structlog → stdlib logging con archivo rotativo JSON + consola legible."""
    log_path = Path(settings.log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    # Evitar handlers duplicados en reloads/tests
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler | logging.StreamHandler):
            root.removeHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
