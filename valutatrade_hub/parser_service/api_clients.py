"""Клиенты внешних API: CoinGecko (крипта) и ExchangeRate-API (фиат)."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now_iso
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.config import ParserConfig

logger = logging.getLogger(PARSER_LOGGER_NAME)

HTTP_OK = 200
HTTP_SERVER_ERROR = 500
HTTP_ERRORS = {
    400: "некорректный запрос (400)",
    401: "неверный или отсутствующий API-ключ (401)",
    403: "доступ запрещён, проверьте API-ключ (403)",
    404: "ресурс не найден, проверьте URL и ключ (404)",
    429: "превышен лимит запросов, повторите позже (429)",
}
EXCHANGERATE_ERRORS = {
    "invalid-key": "неверный API-ключ",
    "inactive-account": "аккаунт не активирован (подтвердите email)",
    "quota-reached": "исчерпан лимит запросов",
    "unsupported-code": "неподдерживаемый код валюты",
    "malformed-request": "некорректный запрос",
}


def _unix_to_iso(timestamp: Any) -> str:
    """Unix-время → ISO UTC с суффиксом Z (иначе — текущее время)."""
    if isinstance(timestamp, int | float) and timestamp > 0:
        moment = datetime.fromtimestamp(timestamp, UTC).replace(microsecond=0)
        return moment.isoformat().replace("+00:00", "Z")
    return utc_now_iso()


def _is_positive_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value > 0
    )


class BaseApiClient(ABC):
    """Единый интерфейс: fetch_rates() -> {'BTC_USD': 59337.21, ...}.

    После вызова доступны метаданные: timestamps, raw_ids, meta.
    """

    name = "base"
    key = "base"

    def __init__(self, config: ParserConfig | None = None) -> None:
        self._config = config or ParserConfig()
        self.timestamps: dict[str, str] = {}
        self.raw_ids: dict[str, str] = {}
        self.meta: dict[str, Any] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Курсы {'XXX_USD': rate}; при сбое — ApiRequestError."""

    def _request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        timeout = self._config.REQUEST_TIMEOUT
        started = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=timeout
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(f"превышен таймаут {timeout} с") from None
        except requests.exceptions.ConnectionError:
            raise ApiRequestError("нет соединения с сервером") from None
        except requests.exceptions.RequestException as exc:
            # Текст исключения не выводим: в нём может быть URL с ключом
            raise ApiRequestError(exc.__class__.__name__) from None
        self.meta = {
            "request_ms": int((time.perf_counter() - started) * 1000),
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }
        return response

    @staticmethod
    def _http_error(status_code: int) -> ApiRequestError:
        if status_code >= HTTP_SERVER_ERROR:
            return ApiRequestError(f"сервис временно недоступен ({status_code})")
        reason = HTTP_ERRORS.get(status_code, f"неожиданный ответ ({status_code})")
        return ApiRequestError(reason)

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


class CoinGeckoClient(BaseApiClient):
    """Курсы криптовалют к USD (по ID монет из CRYPTO_ID_MAP)."""

    name = "CoinGecko"
    key = "coingecko"

    def fetch_rates(self) -> dict[str, float]:
        """Запрашивает курсы и возвращает {'XXX_USD': rate}."""
        cfg = self._config
        vs_currency = cfg.BASE_CURRENCY.lower()
        ids = {code: cfg.CRYPTO_ID_MAP[code] for code in cfg.CRYPTO_CURRENCIES}
        params = {
            "ids": ",".join(ids.values()),
            "vs_currencies": vs_currency,
            "include_last_updated_at": "true",
        }
        headers = (
            {"x-cg-demo-api-key": cfg.COINGECKO_API_KEY}
            if cfg.COINGECKO_API_KEY
            else None
        )
        response = self._request(cfg.COINGECKO_URL, params, headers)
        if response.status_code != HTTP_OK:
            raise self._http_error(response.status_code)

        data = self._json(response)
        rates: dict[str, float] = {}
        self.timestamps, self.raw_ids = {}, {}
        for code, coin_id in ids.items():
            coin = data.get(coin_id) or {}
            price = coin.get(vs_currency)
            if not _is_positive_number(price):
                logger.warning("CoinGecko: no valid price for %s", code)
                continue
            pair = f"{code}_{cfg.BASE_CURRENCY}"
            rates[pair] = float(price)
            self.timestamps[pair] = _unix_to_iso(coin.get("last_updated_at"))
            self.raw_ids[pair] = coin_id
        if not rates:
            raise ApiRequestError("ответ не содержит курсов")
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Курсы фиатных валют к USD.

    API отдаёт «1 USD = x EUR»; сохраняем обратное значение EUR_USD = 1/x,
    чтобы смысл пары был единым: 1 единица валюты = rate USD.
    """

    name = "ExchangeRate-API"
    key = "exchangerate"

    def fetch_rates(self) -> dict[str, float]:
        """Запрашивает курсы и возвращает {'XXX_USD': rate}."""
        cfg = self._config
        if not cfg.EXCHANGERATE_API_KEY:
            raise ApiRequestError("не задан ключ EXCHANGERATE_API_KEY (файл .env)")
        url = (
            f"{cfg.EXCHANGERATE_API_URL}/{cfg.EXCHANGERATE_API_KEY}"
            f"/latest/{cfg.BASE_CURRENCY}"
        )
        response = self._request(url)
        data = self._json(response)
        if data.get("result") == "error":
            error_type = str(data.get("error-type", ""))
            reason = EXCHANGERATE_ERRORS.get(error_type, f"ошибка API ({error_type})")
            raise ApiRequestError(reason)
        if response.status_code != HTTP_OK:
            raise self._http_error(response.status_code)

        quotes = data.get("conversion_rates") or data.get("rates") or {}
        updated_at = _unix_to_iso(data.get("time_last_update_unix"))
        rates: dict[str, float] = {}
        self.timestamps, self.raw_ids = {}, {}
        for code in cfg.FIAT_CURRENCIES:
            quote = quotes.get(code)
            if not _is_positive_number(quote):
                logger.warning("ExchangeRate-API: no valid rate for %s", code)
                continue
            pair = f"{code}_{cfg.BASE_CURRENCY}"
            rates[pair] = 1 / float(quote)
            self.timestamps[pair] = updated_at
            self.raw_ids[pair] = code
        if not rates:
            raise ApiRequestError("ответ не содержит курсов")
        return rates
