"""Singleton SettingsLoader: конфигурация из pyproject.toml [tool.valutatrade]."""

import tomllib
from pathlib import Path
from typing import Any, Self

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = (
    _PACKAGE_ROOT if (_PACKAGE_ROOT / "pyproject.toml").exists() else Path.cwd()
)
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"

DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "history_file": "exchange_rates.json",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "log_level": "INFO",
}


class SettingsLoader:
    """Единственный экземпляр конфигурации проекта.

    Singleton через __new__: проще и читабельнее метакласса;
    любой вызов SettingsLoader() возвращает тот же объект.
    """

    _instance = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._config = {}
            instance.reload()
            cls._instance = instance
        return cls._instance

    def reload(self) -> None:
        """Перечитывает конфигурацию из pyproject.toml."""
        config = dict(DEFAULTS)
        if PYPROJECT_PATH.exists():
            with PYPROJECT_PATH.open("rb") as file:
                data = tomllib.load(file)
            config.update(data.get("tool", {}).get("valutatrade", {}))
        self._config = config

    def get(self, key: str, default: Any = None) -> Any:
        """Значение параметра конфигурации."""
        return self._config.get(key, default)

    def path(self, key: str) -> Path:
        """Абсолютный путь к файлу данных (users_file, rates_file, ...)."""
        return PROJECT_ROOT / self._config["data_dir"] / self._config[key]
