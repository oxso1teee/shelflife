"""/add handlers, called directly with stand-ins for Telegram, the FSM and Wallos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest
from aiogram.filters import CommandObject

from bot.handlers import add
from bot.states import AddFlow
from bot.wallos_client import AddResult, Record, WallosError

TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def fixed_add_today(monkeypatch):
    monkeypatch.setattr(add, "today_in_app_timezone", lambda: TODAY)


@dataclass
class FakeUser:
    id: int = 555


@dataclass
class FakeMessage:
    text: str | None = None
    from_user: FakeUser | None = field(default_factory=FakeUser)
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


@dataclass
class FakeUpdate:
    update_id: int = 4242


class FakeState:
    def __init__(self) -> None:
        self.state = None

    async def set_state(self, state) -> None:
        self.state = state

    async def get_state(self):
        return self.state

    async def clear(self) -> None:
        self.state = None


def record(**overrides) -> Record:
    values = {
        "id": 9,
        "kind": "subscription",
        "name": "Spotify",
        "next_payment": "2026-11-15",
        "price": 500.0,
        "currency": "RUB",
        "cycle": 3,
        "frequency": 1,
        "inactive": False,
        "snoozed_until": None,
    }
    values.update(overrides)
    return Record(**values)


class FakeWallos:
    def __init__(self, result: AddResult | None = None, error: bool = False) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def add_record(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise WallosError("down")
        return self.result


def command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="add", args=args)


async def test_the_specification_example_creates_a_subscription():
    message = FakeMessage()
    wallos = FakeWallos(AddResult("created", record()))

    await add.cmd_add(message, command("Spotify 15.11 500rub"), FakeState(), wallos, FakeUpdate())

    assert wallos.calls == [
        {
            "telegram_id": 555,
            "update_id": 4242,
            "kind": "subscription",
            "name": "Spotify",
            "next_payment": "2026-11-15",
            "price": "500",
            "currency": "RUB",
            "cycle": None,
            "frequency": None,
        }
    ]
    assert message.answers == [
        "✅ Запись добавлена\n\n"
        "<b>Spotify</b>\n"
        "Подписка · каждый месяц\n"
        "Дата: 15.11.2026 — через 32 дня\n"
        "Сумма: 500\u00a0₽\n\n"
        "Изменить или удалить её можно на сайте."
    ]


async def test_a_shelf_life_date_is_described_as_such():
    message = FakeMessage()
    created = record(kind="expiry", name="Витамины", price=0.0, cycle=5, next_payment="2026-10-15")

    await add.cmd_add(
        message,
        command("Витамины 15.10"),
        FakeState(),
        FakeWallos(AddResult("created", created)),
        FakeUpdate(),
    )

    card = message.answers[0].split("\n")
    assert card[3:5] == ["Срок годности", "Дата: 15.10.2026 — завтра"]
    assert "Сумма" not in message.answers[0], "no amount for a shelf-life date"


async def test_the_reply_escapes_the_name():
    message = FakeMessage()

    await add.cmd_add(
        message,
        command("x 15.11 1"),
        FakeState(),
        FakeWallos(AddResult("created", record(name="<b>A & B</b>"))),
        FakeUpdate(),
    )

    assert "&lt;b&gt;A &amp; B&lt;/b&gt;" in message.answers[0]


async def test_a_parse_error_is_explained_without_asking_wallos():
    message = FakeMessage()
    wallos = FakeWallos()

    await add.cmd_add(message, command("Spotify 31.02 500"), FakeState(), wallos, FakeUpdate())

    assert wallos.calls == []
    assert message.answers == [f"⚠️ Такой даты нет: 31.02.\n\n{add.USAGE}"]
    assert message.answers[0].count("/add Spotify 15.11 500rub") == 1, "one example, not two"


async def test_cancel_leaves_the_dialog():
    state = FakeState()
    await state.set_state(AddFlow.amount)
    message = FakeMessage()

    await add.cmd_cancel(message, state)

    assert state.state is None
    assert message.answers == ["Добавление отменено."]


async def test_cancel_with_nothing_to_cancel_says_so():
    message = FakeMessage()

    await add.cmd_cancel(message, FakeState())

    assert message.answers == ["Сейчас нечего отменять. Добавить запись — /add"]


async def test_a_long_name_is_shortened_in_the_reply():
    message = FakeMessage()
    long_name = "Очень длинное название " * 5

    await add.cmd_add(
        message,
        command("x 15.11 1"),
        FakeState(),
        FakeWallos(AddResult("created", record(name=long_name))),
        FakeUpdate(),
    )

    name = message.answers[0].split("<b>")[1].split("</b>")[0]
    assert len(name) == 80 and name.endswith("…")


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (AddResult("not_linked"), add.NOT_LINKED),
        # an update id already processed for another account
        (AddResult("invalid"), add.REFUSED),
        (
            AddResult("invalid", field="currency", message="unknown_currency"),
            "⚠️ Валюты RUB нет в вашем аккаунте. "
            "Добавьте её на сайте в настройках или укажите другую.",
        ),
        (
            AddResult("invalid", field="next_payment", message="x"),
            add.REFUSED_FIELDS["next_payment"],
        ),
        (AddResult("invalid", field="frequency", message="x"), add.REFUSED),
    ],
)
async def test_refusals_from_wallos_are_explained(result, expected):
    message = FakeMessage()

    await add.cmd_add(
        message, command("Spotify 15.11 500rub"), FakeState(), FakeWallos(result), FakeUpdate()
    )

    assert message.answers == [expected]


async def test_wallos_being_down_is_reported():
    message = FakeMessage()

    await add.cmd_add(
        message, command("Spotify 15.11 500rub"), FakeState(), FakeWallos(error=True), FakeUpdate()
    )

    assert message.answers == [add.UNAVAILABLE]


async def test_a_message_without_a_sender_is_ignored():
    message = FakeMessage(from_user=None)
    wallos = FakeWallos()

    await add.cmd_add(message, command("Spotify 15.11 500rub"), FakeState(), wallos, FakeUpdate())

    assert wallos.calls == [] and message.answers == []
