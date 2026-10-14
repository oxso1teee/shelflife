# ShelfLife

Трекер подписок, сроков годности и обслуживания техники: сайт и Telegram-бот с напоминаниями.

ShelfLife собран из готовых проектов:

| Каталог | Основа | Лицензия | Роль |
|---|---|---|---|
| `web/` | [Wallos](https://github.com/ellite/Wallos) 5.8.3 (`cc9677a`) | GPL-3.0 (`web/LICENSE.md`, `web/NOTICE.md`) | сайт, база SQLite, вся логика записей, рассылка напоминаний, внутренний API для бота |
| `bot/` | [telegram-reminder-bot](https://github.com/AlexDreamien/telegram-reminder-bot) (`26f29cb`) | MIT (`bot/LICENSE`) | Telegram-адаптер: `/start <token>`, `/add`, кнопки под напоминаниями |
| — | [Vorrat](https://github.com/MarcelMuechler/Vorrat) | MIT | правила статуса срока годности и их тест-кейсы перенесены в `web/includes/shelflife/status.php` |

Всё лежит в одном репозитории. История Wallos и telegram-reminder-bot сохранена: она влита в каталоги `web/` и `bot/` (как при `git subtree`), поверх неё — изменения ShelfLife. Поэтому исправления из исходных проектов переносятся слиянием (см. OPERATIONS.md, раздел 8).

```bash
git clone https://github.com/<владелец>/shelflife.git && cd shelflife
cp .env.example .env    # секреты заполняются только локально, .env в Git не попадает
```

## Как устроено

```
браузер ─HTTPS─► caddy ─► web (Wallos: nginx + PHP + cron) ──► SQLite .data/db/wallos.db
                               │  includes/shelflife/*  — общая логика записей, дат, привязки, рассылки
                               │  cron каждые 5 мин: напоминания с кнопками ─► Telegram
                               ▲
                 /api/internal/telegram/* (сервисный ключ, только внутренняя сеть)
                               │
            bot (aiogram) ◄── Telegram: /start <token>, /add, нажатия кнопок
```

- Единственный источник данных — база Wallos. Бот не хранит данных и не повторяет логику: каждое действие он передаёт во внутренний API, а тот вызывает те же функции, что и сайт.
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
```

Резервное копирование и восстановление: `scripts/backup.sh`, `scripts/restore.sh` (см. OPERATIONS.md).
