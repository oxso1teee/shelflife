from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from bot.db import ReminderDB
from bot.scheduler import ReminderScheduler, next_recurrence

FUTURE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)

NOW = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)


class TestNextRecurrenceDaily:
    def test_one_day_ahead_when_due_yesterday(self):
        last = NOW - timedelta(hours=1)
        assert next_recurrence(NOW, last, "daily") == last + timedelta(days=1)

    def test_fast_forwards_past_missed_days(self):
        last = NOW - timedelta(days=10)
        result = next_recurrence(NOW, last, "daily")
        assert result > NOW
        # Result should be the first slot strictly after NOW.
        assert result - timedelta(days=1) <= NOW

    def test_already_in_future_advances_by_one_day(self):
        last = NOW + timedelta(hours=2)
        assert next_recurrence(NOW, last, "daily") == last + timedelta(days=1)


class TestNextRecurrenceWeekly:
    def test_advances_one_week(self):
        last = NOW - timedelta(hours=1)
        assert next_recurrence(NOW, last, "weekly") == last + timedelta(weeks=1)

    def test_fast_forwards_past_missed_weeks(self):
        last = NOW - timedelta(weeks=5)
        result = next_recurrence(NOW, last, "weekly")
        assert result > NOW
        assert result - timedelta(weeks=1) <= NOW


class TestNextRecurrenceInvalid:
    def test_unknown_recurrence_raises(self):
        with pytest.raises(KeyError):
            next_recurrence(NOW, NOW, "hourly")  # type: ignore[arg-type]


@pytest.fixture
def db(tmp_path):
    return ReminderDB(tmp_path / "reminders.db")


class TestFireRaceConditions:
    """Tests for _fire behaviour when state changes during delivery."""

    @pytest.mark.asyncio
    async def test_deleted_during_delivery_not_rescheduled(self, db):
        """Recurring reminder deleted while deliver() is running must not be rescheduled."""
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE, recurrence="daily")

        async def deliver_and_delete(reminder):
            db.delete(rid, user_id=1)

        scheduler = ReminderScheduler(db, deliver_and_delete)
        await scheduler._fire(rid)

        assert db.get(rid) is None

    @pytest.mark.asyncio
    async def test_failed_delivery_one_off_stays_active(self, db):
        """One-off reminder whose delivery raises must NOT be deactivated."""
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)

        deliver = AsyncMock(side_effect=RuntimeError("network error"))
        scheduler = ReminderScheduler(db, deliver)
        await scheduler._fire(rid)

        reminder = db.get(rid)
        assert reminder is not None
        assert reminder.active is True
