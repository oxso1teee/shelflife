"""APScheduler wrapper that fires reminders and feeds them to a delivery callback.

The scheduler owns no state of its own — every reminder lives in `ReminderDB`,
and the scheduler reads from / writes to it. This keeps restarts cheap: on
startup, `restore()` re-creates one APScheduler job per active reminder.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from bot.db import Recurrence, Reminder, ReminderDB

__all__ = ["DeliverCallback", "ReminderScheduler", "next_recurrence"]

log = logging.getLogger(__name__)

DeliverCallback = Callable[[Reminder], Awaitable[None]]

_RECURRENCE_DELTA: dict[Recurrence, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def next_recurrence(after: datetime, last_fire_at: datetime, recurrence: Recurrence) -> datetime:
    """Return the next fire time for a recurring reminder strictly after `after`.

    When the bot has been offline for several occurrences, this fast-forwards
    past the missed slots so we deliver one notification, not a backlog.
    """
    delta = _RECURRENCE_DELTA[recurrence]
    next_fire = last_fire_at + delta
    while next_fire <= after:
        next_fire += delta
    return next_fire


class ReminderScheduler:
    def __init__(self, db: ReminderDB, deliver: DeliverCallback) -> None:
        self._db = db
        self._deliver = deliver
        self._scheduler = AsyncIOScheduler(timezone=UTC)

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def restore(self) -> int:
        """Re-schedule every active reminder. Returns the number restored."""
        now = datetime.now(UTC)
        restored = 0
        for reminder in self._db.list_all_active():
            fire_at = reminder.fire_at
            if reminder.recurrence is None and fire_at <= now:
                log.warning("Dropping past one-off reminder id=%d", reminder.id)
                self._db.deactivate(reminder.id)
                continue
            if reminder.recurrence is not None and fire_at <= now:
                fire_at = next_recurrence(now, fire_at, reminder.recurrence)
                self._db.reschedule(reminder.id, fire_at)
            self._schedule_job(reminder.id, fire_at)
            restored += 1
        return restored

    def schedule(self, reminder: Reminder) -> None:
        self._schedule_job(reminder.id, reminder.fire_at)

    def cancel(self, reminder_id: int) -> None:
        try:
            self._scheduler.remove_job(_job_id(reminder_id))
        except Exception:
            log.debug("No scheduler job to cancel for reminder id=%d", reminder_id)

    def _schedule_job(self, reminder_id: int, fire_at: datetime) -> None:
        self._scheduler.add_job(
            self._fire,
            trigger=DateTrigger(run_date=fire_at),
            id=_job_id(reminder_id),
            args=(reminder_id,),
            replace_existing=True,
            misfire_grace_time=60,
        )

    async def _fire(self, reminder_id: int) -> None:
        reminder = self._db.get(reminder_id)
        if reminder is None or not reminder.active:
            log.info("Reminder id=%d is no longer active, skipping", reminder_id)
            return

        delivered = False
        try:
            await self._deliver(reminder)
            delivered = True
        except Exception:
            log.exception("Failed to deliver reminder id=%d", reminder_id)

        # Re-read so we don't resurrect a reminder deleted during delivery.
        reminder = self._db.get(reminder_id)
        if reminder is None or not reminder.active:
            log.info("Reminder id=%d was removed during delivery, skipping reschedule", reminder_id)
            return

        if reminder.recurrence is None:
            if delivered:
                self._db.deactivate(reminder_id)
            return

        now = datetime.now(UTC)
        next_fire = next_recurrence(now, reminder.fire_at, reminder.recurrence)
        self._db.reschedule(reminder_id, next_fire)
        self._schedule_job(reminder_id, next_fire)


def _job_id(reminder_id: int) -> str:
    return f"reminder-{reminder_id}"
