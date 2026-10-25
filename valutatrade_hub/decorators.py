"""Декораторы: @log_action (логирование) и @confirm_action (подтверждение yes/no)."""

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any

from valutatrade_hub.core.utils import format_rate

logger = logging.getLogger("valutatrade.actions")

Func = Callable[..., Any]
YES_ANSWERS = frozenset({"yes", "y", "да", "д"})
NO_ANSWERS = frozenset({"no", "n", "нет", "н"})


def _fmt_number(value: Any, digits: int) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:.{digits}f}"
    return repr(value)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _build_message(
    action: str,
    params: dict[str, Any],
    result: Any,
    verbose: bool,
    error: BaseException | None,
    elapsed_ms: int,
) -> str:
    parts = [action]
    if params.get("username") is not None:
        parts.append(f"user='{params['username']}'")
    elif "user_id" in params:
        parts.append(f"user_id={params['user_id']}")

    info = result if isinstance(result, dict) else {}
    currency = info.get("currency") or params.get("currency_code")
    if currency is not None:
        parts.append(f"currency='{str(currency).upper()}'")
    if "amount" in params:
        parts.append(f"amount={_fmt_number(params['amount'], 4)}")
    if "rate" in info:
        parts.append(f"rate={format_rate(info['rate'])}")
    if "base" in info:
        parts.append(f"base='{info['base']}'")
    if verbose and "before" in info:
        before = _fmt_number(info["before"], 4)
        after = _fmt_number(info["after"], 4)
        parts.append(f"wallet={before}->{after}")

    if error is None:
        parts.append("result=OK")
    else:
        parts.append(
            f"result=ERROR error_type={type(error).__name__} "
            f"error_message='{error}'"
        )
    parts.append(f"duration_ms={elapsed_ms}")
    return " ".join(parts)


def log_action(action: str, *, verbose: bool = False) -> Callable[[Func], Func]:
    """Логирует вызов операции на уровне INFO вместе со временем выполнения.

    Исключения не глотает: фиксирует в логе и пробрасывает дальше.
    verbose=True добавляет состояние кошелька «было→стало».
    """

    def decorator(func: Func) -> Func:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                params = dict(signature.bind_partial(*args, **kwargs).arguments)
            except TypeError:
                params = {}
            started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                elapsed = _elapsed_ms(started)
                message = _build_message(action, params, None, verbose, exc, elapsed)
                logger.info(message)
                raise
            elapsed = _elapsed_ms(started)
            message = _build_message(action, params, result, verbose, None, elapsed)
            logger.info(message)
            return result

        return wrapper

    return decorator


def confirm_action(question: Func) -> Callable[[Func], Func]:
    """Запрашивает подтверждение (yes/no) перед выполнением операции.

    question(*args, **kwargs) строит текст вопроса из аргументов операции.
    При ответе no операция не выполняется и возвращается None;
    на другой ввод вопрос повторяется. Если вопрос построить нельзя
    (например, неверная валюта), операция вызывается сразу,
    чтобы пользователь увидел её штатную ошибку.
    """

    def decorator(func: Func) -> Func:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                text = question(*args, **kwargs)
            except Exception:
                return func(*args, **kwargs)
            while True:
                try:
                    answer = input(f"{text} (yes/no): ").strip().lower()
                except EOFError:
                    return None
                if answer in YES_ANSWERS:
                    return func(*args, **kwargs)
                if answer in NO_ANSWERS:
                    return None
                print("Введите yes или no.")

        return wrapper

    return decorator
