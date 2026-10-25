"""Командный интерфейс ValutaTrade Hub (интерактивный режим)."""

import argparse
import os
import shlex
import sys
from collections.abc import Callable
from typing import Any

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    ValutaTradeError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.utils import format_amount, format_rate, format_timestamp
from valutatrade_hub.decorators import confirm_action
from valutatrade_hub.logging_config import (
    console_logging,
    parser_log_hint,
    setup_logging,
)

PROMPT = "> "
WELCOME = "ValutaTrade Hub. Введите 'help' для списка команд, 'exit' — выход."
SOURCES = ("coingecko", "exchangerate")
CANCELLED_MESSAGE = "Операция отменена."

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"
USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

COMMANDS_HELP = [
    ("register --username <имя> --password <пароль>", "Регистрация"),
    ("login --username <имя> --password <пароль>", "Вход"),
    ("show-portfolio [--base <код>]", "Портфель и его стоимость"),
    ("buy --currency <код> --amount <кол-во> [--yes]", "Покупка валюты"),
    ("sell --currency <код> --amount <кол-во> [--yes]", "Продажа валюты"),
    ("get-rate --from <код> --to <код>", "Текущий курс"),
    ("update-rates [--source coingecko|exchangerate]", "Обновить курсы из API"),
    ("show-rates [--currency <код>] [--top N] [--base <код>]", "Курсы из кеша"),
    ("currencies", "Поддерживаемые валюты"),
    ("help", "Список команд"),
    ("exit", "Выход"),
]


# ---------- оформление вывода ----------


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if USE_COLOR else text


def _success(text: str) -> None:
    print(_paint(text, GREEN))


def _error(text: str) -> None:
    print(_paint(text, RED))


def _warn(text: str) -> None:
    print(_paint(text, YELLOW))


def _enable_ansi_on_windows() -> None:
    if os.name == "nt":
        os.system("")  # включает обработку ANSI-цветов в консоли Windows


def _print_trade(verb: str, result: dict[str, Any], total_key: str, label: str) -> None:
    code, base = result["currency"], result["base"]
    line = f"{verb} выполнена: {format_amount(result['amount'], code)} {code}"
    if code != base:
        line += f" по курсу {format_rate(result['rate'])} {base}/{code}"
    _success(line)
    print("Изменения в портфеле:")
    print(
        f"- {code}: было {format_amount(result['before'], code)} → "
        f"стало {format_amount(result['after'], code)}"
    )
    if code != base:
        print(f"{label}: {format_amount(result[total_key], base)} {base}")


# ---------- разбор команд ----------


class CliArgumentError(Exception):
    """Ошибка разбора аргументов команды."""


class SilentArgumentParser(argparse.ArgumentParser):
    """ArgumentParser, который не завершает процесс при ошибке разбора."""

    def error(self, message: str) -> None:
        """Бросает CliArgumentError вместо завершения процесса."""
        raise CliArgumentError(message)


def build_parser() -> SilentArgumentParser:
    """Описание команд и их аргументов."""
    parser = SilentArgumentParser(prog="valutatrade", add_help=False)
    sub = parser.add_subparsers(dest="command", parser_class=SilentArgumentParser)

    for name in ("register", "login"):
        cmd = sub.add_parser(name, add_help=False)
        cmd.add_argument("--username", required=True)
        cmd.add_argument("--password", required=True)

    cmd = sub.add_parser("show-portfolio", add_help=False)
    cmd.add_argument("--base")

    for name in ("buy", "sell"):
        cmd = sub.add_parser(name, add_help=False)
        cmd.add_argument("--currency", required=True)
        cmd.add_argument("--amount", required=True)
        cmd.add_argument("-y", "--yes", action="store_true")

    cmd = sub.add_parser("get-rate", add_help=False)
    cmd.add_argument("--from", dest="from_code", required=True)
    cmd.add_argument("--to", dest="to_code", required=True)

    cmd = sub.add_parser("update-rates", add_help=False)
    cmd.add_argument("--source", choices=SOURCES)

    cmd = sub.add_parser("show-rates", add_help=False)
    cmd.add_argument("--currency")
    cmd.add_argument("--top", type=int)
    cmd.add_argument("--base")

    for name in ("currencies", "help", "exit"):
        sub.add_parser(name, add_help=False)
    return parser


def _parse_amount(raw: str) -> float:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        raise ValueError("'amount' должен быть положительным числом") from None


def _supported_codes() -> str:
    return ", ".join(c.code for c in usecases.list_supported_currencies())


# ---------- подтверждение операций ----------


def _trade_question(verb: str, currency_code: str, amount: float) -> str:
    quote = usecases.estimate_trade(currency_code, amount)
    code, base = quote["currency"], quote["base"]
    text = f"{verb} {format_amount(quote['amount'], code)} {code}"
    if code != base:
        text += f" ≈ {format_amount(quote['total'], base)} {base}"
    return f"{text}?"


def _buy_question(_user_id: int, currency_code: str, amount: float) -> str:
    return _trade_question("Купить", currency_code, amount)


def _sell_question(_user_id: int, currency_code: str, amount: float) -> str:
    return _trade_question("Продать", currency_code, amount)


confirmed_buy = confirm_action(_buy_question)(usecases.buy)
confirmed_sell = confirm_action(_sell_question)(usecases.sell)


# ---------- оболочка ----------


