"""Вспомогательные функции: валидация и конвертация валют."""

import math

BASE_CURRENCY = "USD"
CURRENCY_CODE_MIN_LEN = 2
CURRENCY_CODE_MAX_LEN = 5

# Заглушка курсов: 1 единица валюты = rate USD.
# Будет заменена кешем data/rates.json после подключения Parser Service.
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
    raise ValueError(f"Курс {from_code}→{to_code} недоступен")
