"""Вспомогательные функции: валидация, конвертация, форматирование."""

import math
from datetime import UTC, datetime

BASE_CURRENCY = "USD"
CURRENCY_CODE_MIN_LEN = 2
CURRENCY_CODE_MAX_LEN = 5

STUB_RATES: dict[str, float] = {
    "EUR_USD": 1.0786,
    "GBP_USD": 1.2650,
    "RUB_USD": 0.01016,
    "BTC_USD": 59337.21,
    "ETH_USD": 3720.00,
    "SOL_USD": 145.12,
}
FIAT_DIGITS = 2
CRYPTO_DIGITS = 4
RATE_DIGITS = 2
SMALL_RATE_DIGITS = 8

# Заглушка курсов: 1 единица валюты = rate USD.
# Заменится данными Parser Service.
STUB_RATES: dict[str, float] = {
    "EUR_USD": 1.0786,
    "RUB_USD": 0.01016,
    "BTC_USD": 59337.21,
    "ETH_USD": 3720.00,
}


def validate_currency_code(code: str) -> str:
    """Проверяет код валюты и возвращает его в верхнем регистре."""
    if not isinstance(code, str):
        raise TypeError("Код валюты должен быть строкой")
    normalized = code.strip().upper()
    length_ok = CURRENCY_CODE_MIN_LEN <= len(normalized) <= CURRENCY_CODE_MAX_LEN
    if not length_ok or not normalized.isalnum():
        raise ValueError(f"Некорректный код валюты '{code}'")
    return normalized


def validate_amount(amount: float) -> float:
    """Проверяет, что сумма — конечное положительное число."""
    is_number = isinstance(amount, int | float) and not isinstance(amount, bool)
    if not is_number or not math.isfinite(amount) or amount <= 0:
        raise ValueError("'amount' должен быть положительным числом")
    return float(amount)


def get_exchange_rate(
    from_code: str, to_code: str, rates: dict[str, float]
) -> float:
    """Возвращает курс from→to по словарю пар 'XXX_YYY'.

    Поддерживает прямой, обратный и кросс-курс через базовую валюту.
    """
    if from_code == to_code:
        return 1.0
    direct = rates.get(f"{from_code}_{to_code}")
    if direct:
        return direct
    reverse = rates.get(f"{to_code}_{from_code}")
    if reverse:
        return 1 / reverse
    if BASE_CURRENCY not in (from_code, to_code):
        to_base = get_exchange_rate(from_code, BASE_CURRENCY, rates)
        from_base = get_exchange_rate(BASE_CURRENCY, to_code, rates)
        return to_base * from_base
    raise ValueError(
        f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
    )


def format_amount(value: float, code: str) -> str:
    """Сумма: 4 знака для крипты, 2 для фиата, с разделителем тысяч."""
    from valutatrade_hub.core.currencies import is_crypto

    digits = CRYPTO_DIGITS if is_crypto(code) else FIAT_DIGITS
    return f"{value:,.{digits}f}"


def format_rate(rate: float) -> str:
    """Курс: 8 знаков для малых значений, иначе 2."""
    digits = RATE_DIGITS if rate >= 1 else SMALL_RATE_DIGITS
    return f"{rate:.{digits}f}"


def utc_now_iso() -> str:
    """Текущее время UTC в ISO-формате с суффиксом Z."""
    now = datetime.now(UTC).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    """ISO-строка → aware datetime (наивное время считается UTC)."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_timestamp(value: str | None) -> str:
    """ISO-строка → 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return "—"
    return parse_timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
