"""Whatever no other handler took: unknown commands, plain text, old buttons."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from aiogram.types import Chat, Message, User

from bot.handlers import callbacks, fallback


@dataclass
class FakeMessage:
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


@dataclass
class FakeQuery:
    answers: list[str | None] = field(default_factory=list)

    async def answer(self, text: str | None = None, **_: object) -> None:
        self.answers.append(text)


def telegram_message(chat_type: str, text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime(2026, 10, 14),
        chat=Chat(id=1, type=chat_type),
        from_user=User(id=555, is_bot=False, first_name="A"),
        text=text,
    )


async def test_an_unknown_command_lists_the_commands():
    message = FakeMessage()
    await fallback.unknown_command(message)
    assert message.answers == [fallback.UNKNOWN_COMMAND]
    assert "/add" in fallback.UNKNOWN_COMMAND and "/help" in fallback.UNKNOWN_COMMAND


async def test_plain_text_gets_a_hint_how_to_add():
    message = FakeMessage()
    await fallback.anything_else(message)
    assert message.answers == [fallback.HINT]
    assert "/add Spotify 15.11 500rub" in fallback.HINT


async def test_an_old_button_is_answered_so_the_client_stops_waiting():
    query = FakeQuery()
    await fallback.unknown_button(query)
    assert query.answers == [callbacks.UNKNOWN_BUTTON]


async def test_messages_are_answered_in_private_chats_only(dispatcher):
    private, _ = await dispatcher.message.check_root_filters(telegram_message("private", "hi"))
    group, _ = await dispatcher.message.check_root_filters(telegram_message("group", "hi"))
    assert (private, group) == (True, False)


def test_the_fallback_router_is_registered_last(dispatcher):
    assert dispatcher.sub_routers[-1] is fallback.router
