"""The command menu and description set at start (bot/menu.py)."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetMyCommands

from bot import menu


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, object]] = []

    async def set_my_commands(self, commands):
        if self.fail:
            raise TelegramNetworkError(method=SetMyCommands(commands=commands), message="down")
        self.calls.append(("commands", [(c.command, c.description) for c in commands]))

    async def set_my_short_description(self, text):
        self.calls.append(("short", text))

    async def set_my_description(self, text):
        self.calls.append(("description", text))


async def test_the_menu_lists_the_bot_commands():
    bot = FakeBot()
    await menu.publish(bot)

    assert bot.calls[0] == (
        "commands",
        [
            ("add", "Добавить запись"),
            ("help", "Как пользоваться ботом"),
            ("start", "Статус привязки аккаунта"),
            ("cancel", "Отменить ввод"),
        ],
    )
    assert [kind for kind, _ in bot.calls] == ["commands", "short", "description"]
    assert len(menu.SHORT_DESCRIPTION) <= 120 and len(menu.DESCRIPTION) <= 512  # Telegram's limits


async def test_telegram_refusing_the_menu_does_not_stop_the_bot(caplog):
    with caplog.at_level(logging.WARNING):
        await menu.publish(FakeBot(fail=True))
    assert "Could not publish" in caplog.text
