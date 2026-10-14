"""ShelfLife acceptance run: the whole specification against a fresh staging stack.

Exercises the running web container over HTTP and the bot's real handlers and
real client (imported from ../bot) against it. Only Telegram itself is replaced:
reminder messages are captured instead of sent, and incoming messages and
button presses are stand-in objects.

Needs a fresh database (it refuses to run when users exist) and the stack
started with SHELFLIFE_SERVICE_KEY, TELEGRAM_BOT_USERNAME and a TELEGRAM_BOT_TOKEN
(any value: the widget data is signed here with it). Run with the bot's venv:

    bot/.venv/bin/python scripts/acceptance.py
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

from bot import screens  # noqa: E402
from bot.handlers import add as add_handlers  # noqa: E402
from bot.handlers import callbacks, common  # noqa: E402
from bot.keyboards import ItemActionCB  # noqa: E402
from bot.wallos_client import WallosClient  # noqa: E402

BASE = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '8282')}"
PASSWORD = "S3cure-pass!"
RESULTS: list[bool] = []


def check(name: str, got, want) -> None:
    ok = got == want
    RESULTS.append(ok)
    print(
        ("ok    " if ok else "FAIL  ") + name + ("" if ok else f": expected {want!r}, got {got!r}")
    )


# --- the stack ---------------------------------------------------------------


def compose(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def sql(query: str) -> str:
    return compose("exec", "-T", "web", "sqlite3", "/var/www/html/db/wallos.db", query)


def php(code: str) -> str:
    return compose("exec", "-T", "web", "php", stdin="<?php\n" + code)


def env(name: str) -> str:
    return compose("exec", "-T", "web", "printenv", name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    """One signed-in visitor: cookies kept, redirects not followed."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
        )
        self.csrf = ""

    def request(self, path: str, data=None, headers=None, json_body=None) -> tuple[int, str, str]:
        body = None
        headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(BASE + path, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=30) as response:
                return (
                    response.status,
                    response.headers.get("Location", ""),
                    response.read().decode(),
                )
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Location", ""), error.read().decode()

    def login(self, username: str) -> str:
        status, location, _ = self.request(
            "/login.php", {"username": username, "password": PASSWORD}
        )
        _, _, page = self.request("/subscriptions.php")
        match = re.search(r'window\.csrfToken = "([^"]+)"', page)
        self.csrf = match.group(1) if match else ""
        return f"{status} {location}"

    def post(self, path: str, data=None, json_body=None) -> str:
        if data is None and json_body is None:
            data = {}  # still a POST, with an empty body
        return self.request(path, data, {"X-CSRF-Token": self.csrf}, json_body)[2]


def register(username: str, first_name: str) -> None:
    Browser().request(
        "/registration.php",
        {
            "username": username,
            "firstname": first_name,
            "lastname": "Тест",
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
            "main_currency": "RUB",
            "language": "ru",
        },
    )


# --- Telegram stand-ins ------------------------------------------------------


@dataclass
class TgUser:
    id: int
    username: str | None = None


@dataclass
class TgMessage:
    from_user: TgUser
    text: str | None = None
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str, **_) -> None:
        self.answers.append(text)


@dataclass
class TgQuery:
    from_user: TgUser
    message: object = None
    answers: list[str] = field(default_factory=list)

    async def answer(self, text=None, show_alert=False, **_) -> None:
        self.answers.append(text)


@dataclass
class TgUpdate:
    update_id: int


_update_ids = iter(range(int(time.time()), int(time.time()) + 10_000))


def next_update() -> TgUpdate:
    return TgUpdate(next(_update_ids))


async def press(client: WallosClient, raw: str, telegram_id: int) -> str:
    query = TgQuery(TgUser(telegram_id))
    await callbacks.on_item_action(query, ItemActionCB.unpack(raw), client, next_update())
    return query.answers[-1]


