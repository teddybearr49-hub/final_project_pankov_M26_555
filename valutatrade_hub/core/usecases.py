"""Бизнес-логика: регистрация, вход, операции с портфелем, курсы."""

from datetime import UTC, datetime
from typing import Any

from valutatrade_hub.core.exceptions import (
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    STUB_RATES,
    get_exchange_rate,
    parse_timestamp,
    utc_now_iso,
    validate_amount,
    validate_currency_code,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader

_db = DatabaseManager()
_settings = SettingsLoader()


def _base_currency() -> str:
    return _settings.get("default_base_currency", "USD")


# ---------- Пользователи ----------


def register_user(username: str, password: str) -> User:
    """Регистрирует пользователя и создаёт ему пустой портфель."""
    username = username.strip()
    users = _db.load_users()
    if any(record["username"] == username for record in users):
        raise ValueError(f"Имя пользователя '{username}' уже занято")

    user_id = max((record["user_id"] for record in users), default=0) + 1
    user = User.create(user_id, username, password)
    users.append(user.to_dict())
    _db.save_users(users)

    portfolios = _db.load_portfolios()
    portfolios.append(Portfolio(user_id).to_dict())
    _db.save_portfolios(portfolios)
    return user


def login_user(username: str, password: str) -> User:
    """Проверяет логин и пароль, возвращает пользователя."""
    record = next(
        (r for r in _db.load_users() if r["username"] == username.strip()), None
    )
    if record is None:
        raise ValueError(f"Пользователь '{username}' не найден")
    user = User.from_dict(record)
    if not user.verify_password(password):
        raise ValueError("Неверный пароль")
    return user


# ---------- Портфели ----------


def _load_portfolio(user_id: int) -> Portfolio:
    for record in _db.load_portfolios():
        if record["user_id"] == user_id:
            return Portfolio.from_dict(record)
    return Portfolio(user_id)


def _save_portfolio(portfolio: Portfolio) -> None:
    records = _db.load_portfolios()
    for index, record in enumerate(records):
        if record["user_id"] == portfolio.user_id:
            records[index] = portfolio.to_dict()
            break
    else:
        records.append(portfolio.to_dict())
    _db.save_portfolios(records)


# ---------- Курсы ----------


def _is_fresh(timestamp: str | None) -> bool:
    if not timestamp:
        return False
    age = datetime.now(UTC) - parse_timestamp(timestamp)
    return age.total_seconds() < _settings.get("rates_ttl_seconds", 300)


def _refresh_rates() -> dict[str, Any]:
    """Обновляет кеш курсов (заглушка до подключения Parser Service)."""
    now = utc_now_iso()
    cache = {
        "pairs": {
            pair: {"rate": rate, "updated_at": now, "source": "stub"}
            for pair, rate in STUB_RATES.items()
        },
        "last_refresh": now,
    }
    _db.save_rates(cache)
    return cache


def _get_rates() -> tuple[dict[str, float], str | None]:
    """Курсы из кеша rates.json; устаревший кеш обновляется."""
    cache = _db.load_rates()
    if not _is_fresh(cache.get("last_refresh")):
        cache = _refresh_rates()
    rates = {pair: info["rate"] for pair, info in cache["pairs"].items()}
    return rates, cache.get("last_refresh")


def _known_codes(rates: dict[str, float]) -> set[str]:
    codes = {_base_currency()}
    for pair in rates:
        codes.update(pair.split("_"))
    return codes


def get_rate(from_code: str, to_code: str) -> dict[str, Any]:
    """Курс from→to, обратный курс и время обновления."""
    src = validate_currency_code(from_code)
    dst = validate_currency_code(to_code)
    rates, updated_at = _get_rates()
    known = _known_codes(rates)
    for code in (src, dst):
        if code not in known:
            raise CurrencyNotFoundError(code)
    rate = get_exchange_rate(src, dst, rates)
    return {
        "from": src,
        "to": dst,
        "rate": rate,
        "reverse_rate": 1 / rate,
        "updated_at": updated_at,
    }


# ---------- Операции ----------


def get_portfolio_report(
    user_id: int, base_currency: str | None = None
) -> dict[str, Any]:
    """Кошельки пользователя и их стоимость в базовой валюте."""
    base = validate_currency_code(base_currency or _base_currency())
    rates, _ = _get_rates()
    if base not in _known_codes(rates):
        raise CurrencyNotFoundError(base)
    portfolio = _load_portfolio(user_id)
    rows = [
        {
            "code": code,
            "balance": wallet.balance,
            "value": wallet.balance * get_exchange_rate(code, base, rates),
        }
        for code, wallet in portfolio.wallets.items()
    ]
    return {
        "base": base,
        "rows": rows,
        "total": portfolio.get_total_value(base, rates),
    }


def buy(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Покупка валюты за базовую (USD); покупка USD — пополнение."""
    code = validate_currency_code(currency_code)
    amount = validate_amount(amount)
    base = _base_currency()
    portfolio = _load_portfolio(user_id)

    rate = 1.0 if code == base else get_rate(code, base)["rate"]
    cost = amount * rate
    if code != base:
        base_wallet = portfolio.get_wallet(base)
        if base_wallet is None:
            raise InsufficientFundsError(0.0, cost, base)
        base_wallet.withdraw(cost)

    wallet = portfolio.get_wallet(code) or portfolio.add_currency(code)
    before = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)
    return {
        "currency": code,
        "amount": amount,
        "rate": rate,
        "base": base,
        "cost": cost,
        "before": before,
        "after": wallet.balance,
    }


def sell(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Продажа валюты; выручка зачисляется на кошелёк базовой валюты."""
    code = validate_currency_code(currency_code)
    amount = validate_amount(amount)
    base = _base_currency()
    portfolio = _load_portfolio(user_id)

    wallet = portfolio.get_wallet(code)
    if wallet is None:
        raise ValueError(
            f"У вас нет кошелька '{code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )
    rate = 1.0 if code == base else get_rate(code, base)["rate"]
    before = wallet.balance
    wallet.withdraw(amount)
    revenue = amount * rate
    if code != base:
        base_wallet = portfolio.get_wallet(base) or portfolio.add_currency(base)
        base_wallet.deposit(revenue)
    _save_portfolio(portfolio)
    return {
        "currency": code,
        "amount": amount,
        "rate": rate,
        "base": base,
        "revenue": revenue,
        "before": before,
        "after": wallet.balance,
    }
