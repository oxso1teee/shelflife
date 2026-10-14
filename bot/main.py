"""Entry point: load config, wire components, start polling."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.db import Reminder, ReminderDB
from bot.handlers import setup as setup_handlers
from bot.scheduler import ReminderScheduler

log = logging.getLogger("bot")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    configure_logging()
    load_dotenv()

    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    db_path = Path(os.environ.get("DB_PATH", "reminders.db"))
    db = ReminderDB(db_path)

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    async def deliver(reminder: Reminder) -> None:
        prefix = "Reminder" if reminder.recurrence is None else f"Reminder ({reminder.recurrence})"
        await bot.send_message(reminder.chat_id, f"<b>{prefix}:</b> {reminder.text}")

    scheduler = ReminderScheduler(db, deliver)
    setup_handlers(dp, db, scheduler)
    scheduler.start()

    restored = scheduler.restore()
    log.info("Restored %d active reminders from %s", restored, db_path)

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
