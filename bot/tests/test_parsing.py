"""The /add parser (bot/parsing.py), in the shape of the original reminder-bot tests."""

from __future__ import annotations

from datetime import date

import pytest

from bot.parsing import (
    ParseError,
    QuickAdd,
    has_date,
    parse_amount,
    parse_date,
    parse_quick_add,
)

TODAY = date(2026, 10, 14)


def parse(text: str) -> QuickAdd:
    return parse_quick_add(text, TODAY)


class TestSpecificationExample:
    def test_spotify(self):
        assert parse("Spotify 15.11 500rub") == QuickAdd(
            name="Spotify",
            due=date(2026, 11, 15),
            kind="subscription",
            price="500",
            currency="RUB",
        )


class TestDates:
    def test_without_a_year_the_next_such_date(self):
        assert parse("Вода 20.10 100").due == date(2026, 10, 20)

    def test_without_a_year_a_passed_day_moves_to_next_year(self):
        assert parse("Вода 01.03 100").due == date(2027, 3, 1)

    def test_today_is_not_moved(self):
        assert parse("Вода 14.10 100").due == TODAY

    def test_two_digit_year(self):
        assert parse("Вода 01.03.27 100").due == date(2027, 3, 1)

    def test_four_digit_year(self):
        assert parse("Вода 01.03.2028 100").due == date(2028, 3, 1)

    def test_iso_date(self):
        assert parse("Вода 2027-01-31 100").due == date(2027, 1, 31)

    def test_single_digit_day_and_month(self):
        assert parse("Вода 5.1 100").due == date(2027, 1, 5)

    def test_leap_day_in_a_leap_year(self):
        assert parse("Вода 29.02.2028 100").due == date(2028, 2, 29)

    def test_leap_day_without_a_year_waits_for_the_next_leap_year(self):
        assert parse("Вода 29.02 100").due == date(2028, 2, 29)


class TestNames:
    def test_name_with_spaces(self):
        assert parse("Яндекс Плюс 15.11 299").name == "Яндекс Плюс"

    def test_a_number_in_the_name_that_is_not_a_date(self):
        result = parse("Сервис 2.0 15.11 299")
        assert (result.name, result.due) == ("Сервис 2.0", date(2026, 11, 15))

    def test_name_keeps_its_case(self):
        assert parse("YouTube Premium 15.11 199").name == "YouTube Premium"


class TestAmounts:
    @pytest.mark.parametrize(
        ("text", "price", "currency"),
        [
            ("X 15.11 500rub", "500", "RUB"),
            ("X 15.11 500руб", "500", "RUB"),
            ("X 15.11 500р", "500", "RUB"),
            ("X 15.11 500₽", "500", "RUB"),
            ("X 15.11 500 руб", "500", "RUB"),
            ("X 15.11 9.99$", "9.99", "USD"),
            ("X 15.11 $9.99", "9.99", "USD"),
            ("X 15.11 9,99€", "9.99", "EUR"),
            ("X 15.11 10 eur", "10", "EUR"),
            ("X 15.11 1500 kzt", "1500", "KZT"),
            ("X 15.11 299", "299", None),
        ],
    )
    def test_amount_and_currency(self, text, price, currency):
        result = parse(text)
        assert (result.price, result.currency) == (price, currency)


class TestKindsAndPeriods:
    def test_no_amount_is_a_shelf_life_date(self):
        result = parse("Витамины 20.11")
        assert (result.kind, result.price, result.cycle) == ("expiry", None, None)

    def test_maintenance_every_three_months(self):
        result = parse("Фильтр для воды 10.01 то 3мес")
        assert (result.name, result.kind, result.cycle, result.frequency) == (
            "Фильтр для воды",
            "maintenance",
            3,
            3,
        )

    def test_yearly_subscription(self):
        result = parse("Netflix 01.12.2026 9.99$ год")
        assert (result.kind, result.cycle, result.frequency) == ("subscription", 4, 1)

    def test_words_and_amount_in_any_order(self):
        result = parse("Хостинг 01.12 ежегодно 3000р")
        assert (result.price, result.currency, result.cycle) == ("3000", "RUB", 4)

    def test_maintenance_with_a_cost(self):
        result = parse("Котёл 15.11 то 5000р")
        assert (result.kind, result.price) == ("maintenance", "5000")


