"""/add handlers, called directly with stand-ins for Telegram, the FSM and Wallos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest
from aiogram.filters import CommandObject

from bot.handlers import add
from bot.states import AddItem
from bot.wallos_client import AddResult, Record, WallosError

TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
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
        "Добавлено: <b>Spotify</b>\n"
        "Подписка · 500 ₽ · каждый месяц\n"
        "Дата: 15.11.2026 (через 32 дня)\n\n"
        "Изменить или удалить можно на сайте."
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

    assert "Срок годности · разово" in message.answers[0]
    assert "(завтра)" in message.answers[0]


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
    assert message.answers[0].startswith("Такой даты нет: 31.02.")
    assert "/add Spotify 15.11 500rub" in message.answers[0]


async def test_add_without_arguments_asks_for_the_line_then_adds_it():
    state = FakeState()
    ask = FakeMessage()
    wallos = FakeWallos(AddResult("created", record()))

    await add.cmd_add(ask, command(None), state, wallos, FakeUpdate())
    assert state.state == AddItem.waiting_for_line
    assert ask.answers == [add.ASK_LINE]

    line = FakeMessage(text="Spotify 15.11 500rub")
    await add.receive_line(line, state, wallos, FakeUpdate(update_id=4243))
    assert state.state is None
    assert wallos.calls[0]["name"] == "Spotify"
    assert wallos.calls[0]["update_id"] == 4243
    assert line.answers[0].startswith("Добавлено")


async def test_cancel_leaves_the_dialog():
    state = FakeState()
    await state.set_state(AddItem.waiting_for_line)
    message = FakeMessage()

    await add.cmd_cancel(message, state)

    assert state.state is None
    assert message.answers == ["Отменено."]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (AddResult("not_linked"), add.NOT_LINKED),
        # an update id already processed for another account
        (AddResult("invalid"), "Не удалось добавить: проверьте данные."),
        (
            AddResult("invalid", field="currency", message="unknown_currency"),
            "Валюта RUB не добавлена в ваш аккаунт. "
            "Добавьте её на сайте в настройках или укажите другую.",
        ),
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


@pytest.mark.parametrize(
    ("cycle", "frequency", "expected"),
    [(5, 1, "разово"), (1, 1, "каждый день"), (4, 1, "каждый год"), (3, 3, "каждые 3 мес.")],
)
def test_period_wording(cycle, frequency, expected):
    assert add.period_text(record(cycle=cycle, frequency=frequency)) == expected
