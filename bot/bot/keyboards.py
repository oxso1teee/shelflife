"""Inline keyboards and callback-data factories for the reminder bot UI."""

from __future__ import annotations

from typing import TypeVar

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import Reminder

__all__ = [
    "PAGE_SIZE",
    "BackCB",
    "ListPageCB",
    "MenuCB",
    "RecurrenceCB",
    "ReminderCB",
    "cancel_kb",
    "main_menu",
    "paginate",
    "recurrence_choice",
    "reminder_actions",
    "reminders_list",
]

PAGE_SIZE = 5


class MenuCB(CallbackData, prefix="menu"):
    action: str  # "add" | "list" | "help"


class RecurrenceCB(CallbackData, prefix="rec"):
    value: str  # "none" | "daily" | "weekly"


class ListPageCB(CallbackData, prefix="page"):
    page: int


class ReminderCB(CallbackData, prefix="rem"):
    reminder_id: int
    action: str  # "view" | "del"


class BackCB(CallbackData, prefix="back"):
    target: str  # "menu" | "list"


T = TypeVar("T")


def paginate(items: list[T], page: int, page_size: int = PAGE_SIZE) -> tuple[list[T], int]:
    """Return the items on `page` (zero-indexed) and the total page count.

    `page` is clamped to a valid index; the total page count is always >= 1
    so an empty list shows as "page 1 of 1".
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    return items[start : start + page_size], total_pages


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Add reminder", callback_data=MenuCB(action="add"))
    builder.button(text="My reminders", callback_data=MenuCB(action="list"))
    builder.button(text="Help", callback_data=MenuCB(action="help"))
    builder.adjust(1)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Cancel", callback_data=BackCB(target="menu"))
    return builder.as_markup()


def recurrence_choice() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="One-off", callback_data=RecurrenceCB(value="none"))
    builder.button(text="Daily", callback_data=RecurrenceCB(value="daily"))
    builder.button(text="Weekly", callback_data=RecurrenceCB(value="weekly"))
    builder.adjust(3)
    return builder.as_markup()


def reminders_list(
    items: list[Reminder], page: int = 0, page_size: int = PAGE_SIZE
) -> InlineKeyboardMarkup:
    page_items, total_pages = paginate(items, page, page_size)
    builder = InlineKeyboardBuilder()
    for r in page_items:
        builder.button(
            text=_format_label(r),
            callback_data=ReminderCB(reminder_id=r.id, action="view"),
        )

    nav_count = 0
    if page > 0:
        builder.button(text="< Prev", callback_data=ListPageCB(page=page - 1))
        nav_count += 1
    if page < total_pages - 1:
        builder.button(text="Next >", callback_data=ListPageCB(page=page + 1))
        nav_count += 1

    builder.button(text="Back", callback_data=BackCB(target="menu"))

    row_sizes: list[int] = [1] * len(page_items)
    if nav_count:
        row_sizes.append(nav_count)
    row_sizes.append(1)
    builder.adjust(*row_sizes)
    return builder.as_markup()


def reminder_actions(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Delete",
        callback_data=ReminderCB(reminder_id=reminder_id, action="del"),
    )
    builder.button(text="Back to list", callback_data=BackCB(target="list"))
    builder.adjust(1)
    return builder.as_markup()


def _format_label(r: Reminder) -> str:
    text = r.text if len(r.text) <= 30 else r.text[:27] + "..."
    if r.recurrence is None:
        when = r.fire_at.strftime("%Y-%m-%d %H:%M")
    else:
        when = f"{r.fire_at.strftime('%H:%M')} {r.recurrence}"
    return f"{text} . {when}"
