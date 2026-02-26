"""Centralized logging config for the booking bot.

Usage in any module:
    from core.log import get_logger
    logger = get_logger(__name__)
    logger.info("message", extra={"user_id": "abc"})

Renders as:
    2026-02-26 14:30:00 INFO  [module.name] message | user_id=abc
"""

import logging
import sys


_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_configured = False


def _setup_root() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FMT))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, initialising root config on first call."""
    _setup_root()
    return logging.getLogger(name)
