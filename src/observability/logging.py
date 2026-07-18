"""Standard-library logging setup with no import-time configuration."""

from __future__ import annotations

import logging
from typing import Final

from src.config import AppSettings, get_settings

_FORMAT: Final = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(settings: AppSettings | None = None) -> None:
    """Configure process logging when the application explicitly starts."""
    resolved = settings or get_settings()
    logging.basicConfig(level=resolved.logging_level, format=_FORMAT, force=True)


def get_logger(name: str) -> logging.Logger:
    """Return a logger without configuring handlers or loading settings."""
    return logging.getLogger(name)
