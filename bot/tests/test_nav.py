"""Sections, record cards, their actions and settings through the real Dispatcher
(see conftest.py): what Wallos is asked, what the user sees."""

from __future__ import annotations

import json

import pytest
from aiogram.methods import EditMessageText, SendMessage

from bot import screens, texts
from bot.handlers import callbacks, nav
from bot.wallos_client import ActionResult, SettingsResult
from tests.conftest import FIXTURE, overview


def without(record_id: int):
    """The fixture account after the record was deleted (as the website would list it)."""
    data = json.loads(json.dumps(FIXTURE["overview"]))
    data["records"] = [r for r in data["records"] if r["id"] != record_id]
    for group in data["upcoming"]["groups"]:
        group["records"] = [r for r in group["records"] if r["id"] != record_id]
    data["expenses"]["top"] = [t for t in data["expenses"]["top"] if t["id"] != record_id]
    return overview(**data)


@pytest.mark.parametrize(
    ("command", "title"),
    [
        ("/start", "<b>ShelfLife</b> · Главная"),
        ("/menu", "<b>ShelfLife</b> · Главная"),
        ("/list", "<b>Мои записи</b>"),
        ("/soon", "<b>Скоро</b> · ближайшие 30 дней"),
        ("/spend", "<b>Расходы</b> · подписки"),
        ("/settings", "<b>Настройки</b>"),
    ],
)
async def test_each_command_opens_its_section_as_a_new_message(tg, command, title):
    calls = await tg.send(command)
    sent = [c for c in calls if isinstance(c, SendMessage)]
    assert len(sent) == 1 and sent[0].text.startswith(title)
    assert tg.wallos.calls == [("overview", {"telegram_id": 555})]


@pytest.mark.parametrize("command", ["/list", "/soon", "/spend", "/settings"])
async def test_sections_need_a_linked_account(tg, command):
    tg.wallos.linked = False
    assert tg.texts(await tg.send(command)) == [screens.NOT_LINKED]


async def test_wallos_being_down_is_reported(tg):
    tg.wallos.error = True
    assert tg.texts(await tg.send("/list")) == [texts.UNAVAILABLE]


async def test_section_buttons_edit_the_same_message(tg):
    calls = await tg.press("n:list:exp:0")
    edits = [c for c in calls if isinstance(c, EditMessageText)]
    assert len(edits) == 1 and edits[0].text.startswith("<b>Мои записи · Сроки</b>")
    assert not any(isinstance(c, SendMessage) for c in calls)
    assert tg.answers(calls) == [None]


async def test_a_message_that_cannot_be_edited_is_sent_anew(tg):
    tg.session.edit_error = "message can't be edited"
    calls = await tg.press("n:soon:all:0")
    assert [type(c) for c in calls if isinstance(c, (SendMessage, EditMessageText))] == [
        EditMessageText,
        SendMessage,
    ]


async def test_pressing_the_same_section_again_changes_nothing(tg):
    tg.session.edit_error = "Bad Request: message is not modified"
    calls = await tg.press("n:home:all:0")
    assert not any(isinstance(c, SendMessage) for c in calls)


async def test_wallos_down_on_a_button_is_an_alert(tg):
    tg.wallos.error = True
    calls = await tg.press("n:list:all:0")
    assert tg.answers(calls) == [texts.UNAVAILABLE]
    assert tg.texts(calls) == []


async def test_help_button_and_command(tg):
    assert tg.texts(await tg.press("n:help:all:0")) == [screens.HELP_TEXT]
    assert tg.texts(await tg.send("/help")) == [screens.HELP_TEXT]
    assert tg.wallos.calls == []  # help needs no account


# --- record cards --------------------------------------------------------------


async def test_a_record_opens_as_a_card_with_the_way_back_to_its_page(tg):
    calls = await tg.press("c:1:sub:0")
    assert tg.texts(calls)[0].startswith("🟡 <b>Spotify</b>")
    assert ("‹ К списку", "n:list:sub:0") in tg.buttons(calls)


async def test_a_record_deleted_on_the_website_leads_back_to_the_list(tg):
    tg.wallos.overview_data = without(1)
    calls = await tg.press("c:1:all:0")
    assert tg.answers(calls) == [nav.GONE]
    assert tg.texts(calls)[0].startswith("<b>Мои записи</b>")


