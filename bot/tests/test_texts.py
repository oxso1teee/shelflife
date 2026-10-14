"""The bot's writing style (bot/texts.py): dates, amounts, periods, the record card."""

from __future__ import annotations

import re
from datetime import date

import pytest

from bot import texts
from bot.handlers import common
from bot.parsing import parse_quick_add
from bot.wallos_client import Record

NBSP = " "
TODAY = date(2026, 10, 14)


def record(**overrides) -> Record:
    values = {
        "id": 9, "kind": "subscription", "name": "Spotify", "next_payment": "2026-11-15",
        "price": 500.0, "currency": "RUB", "cycle": 3, "frequency": 1,
        "inactive": False, "snoozed_until": None,
    }  # fmt: skip
    values.update(overrides)
    return Record(**values)


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "1 день"), (2, "2 дня"), (5, "5 дней"), (11, "11 дней"), (21, "21 день"), (-3, "3 дня")],
)
def test_days(n, expected):
    assert texts.days(n) == expected


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (date(2026, 10, 14), "сегодня"),
        (date(2026, 10, 15), "завтра"),
        (date(2026, 10, 17), "через 3 дня"),
        (date(2026, 10, 13), "вчера"),
        (date(2026, 10, 9), "5 дней назад"),
    ],
)
def test_relative(due, expected):
    assert texts.relative(due, TODAY) == expected


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (500.0, "RUB", f"500{NBSP}₽"),
        (1500.0, "RUB", f"1{NBSP}500{NBSP}₽"),
        (30000.5, "RUB", f"30{NBSP}000,50{NBSP}₽"),
        (9.99, "USD", f"9,99{NBSP}$"),
        (120.0, "PLN", f"120{NBSP}PLN"),
        (120.0, None, "120"),
    ],
)
def test_money(amount, currency, expected):
    assert texts.money(amount, currency) == expected


@pytest.mark.parametrize(
    ("cycle", "frequency", "expected"),
    [
        (1, 1, "каждый день"),
        (2, 1, "каждую неделю"),
        (3, 1, "каждый месяц"),
        (3, 3, "каждые 3 месяца"),
        (4, 1, "каждый год"),
        (4, 5, "каждые 5 лет"),
        (5, 1, None),
    ],
)
def test_period(cycle, frequency, expected):
    assert texts.period(cycle, frequency) == expected


def test_shorten():
    assert texts.shorten("Spotify") == "Spotify"
    long = texts.shorten("a" * 200)
    assert len(long) == texts.NAME_MAX and long.endswith("…")


def test_the_record_card():
    assert texts.record_card(record(), TODAY) == (
        "<b>Spotify</b>\n"
        "Подписка · каждый месяц\n"
        "Дата: 15.11.2026 — через 32 дня\n"
        f"Сумма: 500{NBSP}₽"
    )
    assert texts.record_card(
        record(kind="expiry", name="Молоко & <сыр>", price=0.0, cycle=5, next_payment="2026-10-14"),
        TODAY,
    ) == ("<b>Молоко &amp; &lt;сыр&gt;</b>\nСрок годности\nДата: 14.10.2026 — сегодня")
    assert "Подписка · разово" in texts.record_card(record(cycle=5), TODAY)


def test_every_example_in_help_is_understood_by_the_parser():
    examples = re.findall(r"<code>/add ([^<]+)</code>", common.HELP_TEXT + texts.ADD_EXAMPLE)
    examples = [line for line in examples if "Название" not in line]
    assert len(examples) >= 4
    for line in examples:
        parse_quick_add(line, TODAY)  # raises ParseError if an example went stale
