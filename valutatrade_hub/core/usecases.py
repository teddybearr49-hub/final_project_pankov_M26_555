"""Бизнес-логика: регистрация, вход, операции с портфелем, курсы."""

from datetime import UTC, datetime
from typing import Any

from valutatrade_hub.core.currencies import (
    Currency,
    get_currency,
    is_crypto,
    list_currencies,
)
from valutatrade_hub.core.exceptions import ApiRequestError, InsufficientFundsError
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    get_exchange_rate,
    parse_timestamp,
    validate_amount,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import RatesUpdater, UpdateResult

_db = DatabaseManager()
_settings = SettingsLoader()


def _base_currency() -> str:
    return _settings.get("default_base_currency", "USD")


def list_supported_currencies() -> list[Currency]:
    """Список поддерживаемых валют."""
    return list_currencies()


# ---------- Пользователи ----------


@log_action("REGISTER")
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


@log_action("LOGIN")
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
    """Безопасная операция: чтение → модификация → атомарная запись."""
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
    """Кеш устарел → обновление через Parser Service; неудача → ApiRequestError."""
    result = RatesUpdater().run_update()
    if not result.updated:
        reason = "; ".join(f"{src}: {err}" for src, err in result.errors.items())
        raise ApiRequestError(reason or "курсы не получены")
    return _db.load_rates()


def _get_rates() -> tuple[dict[str, float], str | None]:
    """Курсы из кеша rates.json; устаревший по TTL кеш обновляется."""
    cache = _db.load_rates()
    if not _is_fresh(cache.get("last_refresh")):
        cache = _refresh_rates()
    rates = {pair: info["rate"] for pair, info in cache["pairs"].items()}
    return rates, cache.get("last_refresh")


def get_rate(from_code: str, to_code: str) -> dict[str, Any]:
    """Курс from→to, обратный курс и время обновления."""
    src = get_currency(from_code).code
    dst = get_currency(to_code).code
    rates, updated_at = _get_rates()
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
    base = get_currency(base_currency or _base_currency()).code
    rates, _ = _get_rates()
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


@log_action("BUY", verbose=True)
def buy(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Покупка валюты за базовую (USD); покупка USD — пополнение."""
    code = get_currency(currency_code).code
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


@log_action("SELL", verbose=True)
def sell(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Продажа валюты; выручка зачисляется на кошелёк базовой валюты."""
    code = get_currency(currency_code).code
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

# ---------- Parser Service ----------


def update_rates(source: str | None = None) -> UpdateResult:
    """Немедленное обновление курсов (все источники или один)."""
    return RatesUpdater().run_update(source)


def get_rates_snapshot(
    currency: str | None = None,
    top: int | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Курсы из локального кеша с фильтрами, без обращения к API."""
    cache = _db.load_rates()
    rates = {pair: info["rate"] for pair, info in cache["pairs"].items()}
    if not rates:
        raise ValueError(
            "Локальный кеш курсов пуст. "
            "Выполните 'update-rates', чтобы загрузить данные."
        )
    if top is not None and top <= 0:
        raise ValueError("'top' должен быть положительным целым числом")

    if base:
        base_code = get_currency(base).code
        codes = {code for pair in rates for code in pair.split("_")} - {base_code}
        rows = {
            f"{code}_{base_code}": get_exchange_rate(code, base_code, rates)
            for code in codes
        }
    else:
        rows = dict(rates)

    if currency:
        code = currency.strip().upper()
        rows = {pair: rate for pair, rate in rows.items() if code in pair.split("_")}
        if not rows:
            raise ValueError(f"Курс для '{code}' не найден в кеше.")

    if top is not None:
        crypto = [(p, r) for p, r in rows.items() if is_crypto(p.split("_")[0])]
        items = sorted(crypto, key=lambda item: item[1], reverse=True)[:top]
    else:
        items = sorted(rows.items())

    return {
        "rows": items,
        "last_refresh": cache.get("last_refresh"),
        "stale": not _is_fresh(cache.get("last_refresh")),
    }
