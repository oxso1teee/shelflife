# ShelfLife Telegram bot

The Telegram side of ShelfLife, built on
[telegram-reminder-bot](https://github.com/AlexDreamien/telegram-reminder-bot) (MIT).
It is a thin adapter: accounts, records, dates and reminders live in the
ShelfLife web app (a Wallos fork, `../web`), and the bot reaches them only
through that app's internal API.

## What it does

| In Telegram | What happens |
|---|---|
| `/start <token>` (the link from the profile page) | links the Telegram account to the website account; the token works once, for 15 minutes |
| `/start` | says whether the account is linked and how to link it |
| `/add Spotify 15.11 500rub` | creates a record; `/add` alone asks for the line; `/cancel` leaves |
| buttons under a reminder: «Продлено на …», «Отменено», «Напомнить позже» | renews the record to its next date, makes it inactive, or moves the reminder to tomorrow — once, and only for the record's owner; the reminder then shows the outcome instead of the buttons |
| `/help` | usage, with examples |
| any other command, plain text, an outdated button | a short hint (private chats only) |

At start the bot publishes its command menu and description (`bot/menu.py`).
Every message follows one style (`bot/texts.py`): dates DD.MM.YYYY, amounts
like "1 500 ₽", and the same record card as the reminders the web app sends.

Reminders themselves are sent by the web app's cron job; the bot handles the
button presses that come back.

`/add` grammar: `<name> <date> [<amount>[<currency>]] [words]` — date `DD.MM`,
`DD.MM.YY`, `DD.MM.YYYY` or `YYYY-MM-DD` (without a year: the next such date);
amount like `500rub`, `500 руб`, `9.99$`, `$9.99`, `10€`; words `год`, `ежемесячно`,
`неделя`, `то` (maintenance), `срок` (shelf life), `3мес` (every 3 months). With
an amount the record is a subscription, without one a shelf-life date.

## Configuration

| Variable | |
|---|---|
| `BOT_TOKEN` | token from @BotFather |
| `WALLOS_INTERNAL_URL` | base URL of the internal API, e.g. `http://web/api/internal/telegram` |
| `SHELFLIFE_SERVICE_KEY` | shared secret with the web app, at least 32 characters |
| `TZ` | time zone for "today" in `/add`, e.g. `Europe/Moscow` |

In the ShelfLife deployment these come from the top-level `.env` through `compose.yaml`.

## Layout

```
main.py                    entry point: config, client, routers, polling
bot/wallos_client.py       client of the web app's internal API (replaces the original bot's SQLite store)
bot/parsing.py             /add parser (adapted from the original time parser)
bot/keyboards.py           reminder button format shared with the web app; pagination
bot/states.py              FSM state for /add without arguments
bot/handlers/common.py     /start, /help
bot/handlers/add.py        /add, /cancel
bot/handlers/callbacks.py  reminder buttons
bot/handlers/fallback.py   unknown commands, plain text, outdated buttons (registered last)
bot/texts.py               the writing style: dates, amounts, periods, the record card
bot/menu.py                command menu and description, set at start
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check . && black --check .
```
