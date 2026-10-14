"""List, view, and delete handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Reminder, ReminderDB
from bot.keyboards import (
    BackCB,
    ListPageCB,
    MenuCB,
    ReminderCB,
    main_menu,
    reminder_actions,
    reminders_list,
)
from bot.scheduler import ReminderScheduler

log = logging.getLogger(__name__)
router = Router()


def _render_list(items: list[Reminder], page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    if not items:
        return "You have no active reminders.", main_menu()
    return (
        f"Your active reminders ({len(items)}). Tap one to manage:",
        reminders_list(items, page=page),
    )


async def _replace(query: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    if isinstance(query.message, Message):
        await query.message.edit_text(text, reply_markup=kb)


@router.callback_query(MenuCB.filter(F.action == "list"))
async def show_list(query: CallbackQuery, db: ReminderDB) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    items = db.list_for_user(query.from_user.id)
    text, kb = _render_list(items)
    await _replace(query, text, kb)
    await query.answer()


@router.callback_query(BackCB.filter(F.target == "list"))
async def back_to_list(query: CallbackQuery, db: ReminderDB) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    items = db.list_for_user(query.from_user.id)
    text, kb = _render_list(items)
    await _replace(query, text, kb)
    await query.answer()


@router.callback_query(ListPageCB.filter())
async def change_page(
    query: CallbackQuery,
    callback_data: ListPageCB,
    db: ReminderDB,
) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    items = db.list_for_user(query.from_user.id)
    text, kb = _render_list(items, page=callback_data.page)
    await _replace(query, text, kb)
    await query.answer()


@router.callback_query(ReminderCB.filter(F.action == "view"))
async def view_reminder(
    query: CallbackQuery,
    callback_data: ReminderCB,
    db: ReminderDB,
) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    reminder = db.get(callback_data.reminder_id)
    if reminder is None or reminder.user_id != query.from_user.id:
        await query.answer("Reminder not found.", show_alert=True)
        return
    when = reminder.fire_at.strftime("%Y-%m-%d %H:%M UTC")
    rec = "" if reminder.recurrence is None else f"\nRepeats: {reminder.recurrence}"
    if isinstance(query.message, Message):
        await query.message.edit_text(
            f"<b>Reminder</b>\n{reminder.text}\n\nWhen: {when}{rec}",
            reply_markup=reminder_actions(reminder.id),
            parse_mode="HTML",
        )
    await query.answer()


@router.callback_query(ReminderCB.filter(F.action == "del"))
async def delete_reminder(
    query: CallbackQuery,
    callback_data: ReminderCB,
    db: ReminderDB,
    scheduler: ReminderScheduler,
) -> None:
    if query.from_user is None:
        await query.answer("User not identified.", show_alert=True)
        return
    deleted = db.delete(callback_data.reminder_id, user_id=query.from_user.id)
    if deleted:
        scheduler.cancel(callback_data.reminder_id)
        await query.answer("Deleted.")
    else:
        await query.answer("Not found.", show_alert=True)
    items = db.list_for_user(query.from_user.id)
    text, kb = _render_list(items)
    await _replace(query, text, kb)
