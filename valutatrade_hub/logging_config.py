"""Настройка логов: строковый формат, уровень из конфигурации, ротация."""

import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import PROJECT_ROOT, SettingsLoader

LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
ROOT_LOGGER_NAME = "valutatrade"
ACTIONS_LOG_FILE = "actions.log"
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 5


def setup_logging() -> None:
    """Логгер 'valutatrade' → logs/actions.log с ротацией по размеру."""
    settings = SettingsLoader()
    log_dir = PROJECT_ROOT / settings.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    level_name = str(settings.get("log_level", "INFO")).upper()
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False
    if root.handlers:
        return

    handler = RotatingFileHandler(
        log_dir / ACTIONS_LOG_FILE,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(handler)
