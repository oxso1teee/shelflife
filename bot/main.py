"""Entry point: load config, wire components, start polling."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.handlers import setup as setup_handlers
from bot.wallos_client import WallosClient

log = logging.getLogger("bot")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


async def main() -> None:
    configure_logging()
    load_dotenv()

    token = required_env("BOT_TOKEN")
    wallos = WallosClient(
        required_env("WALLOS_INTERNAL_URL"),
        required_env("SHELFLIFE_SERVICE_KEY"),
    )

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    setup_handlers(dp, wallos)

    try:
        await dp.start_polling(bot)
    finally:
        await wallos.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