async def test_renew_from_a_card_acts_for_the_date_shown_and_redraws_it(tg):
    calls = await tg.press("x:1:20261015:r:all:0")
    assert tg.wallos.calls[0] == (
        "act",
        {
            "telegram_id": 555,
            "update_id": tg.wallos.calls[0][1]["update_id"],
            "subscription_id": 1,
            "action": "renew",
            "expected_due": "2026-10-15",
        },
    )
    assert tg.wallos.names == ["act", "overview"]
    assert tg.answers(calls) == ["✅ Продлено."]  # the stand-in answers without the record
    assert tg.texts(calls)[0].startswith("🟡 <b>Spotify</b>")


@pytest.mark.parametrize(
    ("code", "action"),
    [("c", "cancel"), ("s", "snooze"), ("a", "reactivate")],
)
async def test_card_buttons_map_to_their_actions(tg, code, action):
    await tg.press(f"x:1:20261015:{code}:all:0")
    assert tg.wallos.calls[0][1]["action"] == action


async def test_a_stale_card_says_the_record_changed(tg):
    tg.wallos.act_result = ActionResult("stale", "renew", None)
    calls = await tg.press("x:1:20261015:r:all:0")
    assert tg.answers(calls) == ["Уже обработано: дата записи изменилась."]
    assert tg.texts(calls)[0].startswith("🟡 <b>Spotify</b>")  # redrawn with the current date


async def test_delete_asks_first_and_changes_nothing(tg):
    calls = await tg.press("x:1:20261015:d:all:0")
    assert tg.wallos.names == ["overview"]
    assert tg.texts(calls)[0].startswith("Удалить <b>Spotify</b>?")
    assert ("🗑 Да, удалить", "x:1:20261015:D:all:0") in tg.buttons(calls)


async def test_delete_of_a_record_whose_date_changed_is_refused(tg):
    calls = await tg.press("x:1:20261001:d:all:0")
    assert tg.answers(calls) == ["Запись уже изменилась."]
    assert tg.texts(calls)[0].startswith("🟡 <b>Spotify</b>")


async def test_confirmed_delete_removes_and_returns_to_the_list(tg):
    tg.wallos.overview_data = without(1)
    tg.wallos.act_result = ActionResult("done", "delete", None)
    calls = await tg.press("x:1:20261015:D:all:0")
    assert tg.wallos.calls[0][1]["action"] == "delete"
    assert tg.answers(calls) == ["🗑 Запись удалена."]
    shown = tg.texts(calls)[0]
    assert shown.startswith("<b>Мои записи</b>") and "Spotify" not in shown


async def test_a_malformed_card_button_does_nothing(tg):
    calls = await tg.press("x:1:2026:r:all:0")
    assert tg.wallos.calls == []
    assert tg.answers(calls) == [callbacks.UNKNOWN_BUTTON]


async def test_wallos_down_during_an_action_is_an_alert(tg):
    tg.wallos.error = True
    calls = await tg.press("x:1:20261015:r:all:0")
    assert tg.answers(calls) == [texts.UNAVAILABLE]


# --- settings ------------------------------------------------------------------


async def test_choosing_the_default_reminder_saves_it(tg):
    calls = await tg.press("s:days:3")
    assert tg.wallos.calls[0][1] | {"update_id": 0} == {
        "telegram_id": 555,
        "update_id": 0,
        "op": "reminder_days",
        "days": 3,
    }
    assert tg.answers(calls) == ["Сохранено: напоминать за 3 дня"]
    assert tg.texts(calls)[0].startswith("<b>Настройки</b>")


async def test_same_day_reminder_and_a_refused_value(tg):
    assert tg.answers(await tg.press("s:days:0")) == ["Сохранено: напоминать в день даты"]
    tg.wallos.settings_result = SettingsResult("invalid")
    assert tg.answers(await tg.press("s:days:9")) == ["Такое значение нельзя выбрать."]


async def test_unlinking_asks_then_unlinks(tg):
    calls = await tg.press("s:unlink:0")
    assert tg.wallos.names == ["overview"]
    assert tg.texts(calls)[0].startswith("Отвязать Telegram от аккаунта <b>anna</b>?")

    calls = await tg.press("s:unlink_ok:0")
    assert tg.wallos.calls[-1][0] == "settings" and tg.wallos.calls[-1][1]["op"] == "unlink"
    assert tg.texts(calls) == [screens.UNLINKED]
    assert tg.buttons(calls) == []


# --- leaving an unfinished /add ------------------------------------------------


async def test_a_section_command_ends_an_unfinished_add_but_help_does_not(tg):
    await tg.send("/add")
    await tg.send("/help")
    assert tg.texts(await tg.send("Spotify"))[0].startswith("<b>Новая запись</b> · шаг 2")

    await tg.send("/list")
    calls = await tg.send("Netflix")  # no dialog any more: a hint, not a step
    assert not tg.texts(calls)[0].startswith("<b>Новая запись</b>")
