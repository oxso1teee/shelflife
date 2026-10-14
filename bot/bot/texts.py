"""How the bot writes: one style for every message.

Dates are DD.MM.YYYY, amounts "1 500 ₽" (no-break spaces), the time left
"завтра" / "через 3 дня" / "2 дня назад". A record is shown as the same card
the web app sends as a reminder (web/includes/shelflife/notifications.php)::

    <b>Spotify</b>
    Подписка · каждый месяц
    Дата: 15.11.2026 — через 32 дня
    Сумма: 500 ₽

Emoji only mark the kind of message: ✅ done, ❌ cancelled, ⏰ snoozed,
⚠️ something to fix — and a record's status, as the website's traffic lights:
🔴 overdue, 🟡 less than a week left, 🟢 later, ⚪ cancelled.
"""

from __future__ import annotations

import html
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.wallos_client import Record

NBSP = " "
NAME_MAX = 80

KIND_NAMES = {"subscription": "Подписка", "expiry": "Срок годности", "maintenance": "Обслуживание"}
CURRENCY_SYMBOLS = {
    "RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "UAH": "₴",
    "GBP": "£", "CNY": "¥", "TRY": "₺", "BYN": "Br",
}  # fmt: skip

STATUS_MARKS = {"overdue": "🔴", "soon": "🟡", "ok": "🟢", "inactive": "⚪"}

UNAVAILABLE = "Сервис временно недоступен. Попробуйте ещё раз через минуту."
NOT_LINKED = (
    "Сначала привяжите аккаунт: на сайте откройте <b>Профиль → Telegram-бот</b> "
    "и нажмите «Привязать Telegram»."
)
ADD_EXAMPLE = "<code>/add Spotify 15.11 500rub</code>"

# Periods: (one period, singular / few / many unit for "every N").
_PERIODS = {
    1: ("каждый день", "день", "дня", "дней"),
    2: ("каждую неделю", "неделю", "недели", "недель"),
    3: ("каждый месяц", "месяц", "месяца", "месяцев"),
    4: ("каждый год", "год", "года", "лет"),
}


def today() -> date:
    """Today in the app's time zone (TZ), as the web app counts it."""
    try:
        zone = ZoneInfo(os.environ.get("TZ") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form: 1 день, 2 дня, 5 дней."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days(n: int) -> str:
    return f"{abs(n)} {plural(n, 'день', 'дня', 'дней')}"


def format_date(value: date | str) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d.%m.%Y")


def relative(due: date, now: date) -> str:
    """'сегодня', 'завтра', 'через 3 дня', 'вчера', '2 дня назад'."""
    return relative_days((due - now).days)


def relative_days(delta: int) -> str:
    """The same, from the number of days left."""
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    if delta == -1:
        return "вчера"
    return f"через {days(delta)}" if delta > 0 else f"{days(delta)} назад"


def money(amount: float, currency: str | None) -> str:
    """'1 500 ₽', '9,99 $', '120 PLN' for a code without a symbol."""
    return amount_with(amount, CURRENCY_SYMBOLS.get(currency or "", currency or ""))


def amount_with(amount: float, symbol: str) -> str:
    """An amount with the given currency sign (the account's own, from the website)."""
    integer, cents = f"{amount:,.2f}".split(".")
    text = integer.replace(",", NBSP) + ("" if cents == "00" else "," + cents)
    return f"{text}{NBSP}{symbol}" if symbol else text


def period(cycle: int, frequency: int) -> str | None:
    """'каждый месяц', 'каждые 3 месяца'; None for a one-time record."""
    unit = _PERIODS.get(cycle)
    if unit is None:
        return None
    n = max(1, frequency)
    return unit[0] if n == 1 else f"каждые {n} {plural(n, *unit[1:])}"


def renew_period(cycle: int, frequency: int) -> str:
    """What renewing adds: 'месяц', '3 месяца', 'год'; a one-time record moves by a month
    (as the web app renews it and as its "Продлено на …" reminder button says)."""
    unit = _PERIODS.get(cycle)
    n = max(1, frequency)
    if unit is None or n == 1:
        return unit[1] if unit else "месяц"
    return f"{n} {plural(n, *unit[1:])}"


def shorten(text: str, limit: int = NAME_MAX) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def record_card(record: Record, now: date) -> str:
    """The record as a short card; the name is escaped for HTML."""
    details = [KIND_NAMES.get(record.kind, record.kind)]
    every = period(record.cycle, record.frequency)
    if every is not None:
        details.append(every)
    elif record.kind == "subscription":
        details.append("разово")

    due = date.fromisoformat(record.next_payment)
    lines = [
        f"<b>{html.escape(shorten(record.name))}</b>",
        " · ".join(details),
        f"Дата: {format_date(due)} — {relative(due, now)}",
    ]
    if record.price > 0:
        lines.append(f"Сумма: {money(record.price, record.currency)}")
    return "\n".join(lines)
