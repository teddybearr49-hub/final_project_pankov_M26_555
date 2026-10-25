"""Координация обновления: опрос клиентов, объединение, сохранение."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now_iso
from valutatrade_hub.infra.settings import PROJECT_ROOT
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage

logger = logging.getLogger(PARSER_LOGGER_NAME)


@dataclass
class UpdateResult:
    """Итог обновления: число курсов, время, ошибки по источникам."""

    updated: int = 0
    last_refresh: str | None = None
    errors: dict[str, str] = field(default_factory=dict)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


class RatesUpdater:
    """Точка входа логики парсинга."""

    def __init__(
        self,
        clients: list[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        self._config = config or ParserConfig()
        self._clients = (
            clients
            if clients is not None
            else [CoinGeckoClient(self._config), ExchangeRateApiClient(self._config)]
        )
        self._storage = storage or RatesStorage(self._config)

    def _select_clients(self, source: str | None) -> list[BaseApiClient]:
        if source is None:
            return self._clients
        selected = [c for c in self._clients if c.key == source.lower()]
        if not selected:
            available = ", ".join(c.key for c in self._clients)
            raise ValueError(f"Неизвестный источник '{source}'. Доступны: {available}")
        return selected

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Опрашивает клиентов; сбой одного не останавливает остальных."""
        clients = self._select_clients(source)
        result = UpdateResult()
        pairs: dict[str, dict[str, Any]] = {}
        history: list[dict[str, Any]] = []

        logger.info("Starting rates update...")
        for client in clients:
            try:
                rates = client.fetch_rates()
            except ApiRequestError as exc:
                logger.error("Failed to fetch from %s: %s", client.name, exc.reason)
                result.errors[client.name] = exc.reason
                continue
            logger.info("Fetching from %s... OK (%d rates)", client.name, len(rates))
            for pair, rate in rates.items():
                updated_at = client.timestamps.get(pair) or utc_now_iso()
                pairs[pair] = {
                    "rate": rate,
                    "updated_at": updated_at,
                    "source": client.name,
                }
                history.append(self._history_record(client, pair, rate, updated_at))

        if not pairs:
            logger.error("No rates received, cache not changed")
            return result

        result.last_refresh = utc_now_iso()
        target = _display_path(self._config.RATES_FILE_PATH)
        logger.info("Writing %d rates to %s...", len(pairs), target)
        self._storage.save_rates(pairs, result.last_refresh)
        added = self._storage.append_history(history)
        result.updated = len(pairs)
        logger.info("History: %d new records", added)
        return result

    @staticmethod
    def _history_record(
        client: BaseApiClient, pair: str, rate: float, updated_at: str
    ) -> dict[str, Any]:
        from_code, to_code = pair.split("_")
        return {
            "id": f"{pair}_{updated_at}",
            "from_currency": from_code,
            "to_currency": to_code,
            "rate": rate,
            "timestamp": updated_at,
            "source": client.name,
            "meta": {"raw_id": client.raw_ids.get(pair), **client.meta},
        }
