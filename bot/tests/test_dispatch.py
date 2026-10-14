"""The real Dispatcher, fed real Telegram updates (see conftest.py): routing,
private chats only, reminder buttons, unknown and old buttons."""

from __future__ import annotations

import pytest

from bot import screens
from bot.handlers import callbacks, fallback

TOKEN = "0123456789abcdef0123456789abcdef"


async def test_start_opens_the_home_screen(tg):
    shown = tg.texts(await tg.send("/start"))
    assert shown[0].startswith("<b>ShelfLife</b> · Главная\n\nЗдравствуйте, Анна!")
    assert tg.wallos.names == ["overview"]


async def test_start_for_a_stranger_explains_linking(tg):
    tg.wallos.linked = False
    assert tg.texts(await tg.send("/start")) == [screens.NOT_LINKED]


async def test_the_link_from_the_website_links_and_leads_home(tg):
    calls = await tg.send(f"/start {TOKEN}")
    assert tg.texts(calls)[0].startswith("✅ Аккаунт <b>anna</b> привязан.")
    assert tg.buttons(calls) == [("🏠 Открыть главную", "n:home:all:0")]


async def test_unknown_commands_text_and_stickers_get_a_hint(tg):
    assert tg.texts(await tg.send("/foo")) == [fallback.UNKNOWN_COMMAND]
    assert tg.texts(await tg.send("привет")) == [fallback.HINT]
    assert tg.texts(await tg.send(None)) == [fallback.HINT]
    assert tg.wallos.calls == []


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
@pytest.mark.parametrize(
    "text",
    [
        "/start",
        f"/start {TOKEN}",
        "/help",
        "/list",
        "/spend",
        "/add Spotify 15.11 500rub",
        "/add",
        "/cancel",
        "/foo",
        "привет",
        None,
    ],
)
async def test_the_bot_stays_quiet_in_groups(tg, chat_type, text):
    calls = await tg.send(text, chat_type)
    assert calls == [], "nothing is sent to the group"
    assert tg.wallos.calls == [], "and Wallos is not asked: no account or record leaks"


async def test_reminder_buttons_act_and_report(tg):
    from bot.wallos_client import ActionResult, Record

    tg.wallos.act_result = ActionResult(
        "done", "renew",
        Record(5, "subscription", "Spotify", "2026-12-15", 500.0, "RUB", 3, 1, False, None),
    )  # fmt: skip
    calls = await tg.press("a:5:20261115:r", text="🔔 Оплата завтра")

    assert tg.wallos.calls == [
        ("act", {"telegram_id": 555, "update_id": tg.wallos.calls[0][1]["update_id"], "subscription_id": 5,
                 "action": "renew", "expected_due": "2026-11-15"})
    ]  # fmt: skip
    assert tg.answers(calls) == ["✅ Продлено. Следующая дата — 15.12.2026."]
    assert tg.texts(calls) == [
        "🔔 Оплата завтра\n\n<i>✅ Продлено. Следующая дата — 15.12.2026.</i>"
    ]


@pytest.mark.parametrize("data", ["a:x:1:r", "old_prefix:1", "a:5:2026-11-15:r", ""])
async def test_an_unknown_or_old_button_is_answered_and_changes_nothing(tg, data):
    calls = await tg.press(data)
    assert tg.answers(calls) == [callbacks.UNKNOWN_BUTTON]
    assert tg.wallos.calls == []
    assert tg.texts(calls) == []
