"""Настройка логов: строковый формат, уровень из конфигурации, ротация."""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import PROJECT_ROOT, SettingsLoader

LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
CONSOLE_FORMAT = "%(levelname)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
ROOT_LOGGER_NAME = "valutatrade"
PARSER_LOGGER_NAME = "valutatrade.parser"
ACTIONS_LOG_FILE = "actions.log"
PARSER_LOG_FILE = "parser.log"
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 5


def _log_dir_name() -> str:
    return SettingsLoader().get("log_dir", "logs")


def get_log_dir() -> Path:
    return PROJECT_ROOT / _log_dir_name()


def parser_log_hint() -> str:
    """Путь к логу парсера для сообщений пользователю: logs/parser.log."""
    return f"{_log_dir_name()}/{PARSER_LOG_FILE}"


def _file_handler(filename: str) -> RotatingFileHandler:
    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def setup_logging() -> None:
    """actions.log — доменные операции, parser.log — Parser Service."""
    level_name = str(SettingsLoader().get("log_level", "INFO")).upper()
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False
    if not root.handlers:
        root.addHandler(_file_handler(ACTIONS_LOG_FILE))

    parser_logger = logging.getLogger(PARSER_LOGGER_NAME)
    parser_logger.propagate = False
    if not parser_logger.handlers:
        parser_logger.addHandler(_file_handler(PARSER_LOG_FILE))

@contextmanager
def console_logging(logger_name: str = PARSER_LOGGER_NAME) -> Iterator[None]:
    """Временно дублирует логи в консоль (update-rates, планировщик)."""
    logger = logging.getLogger(logger_name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
