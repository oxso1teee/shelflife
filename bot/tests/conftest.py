"""Shared fixtures.

The handler routers are module-level and aiogram attaches a router to one
Dispatcher only, so the tests share one Dispatcher wired by the real setup().

`tg` drives it like Telegram does, without a network: messages and button
presses go through the real routing, filters and FSM; what the bot sends is
recorded by a stand-in HTTP session; Wallos is a recording stand-in answering
with tests/fixtures/overview.json — a real overview written by the web app
(web/tests/fixtures/make_overview_fixture.php).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot import texts
from bot.handlers import setup
from bot.overview import Overview
from bot.wallos_client import ActionResult, AddResult, LinkResult, Record, SettingsResult

TODAY = date(2026, 10, 14)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "overview.json").read_text())
USER = User(id=555, is_bot=False, first_name="Anna", username="anna_tg")
_ids = count(1000)


def overview(**changes: Any) -> Overview:
    data = json.loads(json.dumps(FIXTURE["overview"]))
    data.update(changes)
    return Overview.from_json(data, FIXTURE["site_url"])


@pytest.fixture(scope="session")
def _dispatcher() -> Dispatcher:
    dp = Dispatcher()
    setup(dp, wallos=None)
    return dp


@pytest.fixture
def dispatcher(_dispatcher: Dispatcher) -> Dispatcher:
    _dispatcher.fsm.storage = MemoryStorage()
    _dispatcher["miniapp_url"] = None
    return _dispatcher


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(texts, "today", lambda: TODAY)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []
        self.edit_error: str | None = (
            None  # Telegram refusing to edit, e.g. "message is not modified"
        )

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, EditMessageText) and self.edit_error:
            raise TelegramBadRequest(method=method, message=self.edit_error)
        if isinstance(method, SendMessage):
            chat = Chat(id=method.chat_id, type="private")
            return Message(message_id=next(_ids), date=datetime.now(), chat=chat, text=method.text)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    async def close(self) -> None:
        pass


class FakeWallos:
    """Answers like the internal API; records every call with its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.linked = True
        self.overview_data: Overview = overview()
        self.act_result: ActionResult | None = None
        self.add_result: AddResult | None = None
        self.settings_result: SettingsResult | None = None
        self.error = False

    def _call(self, method: str, /, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))
        if self.error:
            from bot.wallos_client import WallosError

            raise WallosError("down")

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    async def overview(self, telegram_id: int) -> Overview | None:
        self._call("overview", telegram_id=telegram_id)
        return self.overview_data if self.linked else None

    async def link(self, token, telegram_id, telegram_username):
        self._call("link", token=token)
        return LinkResult("linked", "anna")

    async def add_record(self, **kwargs):
        self._call("add_record", **kwargs)
        if self.add_result is not None:
            return self.add_result
        record = Record(
            id=77, kind=kwargs["kind"], name=kwargs["name"], next_payment=kwargs["next_payment"],
            price=float(kwargs.get("price") or 0), currency=kwargs.get("currency") or "RUB",
            cycle=kwargs.get("cycle") or 3, frequency=kwargs.get("frequency") or 1,
            inactive=False, snoozed_until=None,
        )  # fmt: skip
        return AddResult("created", record)

    async def act(self, **kwargs):
        self._call("act", **kwargs)
        return self.act_result or ActionResult("done", kwargs["action"], None)

    async def settings(self, **kwargs):
        self._call("settings", **kwargs)
        if self.settings_result is not None:
            return self.settings_result
        if kwargs["op"] == "unlink":
            return SettingsResult("unlinked")
        return SettingsResult("saved", kwargs.get("days"))


@dataclass
class Telegram:
    bot: Bot
    dp: Dispatcher
    session: RecordingSession
    wallos: FakeWallos
    last_message: Message | None = field(default=None)

    async def send(self, text: str | None, chat_type: str = "private") -> list[SendMessage]:
        chat = Chat(id=555 if chat_type == "private" else -100123, type=chat_type)
        data: dict[str, Any] = {
            "message_id": next(_ids),
            "date": datetime.now(),
            "chat": chat,
            "from_user": USER,
        }
        if text is None:
            data["sticker"] = {
                "file_id": "x", "file_unique_id": "y", "type": "regular",
                "width": 1, "height": 1, "is_animated": False, "is_video": False,
            }  # fmt: skip
        else:
            data["text"] = text
        return await self._feed(Update(update_id=next(_ids), message=Message(**data)))

    async def press(self, data: str, text: str = "сообщение с кнопками") -> list:
        message = Message(
            message_id=7, date=datetime.now(), chat=Chat(id=555, type="private"), text=text
        )
        query = CallbackQuery(
            id=str(next(_ids)), from_user=USER, chat_instance="c", message=message, data=data
        )
        return await self._feed(Update(update_id=next(_ids), callback_query=query))

    async def _feed(self, update: Update) -> list:
        before = len(self.session.calls)
        await self.dp.feed_update(self.bot, update)
        return self.session.calls[before:]

    @staticmethod
    def texts(calls: list) -> list[str]:
        """What was shown: new messages and edited messages."""
        return [c.text for c in calls if isinstance(c, (SendMessage, EditMessageText))]

    @staticmethod
    def answers(calls: list) -> list[str | None]:
        """Callback answers (the toast)."""
        return [c.text for c in calls if isinstance(c, AnswerCallbackQuery)]

    @staticmethod
    def buttons(calls: list) -> list[tuple[str, str | None]]:
        """(text, callback data or url) of the keyboard of the last shown message."""
        shown = [c for c in calls if isinstance(c, (SendMessage, EditMessageText))]
        if not shown or shown[-1].reply_markup is None:
            return []
        return [
            (b.text, b.callback_data or b.url or (b.web_app.url if b.web_app else None))
            for row in shown[-1].reply_markup.inline_keyboard
            for b in row
        ]


@pytest.fixture
def tg(dispatcher) -> Telegram:
    session = RecordingSession()
    bot = Bot(
        token="123456:" + "A" * 35,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    wallos = FakeWallos()
    dispatcher["wallos"] = wallos
    return Telegram(bot=bot, dp=dispatcher, session=session, wallos=wallos)
