"""Singleton DatabaseManager: абстракция над JSON-хранилищем."""

import json
from pathlib import Path
from typing import Any, Self

from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Единая точка чтения/записи JSON-файлов в data/.

    Singleton через __new__, как и SettingsLoader.
    """

    _instance = None

    def __new__(cls) -> Self:
        """Возвращает единственный экземпляр класса (Singleton)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def _settings(self) -> SettingsLoader:
        return SettingsLoader()

    @staticmethod
    def read_json(path: Path, default: Any) -> Any:
        """Читает JSON; для отсутствующего или пустого файла возвращает default."""
        if not path.exists():
            return default
        content = path.read_text(encoding="utf-8").strip()
        return json.loads(content) if content else default

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        """Атомарная запись: временный файл → rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def load_users(self) -> list[dict[str, Any]]:
        """Читает список пользователей."""
        return self.read_json(self._settings.path("users_file"), [])

    def save_users(self, users: list[dict[str, Any]]) -> None:
        """Сохраняет список пользователей."""
        self.write_json(self._settings.path("users_file"), users)

    def load_portfolios(self) -> list[dict[str, Any]]:
        """Читает список портфелей."""
        return self.read_json(self._settings.path("portfolios_file"), [])

    def save_portfolios(self, portfolios: list[dict[str, Any]]) -> None:
        """Сохраняет список портфелей."""
        self.write_json(self._settings.path("portfolios_file"), portfolios)

    def load_rates(self) -> dict[str, Any]:
        """Читает кеш курсов rates.json."""
        data = self.read_json(self._settings.path("rates_file"), {})
        if "pairs" not in data:
            return {"pairs": {}, "last_refresh": None}
        return data

    def save_rates(self, rates: dict[str, Any]) -> None:
        """Сохраняет кеш курсов rates.json."""
        self.write_json(self._settings.path("rates_file"), rates)
