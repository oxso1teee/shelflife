"""The real Dispatcher, fed real Telegram updates: routing, the /add dialog,
private chats only, buttons. No network: the bot's HTTP session records what
would be sent, and Wallos is a recording stand-in."""

from __future__ import annotations

from datetime import datetime
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.handlers import add, callbacks, common, fallback
from bot.wallos_client import Account, ActionResult, AddResult, LinkResult, Record

TOKEN = "0123456789abcdef0123456789abcdef"
RECORD = Record(
    id=5, kind="subscription", name="Spotify", next_payment="2026-11-15", price=500.0,
    currency="RUB", cycle=3, frequency=1, inactive=False, snoozed_until=None,
)  # fmt: skip
USER = User(id=555, is_bot=False, first_name="Anna", username="anna_tg")
_ids = count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            chat = Chat(id=method.chat_id, type="private")
            return Message(message_id=99, date=datetime.now(), chat=chat, text=method.text)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    async def close(self) -> None:
        pass


class FakeWallos:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def link(self, token, telegram_id, telegram_username):
        self.calls.append("link")
        return LinkResult("linked", "anna")

    async def account(self, telegram_id):
        self.calls.append("account")
        return Account(linked=True, username="anna")

    async def add_record(self, **kwargs):
        self.calls.append("add_record")
        return AddResult("created", RECORD)

    async def act(self, **kwargs):
        self.calls.append("act")
        return ActionResult("done", kwargs["action"], RECORD)


@pytest.fixture
def bot_and_dp(dispatcher):
    session = RecordingSession()
    bot = Bot(
        token="123456:" + "A" * 35,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    wallos = FakeWallos()
    dispatcher["wallos"] = wallos
    return bot, dispatcher, session, wallos


def message(chat_type: str, text: str | None) -> Update:
    chat_id = 555 if chat_type == "private" else -100123
    data = {
        "message_id": next(_ids),
        "date": datetime.now(),
        "chat": Chat(id=chat_id, type=chat_type),
        "from_user": USER,
    }
    if text is None:
        data["sticker"] = {
            "file_id": "x", "file_unique_id": "y", "type": "regular",
            "width": 1, "height": 1, "is_animated": False, "is_video": False,
        }  # fmt: skip
    else:
        data["text"] = text
    return Update(update_id=next(_ids), message=Message(**data))


def press(data: str) -> Update:
    reminder = Message(
        message_id=7,
        date=datetime.now(),
        chat=Chat(id=555, type="private"),
        text="🔔 Оплата завтра",
    )
    query = CallbackQuery(
        id=str(next(_ids)), from_user=USER, chat_instance="c", message=reminder, data=data
    )
    return Update(update_id=next(_ids), callback_query=query)


async def replies(bot_and_dp, update) -> list[str]:
    bot, dp, session, _ = bot_and_dp
    before = len(session.calls)
    await dp.feed_update(bot, update)
    return [call.text for call in session.calls[before:] if isinstance(call, SendMessage)]


async def test_every_command_is_routed_in_a_private_chat(bot_and_dp):
    _, _, _, wallos = bot_and_dp

    assert await replies(bot_and_dp, message("private", "/start")) == [
        common.already_linked_text("anna")
    ]
    assert await replies(bot_and_dp, message("private", f"/start {TOKEN}")) == [
        common.linked_text("anna")
    ]
    assert await replies(bot_and_dp, message("private", "/help")) == [common.HELP_TEXT]
    added = await replies(bot_and_dp, message("private", "/add Spotify 15.11 500rub"))
    assert added[0].startswith("✅ Запись добавлена")
    assert (await replies(bot_and_dp, message("private", "/add Spotify 31.02 500")))[0].startswith(
        "⚠️ Такой даты нет"
    )
    assert await replies(bot_and_dp, message("private", "/foo")) == [fallback.UNKNOWN_COMMAND]
    assert await replies(bot_and_dp, message("private", "привет")) == [fallback.HINT]
    assert await replies(bot_and_dp, message("private", None)) == [fallback.HINT]
    assert wallos.calls == ["account", "link", "add_record"]


async def test_add_without_arguments_waits_for_the_line_and_cancel_leaves(bot_and_dp):
    _, _, _, wallos = bot_and_dp

    assert await replies(bot_and_dp, message("private", "/add")) == [add.ASK_LINE]
    assert (await replies(bot_and_dp, message("private", "Spotify 15.11 500rub")))[0].startswith(
        "✅ Запись добавлена"
    ), "the next message is the line"
    assert await replies(bot_and_dp, message("private", "Spotify 15.11 500rub")) == [
        fallback.HINT
    ], "the dialog is over"
    await replies(bot_and_dp, message("private", "/add"))
    assert await replies(bot_and_dp, message("private", "/cancel")) == ["Ввод отменён."]
    assert await replies(bot_and_dp, message("private", "/cancel")) == [
        "Сейчас нечего отменять. Добавить запись — /add"
    ]
    assert wallos.calls == ["add_record"]


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
@pytest.mark.parametrize(
    "text",
    [
        "/start",
        f"/start {TOKEN}",
        "/help",
        "/add Spotify 15.11 500rub",
        "/add",
        "/cancel",
        "/foo",
        "привет",
        None,
    ],
)
async def test_the_bot_stays_quiet_in_groups(bot_and_dp, chat_type, text):
    bot, dp, session, wallos = bot_and_dp

    await dp.feed_update(bot, message(chat_type, text))

    assert session.calls == [], "nothing is sent to the group"
    assert wallos.calls == [], "and Wallos is not asked: no account or record leaks"


async def test_reminder_buttons_act_and_report(bot_and_dp):
    bot, dp, session, wallos = bot_and_dp

    await dp.feed_update(bot, press("a:5:20261115:r"))

    answers = [c.text for c in session.calls if isinstance(c, AnswerCallbackQuery)]
    edits = [c.text for c in session.calls if isinstance(c, EditMessageText)]
    assert wallos.calls == ["act"]
    assert answers == ["✅ Продлено. Следующая дата — 15.11.2026."]
    assert edits == ["🔔 Оплата завтра\n\n<i>✅ Продлено. Следующая дата — 15.11.2026.</i>"]


@pytest.mark.parametrize("data", ["a:x:1:r", "old_prefix:1", "a:5:2026-11-15:r", ""])
async def test_an_unknown_or_old_button_is_answered_and_changes_nothing(bot_and_dp, data):
    bot, dp, session, wallos = bot_and_dp

    await dp.feed_update(bot, press(data))

    answers = [c.text for c in session.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers == [callbacks.UNKNOWN_BUTTON]
    assert wallos.calls == []
    assert not any(isinstance(c, EditMessageText) for c in session.calls)
