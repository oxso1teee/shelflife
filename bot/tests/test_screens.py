"""Every screen as it is shown, drawn from a real overview (tests/fixtures/overview.json).

The fixture account (today 14.10.2026): RUB main currency, reminders 2 days
ahead by default, 7 active records and one cancelled, subscriptions in RUB and
USD with no exchange rates loaded on the site.
"""

from __future__ import annotations

import json
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from bot import screens
from bot.screens import Screen
from tests.conftest import FIXTURE, overview

APP = "https://shelflife.example.com/tma/index.php"
TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre"}


class _TelegramHTML(HTMLParser):
    """Telegram's HTML parse mode: a few tags, properly nested; text escaped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.open: list[str] = []

    def handle_starttag(self, tag, attrs):
        assert tag in TELEGRAM_TAGS, f"<{tag}> is not allowed by Telegram"
        self.open.append(tag)

    def handle_endtag(self, tag):
        assert self.open and self.open.pop() == tag, f"</{tag}> closes nothing"

    def handle_entityref(self, name):
        assert name in {"lt", "gt", "amp", "quot"}, f"&{name}; is not allowed by Telegram"


def check(screen: Screen) -> Screen:
    """What Telegram would refuse: bad HTML, callback data over 64 bytes, empty keyboards."""
    parser = _TelegramHTML()
    parser.feed(plain(screen))
    parser.close()
    assert parser.open == [], f"unclosed {parser.open}"
    assert len(plain(screen)) <= 4096
    assert screen.markup.inline_keyboard and all(screen.markup.inline_keyboard)
    for row in screen.markup.inline_keyboard:
        for button in row:
            assert button.text
            if button.callback_data is not None:
                assert len(button.callback_data.encode()) <= 64
            else:
                assert (button.url or button.web_app.url).startswith("https://")
    return screen


def plain(screen: Screen) -> str:
    """The text with the non-breaking spaces of amounts ("500 ₽") as plain spaces."""
    return screen.text.replace("\xa0", " ")


def buttons(screen: Screen) -> list[tuple[str, str]]:
    return [
        (b.text, b.callback_data or b.url or b.web_app.url)
        for row in screen.markup.inline_keyboard
        for b in row
    ]


def has_app_button(screen: Screen) -> bool:
    return any(b.web_app for row in screen.markup.inline_keyboard for b in row)


def empty_overview():
    return overview(
        records=[],
        summary={"active": 0, "inactive": 0, "overdue": 0, "today": 0, "week": 0, "nearest": None},
        upcoming={"groups": [], "later": 0},
        expenses={
            "per_currency": [], "total": None, "convertible": True, "top": [],
            "by_category": [], "category_scope": "all", "due_30_days": [],
        },
    )  # fmt: skip


def overview_with_rates():
    expenses = json.loads(json.dumps(FIXTURE["overview"]["expenses"]))
    rub = expenses["per_currency"][0]["currency"]
    expenses.update(
        total={"currency": rub, "monthly": 31007.3, "rates_date": "2026-10-13"},
        convertible=True,
        category_scope="all",
    )
    return overview(expenses=expenses)


def every_screen(ov, app):
    yield screens.not_linked()
    yield screens.home(ov, app)
    for flt in ("all", "sub", "exp", "mnt", "off"):
        yield screens.records(ov, flt, 0)
    yield screens.records(ov, "all", 1)
    for item in ov.items:
        yield screens.card(ov, item, app)
        yield screens.delete_confirm(item)
    yield screens.soon(ov)
    yield screens.spend(ov)
    yield screens.settings(ov, "anna_tg", app)
    yield screens.unlink_confirm(ov)
    yield screens.help_screen(app)


@pytest.mark.parametrize("app", [None, APP])
@pytest.mark.parametrize("make", [overview, empty_overview, overview_with_rates])
def test_every_screen_is_valid_for_telegram(make, app):
    for screen in every_screen(make(), app):
        check(screen)


@pytest.mark.parametrize("make", [overview, empty_overview])
def test_the_app_button_appears_only_when_a_mini_app_is_configured(make):
    ov = make()
    assert not any(has_app_button(s) for s in every_screen(ov, None))
    assert has_app_button(screens.home(ov, APP))
    assert has_app_button(screens.help_screen(APP))
    assert has_app_button(screens.settings(ov, None, APP))


# --- home ----------------------------------------------------------------------


def test_home_sums_up_the_account():
    screen = screens.home(overview(), None)
    assert plain(screen) == (
        "<b>ShelfLife</b> · Главная\n\n"
        "Здравствуйте, Анна!\n\n"
        "Активных записей: <b>7</b>\n"
        "🔴 просрочено: 1 · 🟡 на этой неделе: 3\n"
        "Ближайшее: <b>Молоко</b>, 14.10.2026 — сегодня\n\n"
        "Подписки в месяц: <b>30 930,65 ₽ и 0,83 $</b>"
    )
    assert buttons(screen) == [
        ("📋 Мои записи", "n:list:all:0"),
        ("📅 Скоро", "n:soon:all:0"),
        ("➕ Добавить", "n:add:all:0"),
        ("💳 Расходы", "n:spend:all:0"),
        ("⚙️ Настройки", "n:set:all:0"),
        ("❓ Помощь", "n:help:all:0"),
    ]


def test_home_with_rates_shows_one_converted_total():
    assert "Подписки в месяц: <b>≈ 31 007,30 ₽</b>" in plain(
        screens.home(overview_with_rates(), None)
    )


def test_home_without_records_invites_to_add_the_first_one():
    screen = screens.home(empty_overview(), None)
    assert "Пока здесь пусто." in plain(screen)
    assert "Активных записей" not in plain(screen)
    assert buttons(screen) == [
        ("➕ Добавить первую запись", "n:add:all:0"),
        ("❓ Помощь", "n:help:all:0"),
    ]


def test_the_greeting_falls_back_to_the_username_and_is_escaped():
    account = dict(FIXTURE["overview"]["account"], first_name="", username="<anna>")
    assert "Здравствуйте, &lt;anna&gt;!" in plain(screens.home(overview(account=account), None))


# --- records -------------------------------------------------------------------


def test_the_list_shows_six_records_a_page_with_their_state():
    screen = screens.records(overview())
    lines = plain(screen).split("\n")
    assert lines[:2] == ["<b>Мои записи</b>", "7 записей · страница 1 из 2"]
    assert lines[3] == "1. 🔴 <b>Витамины</b> · 12.10.2026 — 2 дня назад"
    assert lines[5] == "3. 🟡 <b>Spotify</b> · 15.10.2026 — завтра · 500 ₽"
    assert lines[8] == "6. 🟢 <b>Netflix</b> · 23.11.2026 — через 40 дней · 9,99 $"
    shown = buttons(screen)
    assert shown[:2] == [("1. Витамины", "c:4:all:0"), ("2. Молоко", "c:5:all:0")]
    assert ("1 / 2", "n:list:all:0") in shown and ("Дальше ›", "n:list:all:1") in shown
    assert ("✓ Все", "n:list:all:0") in shown
    assert shown[-2:] == [("➕ Добавить", "n:add:all:0"), ("🏠 Главная", "n:home:all:0")]


def test_the_second_page_continues_the_numbering_and_escapes_names():
    screen = screens.records(overview(), "all", 1)
    assert "7. 🟢 <b>Tom &amp; &lt;Jerry&gt; — очень длинное название…</b>" in plain(screen)
    shown = buttons(screen)
    assert shown[0] == ("7. Tom & <Jerry> — очень…", "c:8:all:1")
    assert ("‹ Назад", "n:list:all:0") in shown
    assert not any(text == "Дальше ›" for text, _ in shown)


def test_a_page_past_the_end_shows_the_last_page():
    assert "страница 2 из 2" in plain(screens.records(overview(), "all", 9))


@pytest.mark.parametrize(
    ("flt", "names"),
    [
        ("sub", ["Spotify", "Аренда", "Netflix", "Tom & <Jerry> — очень…"]),
        ("exp", ["Витамины", "Молоко"]),
        ("mnt", ["Фильтр для воды"]),
        ("off", ["Старая подписка"]),
    ],
)
def test_filters_show_their_records(flt, names):
    shown = [
        text.split(". ", 1)[1]
        for text, data in buttons(screens.records(overview(), flt))
        if data.startswith("c:")
    ]
    assert shown == names


def test_an_unknown_filter_is_all():
    assert plain(screens.records(overview(), "zzz")) == plain(screens.records(overview()))


def test_empty_lists_say_so():
    assert "Здесь пока ничего нет." in plain(screens.records(empty_overview()))
    assert "Отменённых записей нет" in plain(screens.records(empty_overview(), "off"))


# --- a record ------------------------------------------------------------------


def test_a_card_due_soon_offers_renew_snooze_cancel_and_delete():
    ov = overview()
    screen = screens.card(ov, ov.item(1), None)
    assert plain(screen) == (
        "🟡 <b>Spotify</b>\n"
        "Подписка · каждый месяц · Музыка\n"
        "Дата: 15.10.2026 — завтра\n"
        "Сумма: 500 ₽\n"
        "Напоминания: за 2 дня до даты (по умолчанию)\n"
        "Статус: активна\n\n"
        "<i>Изменить название, дату или сумму можно на сайте.</i>"
    )
    assert buttons(screen) == [
        ("✅ Продлить на месяц", "x:1:20261015:r:all:0"),
        ("⏰ Напомнить завтра", "x:1:20261015:s:all:0"),
        ("❌ Отменить", "x:1:20261015:c:all:0"),
        ("🗑 Удалить", "x:1:20261015:d:all:0"),
        ("‹ К списку", "n:list:all:0"),
        ("🏠 Главная", "n:home:all:0"),
    ]


def test_a_card_far_from_its_date_has_no_snooze_and_shows_the_monthly_cost():
    ov = overview()
    screen = screens.card(ov, ov.item(2), APP, "sub", 0)
    assert "Сумма: 9,99 $ · ≈ 0,83 $ в месяц" in plain(screen)
    assert "можно на сайте" not in plain(screen)  # the app can edit it
    assert buttons(screen) == [
        ("✅ Продлить на год", "x:2:20261123:r:sub:0"),
        ("❌ Отменить", "x:2:20261123:c:sub:0"),
        ("🗑 Удалить", "x:2:20261123:d:sub:0"),
        ("✏️ Изменить в приложении", APP + "?edit=2"),
        ("‹ К списку", "n:list:sub:0"),
        ("🏠 Главная", "n:home:all:0"),
    ]


def test_a_cancelled_record_can_be_brought_back_or_deleted():
    ov = overview()
    screen = screens.card(ov, ov.item(7), None)
    assert "Напоминания: не приходят — запись отменена" in plain(screen)
    assert "Статус: отменена" in plain(screen)
    assert [data for _, data in buttons(screen)][:2] == [
        "x:7:20260901:a:all:0",
        "x:7:20260901:d:all:0",
    ]


def test_a_card_shows_its_own_reminder_setting_and_a_snooze():
    data = json.loads(json.dumps(FIXTURE["overview"]["records"]))
    for record in data:
        if record["id"] == 4:
            record["snoozed_until"] = "2026-10-15"
        if record["id"] == 5:
            record["notify"] = False
    ov = overview(records=data)
    assert "Напоминания: за 3 дня до даты; отложено до 15.10.2026" in plain(
        screens.card(ov, ov.item(4), None)
    )
    milk = screens.card(ov, ov.item(5), None)
    assert "Напоминания: выключены (включить можно на сайте)" in plain(milk)
    assert not any(text == "⏰ Напомнить завтра" for text, _ in buttons(milk))


def test_a_one_time_record_moves_by_a_month_as_the_reminder_button_does():
    ov = overview()
    assert buttons(screens.card(ov, ov.item(4), None))[0] == (
        "✅ Продлить на месяц",
        "x:4:20261012:r:all:0",
    )


def test_deleting_asks_first():
    ov = overview()
    screen = screens.delete_confirm(ov.item(1))
    assert plain(screen).startswith("Удалить <b>Spotify</b>?")
    assert "нельзя отменить" in plain(screen) and "«Отменить» в карточке" in plain(screen)
    assert buttons(screen) == [
        ("🗑 Да, удалить", "x:1:20261015:D:all:0"),
        ("‹ Не удалять", "c:1:all:0"),
    ]
    assert "«Отменить» в карточке" not in plain(screens.delete_confirm(ov.item(7)))


# --- soon ----------------------------------------------------------------------


def test_soon_groups_the_next_30_days():
    screen = screens.soon(overview())
    assert plain(screen) == (
        "<b>Скоро</b> · ближайшие 30 дней\n\n"
        "<b>Просрочено</b>\n🔴 <b>Витамины</b> · 12.10.2026 — 2 дня назад\n\n"
        "<b>Сегодня</b>\n🟡 <b>Молоко</b> · 14.10.2026 — сегодня\n\n"
        "<b>Завтра</b>\n🟡 <b>Spotify</b> · 15.10.2026 — завтра · 500 ₽\n\n"
        "<b>На этой неделе</b>\n🟡 <b>Аренда</b> · 19.10.2026 — через 5 дней · 30 000 ₽\n\n"
        "<b>В ближайший месяц</b>\n🟢 <b>Фильтр для воды</b> · 03.11.2026 — через 20 дней · 1 500 ₽\n\n"
        "Позже: ещё 2 записи."
    )
    assert buttons(screen)[:5] == [
        ("Витамины", "c:4:all:0"),
        ("Молоко", "c:5:all:0"),
        ("Spotify", "c:1:all:0"),
        ("Аренда", "c:3:all:0"),
        ("Фильтр для воды", "c:6:all:0"),
    ]


def test_soon_with_nothing_ahead():
    assert "ничего не запланировано" in plain(screens.soon(empty_overview()))


# --- spending ------------------------------------------------------------------


def test_spending_in_different_currencies_is_not_added_up_without_rates():
    text = plain(screens.spend(overview()))
    assert "30 930,65 ₽ — 3 подписки\n0,83 $ — 1 подписка" in text
    assert "Суммы в разных валютах не складываются: на сайте не загружены курсы валют." in text
    assert "Итого" not in text
    assert "В год ≈ 371 167,80 ₽ + 9,99 $" in text
    assert "1. Аренда — 30 000 ₽ в месяц" in text and "4. Netflix — 0,83 $ в месяц" in text
    # Categories cover only what is in the main currency, and say so.
    assert "<b>По категориям (только RUB)</b>\nДом — 30 000 ₽ · 97%" in text
    assert "Без категории — 430,65 ₽ · 1%" in text
    assert "<b>К оплате за 30 дней</b>\n2 платежа — 30 500 ₽" in text


def test_spending_with_rates_gives_a_converted_total_and_its_date():
    text = plain(screens.spend(overview_with_rates()))
    assert "Итого ≈ <b>31 007,30 ₽</b> по курсам на 13.10.2026" in text
    assert "не складываются" not in text
    assert "<b>По категориям</b>" in text


def test_spending_without_subscriptions_explains_what_will_be_there():
    screen = screens.spend(empty_overview())
    assert "Активных подписок с суммой пока нет." in plain(screen)
    assert buttons(screen) == [("➕ Добавить", "n:add:all:0"), ("🏠 Главная", "n:home:all:0")]


# --- settings ------------------------------------------------------------------


def test_settings_mark_the_current_reminder_default():
    screen = screens.settings(overview(), "anna_tg", None)
    assert "Аккаунт: <b>anna</b>\nTelegram: привязан (@anna_tg)" in plain(screen)
    assert "Напоминать по умолчанию: <b>за 2 дня до даты</b>" in plain(screen)
    shown = buttons(screen)
    assert shown[:8] == [
        ("в день", "s:days:0"),
        ("1 дн.", "s:days:1"),
        ("✓ 2 дн.", "s:days:2"),
        ("3 дн.", "s:days:3"),
        ("4 дн.", "s:days:4"),
        ("5 дн.", "s:days:5"),
        ("6 дн.", "s:days:6"),
        ("7 дн.", "s:days:7"),
    ]
    assert shown[8:] == [
        ("🌐 Сайт", "https://shelflife.example.com"),
        ("🔗 Отвязать Telegram", "s:unlink:0"),
        ("🏠 Главная", "n:home:all:0"),
    ]


def test_settings_without_a_public_site_have_no_site_button():
    screen = screens.settings(replace(overview(), site_url=None), None, None)
    assert "Telegram: привязан (этот чат)" in plain(screen)
    assert not any(text == "🌐 Сайт" for text, _ in buttons(screen))


def test_unlinking_asks_first():
    screen = screens.unlink_confirm(overview())
    assert "Сами записи останутся на сайте." in plain(screen)
    assert buttons(screen) == [
        ("🔗 Да, отвязать", "s:unlink_ok:0"),
        ("‹ Не отвязывать", "n:set:all:0"),
    ]


def test_the_edit_link_keeps_a_query_the_address_already_has():
    ov = overview()
    screen = screens.card(ov, ov.item(2), "https://x.example/app?lang=ru")
    assert ("✏️ Изменить в приложении", "https://x.example/app?lang=ru&edit=2") in buttons(screen)


def test_help_names_every_section():
    text = plain(screens.help_screen(None))
    for command in ("/start", "/list", "/soon", "/spend", "/settings", "/add", "/cancel"):
        assert command in text
