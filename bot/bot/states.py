"""FSM states for dialogs (adapted from telegram-reminder-bot's add-reminder dialog)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

__all__ = ["AddFlow"]


class AddFlow(StatesGroup):
    """Adding a record step by step (bot/handlers/wizard.py)."""

    name = State()
    kind = State()
    category = State()
    due = State()
    amount = State()
    period = State()
    confirm = State()
