"""Linking: /start with the token from the website's profile page.

/start without a token, /help and the other sections are in nav.py.
"""

from __future__ import annotations

import html
import logging
import re

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import screens, texts
from bot.keyboards import NavCB
from bot.wallos_client import WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

# The profile page issues 32 hex characters; anything else is not worth a request.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

# The texts of /start for a stranger and of /help live with the other screens.
NOT_LINKED = screens.NOT_LINKED
HELP_TEXT = screens.HELP_TEXT

LINK_RESULTS = {
    "invalid_token": (
        "❌ Ссылка не сработала: она устарела (действует 15 минут) или уже использована.\n\n"
        "Получите новую на сайте: <b>Профиль → Telegram-бот</b> → «Привязать Telegram»."
    ),
    "telegram_taken": (
        "❌ Этот Telegram уже привязан к другому аккаунту ShelfLife.\n\n"
        "Отвяжите его в профиле того аккаунта и откройте ссылку ещё раз."
    ),
}

UNAVAILABLE = texts.UNAVAILABLE


def linked_text(username: str | None) -> str:
    name = html.escape(username or "")
    return (
        f"✅ Аккаунт <b>{name}</b> привязан.\n\n"
        "Напоминания из ShelfLife будут приходить в этот чат, "
        "а на главной — ваши записи, ближайшие даты и расходы."
    )


@router.message(CommandStart(deep_link=True))
async def cmd_start_link(message: Message, command: CommandObject, wallos: WallosClient) -> None:
    if message.from_user is None:
        return

    token = (command.args or "").strip()
    if not _TOKEN_RE.match(token):
        await message.answer(LINK_RESULTS["invalid_token"])
        return

    try:
        result = await wallos.link(token, message.from_user.id, message.from_user.username)
    except WallosError:
        log.exception("Linking failed for telegram_id=%d", message.from_user.id)
        await message.answer(UNAVAILABLE)
        return

    if result.status == "linked":
        home = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Открыть главную", callback_data=NavCB(to="home").pack()
                    )
                ]
            ]
        )
        await message.answer(linked_text(result.username), reply_markup=home)
    else:
        await message.answer(LINK_RESULTS[result.status])
