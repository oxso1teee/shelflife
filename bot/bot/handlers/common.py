"""Generic handlers: /start (with or without a link token) and /help."""

from __future__ import annotations

import html
import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot import texts
from bot.wallos_client import WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

# The profile page issues 32 hex characters; anything else is not worth a request.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

NOT_LINKED = (
    "👋 Привет! Я бот <b>ShelfLife</b>.\n\n"
    "Заранее напоминаю о платежах по подпискам, сроках годности и обслуживании "
    "техники. Под каждым напоминанием — кнопки: продлить, отменить, напомнить позже.\n\n"
    "<b>Чтобы начать, привяжите аккаунт:</b>\n"
    "1. Войдите на сайт ShelfLife.\n"
    "2. Откройте <b>Профиль → Telegram-бот</b>.\n"
    "3. Нажмите «Привязать Telegram» и перейдите по ссылке.\n\n"
    "Подсказка по командам — /help"
)

HELP_TEXT = (
    "<b>ShelfLife в Telegram</b>\n\n"
    "<b>Добавить запись</b> — одной строкой:\n"
    "<code>/add Название ДД.ММ [сумма] [период]</code>\n"
    "• <code>/add Spotify 15.11 500rub</code> — подписка, каждый месяц\n"
    "• <code>/add Netflix 01.12.2026 9.99$ год</code> — подписка, раз в год\n"
    "• <code>/add Витамины 20.11</code> — срок годности\n"
    "• <code>/add Фильтр 10.01 то 3мес</code> — обслуживание каждые 3 месяца\n\n"
    "<b>Напоминания</b> приходят заранее. Кнопки под ними:\n"
    "• «Продлено» — перенести дату на следующий период;\n"
    "• «Отменено» — больше не напоминать об этой записи;\n"
    "• «Напомнить позже» — напомнить завтра.\n\n"
    "Изменить или удалить запись можно на сайте.\n\n"
    "/add — добавить запись\n"
    "/cancel — отменить ввод\n"
    "/start — статус привязки"
)

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
        "Напоминания из ShelfLife будут приходить в этот чат.\n"
        f"Добавить запись: {texts.ADD_EXAMPLE}\n"
        "Все возможности — /help"
    )


def already_linked_text(username: str | None) -> str:
    name = html.escape(username or "")
    return (
        f"👋 Аккаунт <b>{name}</b> привязан — напоминания приходят сюда.\n\n"
        f"Добавить запись: {texts.ADD_EXAMPLE}\n"
        "Все возможности — /help"
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
        await message.answer(linked_text(result.username))
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
        await message.answer(already_linked_text(account.username))
    else:
        await message.answer(NOT_LINKED)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