def plus_month(day: date) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def widget_query(token: str, telegram_id: int, auth_date: int) -> str:
    fields = {"id": str(telegram_id), "first_name": "Анна", "auth_date": str(auth_date)}
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    fields["hash"] = hmac.new(
        hashlib.sha256(token.encode()).digest(), check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urllib.parse.urlencode(fields)


# --- the run -----------------------------------------------------------------


async def main() -> None:
    if sql("SELECT COUNT(*) FROM user") != "0":
        sys.exit("acceptance needs a fresh database (users exist)")

    tz = ZoneInfo(env("TZ") or "UTC")
    today = datetime.now(tz).date()

    def d(days: int) -> str:
        return (today + timedelta(days=days)).isoformat()

    # -- accounts and sign-in ------------------------------------------------
    print("\n# Accounts")
    register("anna", "Анна")
    anna = Browser()
    check("the first account signs in with its password", anna.login("anna"), "302 .")
    settings = {
        "open_registrations": 1,
        "max_users": 0,
        "require_email_validation": 0,
        "server_url": "",
        "disable_login": 0,
    }
    anna.post("/endpoints/admin/saveopenregistrations.php", json_body=settings)
    register("boris", "Борис")
    anna.post(
        "/endpoints/admin/saveopenregistrations.php",
        json_body=settings | {"open_registrations": 0},
    )
    boris = Browser()
    check("a second account, registered while the admin allowed it", boris.login("boris"), "302 .")
    check(
        "registration is closed again",
        sql("SELECT registrations_open FROM admin"),
        "0",
    )

    # -- records -------------------------------------------------------------
    print("\n# Records (web form)")
    uid = {name: sql(f"SELECT id FROM user WHERE username='{name}'") for name in ("anna", "boris")}

    def form(user: str, **fields) -> dict:
        defaults = {
            "currency_id": sql(f"SELECT main_currency FROM user WHERE id={uid[user]}"),
            "payment_method_id": sql(
                f"SELECT id FROM payment_methods WHERE user_id={uid[user]} ORDER BY id LIMIT 1"
            ),
            "payer_user_id": sql(
                f"SELECT id FROM household WHERE user_id={uid[user]} ORDER BY id LIMIT 1"
            ),
            "category_id": sql(
                f"SELECT id FROM categories WHERE user_id={uid[user]} ORDER BY id LIMIT 1"
            ),
            "start_date": "",
            "notes": "",
            "url": "",
            "logo-url": "",
            "cancellation_date": "",
            "replacement_subscription_id": "0",
            "notifications": "on",
            "notify_days_before": "-1",
            "frequency": "1",
        }
        return defaults | fields

    def saved(response: str) -> str:
        return json.loads(response).get("status", "?")

    add = "/endpoints/subscription/add.php"
    check(
        "subscription",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="subscription",
                    name="Netflix",
                    price="500",
                    cycle="3",
                    next_payment=d(2),
                ),
            )
        ),
        "Success",
    )
    check(
        "yearly subscription",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="subscription",
                    name="Spotify",
                    price="1200",
                    cycle="4",
                    next_payment=d(40),
                ),
            )
        ),
        "Success",
    )
    check(
        "shelf-life date",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="expiry",
                    name="Витамины",
                    price="",
                    cycle="5",
                    next_payment=d(-2),
                    notify_days_before="3",
                ),
            )
        ),
        "Success",
    )
    check(
        "maintenance",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="maintenance",
                    name="Фильтр",
                    price="1500",
                    cycle="3",
                    frequency="3",
                    next_payment=d(20),
                ),
            )
        ),
        "Success",
    )
    check(
        "rent due on the 31st, renewed by hand",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="subscription",
                    name="Аренда",
                    price="30000",
                    cycle="3",
                    next_payment="2027-01-31",
                ),
            )
        ),
        "Success",
    )
    check(
        "a subscription without a price is refused",
        saved(
            anna.post(
                add,
                form("anna", kind="subscription", name="X", price="", cycle="3", next_payment=d(5)),
            )
        ),
        "Error",
    )
    check(
        "an impossible date is refused",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    kind="subscription",
                    name="X",
                    price="1",
                    cycle="3",
                    next_payment="2027-02-30",
                ),
            )
        ),
        "Error",
    )
    check(
        "boris's own record",
        saved(
            boris.post(
                add,
                form(
                    "boris",
                    kind="subscription",
                    name="Секрет Бориса",
                    price="1",
                    cycle="3",
                    next_payment=d(3),
                ),
            )
        ),
        "Success",
    )

    print("\n# Dashboard")
    _, _, home = anna.request("/index.php")
    active = home.split('shelflife-records">', 1)[1].split(
        '<div class="upcoming-subscriptions">', 1
    )[0]
    check(
        "active records, soonest first",
        re.findall(r'subscription-item-title">([^<]*)', active),
        ["Витамины", "Netflix", "Фильтр", "Spotify", "Аренда"],
    )
    check(
        "green / yellow / red",
        re.findall(r"shelflife-status-(\w+)", active)[:3],
        ["overdue", "soon", "ok"],
    )
    check(
        "days left",
        re.findall(r'shelflife-days-left">([^<]*)', active)[:2],
        ["просрочено на 2 дня", "через 2 дня"],
    )
    budget = home.split('class="budget-subscriptions"', 1)[-1]
    monthly = re.search(r'subscription-item-value">\s*([^<]*?)\s*</p>', budget)
    check(
        "monthly spend counts paid subscriptions only (500 + 1200/12 + 30000)",
        re.sub(r"\D", "", monthly.group(1)) if monthly else None,
        "3060000",
    )
    check("boris does not see anna's records", "Netflix" in boris.request("/index.php")[2], False)
    check("anna does not see boris's record", "Секрет Бориса" in home, False)

    print("\n# Access to other accounts")
    boris_record = sql("SELECT id FROM subscriptions WHERE name='Секрет Бориса'")
    check(
        "anna cannot edit boris's record on the website",
        saved(
            anna.post(
                add,
                form(
                    "anna",
                    id=boris_record,
                    kind="subscription",
                    name="Взлом",
                    price="1",
                    cycle="3",
                    next_payment=d(3),
                ),
            )
        ),
        "Error",
    )
    anna_key = sql(f"SELECT api_key FROM user WHERE id={uid['anna']}")
    _, _, api = anna.request(
        "/api/subscriptions/set_subscriptions.php",
        {"api_key": anna_key, "action": "delete", "id": boris_record},
    )
    check("nor delete it with her API key", json.loads(api)["success"], False)
    check(
        "boris's record is untouched",
        sql(f"SELECT name FROM subscriptions WHERE id={boris_record}"),
        "Секрет Бориса",
    )

    print("\n# Wallos API (API key)")

    def api_call(key: str, **fields) -> dict:
        page = Browser().request(
            "/api/subscriptions/set_subscriptions.php", {"api_key": key} | fields
        )
        return json.loads(page[2])

    created = api_call(
        anna_key,
        action="add",
        name="Котёл",
        kind="maintenance",
        price="0",
        cycle="4",
        frequency="1",
        next_payment=d(10),
        currency_id=sql(f"SELECT main_currency FROM user WHERE id={uid['anna']}"),
    )
    check("API add", created["success"], True)
    api_id = created.get("subscriptionId")
    check(
        "API add stores the kind and the date",
        sql(f"SELECT kind || ' ' || next_payment FROM subscriptions WHERE id={api_id}"),
        f"maintenance {d(10)}",
    )
    api_call(anna_key, action="edit", id=str(api_id), price="250,50")
    check(
        "API edit (comma decimal)",
        sql(f"SELECT price FROM subscriptions WHERE id={api_id}"),
        "250.5",
    )
    check(
        "API edit refuses an impossible date",
        api_call(anna_key, action="edit", id=str(api_id), next_payment="2027-02-29")["success"],
        False,
    )
    check(
        "API add refuses a subscription without a price",
        api_call(
            anna_key, action="add", name="Без цены", cycle="3", frequency="1", next_payment=d(10)
        )["success"],
        False,
    )
    boris_key = sql(f"SELECT api_key FROM user WHERE id={uid['boris']}")
    check(
        "boris's API key cannot edit anna's record",
        api_call(boris_key, action="edit", id=str(api_id), name="Взлом")["success"],
        False,
    )
    check("API delete", api_call(anna_key, action="delete", id=str(api_id))["success"], True)
    check(
        "and the record is gone", sql(f"SELECT COUNT(*) FROM subscriptions WHERE id={api_id}"), "0"
    )

    print("\n# Dates on the 29th-31st")
    rent = sql("SELECT id FROM subscriptions WHERE name='Аренда'")

    def renew() -> None:
        anna.post("/endpoints/subscription/renew.php", json_body={"id": int(rent)})

    sql(f"UPDATE subscriptions SET auto_renew = 0 WHERE id = {rent}")
    renew()
    check(
        "31 January renewed -> 28 February",
        sql(f"SELECT next_payment FROM subscriptions WHERE id={rent}"),
        "2027-02-28",
    )
    renew()
    check(
        "-> back to 31 March",
        sql(f"SELECT next_payment FROM subscriptions WHERE id={rent}"),
        "2027-03-31",
    )
    for month, year, day in [(4, 2027, "30"), (2, 2028, "29")]:
        _, _, month_page = anna.request(f"/calendar.php?month={month}&year={year}")
        days = re.findall(r'<span class="day">(\d+)</span>|title="(Аренда)"', month_page)
        last_day = None
        found = None
        for number, name in days:
            if number:
                last_day = number
            elif name:
                found = last_day
                break
        check(f"calendar {month:02d}/{year}: rent on the {day}th", found, day)

    # -- Telegram ------------------------------------------------------------
    print("\n# Linking Telegram")
    client = WallosClient(f"{BASE}/api/internal/telegram", env("SHELFLIFE_SERVICE_KEY"))
    try:
        _, _, profile = anna.request("/profile.php")
        anna.csrf = re.search(r'window\.csrfToken = "([^"]+)"', profile).group(1)
        issued = json.loads(anna.post("/endpoints/telegram/link_token.php"))
        check(
            "the profile issues a t.me link",
            issued["link"],
            f"https://t.me/{env('TELEGRAM_BOT_USERNAME')}?start={issued['token']}",
        )
        start = TgMessage(TgUser(555, "anna_tg"))
        await common.cmd_start_link(
            start, common.CommandObject(prefix="/", command="start", args=issued["token"]), client
        )
        check("/start <token> links the account", "<b>anna</b> привязан" in start.answers[0], True)
        reuse = TgMessage(TgUser(777))
        await common.cmd_start_link(
            reuse, common.CommandObject(prefix="/", command="start", args=issued["token"]), client
        )
        check(
            "the same link a second time does nothing",
            reuse.answers[0],
            common.LINK_RESULTS["invalid_token"],
        )
        check("the profile shows the link", "@anna_tg" in anna.request("/profile.php")[2], True)

        print("\n# /add")
        message = TgMessage(TgUser(555))
        await add_handlers.add_from_line(message, "Spotify 15.11 500rub", client, next_update())
        check(
            "the specification example",
            [line for i, line in enumerate(message.answers[0].split("\n")) if i in (0, 2, 3, 5)],
            [
                "✅ Запись добавлена",
                "<b>Spotify</b>",
                "Подписка · каждый месяц",
                "Сумма: 500\u00a0₽",
            ],
        )
        tomorrow = (today + timedelta(days=1)).strftime("%d.%m.%Y")
        update = next_update()
        for _ in range(2):
            message = TgMessage(TgUser(555))
            await add_handlers.add_from_line(message, f"Молоко {tomorrow}", client, update)
        check(
            "a repeated Telegram update adds once",
            sql(
                f"SELECT COUNT(*) FROM subscriptions WHERE name='Молоко' AND user_id={uid['anna']}"
            ),
            "1",
        )
        message = TgMessage(TgUser(888))
        await add_handlers.add_from_line(message, "Spotify 15.11 500rub", client, next_update())
        check(
            "an unlinked Telegram account cannot add",
            "привяжите аккаунт" in message.answers[0],
            True,
        )

        print("\n# Reminders")
        captured = php(
            "chdir('/var/www/html/endpoints/cronjobs');"
            "require '/var/www/html/includes/connect_endpoint_crontabs.php';"
            "require '/var/www/html/includes/shelflife/notifications.php';"
            "$sent = [];"
            "$send = function ($chat, $text, $markup) use (&$sent) { $sent[] = compact('chat', 'text', 'markup');"
            " return ['ok' => true, 'result' => ['message_id' => count($sent)], 'error_code' => null, 'description' => null, 'retry_after' => null, 'network_error' => null]; };"
            "$first = shelflife_notify_run($db, $send, shelflife_today(), time());"
            "$second = shelflife_notify_run($db, $send, shelflife_today(), time() + 60);"
            "echo json_encode(['first' => $first, 'second' => $second, 'sent' => $sent]);"
        )
        run = json.loads(captured)
        texts = {m["text"]: m for m in run["sent"]}
        milk = next((m for t, m in texts.items() if "Молоко" in t), None)
        vitamins = next((m for t, m in texts.items() if "Витамины" in t), None)
        check(
            "reminders go to the linked Telegram account", {m["chat"] for m in run["sent"]}, {555}
        )
        check(
            "the shelf-life reminder card",
            (
                [line for i, line in enumerate(milk["text"].split("\n")) if i in (0, 2, 4)]
                if milk
                else None
            ),
            ["🔔 Срок годности истекает завтра", "<b>Молоко</b>", f"Дата: {tomorrow}"],
        )
        check("an overdue shelf-life date is still announced", vitamins is not None, True)
        check("a second run sends nothing again", run["second"]["sent"], 0)
        check(
            "boris (not linked) gets nothing",
            any("Бориса" in m["text"] for m in run["sent"]),
            False,
        )

        print("\n# Buttons")
        buttons = {
            b["text"]: b["callback_data"] for row in milk["markup"]["inline_keyboard"] for b in row
        }
        check("three buttons", list(buttons), ["Продлено на месяц", "Отменено", "Напомнить позже"])
        check(
            "«Напомнить позже»",
            await press(client, buttons["Напомнить позже"], 555),
            f"⏰ Напомню завтра, {tomorrow}.",
        )
        renewed = plus_month(today + timedelta(days=1))
        check(
            "«Продлено на месяц» moves the date a month on",
            await press(client, buttons["Продлено на месяц"], 555),
            f"✅ Продлено. Следующая дата — {renewed.strftime('%d.%m.%Y')}.",
        )
        check(
            "the website shows the new date",
            sql("SELECT next_payment FROM subscriptions WHERE name='Молоко'"),
            renewed.isoformat(),
        )
        check(
            "pressing it again does nothing",
            await press(client, buttons["Продлено на месяц"], 555),
            f"Уже обработано: следующая дата — {renewed.strftime('%d.%m.%Y')}.",
        )
        vitamin_buttons = {
            b["text"]: b["callback_data"]
            for row in vitamins["markup"]["inline_keyboard"]
            for b in row
        }
        check(
            "another Telegram user cannot press anna's button",
            await press(client, vitamin_buttons["Отменено"], 777),
            "Этот Telegram не привязан к аккаунту ShelfLife. Привяжите его в профиле на сайте.",
        )
        check(
            "«Отменено»",
            await press(client, vitamin_buttons["Отменено"], 555),
            "❌ Отменено. Напоминаний по этой записи больше не будет.",
        )
        check(
            "the record is inactive on the website",
            sql("SELECT inactive FROM subscriptions WHERE name='Витамины'"),
            "1",
        )

        print("\n# Sections, record cards and settings (bot)")
        overview = await client.overview(555)
        names = [item.name for item in overview.items]
        check(
            "the overview holds anna's records only",
            ("Netflix" in names, "Секрет Бориса" in names),
            (True, False),
        )
        check("an unlinked Telegram account gets no overview", await client.overview(888), None)
        check(
            "the home screen greets anna",
            screens.home(overview, None).text.split("\n")[2],
            "Здравствуйте, Анна!",
        )
        milk_item = next(item for item in overview.items if item.name == "Молоко")
        check(
            "the card shows the date the button moved it to",
            f"Дата: {renewed.strftime('%d.%m.%Y')}" in screens.card(overview, milk_item, None).text,
            True,
        )
        days_sql = f"SELECT days FROM notification_settings WHERE user_id={uid['anna']}"
        update = next_update()
        result = await client.settings(
            telegram_id=555, update_id=update.update_id, op="reminder_days", days=3
        )
        check("the default reminder is saved", (result.status, sql(days_sql)), ("saved", "3"))
        result = await client.settings(
            telegram_id=555, update_id=next_update().update_id, op="reminder_days", days=9
        )
        check(
            "a value the website does not offer is refused",
            (result.status, sql(days_sql)),
            ("invalid", "3"),
        )
        await client.settings(
            telegram_id=555, update_id=next_update().update_id, op="reminder_days", days=1
        )
        message = TgMessage(TgUser(555))
        due = today + timedelta(days=20)
        await add_handlers.add_from_line(
            message, f"Временная {due.strftime('%d.%m.%Y')}", client, next_update()
        )
        temp_id = int(sql("SELECT id FROM subscriptions WHERE name='Временная'"))
        result = await client.act(
            telegram_id=777, update_id=next_update().update_id, subscription_id=temp_id,
            action="delete", expected_due=due.isoformat(),
        )  # fmt: skip
        check("another Telegram user cannot delete it", result.status, "not_linked")
        result = await client.act(
            telegram_id=555, update_id=next_update().update_id, subscription_id=temp_id,
            action="delete", expected_due=due.isoformat(),
        )  # fmt: skip
        check(
            "«Удалить» deletes the record",
            (result.status, sql("SELECT COUNT(*) FROM subscriptions WHERE name='Временная'")),
            ("done", "0"),
        )
        vitamins_due = sql("SELECT next_payment FROM subscriptions WHERE name='Витамины'")
        result = await client.act(
            telegram_id=555, update_id=next_update().update_id,
            subscription_id=int(sql("SELECT id FROM subscriptions WHERE name='Витамины'")),
            action="reactivate", expected_due=vitamins_due,
        )  # fmt: skip
        check(
            "«Вернуть в работу» reactivates a cancelled record",
            (result.status, sql("SELECT inactive FROM subscriptions WHERE name='Витамины'")),
            ("done", "0"),
        )
    finally:
        await client.close()

    print("\n# Signing in with Telegram")
    token = env("TELEGRAM_BOT_TOKEN")
    visitor = Browser()
    status, location, _ = visitor.request(
        "/telegram_login.php?" + widget_query(token, 555, int(time.time()))
    )
    check("the widget signs the linked account in", f"{status} {location}", "302 .")
    check("onto anna's dashboard", "Netflix" in visitor.request("/index.php")[2], True)
    _, location, _ = Browser().request(
        "/telegram_login.php?" + widget_query(token, 999, int(time.time()))
    )
    check(
        "an unlinked Telegram account is refused", location, "login.php?error=telegram_not_linked"
    )
    _, location, _ = Browser().request(
        "/telegram_login.php?" + widget_query("another:token", 555, int(time.time()))
    )
    check(
        "data signed for another bot is refused", location, "login.php?error=telegram_auth_failed"
    )

    print("\n# Mini App")
    with Browser().opener.open(BASE + "/tma/index.php", timeout=30) as response:
        page = response.read().decode()
        csp = response.headers.get("Content-Security-Policy", "")
    check("the Mini App page is served", "app.js?v" in page, True)
    check(
        "its scripts come only from the site and Telegram",
        "script-src 'self' https://telegram.org;" in csp,
        True,
    )

    def init_data(telegram_id: int, bot_token: str = token, age: int = 0) -> str:
        fields = {
            "auth_date": str(int(time.time()) - age),
            "query_id": "AAHacceptance",
            "user": json.dumps(
                {"id": telegram_id, "first_name": "Anna", "username": "anna_tg"},
                separators=(",", ":"),
            ),
        }
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(fields)

    def tma(init: str | None, body: dict | None = None) -> tuple[int, dict]:
        headers = {} if init is None else {"X-Telegram-Init-Data": init}
        status, _, text = Browser().request(
            "/api/tma/app.php", headers=headers, json_body=body or {"op": "state"}
        )
        return status, json.loads(text)

    anna_init = init_data(555)
    check("a GET is refused", Browser().request("/api/tma/app.php")[0], 405)
    check("without init data", tma(None), (401, {"status": "unauthorized", "reason": "missing"}))
    check(
        "init data with a changed user",
        tma(anna_init.replace("%22id%22%3A555", "%22id%22%3A556"))[1].get("reason"),
        "bad_hash",
    )
    check(
        "init data signed for another bot",
        tma(init_data(555, "654321:another-bot"))[1].get("reason"),
        "bad_hash",
    )
    check(
        "init data older than a day", tma(init_data(555, age=2 * 86400))[1].get("reason"), "expired"
    )
    check("an unlinked Telegram account", tma(init_data(999))[1]["status"], "not_linked")
    status, body = tma(anna_init)
    app_names = [r["name"] for r in body["state"]["records"]]
    check(
        "the linked account sees its own records only",
        (status, body["status"], "Netflix" in app_names, "Секрет Бориса" in app_names),
        (200, "ok", True, False),
    )
    create = {
        "op": "save",
        "request_id": "acceptance-create-1",
        "record": {
            "kind": "maintenance", "name": "Котёл, ТО", "price": "3000",
            "currency_id": int(sql(f"SELECT main_currency FROM user WHERE id={uid['anna']}")),
            "cycle": 4, "frequency": 1, "next_payment": d(40),
        },
    }  # fmt: skip
    _, first = tma(anna_init, create)
    _, again = tma(anna_init, create)
    check(
        "a record added in the app, once for a repeated request",
        (first["status"], again.get("id") == first.get("id"),
         sql("SELECT COUNT(*) FROM subscriptions WHERE name='Котёл, ТО'")),
        ("saved", True, "1"),
    )  # fmt: skip
    _, edited = tma(
        anna_init,
        {
            "op": "save",
            "request_id": "acceptance-edit-1",
            "record": {"id": first["id"], "name": "Котёл — ТО"},
        },
    )
    check(
        "edited in the app, other fields kept",
        (
            edited["status"],
            sql(
                f"SELECT name || '|' || price || '|' || cycle FROM subscriptions WHERE id={first['id']}"
            ),
        ),
        ("saved", "Котёл — ТО|3000.0|4"),
    )
    secret_id = sql("SELECT id FROM subscriptions WHERE name='Секрет Бориса'")
    secret_due = sql(f"SELECT next_payment FROM subscriptions WHERE id={secret_id}")
    _, foreign_edit = tma(
        anna_init,
        {
            "op": "save",
            "request_id": "acceptance-edit-2",
            "record": {"id": int(secret_id), "name": "Взлом"},
        },
    )
    _, foreign_delete = tma(
        anna_init,
        {
            "op": "act",
            "request_id": "acceptance-act-1",
            "id": int(secret_id),
            "action": "delete",
            "expected_due": secret_due,
        },
    )
    check(
        "another account's record can be neither edited nor deleted",
        (foreign_edit["status"], foreign_delete["status"],
         sql(f"SELECT name FROM subscriptions WHERE id={secret_id}")),
        ("not_found", "not_found", "Секрет Бориса"),
    )  # fmt: skip
    netflix_id = sql(f"SELECT id FROM subscriptions WHERE name='Netflix' AND user_id={uid['anna']}")
    netflix_due = sql(f"SELECT next_payment FROM subscriptions WHERE id={netflix_id}")
    _, renewed_body = tma(
        anna_init,
        {
            "op": "act",
            "request_id": "acceptance-act-2",
            "id": int(netflix_id),
            "action": "renew",
            "expected_due": netflix_due,
        },
    )
    check(
        "«Продлить» in the app moves the date",
        (
            renewed_body["status"],
            sql(f"SELECT next_payment FROM subscriptions WHERE id={netflix_id}") > netflix_due,
        ),
        ("done", True),
    )
    _, saved_days = tma(
        anna_init, {"op": "settings", "request_id": "acceptance-set-1", "reminder_days": 4}
    )
    check(
        "the default reminder from the app", (saved_days["status"], sql(days_sql)), ("saved", "4")
    )
    tma(anna_init, {"op": "settings", "request_id": "acceptance-set-2", "reminder_days": 1})
    check(
        "a change without a request id is refused",
        tma(anna_init, {"op": "act"})[1]["status"],
        "invalid",
    )
    check(
        "unlinking needs a confirmation",
        tma(anna_init, {"op": "unlink", "request_id": "acceptance-unlink-1"})[1]["status"],
        "invalid",
    )
    check(
        "unlinking from the app",
        (tma(anna_init, {"op": "unlink", "request_id": "acceptance-unlink-2", "confirm": True})[1]["status"],
         sql(f"SELECT IFNULL(telegram_id, 'none') FROM user WHERE id={uid['anna']}"),
         tma(anna_init)[1]["status"]),
        ("unlinked", "none", "not_linked"),
    )  # fmt: skip

    print("\n# Forged requests and password guessing")
    records = sql("SELECT COUNT(*) FROM subscriptions")
    _, _, forged = anna.request(
        add,
        form("anna", kind="subscription", name="Forged", price="1", cycle="3", next_payment=d(5)),
    )
    check(
        "a form post without the CSRF token is refused",
        json.loads(forged)["message"],
        "Invalid CSRF token",
    )
    check("and changes nothing", sql("SELECT COUNT(*) FROM subscriptions"), records)
    guesser = Browser()
    for _ in range(5):
        guesser.request("/login.php", {"username": "boris", "password": "wrong-password"})
    status, location, _ = Browser().request(
        "/login.php", {"username": "boris", "password": PASSWORD}
    )
    check("after 5 wrong passwords even the right one is refused", f"{status} {location}", "200 ")
    check("other accounts are not affected", Browser().login("anna"), "302 .")

    print("\n# Logs")
    log = compose("logs", "web")
    problems = [
        line
        for line in log.splitlines()
        if re.search(r"fatal|warning|notice|deprecated", line, re.IGNORECASE)
        and not re.search(
            r"cron daemon|NOTICE: (fpm is running|ready to handle|Finishing|Terminating|exiting)|000016\.php on line 60",
            line,
        )
    ]
    check("no PHP errors or warnings", problems, [])

    print(f"\npassed={sum(RESULTS)} failed={len(RESULTS) - sum(RESULTS)}")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
