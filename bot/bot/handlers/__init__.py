"""Register every handler router on a Dispatcher."""

from __future__ import annotations

from aiogram import Dispatcher, F
from aiogram.enums import ChatType

from bot.handlers import add, callbacks, common, fallback, nav, wizard
from bot.wallos_client import WallosClient

__all__ = ["setup"]


def setup(dp: Dispatcher, wallos: WallosClient, miniapp_url: str | None = None) -> None:
    """Wire dependencies and routers onto the dispatcher.

    miniapp_url: the Mini App's https address, or None when there is none.
    """
    dp["wallos"] = wallos
    dp["miniapp_url"] = miniapp_url
    # The bot is personal: in a group it would show the linked account and its
    # records to everyone, so messages are answered in private chats only.
    # Reminder buttons only ever exist in the private chat.
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.include_router(common.router)  # /start <token> before the plain /start
    dp.include_router(nav.router)
    dp.include_router(callbacks.router)
    dp.include_router(add.router)  # /add and /cancel before the dialog's text steps
    dp.include_router(wizard.router)
    dp.include_router(fallback.router)  # last: whatever the others did not take
