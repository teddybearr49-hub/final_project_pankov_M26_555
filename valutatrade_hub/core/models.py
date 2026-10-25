"""Доменные модели: пользователь, кошелёк, портфель."""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any, Self

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    BASE_CURRENCY,
    STUB_RATES,
    get_exchange_rate,
    validate_amount,
    validate_currency_code,
)

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 8


class User:
    """Пользователь системы."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> Self:
        """Создаёт нового пользователя: генерирует соль и хеширует пароль."""
        cls._validate_password(password)
        salt = secrets.token_hex(SALT_BYTES)
        return cls(
            user_id=user_id,
            username=username,
            hashed_password=cls._hash_password(password, salt),
            salt=salt,
            registration_date=datetime.now().replace(microsecond=0),
        )

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_password(password: str) -> None:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
            )

    @property
    def user_id(self) -> int:
        """Идентификатор пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Хеш пароля (SHA-256 с солью)."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Соль для хеширования пароля."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Дата регистрации."""
        return self._registration_date

    def get_user_info(self) -> dict[str, Any]:
        """Информация о пользователе без пароля и соли."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Меняет пароль: новая соль + новый хеш."""
        self._validate_password(new_password)
        self._salt = secrets.token_hex(SALT_BYTES)
        self._hashed_password = self._hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Проверяет пароль на совпадение с сохранённым хешем."""
        candidate = self._hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._hashed_password)

    def to_dict(self) -> dict[str, Any]:
        """Сериализует объект в словарь для JSON."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Восстанавливает объект из словаря JSON."""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=datetime.fromisoformat(data["registration_date"]),
        )


class Wallet:
    """Кошелёк пользователя для одной валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        self.currency_code = validate_currency_code(currency_code)
        self._balance = 0.0
        self.balance = balance

    @property
    def balance(self) -> float:
        """Текущий баланс кошелька."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("Баланс должен быть числом")
        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        """Пополнение баланса."""
        self._balance += validate_amount(amount)

    def withdraw(self, amount: float) -> None:
        """Снятие средств, если баланс позволяет."""
        amount = validate_amount(amount)
        if amount > self._balance:
            raise InsufficientFundsError(self._balance, amount, self.currency_code)
        self._balance -= amount

    def get_balance_info(self) -> str:
        """Строка с кодом валюты и балансом."""
        return f"{self.currency_code}: {self._balance:.4f}"

    def to_dict(self) -> dict[str, Any]:
        """Сериализует объект в словарь для JSON."""
        return {"currency_code": self.currency_code, "balance": self._balance}

    @classmethod
    def from_dict(cls, currency_code: str, data: dict[str, Any]) -> Self:
        """Восстанавливает объект из словаря JSON."""
        return cls(currency_code, data.get("balance", 0.0))


class Portfolio:
    """Все кошельки одного пользователя."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        user: User | None = None,
    ) -> None:
        self._user_id = user_id
        self._wallets: dict[str, Wallet] = dict(wallets) if wallets else {}
        self._user = user

    @property
    def user_id(self) -> int:
        """Идентификатор пользователя."""
        return self._user_id

    @property
    def user(self) -> User | None:
        """Владелец портфеля (только чтение)."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря кошельков."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Добавляет новый кошелёк, если его ещё нет."""
        code = validate_currency_code(currency_code)
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже существует")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Кошелёк по коду валюты или None."""
        return self._wallets.get(validate_currency_code(currency_code))

    def get_total_value(
        self,
        base_currency: str = BASE_CURRENCY,
        exchange_rates: dict[str, float] | None = None,
    ) -> float:
        """Общая стоимость всех кошельков в базовой валюте."""
        base = validate_currency_code(base_currency)
        rates = STUB_RATES if exchange_rates is None else exchange_rates
        return float(
            sum(
                wallet.balance * get_exchange_rate(code, base, rates)
                for code, wallet in self._wallets.items()
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Сериализует объект в словарь для JSON."""
        return {
            "user_id": self._user_id,
            "wallets": {
                code: {"balance": w.balance} for code, w in self._wallets.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], user: User | None = None) -> Self:
        """Восстанавливает объект из словаря JSON."""
        wallets = {
            code: Wallet.from_dict(code, w)
            for code, w in data.get("wallets", {}).items()
        }
        return cls(data["user_id"], wallets, user)
