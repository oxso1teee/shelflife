"""The command menu, the menu button and the description set at start (bot/menu.py)."""

from __future__ import annotations

import logging

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetMyCommands
from aiogram.types import MenuButtonWebApp

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

    async def set_chat_menu_button(self, menu_button):
        self.calls.append(("menu_button", menu_button))


async def test_the_menu_lists_every_section():
    bot = FakeBot()
    await menu.publish(bot)

    assert bot.calls[0] == (
        "commands",
        [
            ("start", "Главная: сводка и ближайшее"),
            ("add", "Добавить запись"),
            ("list", "Мои записи"),
            ("soon", "Ближайшие даты"),
            ("spend", "Расходы на подписки"),
            ("settings", "Настройки и привязка"),
            ("help", "Как пользоваться"),
            ("cancel", "Прервать добавление"),
        ],
    )
    # Without a Mini App the menu button is not touched: what BotFather set stays.
    assert [kind for kind, _ in bot.calls] == ["commands", "short", "description"]
    assert len(menu.SHORT_DESCRIPTION) <= 120 and len(menu.DESCRIPTION) <= 512  # Telegram's limits


async def test_with_a_mini_app_the_menu_button_opens_it():
    bot = FakeBot()
    await menu.publish(bot, "https://shelflife.example.com/tma/index.php")

    button = bot.calls[-1][1]
    assert isinstance(button, MenuButtonWebApp)
    assert (button.text, button.web_app.url) == (
        "ShelfLife",
        "https://shelflife.example.com/tma/index.php",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://shelflife.example.com/tma/index.php",
            "https://shelflife.example.com/tma/index.php",
        ),
        ("http://shelflife.example.com/tma/index.php", None),
        ("https://", None),
        ("", None),
        (None, None),
        ("https://a b/", None),
        ("https://shelflife.example.com/tma/index.php#/home", None),
        ("javascript:alert(1)", None),
    ],
)
def test_only_an_https_address_counts_as_a_mini_app(value, expected):
    assert menu.miniapp_url(value) == expected


async def test_telegram_refusing_the_menu_does_not_stop_the_bot(caplog):
    with caplog.at_level(logging.WARNING):
        await menu.publish(FakeBot(fail=True))
    assert "Could not publish" in caplog.text
