"""The bot's screens: the account's overview turned into a message and its buttons.

Pure functions — no network — so every screen is tested as it is shown. The
navigation lives in one message that is edited from screen to screen (home,
records, a record, soon, spending, settings, help); every screen has a way back.
A button opening the Mini App is shown only when SHELFLIFE_MINIAPP_URL is an
https address: without it there is no app to open.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot import texts
from bot.keyboards import (
    FILTERS,
    PAGE_SIZE,
    CardActionCB,
    CardCB,
    NavCB,
    SettingsCB,
    due_to_callback,
    paginate,
)
from bot.overview import Item, Money, Overview

GROUP_TITLES = {
    "overdue": "Просрочено",
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "week": "На этой неделе",
    "month": "В ближайший месяц",
}
KIND_PLURAL = {
    "subscription": "подписки",
    "expiry": "сроки годности",
    "maintenance": "обслуживание",
}
FILTER_KINDS = {"sub": "subscription", "exp": "expiry", "mnt": "maintenance"}


@dataclass(frozen=True, slots=True)
class Screen:
    text: str
    markup: InlineKeyboardMarkup


def _button(text: str, data) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def _home_button() -> InlineKeyboardButton:
    return _button("🏠 Главная", NavCB(to="home"))


def _app_button(
    miniapp_url: str | None, text: str = "📱 Открыть приложение", query: str = ""
) -> list:
    """A button opening the Mini App; `query` ("edit=5") picks its first screen."""
    if not miniapp_url:
        return []
    url = miniapp_url + (("&" if "?" in miniapp_url else "?") + query if query else "")
    return [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]


def _name(item: Item, limit: int = texts.NAME_MAX) -> str:
    return html.escape(texts.shorten(item.name, limit))


def _sum(money: Money) -> str:
    symbol = money.currency.symbol or money.currency.code if money.currency else ""
    return texts.amount_with(money.amount, symbol)


def _price(item: Item) -> str:
    symbol = (item.currency.symbol or item.currency.code) if item.currency else ""
    return texts.amount_with(item.price, symbol)


def _when(item: Item) -> str:
    if item.next_payment is None:
        return "без даты"
    date_text = texts.format_date(item.next_payment)
    if item.inactive or item.days_left is None:
        return date_text
    return f"{date_text} — {texts.relative_days(item.days_left)}"


def _details(item: Item) -> str:
    parts = [texts.KIND_NAMES.get(item.kind, item.kind)]
    every = texts.period(item.cycle, item.frequency)
    if every is not None:
        parts.append(every)
    elif item.kind == "subscription":
        parts.append("разово")
    if item.category:
        parts.append(html.escape(texts.shorten(item.category, 40)))
    return " · ".join(parts)


def _line(item: Item) -> str:
    """One record in a list: status, name, date, amount."""
    mark = texts.STATUS_MARKS.get(item.status, "")
    line = f"{mark} <b>{_name(item, 40)}</b> · {_when(item)}"
    if item.price > 0:
        line += f" · {_price(item)}"
    return line


def _monthly_text(expenses) -> str | None:
    if expenses.total is not None and len(expenses.per_currency) > 1:
        return f"≈ {_sum(expenses.total)}"
    if expenses.per_currency:
        return " и ".join(_sum(m) for m in expenses.per_currency)
    return None


# --- not linked --------------------------------------------------------------

NOT_LINKED = (
    "👋 Привет! Я бот <b>ShelfLife</b>.\n\n"
    "Слежу за сроками: платежами по подпискам, сроками годности и обслуживанием "
    "техники. Заранее напоминаю, а под напоминанием — кнопки: продлить, отменить, "
    "напомнить позже.\n\n"
    "<b>Чтобы начать, привяжите аккаунт сайта:</b>\n"
    "1. Войдите на сайт ShelfLife.\n"
    "2. Откройте <b>Профиль → Telegram-бот</b>.\n"
    "3. Нажмите «Привязать Telegram» и перейдите по ссылке.\n\n"
    "Ваши записи появятся здесь сразу после привязки. Подробнее — /help"
)


def not_linked() -> Screen:
    return Screen(
        NOT_LINKED,
        InlineKeyboardMarkup(inline_keyboard=[[_button("❓ Как это работает", NavCB(to="help"))]]),
    )


# --- home ----------------------------------------------------------------------


def home(ov: Overview, miniapp_url: str | None) -> Screen:
    name = html.escape(ov.first_name or ov.username)
    lines = [f"<b>ShelfLife</b> · Главная\n\nЗдравствуйте, {name}!"]
    summary = ov.summary

    if not ov.items:
        lines.append(
            "\nПока здесь пусто. Добавьте первую запись: подписку, срок годности продукта "
            "или дату обслуживания — и ShelfLife напомнит о ней заранее."
        )
        keyboard = [[_button("➕ Добавить первую запись", NavCB(to="add"))]]
        keyboard += [_app_button(miniapp_url)] if miniapp_url else []
        keyboard.append([_button("❓ Помощь", NavCB(to="help"))])
        return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))

    facts = [f"Активных записей: <b>{summary['active']}</b>"]
    week = []
    if summary.get("overdue"):
        week.append(f"🔴 просрочено: {summary['overdue']}")
    if summary.get("week"):
        week.append(f"🟡 на этой неделе: {summary['week']}")
    if week:
        facts.append(" · ".join(week))
    nearest = summary.get("nearest")
    if nearest:
        item = ov.item(int(nearest["id"]))
        if item is not None:
            facts.append(f"Ближайшее: <b>{_name(item, 40)}</b>, {_when(item)}")
    lines.append("\n" + "\n".join(facts))

    monthly = _monthly_text(ov.expenses)
    if monthly:
        lines.append(f"\nПодписки в месяц: <b>{monthly}</b>")

    keyboard = [
        [_button("📋 Мои записи", NavCB(to="list")), _button("📅 Скоро", NavCB(to="soon"))],
        [_button("➕ Добавить", NavCB(to="add")), _button("💳 Расходы", NavCB(to="spend"))],
        [_button("⚙️ Настройки", NavCB(to="set")), _button("❓ Помощь", NavCB(to="help"))],
    ]
    if miniapp_url:
        keyboard.append(_app_button(miniapp_url))
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


# --- records -----------------------------------------------------------------


def filtered(ov: Overview, flt: str) -> list[Item]:
    if flt == "off":
        return [i for i in ov.items if i.inactive]
    kind = FILTER_KINDS.get(flt)
    return [i for i in ov.items if not i.inactive and (kind is None or i.kind == kind)]


def records(ov: Overview, flt: str = "all", page: int = 0) -> Screen:
    flt = flt if flt in FILTERS else "all"
    items = filtered(ov, flt)
    shown, pages = paginate(items, page)
    page = max(0, min(page, pages - 1))

    title = "Мои записи" if flt == "all" else f"Мои записи · {FILTERS[flt]}"
    lines = [f"<b>{title}</b>"]
    if not items:
        lines.append(
            "\nЗдесь пока ничего нет."
            if flt != "off"
            else "\nОтменённых записей нет: всё, что вы отслеживаете, активно."
        )
    else:
        count = texts.plural(len(items), "запись", "записи", "записей")
        lines.append(
            f"{len(items)} {count}" + (f" · страница {page + 1} из {pages}" if pages > 1 else "")
        )
        lines.append("")
        lines += [f"{n}. {_line(item)}" for n, item in enumerate(shown, start=page * PAGE_SIZE + 1)]
        lines.append("\nОткройте запись, чтобы продлить, отменить или удалить её.")

    keyboard = []
    row = []
    for n, item in enumerate(shown, start=page * PAGE_SIZE + 1):
        row.append(
            _button(f"{n}. {texts.shorten(item.name, 22)}", CardCB(id=item.id, flt=flt, page=page))
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(_button("‹ Назад", NavCB(to="list", flt=flt, page=page - 1)))
        nav.append(_button(f"{page + 1} / {pages}", NavCB(to="list", flt=flt, page=page)))
        if page < pages - 1:
            nav.append(_button("Дальше ›", NavCB(to="list", flt=flt, page=page + 1)))
        keyboard.append(nav)
    filters = [
        _button(("✓ " if code == flt else "") + title, NavCB(to="list", flt=code))
        for code, title in FILTERS.items()
    ]
    keyboard += [filters[:3], filters[3:]]
    keyboard.append([_button("➕ Добавить", NavCB(to="add")), _home_button()])
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


def _reminder_text(item: Item, ov: Overview) -> str:
    if item.inactive:
        return "не приходят — запись отменена"
    if not item.notify:
        return "выключены (включить можно на сайте)"
    days = item.notify_days_before
    if days is None or days < 0:
        days = ov.reminder_days
        suffix = " (по умолчанию)"
    else:
        suffix = ""
    when = "в день даты" if days == 0 else f"за {texts.days(days)} до даты"
    text = when + suffix
    if item.snoozed_until:
        text += f"; отложено до {texts.format_date(item.snoozed_until)}"
    return text


def card(
    ov: Overview, item: Item, miniapp_url: str | None, flt: str = "all", page: int = 0
) -> Screen:
    mark = texts.STATUS_MARKS.get(item.status, "")
    lines = [f"{mark} <b>{_name(item)}</b>", _details(item), f"Дата: {_when(item)}"]
    if item.price > 0:
        amount = _price(item)
        if item.monthly is not None and not (item.cycle == 3 and item.frequency == 1):
            symbol = (item.currency.symbol or item.currency.code) if item.currency else ""
            amount += f" · ≈ {texts.amount_with(item.monthly, symbol)} в месяц"
        lines.append(f"Сумма: {amount}")
    lines.append(f"Напоминания: {_reminder_text(item, ov)}")
    lines.append("Статус: " + ("отменена" if item.inactive else "активна"))

    due = due_to_callback(item.next_payment)

    def act(text: str, code: str) -> InlineKeyboardButton:
        return _button(text, CardActionCB(id=item.id, due=due, act=code, flt=flt, page=page))

    keyboard = []
    if item.next_payment is not None:
        if item.inactive:
            keyboard.append([act("↩️ Вернуть в работу", "a")])
        else:
            row = [act(f"✅ Продлить на {texts.renew_period(item.cycle, item.frequency)}", "r")]
            if item.days_left is not None and item.days_left <= 7 and item.notify:
                row.append(act("⏰ Напомнить завтра", "s"))
            keyboard.append(row)
            keyboard.append([act("❌ Отменить", "c")])
        keyboard[-1].append(act("🗑 Удалить", "d"))
    if miniapp_url:
        keyboard.append(_app_button(miniapp_url, "✏️ Изменить в приложении", f"edit={item.id}"))
    keyboard.append([_button("‹ К списку", NavCB(to="list", flt=flt, page=page)), _home_button()])

    if not miniapp_url:
        lines.append("\n<i>Изменить название, дату или сумму можно на сайте.</i>")
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


def delete_confirm(item: Item, flt: str = "all", page: int = 0) -> Screen:
    due = due_to_callback(item.next_payment)
    text = (
        f"Удалить <b>{_name(item)}</b>?\n\n"
        "Запись исчезнет и на сайте, напоминаний по ней больше не будет. "
        "Это действие нельзя отменить."
    )
    if not item.inactive:
        text += (
            "\n\nЕсли нужно только перестать получать напоминания — нажмите «Отменить» в карточке."
        )
    keyboard = [
        [_button("🗑 Да, удалить", CardActionCB(id=item.id, due=due, act="D", flt=flt, page=page))],
        [_button("‹ Не удалять", CardCB(id=item.id, flt=flt, page=page))],
    ]
    return Screen(text, InlineKeyboardMarkup(inline_keyboard=keyboard))


# --- soon --------------------------------------------------------------------


def soon(ov: Overview) -> Screen:
    lines = ["<b>Скоро</b> · ближайшие 30 дней"]
    buttons = []
    if not ov.upcoming:
        lines.append("\nВ ближайшие 30 дней ничего не запланировано.")
    for key, items in ov.upcoming:
        lines.append(f"\n<b>{GROUP_TITLES.get(key, key)}</b>")
        for item in items:
            lines.append(_line(item))
            buttons.append(item)
    if ov.later:
        later = texts.plural(ov.later, "запись", "записи", "записей")
        lines.append(f"\nПозже: ещё {ov.later} {later}.")

    keyboard = []
    row = []
    for item in buttons[:8]:
        row.append(_button(texts.shorten(item.name, 24), CardCB(id=item.id)))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([_button("📋 Все записи", NavCB(to="list")), _home_button()])
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


# --- spending ------------------------------------------------------------------


def spend(ov: Overview) -> Screen:
    expenses = ov.expenses
    lines = ["<b>Расходы</b> · подписки"]
    if not expenses.per_currency and not expenses.due:
        lines.append(
            "\nАктивных подписок с суммой пока нет. Добавьте подписку с суммой — "
            "здесь появятся расходы в месяц и ближайшие платежи."
        )
        keyboard = [[_button("➕ Добавить", NavCB(to="add")), _home_button()]]
        return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))

    if expenses.per_currency:
        lines.append("\n<b>В месяц</b>")
        for money in expenses.per_currency:
            count = texts.plural(money.count, "подписка", "подписки", "подписок")
            lines.append(f"{_sum(money)} — {money.count} {count}")
        if len(expenses.per_currency) > 1:
            if expenses.total is not None:
                rates = (
                    f" по курсам на {texts.format_date(expenses.rates_date)}"
                    if expenses.rates_date
                    else ""
                )
                lines.append(f"Итого ≈ <b>{_sum(expenses.total)}</b>{rates}")
            else:
                lines.append(
                    "<i>Суммы в разных валютах не складываются: на сайте не загружены курсы валют.</i>"
                )
        yearly = " + ".join(_sum(Money(m.currency, m.amount * 12)) for m in expenses.per_currency)
        lines.append(f"В год ≈ {yearly}")

    if expenses.top:
        lines.append("\n<b>Самые дорогие</b>")
        for n, (item, monthly) in enumerate(expenses.top, start=1):
            symbol = (item.currency.symbol or item.currency.code) if item.currency else ""
            lines.append(f"{n}. {_name(item, 40)} — {texts.amount_with(monthly, symbol)} в месяц")

    if expenses.by_category and any(name for name, _, _ in expenses.by_category):
        scope = (
            expenses.total.currency if expenses.convertible and expenses.total else ov.main_currency
        )
        total = sum(amount for _, amount, _ in expenses.by_category) or 1
        title = "По категориям"
        if expenses.category_scope == "main" and len(expenses.per_currency) > 1 and scope:
            title += f" (только {scope.code})"
        lines.append(f"\n<b>{title}</b>")
        for name, amount, _ in expenses.by_category[:6]:
            label = html.escape(texts.shorten(name, 30)) if name else "Без категории"
            symbol = (scope.symbol or scope.code) if scope else ""
            lines.append(
                f"{label} — {texts.amount_with(amount, symbol)} · {round(amount * 100 / total)}%"
            )

    if expenses.due:
        lines.append("\n<b>К оплате за 30 дней</b>")
        for money in expenses.due:
            count = texts.plural(money.count, "платёж", "платежа", "платежей")
            lines.append(f"{money.count} {count} — {_sum(money)}")

    lines.append(
        "\n<i>В месяц: недельные платежи ×4,35, годовые ÷12 — как в статистике на сайте. "
        "Разовые покупки и отменённые подписки не учитываются.</i>"
    )
    keyboard = [[_button("📅 Скоро", NavCB(to="soon")), _home_button()]]
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


# --- settings ------------------------------------------------------------------


def settings(ov: Overview, telegram_username: str | None, miniapp_url: str | None) -> Screen:
    days = ov.reminder_days
    when = "в день даты" if days == 0 else f"за {texts.days(days)} до даты"
    tg = f"@{html.escape(telegram_username)}" if telegram_username else "этот чат"
    lines = [
        "<b>Настройки</b>",
        "",
        f"Аккаунт: <b>{html.escape(ov.username)}</b>",
        f"Telegram: привязан ({tg})",
        f"Напоминать по умолчанию: <b>{when}</b>",
        "",
        "<i>Срок «по умолчанию» — для записей, где не указан свой. "
        "Это та же настройка, что на сайте в разделе «Уведомления». "
        "Часовой пояс и время рассылки задаются на сервере.</i>",
    ]

    def day(value: int) -> InlineKeyboardButton:
        label = "в день" if value == 0 else f"{value} дн."
        return _button(("✓ " if value == days else "") + label, SettingsCB(key="days", value=value))

    keyboard = [[day(v) for v in (0, 1, 2, 3)], [day(v) for v in (4, 5, 6, 7)]]
    links = []
    if ov.site_url:
        links.append(InlineKeyboardButton(text="🌐 Сайт", url=ov.site_url))
    if miniapp_url:
        links += _app_button(miniapp_url, "📱 Приложение")
    if links:
        keyboard.append(links)
    keyboard.append([_button("🔗 Отвязать Telegram", SettingsCB(key="unlink"))])
    keyboard.append([_home_button()])
    return Screen("\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard))


def unlink_confirm(ov: Overview) -> Screen:
    text = (
        f"Отвязать Telegram от аккаунта <b>{html.escape(ov.username)}</b>?\n\n"
        "Напоминания перестанут приходить сюда, а бот больше не увидит ваши записи. "
        "Сами записи останутся на сайте. Чтобы привязать Telegram снова, понадобится "
        "новая ссылка: <b>Профиль → Telegram-бот</b> на сайте."
    )
    keyboard = [
        [_button("🔗 Да, отвязать", SettingsCB(key="unlink_ok"))],
        [_button("‹ Не отвязывать", NavCB(to="set"))],
    ]
    return Screen(text, InlineKeyboardMarkup(inline_keyboard=keyboard))


UNLINKED = (
    "Telegram отвязан. Напоминания сюда больше не придут.\n\n"
    "Чтобы привязать снова: на сайте <b>Профиль → Telegram-бот</b> → «Привязать Telegram»."
)


# --- help ----------------------------------------------------------------------

HELP_TEXT = (
    "<b>ShelfLife в Telegram</b>\n\n"
    "Всё о сроках в одном месте: подписки и регулярные платежи, сроки годности, "
    "обслуживание техники. Записи общие с сайтом.\n\n"
    "<b>Разделы</b>\n"
    "🏠 /start — главная: сводка и ближайшее\n"
    "📋 /list — мои записи: фильтры, продление, отмена, удаление\n"
    "📅 /soon — что наступает в ближайшие 30 дней\n"
    "💳 /spend — расходы на подписки в месяц\n"
    "⚙️ /settings — напоминания по умолчанию, привязка\n\n"
    "<b>Добавить запись</b>\n"
    "/add — по шагам, с выбором из кнопок. Или сразу одной строкой:\n"
    "• <code>/add Spotify 15.11 500rub</code> — подписка, каждый месяц\n"
    "• <code>/add Netflix 01.12.2026 9.99$ год</code> — подписка, раз в год\n"
    "• <code>/add Витамины 20.11</code> — срок годности\n"
    "• <code>/add Фильтр 10.01 то 3мес</code> — обслуживание каждые 3 месяца\n\n"
    "<b>Напоминания</b> приходят заранее. Кнопки под ними:\n"
    "• «Продлено» — перенести дату на следующий период;\n"
    "• «Отменено» — больше не напоминать об этой записи;\n"
    "• «Напомнить позже» — напомнить завтра.\n\n"
    "/cancel — прервать добавление"
)


def help_screen(miniapp_url: str | None) -> Screen:
    keyboard = []
    if miniapp_url:
        keyboard.append(_app_button(miniapp_url))
    keyboard.append([_home_button()])
    return Screen(HELP_TEXT, InlineKeyboardMarkup(inline_keyboard=keyboard))