class TestInvalidInput:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "Напишите"),
            ("   ", "Напишите"),
            ("Spotify", "Не нашёл дату"),
            ("Spotify 500rub", "Не нашёл дату"),
            ("15.11 Spotify", "Сначала название"),
            ("Spotify 31.02 500", "Такой даты нет"),
            ("Spotify 15.13 500", "Такой даты нет"),
            ("Spotify 01.03.2025 500", "уже прошла"),
            ("Spotify 31.04 500", "Такой даты нет"),
            ("Spotify 15.11 подписка", "нужна сумма"),
            ("Spotify 15.11 0rub", "больше нуля"),
            ("Spotify 15.11 500 рублей?", "Не понял"),
            ("Spotify 15.11 500xyz1", "Не понял"),
            ("Spotify 15.11 500 abc def", "Не понял"),
            ("Spotify 15.11 500рр", "Не знаю валюту"),
        ],
    )
    def test_refused_with_a_reason(self, text, message):
        with pytest.raises(ParseError, match=message):
            parse(text)

    def test_overlong_name(self):
        with pytest.raises(ParseError, match="слишком длинное"):
            parse("x" * 101 + " 15.11 100")


class TestDeterminism:
    def test_today_is_injected(self):
        assert parse_quick_add("X 01.01 1", date(2026, 12, 31)).due == date(2027, 1, 1)
        assert parse_quick_add("X 01.01 1", date(2027, 1, 1)).due == date(2027, 1, 1)


# --- the single-value readers used by the step-by-step /add ---------------------

TODAY_14_10 = date(2026, 10, 14)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Spotify 15.11 500rub", True),
        ("Витамины 2026-11-20", True),
        ("Spotify", False),
        ("Spotify 500rub", False),
        ("", False),
    ],
)
def test_has_date_spots_a_date_like_token(text, expected):
    assert has_date(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15.11", date(2026, 11, 15)),
        ("14.10", date(2026, 10, 14)),  # today is allowed
        ("13.10", date(2027, 10, 13)),  # passed this year: the next one
        ("  01.12.2026 ", date(2026, 12, 1)),
        ("01.12.27", date(2027, 12, 1)),
        ("2026-12-01", date(2026, 12, 1)),
    ],
)
def test_parse_date_reads_one_date(text, expected):
    assert parse_date(text, TODAY_14_10) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("завтра", "Не понял дату"),
        ("15.11 500", "Не понял дату"),
        ("31.02.2027", "Такой даты нет"),
        ("01.01.2020", "уже прошла"),
        ("", "Не понял дату"),
    ],
)
def test_parse_date_explains_what_is_wrong(text, message):
    with pytest.raises(ParseError, match=message):
        parse_date(text, TODAY_14_10)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500", ("500", None)),
        ("500rub", ("500", "RUB")),
        ("500 руб", ("500", "RUB")),
        ("9,99$", ("9.99", "USD")),
        ("$9.99", ("9.99", "USD")),
        ("10€", ("10", "EUR")),
        ("15 gbp", ("15", "GBP")),
    ],
)
def test_parse_amount_reads_the_price_and_currency(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("сто", "Не понял сумму"),
        ("0", "больше нуля"),
        ("500 рублей денег", "Не понял сумму"),
        ("500$ usd", "Не понял сумму"),
        ("500 тугриков", "Не знаю валюту"),
        ("", "Не понял сумму"),
    ],
)
def test_parse_amount_explains_what_is_wrong(text, message):
    with pytest.raises(ParseError, match=message):
        parse_amount(text)
