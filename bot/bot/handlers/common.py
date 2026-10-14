"""Generic handlers: /start (with or without a link token) and /help."""

from __future__ import annotations

import html
import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.wallos_client import WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

# The profile page issues 32 hex characters; anything else is not worth a request.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

NOT_LINKED = (
    "Привет! Я бот ShelfLife: напоминаю о платежах по подпискам, сроках годности "
    "и обслуживании техники.\n\n"
    "Чтобы получать уведомления, привяжите аккаунт: на сайте откройте "
    "<b>Профиль → Telegram-бот</b>, нажмите «Привязать Telegram» и перейдите по ссылке."
)

HELP_TEXT = (
    "<b>Что умеет бот</b>\n\n"
    "• присылает напоминания о предстоящих платежах, сроках годности и обслуживании;\n"
    "• под каждым напоминанием — кнопки «Продлено», «Отменено», «Напомнить позже»;\n"
    "• /add — быстро добавить запись: <code>/add Spotify 15.11 500rub</code>.\n\n"
    "<b>Привязка</b>: на сайте <b>Профиль → Telegram-бот</b> → «Привязать Telegram».\n\n"
    "Команды: /add, /cancel, /start, /help"
)

LINK_RESULTS = {
    "invalid_token": (
        "Ссылка недействительна: её срок истёк или она уже использована. "
        "Получите новую в профиле на сайте."
    ),
    "telegram_taken": (
        "Этот Telegram уже привязан к другому аккаунту ShelfLife. "
        "Отвяжите его там и попробуйте ещё раз."
    ),
}

UNAVAILABLE = "Сервис временно недоступен. Попробуйте позже."


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
        name = html.escape(result.username or "")
        await message.answer(
            f"Готово! Аккаунт <b>{name}</b> привязан. "
            "Сюда будут приходить напоминания из ShelfLife.\n\n/help — что умеет бот."
        )
    else:
        await message.answer(LINK_RESULTS[result.status])


@router.message(CommandStart())
async def cmd_start(message: Message, wallos: WallosClient) -> None:
    if message.from_user is None:
        return

    try:
        account = await wallos.account(message.from_user.id)
    except WallosError:
        log.exception("Account lookup failed for telegram_id=%d", message.from_user.id)
        await message.answer(UNAVAILABLE)
        return

    if account.linked:
        name = html.escape(account.username or "")
        await message.answer(
            f"Аккаунт <b>{name}</b> уже привязан. Напоминания будут приходить сюда.\n\n/help — что умеет бот."
        )
    else:
        await message.answer(NOT_LINKED)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
