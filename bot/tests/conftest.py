"""Shared fixtures.

The handler routers are module-level and aiogram attaches a router to one
Dispatcher only, so the tests share one Dispatcher wired by the real setup().
Each test gets it with a fresh FSM storage; the Wallos stand-in is set per test.
"""

from __future__ import annotations

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import setup


@pytest.fixture(scope="session")
def _dispatcher() -> Dispatcher:
    dp = Dispatcher()
    setup(dp, wallos=None)
    return dp


@pytest.fixture
def dispatcher(_dispatcher: Dispatcher) -> Dispatcher:
    _dispatcher.fsm.storage = MemoryStorage()
    return _dispatcher
