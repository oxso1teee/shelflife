"""/add: create a record from one line (adapted from telegram-reminder-bot's add dialog).

``/add Spotify 15.11 500rub`` creates the record at once. ``/add`` alone asks for
the line in the next message, the way the original bot's dialog asked for each
part. The record is created by Wallos through the internal API with the same
validation as the website; a repeated Telegram update creates nothing twice.
"""

from __future__ import annotations

import html
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Update

from bot.parsing import ParseError, QuickAdd, parse_quick_add
from bot.states import AddItem
from bot.wallos_client import AddResult, Record, WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

USAGE = (
    "Формат: <code>/add Название ДД.ММ [сумма]</code>\n"
    "Примеры:\n"
    "<code>/add Spotify 15.11 500rub</code> — подписка, каждый месяц\n"
    "<code>/add Netflix 01.12.2026 9.99$ год</code> — подписка, раз в год\n"
    "<code>/add Витамины 20.11</code> — срок годности\n"
    "<code>/add Фильтр для воды 10.01 то 3мес</code> — обслуживание каждые 3 месяца"
)
ASK_LINE = "Что добавить? Напишите одной строкой.\n\n" + USAGE + "\n\n/cancel — отмена."
UNAVAILABLE = "Сервис временно недоступен. Попробуйте позже."
NOT_LINKED = (
    "Сначала привяжите аккаунт: на сайте <b>Профиль → Telegram-бот</b> → «Привязать Telegram»."
)

KIND_NAMES = {"subscription": "Подписка", "expiry": "Срок годности", "maintenance": "Обслуживание"}
CURRENCY_SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸"}
PERIOD_ONE = {1: "каждый день", 2: "каждую неделю", 3: "каждый месяц", 4: "каждый год"}
PERIOD_UNIT = {1: "дн.", 2: "нед.", 3: "мес.", 4: "г."}


def today_in_app_timezone() -> date:
    try:
        zone = ZoneInfo(os.environ.get("TZ") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def ru_days(n: int) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def days_left_text(due: date, today: date) -> str:
    days = (due - today).days
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {ru_days(days)}" if days > 0 else f"просрочено на {ru_days(days)}"


def price_text(record: Record) -> str:
    amount = f"{record.price:.2f}".replace(".", ",").removesuffix(",00")
    symbol = CURRENCY_SYMBOLS.get(record.currency or "", record.currency or "")
    return f"{amount} {symbol}".strip()


def period_text(record: Record) -> str:
    if record.cycle == 5:
        return "разово"
    if record.frequency == 1:
        return PERIOD_ONE.get(record.cycle, "")
    return f"каждые {record.frequency} {PERIOD_UNIT.get(record.cycle, '')}".strip()


def created_text(record: Record, today: date) -> str:
    due = date.fromisoformat(record.next_payment)
    parts = [KIND_NAMES.get(record.kind, record.kind)]
    if record.kind == "subscription" or record.price > 0:
        parts.append(price_text(record))
    parts.append(period_text(record))
    return (
        f"Добавлено: <b>{html.escape(record.name)}</b>\n"
        f"{' · '.join(part for part in parts if part)}\n"
        f"Дата: {due.strftime('%d.%m.%Y')} ({days_left_text(due, today)})\n\n"
        "Изменить или удалить можно на сайте."
    )


def refused_text(result: AddResult, parsed: QuickAdd) -> str:
    if result.status == "not_linked":
        return NOT_LINKED
    if result.field == "currency":
        return (
            f"Валюта {html.escape(parsed.currency or '')} не добавлена в ваш аккаунт. "
            "Добавьте её на сайте в настройках или укажите другую."
        )
    if result.field == "price":
        return "Для подписки нужна сумма: <code>/add Spotify 15.11 500rub</code>"
    return "Не удалось добавить: " + html.escape(result.message or "проверьте данные.")


async def add_from_line(
    message: Message, line: str, wallos: WallosClient, event_update: Update
) -> None:
    if message.from_user is None:
        return

    today = today_in_app_timezone()
    try:
        parsed = parse_quick_add(line, today)
    except ParseError as exc:
        await message.answer(f"{html.escape(str(exc))}\n\n{USAGE}")
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
    await state.clear()
    await message.answer("Отменено.")


@router.message(AddItem.waiting_for_line)
async def receive_line(
    message: Message, state: FSMContext, wallos: WallosClient, event_update: Update
) -> None:
    await state.clear()
    await add_from_line(message, (message.text or "").strip(), wallos, event_update)
