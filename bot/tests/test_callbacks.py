"""Reminder buttons: the callback format shared with Wallos and the handler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest
from aiogram.types import Chat, Message

from bot import texts
from bot.handlers import callbacks
from bot.keyboards import ItemActionCB, due_from_callback
from bot.wallos_client import ActionResult, Record, WallosError

# Exactly what web/includes/shelflife/notifications.php puts on the buttons.
WALLOS_BUTTONS = ["a:5:20261014:r", "a:5:20261014:c", "a:5:20261014:s"]


def test_the_wallos_button_format_round_trips():
    for raw in WALLOS_BUTTONS:
        data = ItemActionCB.unpack(raw)
        assert (data.subscription_id, data.due) == (5, "20261014")
        assert data.pack() == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("20261014", "2026-10-14"), ("2026-10-14", None), ("2026101", None), ("abcdefgh", None)],
)
def test_due_dates_from_buttons(raw, expected):
    assert due_from_callback(raw) == expected


def record(**overrides) -> Record:
    values = {
        "id": 5,
        "kind": "subscription",
        "name": "Spotify",
        "next_payment": "2026-11-14",
        "price": 9.99,
        "currency": "USD",
        "cycle": 3,
        "frequency": 1,
        "inactive": False,
        "snoozed_until": None,
    }
    values.update(overrides)
    return Record(**values)


@dataclass
class FakeUser:
    id: int = 555


@dataclass
class FakeUpdate:
    update_id: int = 777


@dataclass
class FakeQuery:
    message: object = None
    from_user: FakeUser | None = field(default_factory=FakeUser)
    answers: list[tuple[str | None, bool]] = field(default_factory=list)

    async def answer(self, text: str | None = None, show_alert: bool = False, **_: object) -> None:
        self.answers.append((text, show_alert))


class FakeWallos:
    def __init__(self, result: ActionResult | None = None, error: bool = False) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def act(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise WallosError("down")
        return self.result


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(texts, "today", lambda: date(2026, 10, 13))


@pytest.fixture
def reminder(monkeypatch):
    """A real aiogram Message whose edit_text is recorded instead of sent."""
    edits: list[tuple[str, object]] = []

    async def fake_edit_text(self, text, reply_markup=None, **_):
        edits.append((text, reply_markup))

    monkeypatch.setattr(Message, "edit_text", fake_edit_text)
    message = Message(
        message_id=1,
        date=datetime(2026, 10, 13),
        chat=Chat(id=555, type="private"),
        text="Завтра спишется оплата за Spotify — 14.10.2026.",
    )
    return message, edits


async def test_renew_is_applied_with_the_due_date_from_the_button(reminder):
    message, edits = reminder
    query = FakeQuery(message=message)
    wallos = FakeWallos(ActionResult("done", "renew", record(next_payment="2026-11-14")))

    await callbacks.on_item_action(
        query, ItemActionCB.unpack("a:5:20261014:r"), wallos, FakeUpdate()
    )

    assert wallos.calls == [
        {
            "telegram_id": 555,
            "update_id": 777,
            "subscription_id": 5,
            "action": "renew",
            "expected_due": "2026-10-14",
        }
    ]
    assert query.answers == [("✅ Продлено. Следующая дата — 14.11.2026.", False)]
    text, markup = edits[0]
    assert text.endswith("\n\n<i>✅ Продлено. Следующая дата — 14.11.2026.</i>")
    assert markup is None, "the buttons are removed"


@pytest.mark.parametrize(
    ("raw", "result", "expected"),
    [
        (
            "a:5:20261014:c",
            ActionResult("done", "cancel", record(inactive=True)),
            "❌ Отменено. Напоминаний по этой записи больше не будет.",
        ),
        (
            "a:5:20261014:s",
            ActionResult("done", "snooze", record(snoozed_until="2026-10-14")),
            "⏰ Напомню завтра, 14.10.2026.",
        ),
        (
            "a:5:20261014:r",
            ActionResult("stale", "renew", record()),
            "Уже обработано: следующая дата — 14.11.2026.",
        ),
        (
            "a:5:20261014:c",
            ActionResult("inactive", "cancel", record(inactive=True)),
            "Запись уже отключена — напоминаний по ней не будет.",
        ),
        (
            "a:5:20261014:r",
            ActionResult("not_found"),
            "Запись не найдена — возможно, её удалили на сайте.",
        ),
    ],
)
async def test_each_outcome_is_explained(reminder, raw, result, expected):
    message, edits = reminder
    query = FakeQuery(message=message)

    await callbacks.on_item_action(
        query, ItemActionCB.unpack(raw), FakeWallos(result), FakeUpdate()
    )

    assert query.answers == [(expected, False)]
    assert edits and edits[0][1] is None


async def test_a_foreign_or_unlinked_press_changes_nothing_on_screen(reminder):
    message, edits = reminder
    query = FakeQuery(message=message)

    await callbacks.on_item_action(
        query,
        ItemActionCB.unpack("a:5:20261014:r"),
        FakeWallos(ActionResult("not_linked")),
        FakeUpdate(),
    )

    assert query.answers == [
        ("Этот Telegram не привязан к аккаунту ShelfLife. Привяжите его в профиле на сайте.", False)
    ]
    assert edits == [], "the reminder keeps its buttons"


async def test_a_refused_repeated_update_shows_nothing_of_a_record(reminder):
    """Wallos refuses an update id already processed for another account."""
    message, edits = reminder
    query = FakeQuery(message=message)

    await callbacks.on_item_action(
        query,
        ItemActionCB.unpack("a:5:20261014:r"),
        FakeWallos(ActionResult("invalid")),
        FakeUpdate(),
    )

    assert query.answers == [(callbacks.UNKNOWN_BUTTON, False)]
    assert edits == [], "the reminder is left as it was"


@pytest.mark.parametrize("raw", ["a:5:20261014:x", "a:5:2026-10-14:r"])
async def test_an_unknown_button_does_not_reach_wallos(reminder, raw):
    message, _ = reminder
    query = FakeQuery(message=message)
    wallos = FakeWallos()

    await callbacks.on_item_action(query, ItemActionCB.unpack(raw), wallos, FakeUpdate())

    assert wallos.calls == []
    assert query.answers == [(callbacks.UNKNOWN_BUTTON, True)]


async def test_wallos_being_down_is_reported_and_the_buttons_stay(reminder):
    message, edits = reminder
    query = FakeQuery(message=message)

    await callbacks.on_item_action(
        query, ItemActionCB.unpack("a:5:20261014:r"), FakeWallos(error=True), FakeUpdate()
    )

    assert query.answers == [(callbacks.UNAVAILABLE, True)]
    assert edits == []


async def test_a_press_without_a_sender_is_ignored():
    query = FakeQuery(from_user=None)
    wallos = FakeWallos()

    await callbacks.on_item_action(
        query, ItemActionCB.unpack("a:5:20261014:r"), wallos, FakeUpdate()
    )

    assert wallos.calls == []
    assert query.answers == [(None, False)]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (ActionResult("stale", "renew", None), "Уже обработано: дата записи изменилась."),
        (
            ActionResult("not_recurring", "renew", record()),
            "Эту запись нельзя продлить. Измените дату на сайте.",
        ),
        (ActionResult("surprise"), callbacks.UNKNOWN_BUTTON),
    ],
)
def test_outcomes_without_a_record_or_unknown(result, expected):
    assert callbacks.outcome_text(result) == expected


def test_a_snooze_further_away_names_the_days():
    result = ActionResult("done", "snooze", record(snoozed_until="2026-10-16"))
    assert callbacks.outcome_text(result) == "⏰ Напомню через 3 дня, 16.10.2026."
