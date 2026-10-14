"""The bot's command menu, its menu button and its description in Telegram.

Set at every start (idempotent), so the menu and the "What can this bot do?"
screen of an empty chat always match the code. The menu button is set only
when the Mini App has an https address (SHELFLIFE_MINIAPP_URL): it then opens
the app. Without one the button is left as it is (by default it lists the
commands; whatever was set in BotFather stays). Telegram refusing any of this
is logged and does not stop the bot.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Главная: сводка и ближайшее"),
    BotCommand(command="add", description="Добавить запись"),
    BotCommand(command="list", description="Мои записи"),
    BotCommand(command="soon", description="Ближайшие даты"),
    BotCommand(command="spend", description="Расходы на подписки"),
    BotCommand(command="settings", description="Настройки и привязка"),
    BotCommand(command="help", description="Как пользоваться"),
    BotCommand(command="cancel", description="Прервать добавление"),
]
SHORT_DESCRIPTION = "Подписки, сроки годности и обслуживание — с напоминаниями заранее."
DESCRIPTION = (
    "ShelfLife следит за сроками: платежи по подпискам, сроки годности, обслуживание техники.\n\n"
    "• сводка и ближайшие даты\n"
    "• напоминания с кнопками «Продлено», «Отменено», «Напомнить позже»\n"
    "• расходы на подписки в месяц\n"
    "• быстрое добавление: /add Spotify 15.11 500rub\n\n"
    "Нажмите «Запустить» и привяжите аккаунт сайта ShelfLife."
)
MENU_BUTTON_TEXT = "ShelfLife"


def miniapp_url(value: str | None) -> str | None:
    """The Mini App address if it is a usable https URL (Telegram accepts no other).

    It may not have a #fragment: Telegram passes the launch data in the fragment.
    """
    value = (value or "").strip()
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or "#" in value
        or any(c.isspace() for c in value)
    ):
        return None
    return value


async def publish(bot: Bot, app_url: str | None = None) -> None:
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        await bot.set_my_description(DESCRIPTION)
        if app_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text=MENU_BUTTON_TEXT, web_app=WebAppInfo(url=app_url))
            )
    except Exception:  # the menu is a convenience; the bot works without it
        log.warning("Could not publish the bot's command menu and description", exc_info=True)
