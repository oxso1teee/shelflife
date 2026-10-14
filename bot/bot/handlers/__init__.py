"""Register every handler router on a Dispatcher."""

from __future__ import annotations

from aiogram import Dispatcher

from bot.db import ReminderDB
from bot.handlers import add, common, manage
from bot.scheduler import ReminderScheduler

__all__ = ["setup"]


def setup(dp: Dispatcher, db: ReminderDB, scheduler: ReminderScheduler) -> None:
    """Wire dependencies and routers onto the dispatcher."""
    dp["db"] = db
    dp["scheduler"] = scheduler
    dp.include_router(common.router)
    dp.include_router(add.router)
    dp.include_router(manage.router)
