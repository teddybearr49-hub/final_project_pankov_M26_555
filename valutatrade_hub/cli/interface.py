"""Командный интерфейс ValutaTrade Hub (интерактивный режим)."""

import argparse
import shlex
from collections.abc import Callable

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    ValutaTradeError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.utils import format_amount, format_rate, format_timestamp
from valutatrade_hub.logging_config import (
    console_logging,
    parser_log_hint,
    setup_logging,
)

PROMPT = "> "
WELCOME = "ValutaTrade Hub. Введите 'help' для списка команд, 'exit' — выход."
SEPARATOR = "-" * 33
SOURCES = ("coingecko", "exchangerate")

COMMANDS_HELP = [
    ("register --username <имя> --password <пароль>", "Регистрация"),
    ("login --username <имя> --password <пароль>", "Вход"),
    ("show-portfolio [--base <код>]", "Портфель и его стоимость"),
    ("buy --currency <код> --amount <кол-во>", "Покупка валюты"),
    ("sell --currency <код> --amount <кол-во>", "Продажа валюты"),
    ("get-rate --from <код> --to <код>", "Текущий курс"),
    ("update-rates [--source coingecko|exchangerate]", "Обновить курсы из API"),
    ("show-rates [--currency <код>] [--top N] [--base <код>]", "Курсы из кеша"),
    ("currencies", "Поддерживаемые валюты"),
    ("help", "Список команд"),
    ("exit", "Выход"),
]


class CliArgumentError(Exception):
    """Ошибка разбора аргументов команды."""


class SilentArgumentParser(argparse.ArgumentParser):
    """ArgumentParser, который не завершает процесс при ошибке разбора."""

    def error(self, message: str) -> None:
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
        print(WELCOME)
        while True:
            try:
                line = input(PROMPT).strip()
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
            print(f"Ошибка ввода: {exc}")
            return True
        if args.command == "exit":
            return False
        if args.command is None:
            print("Введите команду. Список команд: help")
            return True
        try:
            self._handlers[args.command](args)
        except CurrencyNotFoundError as exc:
            print(exc)
            print(f"Поддерживаемые валюты: {_supported_codes()}")
        except ApiRequestError as exc:
            print(f"{exc}. Повторите попытку позже или проверьте подключение к сети.")
        except (ValutaTradeError, ValueError, TypeError, OSError) as exc:
            print(exc)
        return True

    def _require_login(self) -> User:
        if self._current_user is None:
            raise ValueError("Сначала выполните login")
        return self._current_user

    # ---------- обработчики команд ----------

    def _register(self, args: argparse.Namespace) -> None:
        user = usecases.register_user(args.username, args.password)
        print(
            f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
            f"Войдите: login --username {user.username} --password ****"
        )

    def _login(self, args: argparse.Namespace) -> None:
        self._current_user = usecases.login_user(args.username, args.password)
        print(f"Вы вошли как '{self._current_user.username}'")

    def _show_portfolio(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        try:
            report = usecases.get_portfolio_report(user.user_id, args.base)
        except CurrencyNotFoundError as exc:
            print(f"Неизвестная базовая валюта '{exc.code}'")
            return
        base = report["base"]
        if not report["rows"]:
            print("Портфель пуст. Купите валюту: buy --currency <код> --amount <N>")
            return
        print(f"Портфель пользователя '{user.username}' (база: {base}):")
        for row in report["rows"]:
            code = row["code"]
            print(
                f"- {code}: {format_amount(row['balance'], code)}  → "
                f"{format_amount(row['value'], base)} {base}"
            )
        print(SEPARATOR)
        print(f"ИТОГО: {format_amount(report['total'], base)} {base}")

    def _buy(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        result = usecases.buy(user.user_id, args.currency, _parse_amount(args.amount))
        code, base = result["currency"], result["base"]
        line = f"Покупка выполнена: {format_amount(result['amount'], code)} {code}"
        if code != base:
            line += f" по курсу {format_rate(result['rate'])} {base}/{code}"
        print(line)
        print("Изменения в портфеле:")
        print(
            f"- {code}: было {format_amount(result['before'], code)} → "
            f"стало {format_amount(result['after'], code)}"
        )
        if code != base:
            print(
                f"Оценочная стоимость покупки: "
                f"{format_amount(result['cost'], base)} {base}"
            )

    def _sell(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        result = usecases.sell(user.user_id, args.currency, _parse_amount(args.amount))
        code, base = result["currency"], result["base"]
        line = f"Продажа выполнена: {format_amount(result['amount'], code)} {code}"
        if code != base:
            line += f" по курсу {format_rate(result['rate'])} {base}/{code}"
        print(line)
        print("Изменения в портфеле:")
        print(
            f"- {code}: было {format_amount(result['before'], code)} → "
            f"стало {format_amount(result['after'], code)}"
        )
        if code != base:
            print(
                f"Оценочная выручка: {format_amount(result['revenue'], base)} {base}"
            )

    def _get_rate(self, args: argparse.Namespace) -> None:
        result = usecases.get_rate(args.from_code, args.to_code)
        src, dst = result["from"], result["to"]
        print(
            f"Курс {src}→{dst}: {format_rate(result['rate'])} "
            f"(обновлено: {format_timestamp(result['updated_at'])})"
        )
        print(f"Обратный курс {dst}→{src}: {format_rate(result['reverse_rate'])}")

    def _update_rates(self, args: argparse.Namespace) -> None:
        with console_logging():
            result = usecases.update_rates(args.source)
        if result.errors:
            hint = parser_log_hint()
            print(f"Update completed with errors. Check {hint} for details.")
        else:
            print(
                f"Update successful. Total rates updated: {result.updated}. "
                f"Last refresh: {result.last_refresh}"
            )

    def _show_rates(self, args: argparse.Namespace) -> None:
        snapshot = usecases.get_rates_snapshot(args.currency, args.top, args.base)
        updated = format_timestamp(snapshot["last_refresh"])
        print(f"Rates from cache (updated at {updated}):")
        for pair, rate in snapshot["rows"]:
            print(f"- {pair}: {format_rate(rate)}")
        if snapshot["stale"]:
            print("Внимание: кеш устарел. Выполните 'update-rates'.")

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
    setup_logging()
    ValutaTradeCLI().run()


if __name__ == "__main__":
    main()
