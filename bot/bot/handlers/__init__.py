"""Register every handler router on a Dispatcher."""

from __future__ import annotations

from aiogram import Dispatcher

from bot.handlers import add, callbacks, common
from bot.wallos_client import WallosClient

__all__ = ["setup"]


def setup(dp: Dispatcher, wallos: WallosClient) -> None:
    """Wire dependencies and routers onto the dispatcher."""
    dp["wallos"] = wallos
    dp.include_router(common.router)
    dp.include_router(callbacks.router)
    dp.include_router(add.router)
