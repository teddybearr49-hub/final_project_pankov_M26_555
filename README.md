# ValutaTrade Hub

Консольная платформа для симуляции торговли фиатными и криптовалютами.
Пользователь регистрируется, управляет виртуальным портфелем, покупает и продаёт
валюту по актуальным курсам. Курсы собирает отдельный **Parser Service**
из CoinGecko (крипта) и ExchangeRate-API (фиат).

## Архитектура

- **Core Service** — модели (`User`, `Wallet`, `Portfolio`), иерархия валют,
  бизнес-логика (`usecases.py`), CLI.
- **Parser Service** — API-клиенты, обновление курсов, хранилище, планировщик.
- **Infra** — синглтоны `SettingsLoader` (конфигурация) и `DatabaseManager`
  (атомарная работа с JSON).

```
finalproject_pankov_M26_555/
├── data/
│   ├── users.json            # пользователи
│   ├── portfolios.json       # портфели и кошельки
│   ├── rates.json            # кеш актуальных курсов (для Core)
│   └── exchange_rates.json   # история измерений (Parser Service)
├── valutatrade_hub/
│   ├── logging_config.py     # формат логов, ротация
│   ├── decorators.py         # @log_action
│   ├── core/                 # currencies, exceptions, models, usecases, utils
│   ├── infra/                # settings (SettingsLoader), database (DatabaseManager)
│   ├── parser_service/       # config, api_clients, updater, storage, scheduler
│   └── cli/interface.py      # команды
├── main.py
├── Makefile
├── pyproject.toml
└── uv.lock
```

## Установка

Требуется Python ≥ 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
git clone <url-репозитория>
cd finalproject_pankov_M26_555
make install          # или: uv sync
```

### API-ключ

Ключ ExchangeRate-API (бесплатно на https://www.exchangerate-api.com/)
хранится в файле `.env` в корне проекта; файл исключён из git:

```bash
cp .env.example .env   # затем впишите свой ключ
```

```
EXCHANGERATE_API_KEY=ваш_ключ
# COINGECKO_API_KEY=   # необязательно: Demo-ключ CoinGecko при ошибке 429
```

## Запуск

```bash
make project          # или: uv run project
```

Сборка и установка пакета:

```bash
make build
make package-install
```

## Команды

| Команда | Назначение |
|---|---|
| `register --username <имя> --password <пароль>` | регистрация |
| `login --username <имя> --password <пароль>` | вход |
| `show-portfolio [--base <код>]` | портфель и стоимость в базовой валюте |
| `buy --currency <код> --amount <кол-во>` | покупка |
| `sell --currency <код> --amount <кол-во>` | продажа |
| `get-rate --from <код> --to <код>` | курс пары |
| `update-rates [--source coingecko\|exchangerate]` | обновить курсы из API |
| `show-rates [--currency <код>] [--top N] [--base <код>]` | курсы из кеша |
| `currencies` | поддерживаемые валюты |
| `help`, `exit` | справка, выход |

Пример сессии:

```
> register --username alice --password 1234
Пользователь 'alice' зарегистрирован (id=1). Войдите: login --username alice --password ****
> login --username alice --password 1234
Вы вошли как 'alice'
> buy --currency USD --amount 10000
> buy --currency BTC --amount 0.05
Покупка выполнена: 0.0500 BTC по курсу 59337.21 USD/BTC
Изменения в портфеле:
- BTC: было 0.0000 → стало 0.0500
Оценочная стоимость покупки: 2,966.86 USD
> show-portfolio
Портфель пользователя 'alice' (база: USD):
- USD: 7,033.14  → 7,033.14 USD
- BTC: 0.0500  → 2,966.86 USD
---------------------------------
ИТОГО: 10,000.00 USD
> get-rate --from USD --to BTC
Курс USD→BTC: 0.00001685 (обновлено: 2025-10-09 10:29:42)
Обратный курс BTC→USD: 59337.21
```

### Логика расчётов

- `buy USD` — пополнение USD-кошелька.
- `buy <валюта>` — стоимость списывается с USD-кошелька; кошелёк валюты
  создаётся автоматически.
- `sell <валюта>` — выручка зачисляется на USD-кошелёк.

### Подтверждение операций

`buy` и `sell` запрашивают подтверждение с оценкой суммы:

```
alice> buy --currency BTC --amount 0.05
Купить 0.0500 BTC ≈ 2,966.86 USD? (yes/no): yes
```

Флаг `--yes` (`-y`) пропускает вопрос. Отменённые операции не выполняются и не логируются.

## Кеш курсов и TTL

- `data/rates.json` — последний срез по каждой паре (`BTC_USD`, `EUR_USD`, …);
  пара означает «1 единица валюты = rate USD». Кросс-курсы считаются через USD.
- TTL задаётся в `pyproject.toml`:

  ```toml
  [tool.valutatrade]
  rates_ttl_seconds = 300
  ```

- Если кеш старше TTL, Core автоматически запускает Parser Service.
  Если API недоступен, выводится сообщение с предложением повторить позже.
  `show-rates` работает только с кешем и предупреждает, если он устарел.

## Parser Service

- Ручное обновление: `update-rates` (все источники) или
  `update-rates --source coingecko`.
- Автоматическое обновление по таймеру:

  ```bash
  make scheduler
  # или: uv run python -m valutatrade_hub.parser_service.scheduler --interval 60
  ```

- Сбой одного источника не останавливает обновление по другому.
- Запись атомарная (временный файл → rename); история пишется в
  `data/exchange_rates.json` с уникальным `id` = `<FROM>_<TO>_<timestamp>`.

## Логи

- `logs/actions.log` — операции `REGISTER`, `LOGIN`, `BUY`, `SELL`
  (декоратор `@log_action`):

  ```
  INFO 2025-10-09T12:05:22 BUY user_id=1 currency='BTC' amount=0.0500 rate=59300.00 base='USD' wallet=0.0000->0.0500 result=OK
  ```

- `logs/parser.log` — работа Parser Service.
- Ротация по размеру (1 МБ, 5 архивов), уровень — `log_level` в `pyproject.toml`.

## Качество кода

```bash
make lint             # ruff check
```

## Демо

[Запись сессии на asciinema](https://asciinema.org/a/BP8rWPlN6VU2nLmv)