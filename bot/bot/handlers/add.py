"""Three-step dialog that adds a new reminder."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Recurrence, ReminderDB
from bot.keyboards import (
    MenuCB,
    RecurrenceCB,
    cancel_kb,
    main_menu,
    recurrence_choice,
)
from bot.parsing import TimeParseError, parse_time
from bot.scheduler import ReminderScheduler
from bot.states import AddReminder

log = logging.getLogger(__name__)
router = Router()

MAX_TEXT_LEN = 500


@router.callback_query(MenuCB.filter(F.action == "add"))
async def start_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddReminder.waiting_for_text)
    if isinstance(query.message, Message):
        await query.message.edit_text(
            "What should I remind you about? Send the text.",
            reply_markup=cancel_kb(),
        )
    await query.answer()


@router.message(AddReminder.waiting_for_text)
async def receive_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send some text.", reply_markup=cancel_kb())
        return
    if len(text) > MAX_TEXT_LEN:
        await message.answer(
            f"Too long (max {MAX_TEXT_LEN} chars). Please shorten.",
            reply_markup=cancel_kb(),
        )
        return
    await state.update_data(text=text)
    await state.set_state(AddReminder.waiting_for_time)
    await message.answer(
        "When? Examples:\n" "- in 30 minutes\n" "- tomorrow 09:30\n" "- 2026-05-14 18:30",
        reply_markup=cancel_kb(),
    )


@router.message(AddReminder.waiting_for_time)
async def receive_time(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        fire_at = parse_time(raw, tz=UTC)
    except TimeParseError as exc:
        await message.answer(
            f"I couldn't parse that time: {exc}\nTry another format or tap Cancel.",
            reply_markup=cancel_kb(),
        )
        return
    await state.update_data(fire_at_iso=fire_at.isoformat())
    await state.set_state(AddReminder.waiting_for_recurrence)
    await message.answer("Should it repeat?", reply_markup=recurrence_choice())


@router.callback_query(AddReminder.waiting_for_recurrence, RecurrenceCB.filter())
async def receive_recurrence(
    query: CallbackQuery,
    callback_data: RecurrenceCB,
    state: FSMContext,
    db: ReminderDB,
    scheduler: ReminderScheduler,
) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    data = await state.get_data()
    text: str = data["text"]
    fire_at = datetime.fromisoformat(data["fire_at_iso"])
    recurrence: Recurrence | None
    if callback_data.value == "none":
        recurrence = None
    elif callback_data.value in {"daily", "weekly"}:
        recurrence = callback_data.value  # type: ignore[assignment]
    else:
        await query.answer("Unknown choice.", show_alert=True)
        return

    if not isinstance(query.message, Message):
        await query.answer()
        return

    rid = db.add(
        user_id=query.from_user.id,
        chat_id=query.message.chat.id,
        text=text,
        fire_at=fire_at,
        recurrence=recurrence,
    )
    reminder = db.get(rid)
    assert reminder is not None
    scheduler.schedule(reminder)
    await state.clear()

    when_str = fire_at.strftime("%Y-%m-%d %H:%M UTC")
    rec_str = "" if recurrence is None else f" (repeats {recurrence})"
    await query.message.edit_text(
        f'Saved: "{text}" at {when_str}{rec_str}.',
        reply_markup=main_menu(),
    )
    await query.answer()
