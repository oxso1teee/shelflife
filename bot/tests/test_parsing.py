from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.parsing import TimeParseError, parse_time

NOW = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)


class TestRelative:
    def test_minutes(self):
        assert parse_time("in 5 minutes", now=NOW) == NOW + timedelta(minutes=5)

    def test_singular_minute(self):
        assert parse_time("in 1 minute", now=NOW) == NOW + timedelta(minutes=1)

    def test_hours(self):
        assert parse_time("in 2 hours", now=NOW) == NOW + timedelta(hours=2)

    def test_short_unit_m(self):
        assert parse_time("in 30 m", now=NOW) == NOW + timedelta(minutes=30)

    def test_short_unit_h(self):
        assert parse_time("in 3 h", now=NOW) == NOW + timedelta(hours=3)

    def test_days(self):
        assert parse_time("in 2 days", now=NOW) == NOW + timedelta(days=2)

    def test_weeks(self):
        assert parse_time("in 1 week", now=NOW) == NOW + timedelta(weeks=1)

    def test_seconds(self):
        assert parse_time("in 45 seconds", now=NOW) == NOW + timedelta(seconds=45)

    def test_case_insensitive(self):
        assert parse_time("IN 5 Minutes", now=NOW) == NOW + timedelta(minutes=5)

    def test_zero_rejected(self):
        with pytest.raises(TimeParseError):
            parse_time("in 0 minutes", now=NOW)


class TestDayAnchored:
    def test_today_future(self):
        assert parse_time("today 18:00", now=NOW) == NOW.replace(hour=18, minute=0)

    def test_tomorrow(self):
        expected = (NOW + timedelta(days=1)).replace(hour=9, minute=30)
        assert parse_time("tomorrow 09:30", now=NOW) == expected

    def test_tomorrow_early_morning(self):
        expected = (NOW + timedelta(days=1)).replace(hour=0, minute=15)
        assert parse_time("tomorrow 00:15", now=NOW) == expected

    def test_today_in_past_rejected(self):
        with pytest.raises(TimeParseError):
            parse_time("today 08:00", now=NOW)

    def test_invalid_hour(self):
        with pytest.raises(TimeParseError):
            parse_time("today 25:00", now=NOW)

    def test_invalid_minute(self):
        with pytest.raises(TimeParseError):
            parse_time("today 12:99", now=NOW)


class TestAbsoluteISO:
    def test_space_separator(self):
        assert parse_time("2026-05-15 18:30", now=NOW) == datetime(2026, 5, 15, 18, 30, tzinfo=UTC)

    def test_t_separator(self):
        assert parse_time("2026-05-15T18:30", now=NOW) == datetime(2026, 5, 15, 18, 30, tzinfo=UTC)

    def test_single_digit_components(self):
        assert parse_time("2026-6-1 9:05", now=NOW) == datetime(2026, 6, 1, 9, 5, tzinfo=UTC)

    def test_past_rejected(self):
        with pytest.raises(TimeParseError):
            parse_time("2025-01-01 12:00", now=NOW)

    def test_invalid_calendar_date(self):
        with pytest.raises(TimeParseError):
            parse_time("2026-02-30 12:00", now=NOW)


class TestAbsoluteDot:
    def test_dot_format(self):
        assert parse_time("15.05.2026 18:30", now=NOW) == datetime(2026, 5, 15, 18, 30, tzinfo=UTC)

    def test_dot_single_digit(self):
        assert parse_time("1.6.2026 9:05", now=NOW) == datetime(2026, 6, 1, 9, 5, tzinfo=UTC)

    def test_dot_past_rejected(self):
        with pytest.raises(TimeParseError):
            parse_time("01.01.2025 12:00", now=NOW)


class TestInvalidInput:
    def test_empty(self):
        with pytest.raises(TimeParseError):
            parse_time("", now=NOW)

    def test_whitespace(self):
        with pytest.raises(TimeParseError):
            parse_time("   ", now=NOW)

    def test_garbage(self):
        with pytest.raises(TimeParseError):
            parse_time("when the cows come home", now=NOW)

    def test_relative_without_unit(self):
        with pytest.raises(TimeParseError):
            parse_time("in 5", now=NOW)

    def test_relative_missing_amount(self):
        with pytest.raises(TimeParseError):
            parse_time("in minutes", now=NOW)


class TestTimezoneHandling:
    def test_naive_now_is_attached_to_tz(self):
        naive_now = datetime(2026, 5, 14, 12, 0)
        result = parse_time("in 1 hour", now=naive_now, tz=UTC)
        assert result.tzinfo is not None
        assert result == datetime(2026, 5, 14, 13, 0, tzinfo=UTC)

    def test_default_tz_is_utc(self):
        result = parse_time("2030-01-01 12:00", now=NOW)
        assert result.tzinfo == UTC
