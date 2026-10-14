# telegram-reminder-bot

[![CI](https://github.com/AlexDreamien/telegram-reminder-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexDreamien/telegram-reminder-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

A personal Telegram reminder bot. Set one-off or recurring reminders through a
clean inline-button menu, and the bot delivers them on time — even across
restarts. Built with aiogram 3, APScheduler, and SQLite.

> _Screenshot of the conversation goes here once the bot is running._
>
> ![Screenshot placeholder](docs/screenshot.png)

## Features

- **Inline menu UI** — add, list, and delete reminders without typing commands.
- **Flexible time input**:
  - Relative — `in 5 minutes`, `in 2 hours`, `in 1 day`
  - Day-anchored — `today 18:00`, `tomorrow 09:30`
  - Absolute — `2026-05-14 18:30`, `14.05.2026 18:30`
- **Recurrence** — one-off, daily, or weekly.
- **Pagination** for users with many reminders.
- **Survives restarts** — every active reminder is re-scheduled from SQLite on
  startup; missed recurring slots are fast-forwarded so you get one
  notification, not a backlog.
- **Tested core** — 65 unit tests cover the time parser, persistence layer,
  recurrence math, and pagination.

## Installation

```bash
git clone https://github.com/AlexDreamien/telegram-reminder-bot.git
cd telegram-reminder-bot

python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt
cp .env.example .env                # then edit .env and set BOT_TOKEN
python main.py
```

Obtain `BOT_TOKEN` from [@BotFather](https://t.me/BotFather) by sending
`/newbot` and following the prompts.

## Usage

1. Send `/start` to your bot. The main menu appears with three buttons:
   _Add reminder_, _My reminders_, _Help_.
2. **Add reminder** opens a three-step dialog:
   1. Send the reminder text.
   2. Send the time (any format from the Features list).
   3. Pick the recurrence: one-off, daily, or weekly.
3. **My reminders** lists active reminders, paginated. Tap one to view details
   or delete.
4. **Help** (or `/help`) prints the full reference inside Telegram.

## Architecture

```
main.py              Entry point: load .env, wire bot/db/scheduler, start polling.
bot/parsing.py       Time-expression parser (pure logic, fully unit-tested).
bot/db.py            SQLite reminder store: add / list / delete / reschedule.
bot/scheduler.py     APScheduler wrapper: schedules jobs, restores from DB,
                     fast-forwards missed recurrences.
bot/keyboards.py     Inline keyboards and CallbackData factories.
bot/states.py        FSM states for the add-reminder dialog.
bot/handlers/        Routers split by responsibility:
  common.py            /start, /help, menu navigation
  add.py               Add-reminder FSM dialog
  manage.py            List, view, delete reminders
```

The core logic — parsing, persistence, scheduling math, pagination — is kept
free of aiogram so it can be tested in isolation. Telegram-facing code is a
thin layer on top.

## Tech stack

- Python 3.11+
- [aiogram 3](https://docs.aiogram.dev/) — Telegram bot framework
- [APScheduler 3](https://apscheduler.readthedocs.io/) — async job scheduling
- SQLite (stdlib `sqlite3`) — persistent storage
- `python-dotenv` — configuration
- pytest, ruff, black — quality

## Testing & CI

```bash
pip install -r requirements-dev.txt
pytest                  # 65 tests
ruff check .            # lint
black --check .         # formatting
```

GitHub Actions runs the same three checks on every push and pull request,
across Python 3.11, 3.12, and 3.13 — see [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Configuration

Environment variables (see `.env.example`):

| Variable    | Description                                  | Default         |
| ----------- | -------------------------------------------- | --------------- |
| `BOT_TOKEN` | Telegram bot token from @BotFather (required) | _empty_         |
| `DB_PATH`   | Path to the SQLite database file              | `reminders.db`  |
| `TZ`        | IANA timezone (reserved for future use)       | `UTC`           |

Times are interpreted and stored in UTC; the bot currently displays times as
UTC. Multi-user timezone support is intentionally out of scope.

## Out of scope

By design, this bot does not implement payments, multilingual replies, an
admin panel, inline mode, or third-party integrations. The codebase is meant
to be small and easy to read.

## License

[MIT](LICENSE)
