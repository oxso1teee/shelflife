"""Parse human-friendly time expressions into timezone-aware datetimes.

Supports three grammars:

* Relative:      "in 5 minutes", "in 2 hours", "in 1 day", "in 30 m"
* Day-anchored:  "today 18:00", "tomorrow 09:30"
* Absolute:      "2026-05-14 18:30", "2026-05-14T18:30", "14.05.2026 18:30"

Times in the past (relative to `now`) are rejected with `TimeParseError`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, tzinfo

__all__ = ["TimeParseError", "parse_time"]


class TimeParseError(ValueError):
    """Raised when an input string cannot be parsed as a time expression."""


_RELATIVE_RE = re.compile(
    r"^\s*in\s+(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|s|m|h|d|w)\s*$",
    re.IGNORECASE,
)
_DAY_ANCHORED_RE = re.compile(
    r"^\s*(today|tomorrow)\s+(\d{1,2}):(\d{2})\s*$",
    re.IGNORECASE,
)
_ISO_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})\s*$")
_DOT_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})\s*$")

_UNIT_TO_KEY = {
    "s": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "week": "weeks",
    "weeks": "weeks",
}


def parse_time(
    text: str,
    now: datetime | None = None,
    tz: tzinfo | None = None,
) -> datetime:
    """Parse `text` into a timezone-aware datetime in the future.

    Args:
        text: The expression to parse.
        now:  Reference "current" time. Defaults to `datetime.now(tz)`. Pass
              an explicit value in tests for determinism.
        tz:   Timezone used when interpreting absolute/day-anchored grammars
              and as the default for `now`. Defaults to UTC.

    Raises:
        TimeParseError: when the input is empty, malformed, or resolves to a
            point in the past.
    """
    if not text or not text.strip():
        raise TimeParseError("empty input")

    tz = tz or UTC
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    if m := _RELATIVE_RE.match(text):
        amount = int(m.group(1))
        if amount == 0:
            raise TimeParseError("relative offset must be positive")
        key = _UNIT_TO_KEY[m.group(2).lower()]
        return now + timedelta(**{key: amount})

    if m := _DAY_ANCHORED_RE.match(text):
        word = m.group(1).lower()
        hour = int(m.group(2))
        minute = int(m.group(3))
        _validate_clock(hour, minute)
        base = now if word == "today" else now + timedelta(days=1)
        result = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if result <= now:
            raise TimeParseError(f"{word!s} {hour:02d}:{minute:02d} is in the past")
        return result

    if m := _ISO_RE.match(text):
        return _build_absolute(
            year=int(m.group(1)),
            month=int(m.group(2)),
            day=int(m.group(3)),
            hour=int(m.group(4)),
            minute=int(m.group(5)),
            tz=tz,
            now=now,
        )

    if m := _DOT_RE.match(text):
        return _build_absolute(
            year=int(m.group(3)),
            month=int(m.group(2)),
            day=int(m.group(1)),
            hour=int(m.group(4)),
            minute=int(m.group(5)),
            tz=tz,
            now=now,
        )

    raise TimeParseError(f"could not parse time expression: {text!r}")


def _build_absolute(
    *,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    tz: tzinfo,
    now: datetime,
) -> datetime:
    _validate_clock(hour, minute)
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError as exc:
        raise TimeParseError(f"invalid date: {exc}") from exc
    if dt <= now:
        raise TimeParseError(f"specified time {dt.isoformat()} is in the past")
    return dt


def _validate_clock(hour: int, minute: int) -> None:
    if not 0 <= hour <= 23:
        raise TimeParseError(f"hour must be 0..23, got {hour}")
    if not 0 <= minute <= 59:
        raise TimeParseError(f"minute must be 0..59, got {minute}")
