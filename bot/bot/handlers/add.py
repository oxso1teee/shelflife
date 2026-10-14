"""/add: create a record from one line (adapted from telegram-reminder-bot's add dialog).

``/add Spotify 15.11 500rub`` creates the record at once. ``/add`` alone asks for
the line in the next message, the way the original bot's dialog asked for each
part. The record is created by Wallos through the internal API with the same
validation as the website; a repeated Telegram update creates nothing twice.
"""

from __future__ import annotations

import html
import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Update

from bot import texts
from bot.parsing import ParseError, QuickAdd, parse_quick_add
from bot.states import AddItem
from bot.wallos_client import AddResult, Record, WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

USAGE = (
    "Формат: <code>/add Название ДД.ММ [сумма]</code>\n"
    f"Например: {texts.ADD_EXAMPLE}\n"
    "Все варианты — /help"
)
ASK_LINE = (
    "Что добавить? Напишите одной строкой название, дату и для подписки — сумму.\n"
    "Например: <code>Spotify 15.11 500rub</code>\n\n"
    "/cancel — отменить"
)
UNAVAILABLE = texts.UNAVAILABLE
NOT_LINKED = texts.NOT_LINKED

# What the web app can refuse in /add, by field (api/internal/telegram/item_add.php).
REFUSED_FIELDS = {
    "price": f"⚠️ Для подписки нужна сумма, например: {texts.ADD_EXAMPLE}",
    "next_payment": "⚠️ Дата не подходит. Укажите её как ДД.ММ или ДД.ММ.ГГГГ.",
    "name": "⚠️ Название не подходит: оно пустое или слишком длинное.",
}
REFUSED = "⚠️ Не удалось добавить запись. Проверьте строку или добавьте запись на сайте."


def today_in_app_timezone() -> date:
    return texts.today()


def created_text(record: Record, today: date) -> str:
    return (
        "✅ Запись добавлена\n\n"
        f"{texts.record_card(record, today)}\n\n"
        "Изменить или удалить её можно на сайте."
    )


def refused_text(result: AddResult, parsed: QuickAdd) -> str:
    if result.status == "not_linked":
        return NOT_LINKED
    if result.field == "currency":
        return (
            f"⚠️ Валюты {html.escape(parsed.currency or '')} нет в вашем аккаунте. "
            "Добавьте её на сайте в настройках или укажите другую."
        )
    return REFUSED_FIELDS.get(result.field or "", REFUSED)


async def add_from_line(
    message: Message, line: str, wallos: WallosClient, event_update: Update
) -> None:
    if message.from_user is None:
        return

    today = today_in_app_timezone()
    try:
        parsed = parse_quick_add(line, today)
    except ParseError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}\n\n{USAGE}")
        return

    try:
        result = await wallos.add_record(
            telegram_id=message.from_user.id,
            update_id=event_update.update_id,
            kind=parsed.kind,
            name=parsed.name,
            next_payment=parsed.due.isoformat(),
            price=parsed.price,
            currency=parsed.currency,
            cycle=parsed.cycle,
            frequency=parsed.frequency,
        )
    except WallosError:
        log.exception("/add failed for telegram_id=%d", message.from_user.id)
        await message.answer(UNAVAILABLE)
        return

    if result.status == "created" and result.record is not None:
        await message.answer(created_text(result.record, today))
    else:
        await message.answer(refused_text(result, parsed))


@router.message(Command("add"))
async def cmd_add(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    wallos: WallosClient,
    event_update: Update,
) -> None:
    if not (command.args or "").strip():
        await state.set_state(AddItem.waiting_for_line)
        await message.answer(ASK_LINE)
        return

    await state.clear()
    await add_from_line(message, command.args, wallos, event_update)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять. Добавить запись — /add")
        return
    await state.clear()
    await message.answer("Ввод отменён.")


@router.message(AddItem.waiting_for_line)
async def receive_line(
    message: Message, state: FSMContext, wallos: WallosClient, event_update: Update
) -> None:
    await state.clear()
    await add_from_line(message, (message.text or "").strip(), wallos, event_update)
