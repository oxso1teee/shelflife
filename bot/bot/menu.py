"""The bot's command menu and its description in Telegram.

Set at every start (idempotent), so the menu and the "What can this bot do?"
screen of an empty chat always match the code. Telegram refusing them is
logged and does not stop the bot.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="add", description="Добавить запись"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="start", description="Статус привязки аккаунта"),
    BotCommand(command="cancel", description="Отменить ввод"),
]
SHORT_DESCRIPTION = "Напоминания о подписках, сроках годности и обслуживании техники."
DESCRIPTION = (
    "ShelfLife заранее напоминает о платежах по подпискам, сроках годности "
    "и обслуживании техники.\n\n"
    "Нажмите «Запустить», чтобы привязать аккаунт сайта и получать напоминания здесь."
)


async def publish(bot: Bot) -> None:
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        await bot.set_my_description(DESCRIPTION)
    except Exception:  # the menu is a convenience; the bot works without it
        log.warning("Could not publish the bot's command menu and description", exc_info=True)
