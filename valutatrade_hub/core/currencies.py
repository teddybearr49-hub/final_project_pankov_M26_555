"""Иерархия валют (Currency → FiatCurrency / CryptoCurrency) и реестр."""

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

CODE_MIN_LEN = 2
CODE_MAX_LEN = 5


class Currency(ABC):
    """Абстрактная валюта: имя, код и строковое представление."""

    def __init__(self, name: str, code: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        if not self._is_valid_code(code):
            raise ValueError(f"Некорректный код валюты '{code}'")
        self.name = name.strip()
        self.code = code

    @staticmethod
    def _is_valid_code(code: str) -> bool:
        return (
            isinstance(code, str)
            and code == code.upper()
            and CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN
            and " " not in code
        )

    @abstractmethod
    def get_display_info(self) -> str:
        """Строковое представление для UI и логов."""


class FiatCurrency(Currency):
    """Фиатная валюта с указанием страны/зоны эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        """Строковое представление валюты для UI и логов."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и рыночной капитализацией."""

    def __init__(
        self, name: str, code: str, algorithm: str, market_cap: float
    ) -> None:
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = float(market_cap)

    def get_display_info(self) -> str:
        """Строковое представление валюты для UI и логов."""
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {_short_sci(self.market_cap)})"
        )


def _short_sci(value: float) -> str:
    """1.12e+12 → 1.12e12."""
    mantissa, exponent = f"{value:.2e}".split("e")
    return f"{mantissa}e{int(exponent)}"


_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("British Pound", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
        CryptoCurrency("Solana", "SOL", "Proof of History", 6.5e10),
    )
}


def get_currency(code: str) -> Currency:
    """Валюта по коду; неизвестный код → CurrencyNotFoundError."""
    normalized = code.strip().upper() if isinstance(code, str) else str(code)
    try:
        return _REGISTRY[normalized]
    except KeyError:
        raise CurrencyNotFoundError(normalized) from None


def list_currencies() -> list[Currency]:
    """Все поддерживаемые валюты, отсортированные по коду."""
    return sorted(_REGISTRY.values(), key=lambda currency: currency.code)


def is_crypto(code: str) -> bool:
    """Проверяет, является ли код криптовалютой из реестра."""
    return isinstance(_REGISTRY.get(code), CryptoCurrency)
