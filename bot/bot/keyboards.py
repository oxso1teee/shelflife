"""Inline keyboards and callback-data factories for the ShelfLife bot UI."""

from __future__ import annotations

import re
from typing import TypeVar

from aiogram.filters.callback_data import CallbackData

__all__ = [
    "ACTIONS",
    "CARD_ACTIONS",
    "FILTERS",
    "PAGE_SIZE",
    "CardActionCB",
    "CardCB",
    "ItemActionCB",
    "NavCB",
    "SettingsCB",
    "WizardCB",
    "due_from_callback",
    "due_to_callback",
    "paginate",
]

PAGE_SIZE = 6

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


# Record-card button code -> internal API action ("d" asks first, "D" deletes).
CARD_ACTIONS = {"r": "renew", "c": "cancel", "s": "snooze", "a": "reactivate", "D": "delete"}

# List filters: code -> (title, predicate name). "all" is every active record.
FILTERS = {
    "all": "Все",
    "sub": "Подписки",
    "exp": "Сроки",
    "mnt": "Обслуживание",
    "off": "Отключённые",
}


class NavCB(CallbackData, prefix="n"):
    """A section: home, list, soon, spend, set (settings), help, add (start adding)."""

    to: str
    flt: str = "all"
    page: int = 0


class CardCB(CallbackData, prefix="c"):
    """Open a record card; the filter and page lead back to the same list page."""

    id: int
    flt: str = "all"
    page: int = 0


class CardActionCB(CallbackData, prefix="x"):
    """An action on a record card, for the due date the card showed."""

    id: int
    due: str
    act: str
    flt: str = "all"
    page: int = 0


class SettingsCB(CallbackData, prefix="s"):
    """days (value 0-7), unlink (asks), unlink_ok (unlinks)."""

    key: str
    value: int = 0


class WizardCB(CallbackData, prefix="w"):
    """A choice in the step-by-step /add: step and the chosen value."""

    step: str
    value: str = ""


_DUE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def due_from_callback(value: str) -> str | None:
    """'20261115' -> '2026-11-15'; None for anything else."""
    match = _DUE_RE.match(value)
    if match is None:
        return None
    return "-".join(match.groups())


def due_to_callback(value: str | None) -> str:
    """'2026-11-15' -> '20261115' (as the reminder buttons write it)."""
    return (value or "").replace("-", "")


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
