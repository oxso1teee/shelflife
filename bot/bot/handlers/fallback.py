"""Everything no other handler took: unknown commands, plain text, old buttons.

Registered last, so /start, /help, /add (and the line it waits for) and the
reminder buttons are matched first. Like every message handler it only sees
private chats (bot/handlers/__init__.py); in a group the bot stays quiet.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import texts
from bot.handlers.callbacks import UNKNOWN_BUTTON

router = Router()

UNKNOWN_COMMAND = (
    "Такой команды нет.\n\n"
    "/add — добавить запись\n"
    "/help — подсказка\n"
    "/start — статус привязки"
)
HINT = (
    "Чтобы добавить запись, отправьте команду, например:\n"
    f"{texts.ADD_EXAMPLE}\n\n"
    "Подсказка — /help"
)


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer(UNKNOWN_COMMAND)


@router.message()
async def anything_else(message: Message) -> None:
    await message.answer(HINT)


@router.callback_query()
async def unknown_button(query: CallbackQuery) -> None:
    # A button of an older message or bot version: answer so the client stops waiting.
    await query.answer(UNKNOWN_BUTTON)
