"""Inline keyboards and callback-data factories for the ShelfLife bot UI."""

from __future__ import annotations

import re
from typing import TypeVar

from aiogram.filters.callback_data import CallbackData

__all__ = ["ACTIONS", "PAGE_SIZE", "ItemActionCB", "due_from_callback", "paginate"]

PAGE_SIZE = 5

# Button code -> internal API action.
ACTIONS = {"r": "renew", "c": "cancel", "s": "snooze"}


class ItemActionCB(CallbackData, prefix="a"):
    """A reminder button, as Wallos writes it: a:<record id>:<due YYYYMMDD>:<r|c|s>.

    The buttons are built by web/includes/shelflife/notifications.php, which
    sends the reminders; the field order here must match that format.
    """

    subscription_id: int
    due: str
    act: str


_DUE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def due_from_callback(value: str) -> str | None:
    """'20261115' -> '2026-11-15'; None for anything else."""
    match = _DUE_RE.match(value)
    if match is None:
        return None
    return "-".join(match.groups())


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
