"""Конфигурация Parser Service: ключи, эндпоинты, списки валют, пути."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import PROJECT_ROOT, SettingsLoader

ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Загружает KEY=VALUE из .env в окружение (не перезаписывая существующие)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file()


def _env(name: str) -> str | None:
    return os.getenv(name) or None


@dataclass(frozen=True)
class ParserConfig:
    """Все изменяемые параметры Parser Service в одном месте."""

    # Ключи берутся только из окружения / .env, не из кода
    EXCHANGERATE_API_KEY: str | None = field(
        default_factory=lambda: _env("EXCHANGERATE_API_KEY")
    )
    COINGECKO_API_KEY: str | None = field(
        default_factory=lambda: _env("COINGECKO_API_KEY")
    )

    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )

    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().path("rates_file")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().path("history_file")
    )

    REQUEST_TIMEOUT: int = 10
    UPDATE_INTERVAL_SECONDS: int = 300
