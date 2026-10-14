"""SQLite-backed storage for reminders.

The schema is created on first connection. Datetimes are normalised to UTC
ISO 8601 on the way in and parsed back as timezone-aware objects on the way out.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

__all__ = ["Recurrence", "Reminder", "ReminderDB"]

Recurrence = Literal["daily", "weekly"]
_ALLOWED_RECURRENCES: frozenset[str | None] = frozenset({None, "daily", "weekly"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    fire_at TEXT NOT NULL,
    recurrence TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reminders_user_active
    ON reminders(user_id, active);
CREATE INDEX IF NOT EXISTS idx_reminders_active_fire_at
    ON reminders(active, fire_at);
"""


@dataclass(frozen=True, slots=True)
class Reminder:
    id: int
    user_id: int
    chat_id: int
    text: str
    fire_at: datetime
    recurrence: Recurrence | None
    active: bool


class ReminderDB:
    """SQLite-backed reminders store."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        *,
        user_id: int,
        chat_id: int,
        text: str,
        fire_at: datetime,
        recurrence: Recurrence | None = None,
    ) -> int:
        _validate_recurrence(recurrence)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO reminders (user_id, chat_id, text, fire_at, recurrence) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, chat_id, text, _serialize(fire_at), recurrence),
            )
            assert cur.lastrowid is not None
            return cur.lastrowid

    def get(self, reminder_id: int) -> Reminder | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            return _row_to_reminder(row) if row else None

    def list_for_user(self, user_id: int) -> list[Reminder]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND active = 1 " "ORDER BY fire_at ASC",
                (user_id,),
            ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    def list_all_active(self) -> list[Reminder]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE active = 1 ORDER BY fire_at ASC"
            ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    def delete(self, reminder_id: int, user_id: int) -> bool:
        """Delete a reminder, only if it belongs to `user_id`.

        Returns True if a row was deleted.
        """
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            return cur.rowcount > 0

    def deactivate(self, reminder_id: int) -> None:
        """Mark a one-off reminder as fired so it stops appearing in lists."""
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))

    def reschedule(self, reminder_id: int, new_fire_at: datetime) -> None:
        """Advance a recurring reminder's next fire time."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE reminders SET fire_at = ? WHERE id = ?",
                (_serialize(new_fire_at), reminder_id),
            )


def _validate_recurrence(recurrence: Recurrence | None) -> None:
    if recurrence not in _ALLOWED_RECURRENCES:
        allowed = ", ".join(repr(r) for r in sorted(_ALLOWED_RECURRENCES, key=str))
        raise ValueError(f"recurrence must be one of {allowed}, got {recurrence!r}")


def _serialize(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _deserialize(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        user_id=row["user_id"],
        chat_id=row["chat_id"],
        text=row["text"],
        fire_at=_deserialize(row["fire_at"]),
        recurrence=row["recurrence"],
        active=bool(row["active"]),
    )