class ValutaTradeCLI:
    """Интерактивная оболочка: разбирает команды и вызывает usecases."""

    def __init__(self) -> None:
        self._parser = build_parser()
        self._current_user: User | None = None
        self._handlers: dict[str, Callable[[argparse.Namespace], None]] = {
            "register": self._register,
            "login": self._login,
            "show-portfolio": self._show_portfolio,
            "buy": self._buy,
            "sell": self._sell,
            "get-rate": self._get_rate,
            "update-rates": self._update_rates,
            "show-rates": self._show_rates,
            "currencies": self._currencies,
            "help": self._help,
        }

    def run(self) -> None:
        """Запускает интерактивный цикл ввода команд."""
        print(_paint(WELCOME, BOLD))
        while True:
            user = self._current_user
            prompt = f"{_paint(user.username, CYAN)}{PROMPT}" if user else PROMPT
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line and not self.execute(line):
                break

    def execute(self, line: str) -> bool:
        """Выполняет одну команду. Возвращает False для выхода."""
        try:
            args = self._parser.parse_args(shlex.split(line))
        except (CliArgumentError, ValueError) as exc:
            _error(f"Ошибка ввода: {exc}")
            return True
        if args.command == "exit":
            return False
        if args.command is None:
            _warn("Введите команду. Список команд: help")
            return True
        try:
            self._handlers[args.command](args)
        except CurrencyNotFoundError as exc:
            _error(str(exc))
            print(f"Поддерживаемые валюты: {_supported_codes()}")
        except ApiRequestError as exc:
            _error(f"{exc}. Повторите попытку позже или проверьте подключение к сети.")
        except (ValutaTradeError, ValueError, TypeError, OSError) as exc:
            _error(str(exc))
        return True

    def _require_login(self) -> User:
        if self._current_user is None:
            raise ValueError("Сначала выполните login")
        return self._current_user

    # ---------- обработчики команд ----------

    def _register(self, args: argparse.Namespace) -> None:
        user = usecases.register_user(args.username, args.password)
        _success(
            f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
            f"Войдите: login --username {user.username} --password ****"
        )

    def _login(self, args: argparse.Namespace) -> None:
        self._current_user = usecases.login_user(args.username, args.password)
        _success(f"Вы вошли как '{self._current_user.username}'")

    def _show_portfolio(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        try:
            report = usecases.get_portfolio_report(user.user_id, args.base)
        except CurrencyNotFoundError as exc:
            _error(f"Неизвестная базовая валюта '{exc.code}'")
            return
        base = report["base"]
        if not report["rows"]:
            _warn("Портфель пуст. Купите валюту: buy --currency <код> --amount <N>")
            return
        print(_paint(f"Портфель пользователя '{user.username}' (база: {base}):", BOLD))
        table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {base}"])
        table.align = "r"
        table.align["Валюта"] = "l"
        for row in report["rows"]:
            code = row["code"]
            table.add_row(
                [
                    code,
                    format_amount(row["balance"], code),
                    format_amount(row["value"], base),
                ]
            )
        print(table)
        print(_paint(f"ИТОГО: {format_amount(report['total'], base)} {base}", BOLD))

    def _buy(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        operation = usecases.buy if args.yes else confirmed_buy
        result = operation(user.user_id, args.currency, _parse_amount(args.amount))
        if result is None:
            _warn(CANCELLED_MESSAGE)
            return
        _print_trade("Покупка", result, "cost", "Оценочная стоимость покупки")

    def _sell(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        operation = usecases.sell if args.yes else confirmed_sell
        result = operation(user.user_id, args.currency, _parse_amount(args.amount))
        if result is None:
            _warn(CANCELLED_MESSAGE)
            return
        _print_trade("Продажа", result, "revenue", "Оценочная выручка")

    def _get_rate(self, args: argparse.Namespace) -> None:
        result = usecases.get_rate(args.from_code, args.to_code)
        src, dst = result["from"], result["to"]
        rate = _paint(format_rate(result["rate"]), BOLD)
        print(
            f"Курс {src}→{dst}: {rate} "
            f"(обновлено: {format_timestamp(result['updated_at'])})"
        )
        print(f"Обратный курс {dst}→{src}: {format_rate(result['reverse_rate'])}")

    def _update_rates(self, args: argparse.Namespace) -> None:
        with console_logging():
            result = usecases.update_rates(args.source)
        if result.errors:
            hint = parser_log_hint()
            _warn(f"Update completed with errors. Check {hint} for details.")
        else:
            _success(
                f"Update successful. Total rates updated: {result.updated}. "
                f"Last refresh: {result.last_refresh}"
            )

    def _show_rates(self, args: argparse.Namespace) -> None:
        snapshot = usecases.get_rates_snapshot(args.currency, args.top, args.base)
        updated = format_timestamp(snapshot["last_refresh"])
        print(_paint(f"Rates from cache (updated at {updated}):", BOLD))
        table = PrettyTable(["Пара", "Курс"])
        table.align["Пара"] = "l"
        table.align["Курс"] = "r"
        for pair, rate in snapshot["rows"]:
            table.add_row([pair, format_rate(rate)])
        print(table)
        if snapshot["stale"]:
            _warn("Внимание: кеш устарел. Выполните 'update-rates'.")

    def _currencies(self, _args: argparse.Namespace) -> None:
        table = PrettyTable(["Код", "Описание"])
        table.align = "l"
        for currency in usecases.list_supported_currencies():
            table.add_row([currency.code, currency.get_display_info()])
        print(table)

    def _help(self, _args: argparse.Namespace) -> None:
        table = PrettyTable(["Команда", "Описание"])
        table.align = "l"
        for command, description in COMMANDS_HELP:
            table.add_row([command, description])
        print(table)


def main() -> None:
    """Точка входа CLI."""
    _enable_ansi_on_windows()
    setup_logging()
    ValutaTradeCLI().run()


if __name__ == "__main__":
    main()
