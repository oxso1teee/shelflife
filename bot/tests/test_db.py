from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from bot.db import ReminderDB

FUTURE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    return ReminderDB(tmp_path / "reminders.db")


class TestAdd:
    def test_returns_id(self, db):
        rid = db.add(user_id=1, chat_id=10, text="hi", fire_at=FUTURE)
        assert isinstance(rid, int) and rid > 0

    def test_round_trip(self, db):
        rid = db.add(user_id=1, chat_id=10, text="hi", fire_at=FUTURE)
        r = db.get(rid)
        assert r is not None
        assert (r.user_id, r.chat_id, r.text) == (1, 10, "hi")
        assert r.fire_at == FUTURE
        assert r.recurrence is None
        assert r.active is True

    def test_with_daily_recurrence(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE, recurrence="daily")
        assert db.get(rid).recurrence == "daily"

    def test_with_weekly_recurrence(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE, recurrence="weekly")
        assert db.get(rid).recurrence == "weekly"

    def test_invalid_recurrence_rejected(self, db):
        with pytest.raises(ValueError, match="recurrence"):
            db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE, recurrence="hourly")


class TestGet:
    def test_missing_returns_none(self, db):
        assert db.get(999) is None


class TestListForUser:
    def test_isolated_per_user(self, db):
        db.add(user_id=1, chat_id=10, text="A", fire_at=FUTURE)
        db.add(user_id=2, chat_id=20, text="B", fire_at=FUTURE)
        items = db.list_for_user(1)
        assert [r.text for r in items] == ["A"]

    def test_sorted_by_fire_at(self, db):
        db.add(user_id=1, chat_id=10, text="later", fire_at=FUTURE + timedelta(hours=2))
        db.add(user_id=1, chat_id=10, text="sooner", fire_at=FUTURE + timedelta(hours=1))
        db.add(user_id=1, chat_id=10, text="latest", fire_at=FUTURE + timedelta(days=1))
        assert [r.text for r in db.list_for_user(1)] == ["sooner", "later", "latest"]

    def test_excludes_inactive(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        db.deactivate(rid)
        assert db.list_for_user(1) == []

    def test_empty_for_unknown_user(self, db):
        assert db.list_for_user(42) == []


class TestListAllActive:
    def test_returns_across_users(self, db):
        db.add(user_id=1, chat_id=10, text="A", fire_at=FUTURE)
        db.add(user_id=2, chat_id=20, text="B", fire_at=FUTURE)
        assert {r.text for r in db.list_all_active()} == {"A", "B"}

    def test_excludes_deactivated(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        db.deactivate(rid)
        assert db.list_all_active() == []


class TestDelete:
    def test_owner_can_delete(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        assert db.delete(rid, user_id=1) is True
        assert db.get(rid) is None

    def test_non_owner_blocked(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        assert db.delete(rid, user_id=999) is False
        assert db.get(rid) is not None

    def test_missing_id(self, db):
        assert db.delete(reminder_id=42, user_id=1) is False


class TestDeactivate:
    def test_marks_inactive(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        db.deactivate(rid)
        assert db.get(rid).active is False


class TestReschedule:
    def test_updates_fire_at(self, db):
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=FUTURE)
        new_time = FUTURE + timedelta(days=7)
        db.reschedule(rid, new_time)
        assert db.get(rid).fire_at == new_time


class TestPersistence:
    def test_data_survives_reopen(self, tmp_path):
        path = tmp_path / "persistent.db"
        ReminderDB(path).add(user_id=1, chat_id=10, text="persists", fire_at=FUTURE)
        reopened = ReminderDB(path)
        items = reopened.list_for_user(1)
        assert [r.text for r in items] == ["persists"]


class TestTimezone:
    def test_naive_datetime_treated_as_utc(self, db):
        naive = datetime(2030, 1, 1, 12, 0)
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=naive)
        assert db.get(rid).fire_at == naive.replace(tzinfo=UTC)

    def test_aware_non_utc_normalised(self, db):
        plus_three = timezone(timedelta(hours=3))
        local = datetime(2030, 1, 1, 15, 0, tzinfo=plus_three)
        rid = db.add(user_id=1, chat_id=10, text="x", fire_at=local)
        stored = db.get(rid).fire_at
        assert stored == local
        assert stored.utcoffset() == timedelta(0)
