"""Reminder buttons: "renewed", "cancelled", "remind me later".

Wallos sends the reminders with these buttons; the press comes back here and is
applied through the internal API, which checks that the record belongs to the
pressing Telegram user and still has the due date the reminder was sent for.
A second press of the same button finds the date changed and does nothing.
"""

from __future__ import annotations

import html
import logging
from datetime import date

from aiogram import Router
from aiogram.types import CallbackQuery, Message, Update

from bot import texts
from bot.keyboards import ACTIONS, ItemActionCB, due_from_callback
from bot.wallos_client import ActionResult, WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

UNAVAILABLE = texts.UNAVAILABLE
UNKNOWN_BUTTON = "Эта кнопка больше не работает."

STATUS_TEXTS = {
    "stale": "Уже обработано: дата записи изменилась.",
    "inactive": "Запись уже отключена — напоминаний по ней не будет.",
    "not_recurring": "Эту запись нельзя продлить. Измените дату на сайте.",
    "not_found": "Запись не найдена — возможно, её удалили на сайте.",
    "not_linked": "Этот Telegram не привязан к аккаунту ShelfLife. Привяжите его в профиле на сайте.",
    "invalid": UNKNOWN_BUTTON,
}


def outcome_text(result: ActionResult, today: date | None = None) -> str:
    """What the user is told after a press: what happened and, if nothing did, why."""
    record = result.record
    if result.status == "done" and record is not None:
        if result.action == "renew":
            return f"✅ Продлено. Следующая дата — {texts.format_date(record.next_payment)}."
        if result.action == "cancel":
            return "❌ Отменено. Напоминаний по этой записи больше не будет."
        if result.action == "snooze" and record.snoozed_until:
            until = date.fromisoformat(record.snoozed_until)
            when = texts.relative(until, today or texts.today())
            return f"⏰ Напомню {when}, {texts.format_date(until)}."
    if result.status == "stale" and record is not None:
        return f"Уже обработано: следующая дата — {texts.format_date(record.next_payment)}."
    return STATUS_TEXTS.get(result.status, UNKNOWN_BUTTON)


@router.callback_query(ItemActionCB.filter())
async def on_item_action(
    query: CallbackQuery,
    callback_data: ItemActionCB,
    wallos: WallosClient,
    event_update: Update,
) -> None:
    if query.from_user is None:
        await query.answer()
        return

    action = ACTIONS.get(callback_data.act)
    due = due_from_callback(callback_data.due)
    if action is None or due is None:
        await query.answer(UNKNOWN_BUTTON, show_alert=True)
        return

    try:
        result = await wallos.act(
            telegram_id=query.from_user.id,
            update_id=event_update.update_id,
            subscription_id=callback_data.subscription_id,
            action=action,
            expected_due=due,
        )
    except WallosError:
        log.exception("Button %s failed for telegram_id=%d", action, query.from_user.id)
        await query.answer(UNAVAILABLE, show_alert=True)
        return

    text = outcome_text(result)
    await query.answer(text)

    # The buttons have done their job (or no longer apply): replace them with the outcome.
    if result.status in {"done", "stale", "inactive", "not_found"} and isinstance(
        query.message, Message
    ):
        await query.message.edit_text(
            f"{query.message.html_text}\n\n<i>{html.escape(text)}</i>", reply_markup=None
        )
