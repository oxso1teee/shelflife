# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Personal Telegram reminder bot: one-off / recurring reminders via inline menu, survives restarts. aiogram 3 + APScheduler 3 + SQLite. See `README.md` for usage.

## Build & test

```bash
pip install -r requirements.txt
cp .env.example .env            # set BOT_TOKEN (from @BotFather)
python main.py
pip install -r requirements-dev.txt
pytest                          # 65+ tests
pytest tests/test_parsing.py::test_name   # single test
ruff check . && black --check .
```

## Architecture invariant

Core logic — `bot/parsing.py` (time parser), `bot/db.py` (SQLite store), `bot/scheduler.py` (scheduling/recurrence math), pagination in `bot/keyboards.py` — is **free of aiogram** and unit-tested in isolation. The `bot/handlers/` routers are a thin Telegram-facing layer. Keep new logic out of the handlers.

## Gotchas — do not regress

- **`_fire` re-reads the reminder from the DB *after* the delivery `await`.** A reminder can be deleted/deactivated during delivery; rescheduling blindly would resurrect it. After delivery, re-fetch and bail if it is gone or inactive.
- **One-off reminders are deactivated only after a *successful* delivery.** A failed send must not silently drop the reminder from the DB.
- **Callback handlers guard `query.from_user is None`** (aiogram types it as `User | None`) before using `.id`.
- **All SQL is parameterized and filtered by `user_id`** (`db.delete` / `db.get` / etc.) — no string interpolation, no IDOR. Keep it that way.
- **Times are stored and interpreted in UTC.** `next_recurrence` uses a strict `<=` loop so fast-forward lands on a slot strictly after `after` (no infinite loop on an exact match).

## Known limitation (not a bug)

`bot/db.py` opens `sqlite3` connections synchronously on the asyncio event loop (default `check_same_thread`). This works because the event loop is single-threaded, but DB I/O blocks the loop. A proper async fix means moving to `aiosqlite` / `asyncio.to_thread` — a deliberate, separate refactor, not a quick patch.

## Out of scope (deliberate)

No payments, multilingual replies, admin panel, inline mode, or per-user timezones.
