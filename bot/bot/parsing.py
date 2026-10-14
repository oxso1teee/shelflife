"""Parse the one-line ``/add`` command into a record for Wallos.

Adapted from the time-expression parser of telegram-reminder-bot: the same
shape (strict regular expressions, a dedicated error type whose message is
shown to the user, an explicit ``today`` for deterministic tests), applied to
ShelfLife's grammar instead of reminder times::

    /add <name> <date> [<amount>[<currency>]] [<kind or period words>]

    /add Spotify 15.11 500rub          subscription, monthly, 500 RUB
    /add Netflix 01.12.2026 9.99$ год  subscription, yearly, 9.99 USD
    /add Витамины 20.11                shelf-life date (no amount)
    /add Фильтр для воды 10.01 то 3мес maintenance every 3 months

The date is DD.MM, DD.MM.YY or DD.MM.YYYY (or YYYY-MM-DD). Without a year it
is the next such date from today. Anything the parser does not understand is
reported, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

__all__ = [
    "CURRENCY_ALIASES",
    "ParseError",
    "QuickAdd",
    "has_date",
    "parse_amount",
    "parse_date",
    "parse_quick_add",
]

MAX_NAME_LENGTH = 100


class ParseError(ValueError):
    """The input cannot be turned into a record; the message is for the user."""


@dataclass(frozen=True, slots=True)
class QuickAdd:
    name: str
    due: date
    kind: str  # "subscription" | "expiry" | "maintenance"
    price: str | None = None  # decimal string with a dot, e.g. "9.99"
    currency: str | None = None  # ISO code, e.g. "RUB"; None = the account's main currency
    cycle: int | None = None  # 1 days, 2 weeks, 3 months, 4 years, 5 one-time
    frequency: int | None = None


_DOT_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_AMOUNT_RE = re.compile(r"^([$€₽]?)(\d+(?:[.,]\d{1,2})?)([^\d.,]*)$")
_EVERY_MONTHS_RE = re.compile(r"^(\d{1,2})(?:мес|m)$")

CURRENCY_ALIASES = {
    "₽": "RUB", "rub": "RUB", "rur": "RUB", "руб": "RUB", "р": "RUB",
    "$": "USD", "usd": "USD", "долл": "USD",
    "€": "EUR", "eur": "EUR", "евро": "EUR",
    "₸": "KZT", "kzt": "KZT", "тенге": "KZT",
    "byn": "BYN", "uah": "UAH", "gbp": "GBP", "cny": "CNY", "try": "TRY",
}  # fmt: skip

_KIND_WORDS = {
    "подписка": "subscription",
    "срок": "expiry", "годен": "expiry", "годность": "expiry",
    "то": "maintenance", "обслуживание": "maintenance",
}  # fmt: skip

# word -> (cycle, frequency)
_PERIOD_WORDS = {
    "ежедневно": (1, 1), "день": (1, 1),
    "еженедельно": (2, 1), "неделя": (2, 1), "нед": (2, 1),
    "ежемесячно": (3, 1), "месяц": (3, 1), "мес": (3, 1),
    "ежегодно": (4, 1), "год": (4, 1),
    "разово": (5, 1),
}  # fmt: skip


def parse_quick_add(text: str, today: date) -> QuickAdd:
    """Parse the arguments of ``/add`` (everything after the command)."""
    tokens = (text or "").split()
    if not tokens:
        raise ParseError("Напишите, что добавить.")

    date_index, due = _find_date(tokens, today)
    name = " ".join(tokens[:date_index]).strip()
    if not name:
        raise ParseError("Сначала название, потом дата.")
    if len(name) > MAX_NAME_LENGTH:
        raise ParseError(f"Название слишком длинное (до {MAX_NAME_LENGTH} символов).")

    price: str | None = None
    currency: str | None = None
    kind: str | None = None
    cycle: int | None = None
    frequency: int | None = None

    rest = [token.lower() for token in tokens[date_index + 1 :]]
    i = 0
    while i < len(rest):
        token = rest[i]
        # Words and periods first: "3мес" would otherwise read as an amount of 3.
        if token in _KIND_WORDS and kind is None:
            kind = _KIND_WORDS[token]
        elif token in _PERIOD_WORDS and cycle is None:
            cycle, frequency = _PERIOD_WORDS[token]
        elif (every := _EVERY_MONTHS_RE.match(token)) and cycle is None:
            frequency = int(every.group(1))
            if frequency < 1:
                raise ParseError("Период должен быть не меньше 1 месяца.")
            cycle = 3
        elif price is None and (amount := _AMOUNT_RE.match(token)):
            prefix, number, suffix = amount.groups()
            price = _price(number)
            unit = prefix or suffix
            if not unit and i + 1 < len(rest) and _currency(rest[i + 1]) is not None:
                i += 1
                unit = rest[i]
            if unit:
                currency = _currency(unit)
                if currency is None:
                    raise ParseError(f"Не знаю валюту «{unit}». Например: 500rub, 9.99$, 10€.")
        else:
            raise ParseError(f"Не понял «{tokens[date_index + 1 + i]}»: это не сумма и не период.")
        i += 1

    if kind is None:
        # A price means something paid for; a bare date is a shelf-life date.
        kind = "subscription" if price is not None else "expiry"
    if kind == "subscription" and price is None:
        raise ParseError("Для подписки нужна сумма, например 500rub.")

    return QuickAdd(
        name=name,
        due=due,
        kind=kind,
        price=price,
        currency=currency,
        cycle=cycle,
        frequency=frequency,
    )


def has_date(text: str) -> bool:
    """Whether the text has a date-like token, as /add would look for one."""
    return any(_DOT_RE.match(token) or _ISO_RE.match(token) for token in (text or "").split())


def parse_date(text: str, today: date) -> date:
    """One date, as /add reads it: DD.MM (the next such date), DD.MM.YY,
    DD.MM.YYYY or YYYY-MM-DD; a date that has passed is refused."""
    token = (text or "").strip()
    if not (_DOT_RE.match(token) or _ISO_RE.match(token)):
        raise ParseError("Не понял дату. Формат: ДД.ММ или ДД.ММ.ГГГГ, например 15.11.")
    return _build_date(token, today)


def parse_amount(text: str) -> tuple[str, str | None]:
    """One amount, as /add reads it: 500, 500rub, 500 руб, 9.99$, $9.99, 10€.

    Returns the price as a decimal string with a dot and the ISO currency code
    (None: the account's main currency).
    """
    tokens = (text or "").lower().split()
    amount = _AMOUNT_RE.match(tokens[0]) if 1 <= len(tokens) <= 2 else None
    if amount is None:
        raise ParseError("Не понял сумму. Например: 500, 500rub, 9.99$.")
    prefix, number, suffix = amount.groups()
    price = _price(number)
    unit = prefix or suffix
    if len(tokens) == 2:
        if unit:
            raise ParseError("Не понял сумму. Например: 500, 500rub, 9.99$.")
        unit = tokens[1]
    currency = _currency(unit) if unit else None
    if unit and currency is None:
        raise ParseError(f"Не знаю валюту «{unit}». Например: 500rub, 9.99$, 10€.")
    return price, currency


def _find_date(tokens: list[str], today: date) -> tuple[int, date]:
    """The first token after the name that is a date; a date-like token that
    is not a real date ("31.02") is an error unless a later token is valid."""
    impossible: str | None = None
    for index in range(1, len(tokens)):
        token = tokens[index]
        if not (_DOT_RE.match(token) or _ISO_RE.match(token)):
            continue
        try:
            return index, _build_date(token, today)
        except ParseError as exc:
            impossible = impossible or str(exc)
    if impossible:
        raise ParseError(impossible)
    if _DOT_RE.match(tokens[0]) or _ISO_RE.match(tokens[0]):
        raise ParseError("Сначала название, потом дата.")
    raise ParseError("Не нашёл дату. Формат: ДД.ММ или ДД.ММ.ГГГГ, например 15.11.")


def _build_date(token: str, today: date) -> date:
    if match := _ISO_RE.match(token):
        year, month, day = (int(part) for part in match.groups())
        explicit_year = True
    else:
        match = _DOT_RE.match(token)
        assert match is not None
        day, month = int(match.group(1)), int(match.group(2))
        year_text = match.group(3)
        explicit_year = year_text is not None
        year = (
            int(year_text) + (2000 if year_text and len(year_text) == 2 else 0)
            if year_text
            else today.year
        )

    if not explicit_year:
        # The next such date from today; 29.02 waits for the next leap year.
        for candidate_year in range(today.year, today.year + 5):
            try:
                candidate = date(candidate_year, month, day)
            except ValueError:
                continue
            if candidate >= today:
                return candidate
        raise ParseError(f"Такой даты нет: {token}.")

    try:
        result = date(year, month, day)
    except ValueError:
        raise ParseError(f"Такой даты нет: {token}.") from None
    if result < today:
        raise ParseError(f"Дата {result.strftime('%d.%m.%Y')} уже прошла.")
    return result


def _price(number: str) -> str:
    value = number.replace(",", ".")
    if float(value) <= 0:
        raise ParseError("Сумма должна быть больше нуля.")
    return value


def _currency(unit: str) -> str | None:
    unit = unit.strip().lower().rstrip(".")
    if unit in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[unit]
    if re.fullmatch(r"[a-z]{3}", unit):
        return unit.upper()
    return None
