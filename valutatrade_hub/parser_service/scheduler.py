"""Планировщик периодического обновления курсов.

Запуск: uv run python -m valutatrade_hub.parser_service.scheduler --interval 60
"""

import argparse
import logging
import time

from valutatrade_hub.logging_config import (
    PARSER_LOGGER_NAME,
    console_logging,
    setup_logging,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater

logger = logging.getLogger(PARSER_LOGGER_NAME)
TICK_SECONDS = 1


class RatesScheduler:
    """Вызывает RatesUpdater.run_update() каждые interval_seconds секунд."""

    def __init__(
        self,
        updater: RatesUpdater | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._updater = updater or RatesUpdater()
        self._interval = interval_seconds or ParserConfig().UPDATE_INTERVAL_SECONDS
        self._running = False

    def run_forever(self) -> None:
        """Циклически обновляет курсы до остановки."""
        self._running = True
        logger.info("Scheduler started, interval %d s", self._interval)
        while self._running:
            try:
                self._updater.run_update()
            except Exception:
                logger.exception("Scheduled update failed")
            self._sleep()

    def _sleep(self) -> None:
        # Короткие тики, чтобы Ctrl+C срабатывал сразу (в т.ч. на Windows)
        waited = 0
        while self._running and waited < self._interval:
            time.sleep(TICK_SECONDS)
            waited += TICK_SECONDS

    def stop(self) -> None:
        """Останавливает планировщик."""
        self._running = False


def main() -> None:
    """Точка входа планировщика."""
    parser = argparse.ArgumentParser(description="Периодическое обновление курсов")
    parser.add_argument("--interval", type=int, help="интервал, секунды")
    args = parser.parse_args()

    setup_logging()
    scheduler = RatesScheduler(interval_seconds=args.interval)
    with console_logging():
        try:
            scheduler.run_forever()
        except KeyboardInterrupt:
            scheduler.stop()
            logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
