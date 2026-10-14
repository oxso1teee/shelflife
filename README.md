# ShelfLife

Трекер подписок, сроков годности и обслуживания техники: сайт и Telegram-бот с напоминаниями.

ShelfLife собран из готовых проектов:

| Каталог | Основа | Лицензия | Роль |
|---|---|---|---|
| `web/` | [Wallos](https://github.com/ellite/Wallos) 5.8.3 (`cc9677a`) | GPL-3.0 (`web/LICENSE.md`, `web/NOTICE.md`) | сайт, база SQLite, вся логика записей, рассылка напоминаний, внутренний API для бота |
| `bot/` | [telegram-reminder-bot](https://github.com/AlexDreamien/telegram-reminder-bot) (`26f29cb`) | MIT (`bot/LICENSE`) | Telegram-адаптер: главная, записи и их карточки, добавление по шагам и одной строкой, «Скоро», расходы, настройки, кнопки под напоминаниями |
| — | [Vorrat](https://github.com/MarcelMuechler/Vorrat) | MIT | правила статуса срока годности и их тест-кейсы перенесены в `web/includes/shelflife/status.php` |

Всё лежит в одном репозитории. История Wallos и telegram-reminder-bot сохранена: она влита в каталоги `web/` и `bot/` (как при `git subtree`), поверх неё — изменения ShelfLife. Поэтому исправления из исходных проектов переносятся слиянием (см. OPERATIONS.md, раздел 8).

```bash
git clone https://github.com/<владелец>/shelflife.git && cd shelflife
cp .env.example .env    # секреты заполняются только локально, .env в Git не попадает
```

## Как устроено

```
браузер ─HTTPS─► caddy ─► web (Wallos: nginx + PHP + cron) ──► SQLite .data/db/wallos.db
Mini App ─HTTPS─┘   │  includes/shelflife/*  — общая логика записей, дат, сводки, привязки, рассылки
 (web/tma,          │  /api/tma/app.php — Mini App, вход по подписи Telegram (initData)
  внутри Telegram)  │  cron каждые 5 мин: напоминания с кнопками ─► Telegram
                    ▲
      /api/internal/telegram/* (сервисный ключ, только внутренняя сеть)
                    │
 bot (aiogram) ◄── Telegram: команды, кнопки разделов и записей, /add, кнопки напоминаний
```

- Единственный источник данных — база Wallos. Бот и Mini App не хранят данных и не повторяют логику: каждое действие идёт в API сайта, а тот вызывает те же функции, что и сайт. Сводку, статусы, «Скоро» и расходы считает `includes/shelflife/overview.php` — одинаково для бота и Mini App.
- Mini App узнаёт пользователя только по `initData`, подписанным Telegram; сервер проверяет подпись токеном бота. Подробнее — в OPERATIONS.md (разделы 11 и 13) и в [branding/telegram/README.md](branding/telegram/README.md): аватар, тексты BotFather и подключение Mini App.
- Подробности по установке, резервному копированию и обновлению — в [OPERATIONS.md](OPERATIONS.md).

## Разработка

```bash
cp .env.example .env              # для локальной работы достаточно SHELFLIFE_SERVICE_KEY
docker compose up -d --build web  # сайт: http://127.0.0.1:8282
docker compose up -d bot          # бот (нужен TELEGRAM_BOT_TOKEN)
docker compose --profile proxy up -d   # плюс HTTPS через Caddy (нужен SHELFLIFE_DOMAIN)
```

Данные лежат в `.data/` (файлы принадлежат пользователю контейнера, uid 82).

Тесты:

```bash
# PHP (Wallos + ShelfLife): рабочая копия монтируется только для чтения
docker run --rm -v "$PWD/web":/var/www/html:ro -w /var/www/html php:8.3-cli php tests/run.php

# бот
cd bot && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/black --check .
```

Приёмочный прогон всего ТЗ (сайт по HTTP, настоящие обработчики и клиент бота; подменён только Telegram):

```bash
# на чистой базе: стек запущен с SHELFLIFE_SERVICE_KEY, TELEGRAM_BOT_USERNAME и любым TELEGRAM_BOT_TOKEN
bot/.venv/bin/python scripts/acceptance.py

# затем Mini App в Chrome (Playwright): экраны, действия, обе темы, 320 px, проверка базы
python3 scripts/tma_ui_check.py --out /tmp/tma-shots
```

Оба скрипта меняют базу стека, на котором запущены, — гоняйте их на отдельном стенде (OPERATIONS.md, раздел 9), не на рабочей базе.

Резервное копирование и восстановление: `scripts/backup.sh`, `scripts/restore.sh` (см. OPERATIONS.md).
