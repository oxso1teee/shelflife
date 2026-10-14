"""/start and /help handlers, called directly with stand-ins for Telegram and Wallos."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from aiogram.filters import CommandObject

from bot.handlers import common
from bot.wallos_client import Account, LinkResult, WallosError

TOKEN = "0123456789abcdef0123456789abcdef"


@dataclass
class FakeUser:
    id: int = 555
    username: str | None = "alice_tg"


@dataclass
class FakeMessage:
    from_user: FakeUser | None = field(default_factory=FakeUser)
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class FakeWallos:
    def __init__(self, link_result=None, account=None, error: bool = False) -> None:
        self.link_result = link_result
        self.account_result = account
        self.error = error
        self.link_calls: list[tuple] = []

    async def link(self, token, telegram_id, telegram_username):
        self.link_calls.append((token, telegram_id, telegram_username))
        if self.error:
            raise WallosError("down")
        return self.link_result

    async def account(self, telegram_id):
        if self.error:
            raise WallosError("down")
        return self.account_result


def start_command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="start", args=args)


async def test_a_valid_token_links_the_sender():
    message = FakeMessage()
    wallos = FakeWallos(link_result=LinkResult("linked", "alice"))

    await common.cmd_start_link(message, start_command(TOKEN), wallos)

    assert wallos.link_calls == [(TOKEN, 555, "alice_tg")]
    assert message.answers == [common.linked_text("alice")]
    assert message.answers[0].startswith("✅ Аккаунт <b>alice</b> привязан.")
    assert "/add Spotify 15.11 500rub" in message.answers[0], "the next step is shown"


async def test_the_account_name_is_escaped():
    message = FakeMessage()
    wallos = FakeWallos(link_result=LinkResult("linked", "<i>x</i>"))

    await common.cmd_start_link(message, start_command(TOKEN), wallos)

    assert "&lt;i&gt;x&lt;/i&gt;" in message.answers[0]
    assert "<i>x</i>" not in message.answers[0]


@pytest.mark.parametrize("args", ["short", TOKEN.upper(), TOKEN + "0", "' OR 1=1"])
async def test_a_malformed_token_is_refused_without_asking_wallos(args):
    message = FakeMessage()
    wallos = FakeWallos()

    await common.cmd_start_link(message, start_command(args), wallos)

    assert wallos.link_calls == []
    assert message.answers == [common.LINK_RESULTS["invalid_token"]]


@pytest.mark.parametrize("status", ["invalid_token", "telegram_taken"])
async def test_refusals_are_explained(status):
    message = FakeMessage()

    await common.cmd_start_link(
        message, start_command(TOKEN), FakeWallos(link_result=LinkResult(status, None))
    )

    assert message.answers == [common.LINK_RESULTS[status]]


async def test_wallos_being_down_is_reported():
    message = FakeMessage()

    await common.cmd_start_link(message, start_command(TOKEN), FakeWallos(error=True))

    assert message.answers == [common.UNAVAILABLE]


async def test_start_without_a_token_explains_how_to_link():
    message = FakeMessage()

    await common.cmd_start(message, FakeWallos(account=Account(linked=False, username=None)))

    assert message.answers == [common.NOT_LINKED]


async def test_start_without_a_token_recognises_a_linked_account():
    message = FakeMessage()

    await common.cmd_start(message, FakeWallos(account=Account(linked=True, username="alice")))

    assert message.answers == [common.already_linked_text("alice")]
    assert message.answers[0].startswith("👋 Аккаунт <b>alice</b> привязан")


async def test_a_message_without_a_sender_is_ignored():
    message = FakeMessage(from_user=None)
    wallos = FakeWallos(link_result=LinkResult("linked", "alice"))

    await common.cmd_start_link(message, start_command(TOKEN), wallos)
    await common.cmd_start(message, wallos)

    assert message.answers == []
    assert wallos.link_calls == []


async def test_the_start_screen_explains_the_bot_and_the_next_step():
    text = common.NOT_LINKED
    assert text.startswith("👋 Привет! Я бот <b>ShelfLife</b>.")
    assert "Профиль → Telegram-бот" in text and "«Привязать Telegram»" in text
    assert text.endswith("/help")


async def test_help_lists_the_commands_and_the_buttons():
    message = FakeMessage()

    await common.cmd_help(message)

    assert message.answers == [common.HELP_TEXT]
    for fragment in ("/add", "/cancel", "/start", "«Продлено»", "«Отменено»", "«Напомнить позже»"):
        assert fragment in common.HELP_TEXT
