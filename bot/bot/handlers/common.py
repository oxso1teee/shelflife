"""Generic handlers: /start, /help, menu navigation."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import BackCB, MenuCB, main_menu

log = logging.getLogger(__name__)
router = Router()

WELCOME = (
    "Hi! I'm your personal reminder bot.\n" "Use the menu below to add, view, or delete reminders."
)

HELP_TEXT = (
    "<b>How to use</b>\n\n"
    "<b>Add reminder</b> — opens a 3-step dialog (text, time, recurrence).\n"
    "<b>My reminders</b> — shows your active reminders; tap one to delete.\n\n"
    "<b>Time formats</b>\n"
    "- Relative: <code>in 5 minutes</code>, <code>in 2 hours</code>, <code>in 1 day</code>\n"
    "- Day-anchored: <code>today 18:00</code>, <code>tomorrow 09:30</code>\n"
    "- Absolute: <code>2026-05-14 18:30</code>, <code>14.05.2026 18:30</code>\n\n"
    "<b>Recurrence</b>\n"
    "- One-off (fires once)\n"
    "- Daily / Weekly (same time, same day of week for weekly)\n\n"
    "Commands: /start, /help"
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu(), parse_mode="HTML")


@router.callback_query(MenuCB.filter(F.action == "help"))
async def menu_help(query: CallbackQuery) -> None:
    if isinstance(query.message, Message):
        await query.message.edit_text(HELP_TEXT, reply_markup=main_menu(), parse_mode="HTML")
    await query.answer()


@router.callback_query(BackCB.filter(F.target == "menu"))
async def back_to_menu(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(query.message, Message):
        await query.message.edit_text(WELCOME, reply_markup=main_menu())
    await query.answer()
