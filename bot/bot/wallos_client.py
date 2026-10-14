"""Client for the ShelfLife internal API of the Wallos web app.

The bot keeps no data of its own. Every account lookup and every change to a
record goes through Wallos (``web/api/internal/telegram/*.php``), which applies
the same validation, ownership checks and date rules as the web pages. Requests
carry the shared service key; the user is identified by the Telegram id taken
from the update, never from what the user typed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

__all__ = [
    "Account",
    "ActionResult",
    "AddResult",
    "LinkResult",
    "Record",
    "SettingsResult",
    "WallosClient",
    "WallosError",
]

log = logging.getLogger(__name__)


class WallosError(Exception):
    """Wallos could not be reached or did not answer as expected."""


@dataclass(frozen=True, slots=True)
class LinkResult:
    status: str  # "linked" | "invalid_token" | "telegram_taken"
    username: str | None


@dataclass(frozen=True, slots=True)
class Account:
    linked: bool
    username: str | None


@dataclass(frozen=True, slots=True)
class Record:
    id: int
    kind: str  # "subscription" | "expiry" | "maintenance"
    name: str
    next_payment: str  # YYYY-MM-DD
    price: float
    currency: str | None
    cycle: int
    frequency: int
    inactive: bool
    snoozed_until: str | None

    @classmethod
    def from_json(cls, data: Any) -> Record:
        if not isinstance(data, dict):
            raise WallosError("record: unexpected shape")
        try:
            return cls(
                id=int(data["id"]),
                kind=str(data["kind"]),
                name=str(data["name"]),
                next_payment=str(data["next_payment"]),
                price=float(data["price"]),
                currency=_optional_str(data.get("currency")),
                cycle=int(data["cycle"]),
                frequency=int(data["frequency"]),
                inactive=data.get("inactive") is True,
                snoozed_until=_optional_str(data.get("snoozed_until")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WallosError(f"record: {exc}") from exc


@dataclass(frozen=True, slots=True)
class AddResult:
    status: str  # "created" | "invalid" | "not_linked"
    record: Record | None = None
    field: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    # "done" | "stale" | "inactive" | "active" | "not_recurring" | "not_found" | "invalid" | "not_linked"
    status: str
    action: str | None = None
    record: Record | None = None


@dataclass(frozen=True, slots=True)
class SettingsResult:
    status: str  # "saved" | "unlinked" | "invalid" | "not_linked"
    reminder_days: int | None = None


class WallosClient:
    def __init__(self, base_url: str, service_key: str, *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def link(self, token: str, telegram_id: int, telegram_username: str | None) -> LinkResult:
        data = await self._post(
            "link",
            {"token": token, "telegram_id": telegram_id, "telegram_username": telegram_username},
        )
        status = data.get("status")
        if status not in {"linked", "invalid_token", "telegram_taken"}:
            raise WallosError(f"link: unexpected status {status!r}")
        return LinkResult(status=status, username=_optional_str(data.get("username")))

    async def account(self, telegram_id: int) -> Account:
        data = await self._post("me", {"telegram_id": telegram_id})
        return Account(
            linked=data.get("linked") is True, username=_optional_str(data.get("username"))
        )

    async def add_record(
        self,
        *,
        telegram_id: int,
        update_id: int,
        kind: str,
        name: str,
        next_payment: str,
        price: str | None = None,
        currency: str | None = None,
        cycle: int | None = None,
        frequency: int | None = None,
        category_id: int | None = None,
    ) -> AddResult:
        payload: dict[str, Any] = {
            "telegram_id": telegram_id,
            "update_id": update_id,
            "kind": kind,
            "name": name,
            "next_payment": next_payment,
        }
        optional = {
            "price": price,
            "currency": currency,
            "cycle": cycle,
            "frequency": frequency,
            "category_id": category_id,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})

        data = await self._post("item_add", payload)
        status = data.get("status")
        if status == "created":
            return AddResult(status=status, record=Record.from_json(data.get("record")))
        if status in {"invalid", "not_linked"}:
            return AddResult(
                status=status,
                field=_optional_str(data.get("field")),
                message=_optional_str(data.get("message")),
            )
        raise WallosError(f"item_add: unexpected status {status!r}")

    async def act(
        self,
        *,
        telegram_id: int,
        update_id: int,
        subscription_id: int,
        action: str,
        expected_due: str,
        snooze_days: int = 1,
    ) -> ActionResult:
        data = await self._post(
            "item_action",
            {
                "telegram_id": telegram_id,
                "update_id": update_id,
                "subscription_id": subscription_id,
                "action": action,
                "expected_due": expected_due,
                "snooze_days": snooze_days,
            },
        )
        status = data.get("status")
        known = {
            "done", "stale", "inactive", "active", "not_recurring", "not_found", "invalid", "not_linked",
        }  # fmt: skip
        if status not in known:
            raise WallosError(f"item_action: unexpected status {status!r}")
        record = data.get("record")
        return ActionResult(
            status=status,
            action=_optional_str(data.get("action")),
            record=Record.from_json(record) if record is not None else None,
        )

    async def overview(self, telegram_id: int):
        """The linked account's overview (bot.overview.Overview), or None when not linked."""
        from bot.overview import Overview  # the model module imports this one

        data = await self._post("overview", {"telegram_id": telegram_id})
        status = data.get("status")
        if status == "not_linked":
            return None
        if status != "linked":
            raise WallosError(f"overview: unexpected status {status!r}")
        return Overview.from_json(data.get("overview"), data.get("site_url"))

    async def settings(
        self, *, telegram_id: int, update_id: int, op: str, days: int | None = None
    ) -> SettingsResult:
        payload: dict[str, Any] = {"telegram_id": telegram_id, "update_id": update_id, "op": op}
        if days is not None:
            payload["days"] = days
        data = await self._post("settings", payload)
        status = data.get("status")
        if status not in {"saved", "unlinked", "invalid", "not_linked"}:
            raise WallosError(f"settings: unexpected status {status!r}")
        days_value = data.get("reminder_days")
        return SettingsResult(
            status=status, reminder_days=days_value if isinstance(days_value, int) else None
        )

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

        url = f"{self._base_url}/{endpoint}.php"
        try:
            async with self._session.post(
                url, json=payload, headers={"X-ShelfLife-Service-Key": self._service_key}
            ) as response:
                if response.status != 200:
                    # The body names the error; the key is never logged.
                    body = (await response.text())[:200]
                    raise WallosError(f"{endpoint}: HTTP {response.status} {body}")
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise WallosError(f"{endpoint}: {exc}") from exc

        if not isinstance(data, dict):
            raise WallosError(f"{endpoint}: unexpected response")
        return data


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
