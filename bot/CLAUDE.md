# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ShelfLife Telegram bot, built on telegram-reminder-bot (MIT). It is a thin Telegram adapter for the ShelfLife web app (a Wallos fork, `../web`): it links accounts, takes `/add` and button presses, and calls the Wallos internal API. aiogram 3.

## Build & test

```bash
pip install -r requirements-dev.txt
cp .env.example .env            # BOT_TOKEN, WALLOS_INTERNAL_URL, SHELFLIFE_SERVICE_KEY
python main.py
pytest
ruff check . && black --check .
```

## Architecture invariant

- **The bot keeps no data.** Accounts, records, dates and notifications live in the Wallos SQLite database. Every read or change goes through `bot/wallos_client.py` → `web/api/internal/telegram/*.php`, which use the same PHP functions as the web pages (`web/includes/shelflife/`). Do not add a local store or duplicate date/business rules here.
- Requests carry `X-ShelfLife-Service-Key`. The user is identified by `message.from_user.id` / `query.from_user.id` from the update, never by anything the user typed.
- `bot/parsing.py` is pure and unit-tested in isolation; `bot/handlers/` is the thin Telegram-facing layer.
- **Reminder buttons are written by Wallos** (`web/includes/shelflife/notifications.php`) as `a:<record id>:<due YYYYMMDD>:<r|c|s>` and read here by `ItemActionCB` (`bot/keyboards.py`). Change both sides together; `tests/test_callbacks.py` pins the format.

## Gotchas — do not regress

- **Callback handlers guard `query.from_user is None`** (aiogram types it as `User | None`) before using `.id`; message handlers guard `message.from_user`.
- **Escape everything that reaches an HTML message** (`html.escape`): the default parse mode is HTML, and an unescaped `<` makes Telegram reject the whole message.
- **Never log the service key or the bot token.**
