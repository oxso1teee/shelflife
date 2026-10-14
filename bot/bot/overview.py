"""The account as the bot shows it, parsed from the web app's overview.

Everything here is computed by Wallos (web/includes/shelflife/overview.php,
served by api/internal/telegram/overview.php) — the records with their status
and days left, what is due soon, the spending — with the same rules as the
website and the Mini App. The bot only reads it; it does no date or money
arithmetic of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.wallos_client import WallosError

__all__ = ["Currency", "Expenses", "Item", "Money", "Overview"]


@dataclass(frozen=True, slots=True)
class Currency:
    id: int
    code: str
    symbol: str


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    kind: str  # "subscription" | "expiry" | "maintenance"
    name: str
    next_payment: str | None  # YYYY-MM-DD
    days_left: int | None
    status: str  # "ok" | "soon" | "overdue" | "inactive"
    price: float
    currency: Currency | None
    cycle: int
    frequency: int
    category: str | None
    inactive: bool
    notify: bool
    notify_days_before: int | None  # None or -1: the account default
    snoozed_until: str | None
    monthly: float | None  # monthly equivalent, for an active priced recurring subscription


@dataclass(frozen=True, slots=True)
class Money:
    currency: Currency | None
    amount: float
    count: int = 0


@dataclass(frozen=True, slots=True)
class Expenses:
    per_currency: list[Money]
    total: Money | None  # one total in the main currency, only when honest to give
    rates_date: str | None  # the date of the rates the total was converted with
    convertible: bool
    top: list[tuple[Item, float]]  # (item, monthly in its own currency)
    by_category: list[tuple[str | None, float, int]]
    category_scope: str  # "all" (converted) | "main" (main currency only)
    due: list[Money]  # payments due in the next 30 days


@dataclass(frozen=True, slots=True)
class Overview:
    today: str
    username: str
    first_name: str
    reminder_days: int
    main_currency: Currency | None
    items: list[Item]
    summary: dict[str, Any]
    upcoming: list[tuple[str, list[Item]]]  # group key -> items
    later: int
    expenses: Expenses
    categories: list[tuple[int, str | None]] = field(default_factory=list)
    currencies: list[Currency] = field(default_factory=list)
    site_url: str | None = None

    def item(self, item_id: int) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    @property
    def active(self) -> list[Item]:
        return [i for i in self.items if not i.inactive]

    @classmethod
    def from_json(cls, data: Any, site_url: Any = None) -> Overview:
        try:
            account = data["account"]
            currencies = [_currency(c) for c in data.get("currencies", [])]
            by_id = {c.id: c for c in currencies}
            items = [_item(r) for r in data["records"]]
            items_by_id = {i.id: i for i in items}
            expenses = data["expenses"]
            total = expenses.get("total")
            return cls(
                today=str(data["today"]),
                username=str(account["username"]),
                first_name=str(account.get("first_name") or ""),
                reminder_days=int(account["reminder_days"]),
                main_currency=by_id.get(int(account["main_currency_id"])),
                items=items,
                summary=dict(data["summary"]),
                upcoming=[
                    (str(g["key"]), [items_by_id[int(r["id"])] for r in g["records"]])
                    for g in data["upcoming"]["groups"]
                ],
                later=int(data["upcoming"]["later"]),
                expenses=Expenses(
                    per_currency=[_money(m, "monthly") for m in expenses["per_currency"]],
                    total=_money(total, "monthly") if total else None,
                    rates_date=(total or {}).get("rates_date"),
                    convertible=expenses["convertible"] is True,
                    top=[(items_by_id[int(t["id"])], float(t["monthly"])) for t in expenses["top"]],
                    by_category=[
                        (c["name"], float(c["monthly"]), int(c["count"]))
                        for c in expenses["by_category"]
                    ],
                    category_scope=str(expenses["category_scope"]),
                    due=[_money(m, "amount") for m in expenses["due_30_days"]],
                ),
                categories=[(int(c["id"]), c.get("name")) for c in data.get("categories", [])],
                currencies=currencies,
                site_url=(
                    site_url
                    if isinstance(site_url, str) and site_url.startswith("https://")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WallosError(f"overview: {exc!r}") from exc


def _currency(data: Any) -> Currency | None:
    if not data:
        return None
    return Currency(
        id=int(data["id"]), code=str(data["code"]), symbol=str(data.get("symbol") or "")
    )


def _item(data: dict[str, Any]) -> Item:
    category = data.get("category") or {}
    return Item(
        id=int(data["id"]),
        kind=str(data["kind"]),
        name=str(data["name"]),
        next_payment=data.get("next_payment"),
        days_left=None if data.get("days_left") is None else int(data["days_left"]),
        status=str(data["status"]),
        price=float(data["price"]),
        currency=_currency(data.get("currency")),
        cycle=int(data["cycle"]),
        frequency=int(data["frequency"]),
        category=category.get("name"),
        inactive=data.get("inactive") is True,
        notify=data.get("notify") is True,
        notify_days_before=data.get("notify_days_before"),
        snoozed_until=data.get("snoozed_until"),
        monthly=None if data.get("monthly") is None else float(data["monthly"]),
    )


def _money(data: dict[str, Any], key: str) -> Money:
    return Money(
        currency=_currency(data.get("currency")),
        amount=float(data[key]),
        count=int(data.get("count", 0)),
    )
