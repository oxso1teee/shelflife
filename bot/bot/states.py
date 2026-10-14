"""FSM states for the multi-step add-reminder dialog."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

__all__ = ["AddReminder"]


class AddReminder(StatesGroup):
    waiting_for_text = State()
    waiting_for_time = State()
    waiting_for_recurrence = State()
