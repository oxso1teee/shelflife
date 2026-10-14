"""FSM states for dialogs (adapted from telegram-reminder-bot's add-reminder dialog)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

__all__ = ["AddItem"]


class AddItem(StatesGroup):
    # /add without arguments asks for the whole line in the next message.
    waiting_for_line = State()
