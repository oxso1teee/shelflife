"""Register every handler router on a Dispatcher."""

from __future__ import annotations

from aiogram import Dispatcher, F
from aiogram.enums import ChatType

from bot.handlers import add, callbacks, common, fallback
from bot.wallos_client import WallosClient

__all__ = ["setup"]


def setup(dp: Dispatcher, wallos: WallosClient) -> None:
    """Wire dependencies and routers onto the dispatcher."""
    dp["wallos"] = wallos
    # The bot is personal: in a group it would show the linked account and its
    # records to everyone, so messages are answered in private chats only.
    # Reminder buttons only ever exist in the private chat.
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.include_router(common.router)
    dp.include_router(callbacks.router)
    dp.include_router(add.router)
    dp.include_router(fallback.router)  # last: whatever the others did not take
