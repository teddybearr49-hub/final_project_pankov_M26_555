"""Хранилище Parser Service: rates.json (снимок) и exchange_rates.json (история)."""

from typing import Any

from valutatrade_hub.core.utils import parse_timestamp
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


class RatesStorage:
    """Чтение/запись кеша и истории курсов (атомарно, через DatabaseManager)."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self._config = config or ParserConfig()
        self._db = DatabaseManager()

    def load_rates(self) -> dict[str, Any]:
        """Читает кеш курсов rates.json."""
        data = self._db.read_json(self._config.RATES_FILE_PATH, {})
        if "pairs" not in data:
            return {"pairs": {}, "last_refresh": None}
        return data

    def save_rates(self, pairs: dict[str, dict[str, Any]], last_refresh: str) -> None:
        """Обновляет снимок: пара перезаписывается, если новая запись не старше."""
        cache = self.load_rates()
        current = cache["pairs"]
        for pair, info in pairs.items():
            old = current.get(pair)
            if old is None or not old.get("updated_at"):
                current[pair] = info
                continue
            new_ts = parse_timestamp(info["updated_at"])
            if new_ts >= parse_timestamp(old["updated_at"]):
                current[pair] = info
        cache["last_refresh"] = last_refresh
        self._db.write_json(self._config.RATES_FILE_PATH, cache)

    def load_history(self) -> list[dict[str, Any]]:
        """Читает историю курсов exchange_rates.json."""
        return self._db.read_json(self._config.HISTORY_FILE_PATH, [])

    def append_history(self, records: list[dict[str, Any]]) -> int:
        """Добавляет в историю только записи с новыми id; возвращает их число."""
        history = self.load_history()
        known_ids = {record.get("id") for record in history}
        new_records = [r for r in records if r["id"] not in known_ids]
        if new_records:
            history.extend(new_records)
            self._db.write_json(self._config.HISTORY_FILE_PATH, history)
        return len(new_records)
