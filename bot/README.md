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
| `/start` (or `/menu`) | the home screen: active records, what is overdue or due this week, the nearest date, the monthly spending, and buttons to every section; for an unlinked account, how to link it |
| `/list` | records, six a page, with filters (all, subscriptions, shelf life, maintenance, cancelled); a record opens as a card |
| record card | renew for one period, «напомнить завтра» (within a week of the date), cancel, bring a cancelled record back, delete (asks first); applied once, only for the record's owner and only while it still has the date the card showed |
| `/soon` | the next 30 days grouped: overdue, today, tomorrow, this week, this month |
| `/spend` | monthly spending on subscriptions per currency, a total only when the site has exchange rates, the most expensive, by category, payments due in 30 days |
| `/settings` | the default reminder (0–7 days, the website's notification setting), the site, unlinking (asks first) |
| `/add` | step by step with buttons: name, kind, category, date, amount, period, confirm; «‹ Назад» and «Отмена» on every step |
| `/add Spotify 15.11 500rub` | creates the record at once, as before; `/add Spotify` starts the steps with the name filled in |
| buttons under a reminder: «Продлено на …», «Отменено», «Напомнить позже» | as on the card; the reminder then shows the outcome instead of the buttons |
| `/help` | usage, with examples; `/cancel` leaves `/add` |
| any other command, plain text, an outdated button | a short hint |

The sections live in one message that the buttons edit, so the chat does not
fill up with menus. Every screen is drawn from a fresh overview of the account
that the web app computes (`api/internal/telegram/overview.php`,
`includes/shelflife/overview.php`) — the same numbers as the website and the
Mini App; the bot does no date or money arithmetic of its own.

Messages are answered in private chats only: in a group the bot stays quiet,
so it never shows a linked account or its records to other members.

At start the bot publishes its command menu and description (`bot/menu.py`).
With `SHELFLIFE_MINIAPP_URL` (an https address) it also sets the chat's menu
button to the Mini App and shows «Открыть приложение» / «Изменить в
приложении» buttons; without it there are no app buttons and the menu button is
left as it is. Every message follows one style (`bot/texts.py`): dates
DD.MM.YYYY, amounts like "1 500 ₽", and the same record card as the reminders
the web app sends.

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
| `SHELFLIFE_MINIAPP_URL` | optional: the Mini App's https address, e.g. `https://shelflife.example.com/tma/index.php` |
| `TZ` | time zone for "today" in `/add`, e.g. `Europe/Moscow` |

In the ShelfLife deployment these come from the top-level `.env` through `compose.yaml`.

## Layout

```
main.py                    entry point: config, client, routers, polling
bot/wallos_client.py       client of the web app's internal API (replaces the original bot's SQLite store)
bot/overview.py            the account overview the web app computes, as the bot reads it
bot/screens.py             every screen (home, records, card, soon, spending, settings, help): text + buttons, pure
bot/parsing.py             /add parser (adapted from the original time parser) and its date/amount readers
bot/keyboards.py           callback data: reminder buttons (shared with the web app), sections, cards, steps
bot/states.py              FSM states of the step-by-step /add
bot/handlers/common.py     /start <token>: linking
bot/handlers/nav.py        sections, cards and their actions, settings (/start, /list, /soon, /spend, /settings, /help)
bot/handlers/add.py        /add with a line, /cancel
bot/handlers/wizard.py     the step-by-step /add
bot/handlers/callbacks.py  reminder buttons
bot/handlers/fallback.py   unknown commands, plain text, outdated buttons (registered last)
bot/texts.py               the writing style: dates, amounts, periods, the record card
bot/menu.py                command menu, description and menu button, set at start
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check . && black --check .
```

`tests/conftest.py` feeds real Telegram updates through the real Dispatcher
(routing, filters, FSM) with a stand-in for the web app that answers with
`tests/fixtures/overview.json` — an overview written by the web app itself
(`web/tests/fixtures/make_overview_fixture.php`; regenerate it after changing
the overview).
