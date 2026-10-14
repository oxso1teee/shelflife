"""ShelfLife Mini App in a real browser, against a staging stack (not production).

Opens web/tma/index.php in Chrome the way Telegram opens it: with Telegram's own
telegram-web-app.js and signed launch data in the URL fragment
(#tgWebAppData=...&tgWebAppThemeParams=...). The data is signed here with the
stack's TELEGRAM_BOT_TOKEN, so the server checks it exactly as it checks
Telegram's. Then it goes through the screens a user would: home, records,
search, a record and its actions, adding and editing (Telegram's MainButton and
BackButton are pressed through telegram-web-app.js's own event entry point),
deleting, settings, the not-linked and outside-Telegram states, both themes and
a 320px screen, and checks the database after every change. Screenshots go to
--out.

What it cannot show: Telegram's own chrome (header, MainButton, BackButton are
drawn by the Telegram app, not by the page) and a real Telegram client.

Needs the stack used by scripts/acceptance.py after its run (users anna and
boris exist) and Playwright with Chrome:

    COMPOSE_PROJECT_NAME=shelflife-acceptance WEB_PORT=8285 \\
        python3 scripts/tma_ui_check.py --out /tmp/tma-shots [--sdk telegram-web-app.js]

--sdk serves a saved copy of https://telegram.org/js/telegram-web-app.js instead
of downloading it. The check links anna's account to Telegram id 555 in that
stack's database, adds and deletes its own records, and unlinks at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '8285')}"
SDK_URL = "https://telegram.org/js/telegram-web-app.js"
RESULTS: list[bool] = []

LIGHT = {
    "bg_color": "#ffffff", "text_color": "#000000", "hint_color": "#999999",
    "link_color": "#2481cc", "button_color": "#2481cc", "button_text_color": "#ffffff",
    "secondary_bg_color": "#efeff3", "header_bg_color": "#ffffff",
    "accent_text_color": "#2481cc", "section_bg_color": "#ffffff",
    "section_header_text_color": "#6d6d72", "subtitle_text_color": "#999999",
    "destructive_text_color": "#ff3b30",
}  # fmt: skip
DARK = {
    "bg_color": "#212121", "text_color": "#ffffff", "hint_color": "#aaaaaa",
    "link_color": "#8774e1", "button_color": "#8774e1", "button_text_color": "#ffffff",
    "secondary_bg_color": "#0f0f0f", "header_bg_color": "#212121",
    "accent_text_color": "#8774e1", "section_bg_color": "#212121",
    "section_header_text_color": "#aaaaaa", "subtitle_text_color": "#aaaaaa",
    "destructive_text_color": "#e53935",
}  # fmt: skip


def check(name: str, got, want) -> None:
    ok = got == want
    RESULTS.append(ok)
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f": expected {want!r}, got {got!r}"))


def compose(*args: str) -> str:
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def sql(query: str) -> str:
    return compose("exec", "-T", "web", "sqlite3", "/var/www/html/db/wallos.db", query)


def init_data(token: str, telegram_id: int, age: int = 0) -> str:
    fields = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAHuicheck",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Anna", "username": "anna_tg", "language_code": "ru"},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def launch_url(init: str | None, theme: dict, query: str = "") -> str:
    url = f"{BASE}/tma/index.php{query}"
    if init is None:
        return url
    params = {
        "tgWebAppData": init,
        "tgWebAppVersion": "8.0",
        "tgWebAppPlatform": "android",
        "tgWebAppThemeParams": json.dumps(theme, separators=(",", ":")),
    }
    return url + "#" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sdk", type=Path, help="a saved copy of telegram-web-app.js")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    token = compose("exec", "-T", "web", "printenv", "TELEGRAM_BOT_TOKEN")
    anna = sql("SELECT id FROM user WHERE username='anna'")
    if not anna:
        sys.exit("run scripts/acceptance.py on this stack first")
    sql(f"UPDATE user SET telegram_id=555, telegram_username='anna_tg' WHERE id={anna}")
    sql(f"UPDATE notification_settings SET days=1 WHERE user_id={anna}")
    today = date.fromisoformat(compose("exec", "-T", "web", "date", "+%Y-%m-%d"))
    sdk = args.sdk.read_text() if args.sdk else None

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)

        def open_app(init, theme=LIGHT, width=390, query="") -> tuple[Page, list[str]]:
            context = browser.new_context(
                viewport={"width": width, "height": 844},
                device_scale_factor=2,
                locale="ru-RU",
                color_scheme="dark" if theme is DARK else "light",
            )
            if sdk is not None:
                context.route(
                    SDK_URL,
                    lambda route: route.fulfill(body=sdk, content_type="application/javascript"),
                )
            page = context.new_page()
            problems: list[str] = []
            page.on(
                "console",
                lambda m: problems.append(m.text)
                if m.type == "error" and "Telegram.WebView" not in m.text
                else None,
            )
            page.on("pageerror", lambda e: problems.append(str(e)))
            page.goto(launch_url(init, theme, query))
            return page, problems

        def shot(page: Page, name: str) -> None:
            page.wait_for_timeout(250)  # let a toast or a sheet finish appearing
            page.screenshot(path=str(args.out / f"{name}.png"), full_page=True)

        def tg(page: Page, event: str) -> None:
            page.evaluate(f"window.Telegram.WebView.receiveEvent('{event}')")

        def no_overflow(page: Page) -> bool:
            return page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )

        anna_init = init_data(token, 555)

        print("\n# Home")
        page, problems = open_app(anna_init)
        expect(page.locator(".hello h1")).to_have_text("Здравствуйте, Анна!")
        check("the launch data is accepted", page.evaluate("Telegram.WebApp.initData.length > 0"), True)
        check("the five tabs", page.locator(".tab span").all_inner_texts(),
              ["Главная", "Записи", "Скоро", "Расходы", "Настройки"])  # fmt: skip
        check("the theme comes from Telegram", page.evaluate(
            "getComputedStyle(document.body).backgroundColor"), "rgb(239, 239, 243)")  # fmt: skip
        check("no Back button on a tab", page.evaluate("Telegram.WebApp.BackButton.isVisible"), False)
        shot(page, "01-home-light")

        print("\n# Records")
        page.click(".tab[data-tab=records]")
        expect(page.locator(".page-title")).to_have_text("Записи")
        all_rows = page.locator(".row").count()
        page.fill(".search input", "net")
        check("search finds Netflix", page.locator(".row-name").all_inner_texts(), ["Netflix"])
        page.fill(".search input", "")
        page.click(".chip[data-filter=expiry]")
        check(
            "the expiry filter",
            set(page.locator(".row-name").all_inner_texts()) <= {"Витамины", "Молоко"},
            True,
        )
        page.click(".chip[data-filter=all]")
        check("every active record is listed", page.locator(".row").count(), all_rows)
        shot(page, "02-records-light")

        print("\n# A record")
        netflix_id = sql(f"SELECT id FROM subscriptions WHERE name='Netflix' AND user_id={anna} ORDER BY id LIMIT 1")
        before = sql(f"SELECT next_payment FROM subscriptions WHERE id={netflix_id}")
        page.click(f".row[data-record='{netflix_id}']")
        expect(page.locator(".record-head h1")).to_have_text("Netflix")
        check("the Back button is shown over a tab", page.evaluate("Telegram.WebApp.BackButton.isVisible"), True)
        shot(page, "03-card-light")
        page.get_by_role("button", name="Продлить").click()
        expect(page.locator(".toast")).to_contain_text("Продлено. Следующая дата")
        after = sql(f"SELECT next_payment FROM subscriptions WHERE id={netflix_id}")
        check("«Продлить» moved the date on the website", after > before, True)
        check(
            "the card shows the new date",
            page.locator(".fact", has_text="Дата").inner_text().split("\n")[-1].split(" — ")[0],
            ".".join(reversed(after.split("-"))),
        )
        tg(page, "back_button_pressed")
        expect(page.locator(".page-title")).to_have_text("Записи")
        check("Back returns to the list", page.evaluate("Telegram.WebApp.BackButton.isVisible"), False)

        print("\n# Adding")
        page.click(".fab")
        expect(page.locator(".page-title")).to_have_text("Новая запись")
        check("the MainButton offers to add", page.evaluate(
            "[Telegram.WebApp.MainButton.isVisible, Telegram.WebApp.MainButton.text]"),
            [True, "Добавить запись"])  # fmt: skip
        check("no tab bar over the form", page.locator(".tabbar").count(), 0)
        tg(page, "main_button_pressed")
        expect(page.locator(".field.invalid .field-error").first).to_have_text("Укажите название.")
        check(
            "an empty form is not sent",
            page.locator(".field-error").all_inner_texts(),
            ["Укажите название.", "Укажите дату.", "У подписки должна быть сумма."],
        )
        shot(page, "04-form-errors-light")
        due = (today + timedelta(days=12)).isoformat()
        page.fill("input[name=name]", "Кинопоиск <test> & co")
        page.fill("input[name=next_payment]", due)
        page.fill("input[name=price]", "299,5")
        page.select_option("select[name=cycle]", "custom")
        page.fill("input[name=custom_every]", "2")
        page.select_option("select[name=custom_unit]", "2")
        page.select_option("select[name=notify_days_before]", "3")
        check("leaving with changes asks first", page.evaluate("Telegram.WebApp.isClosingConfirmationEnabled"), True)
        shot(page, "05-form-filled-light")
        tg(page, "main_button_pressed")
        expect(page.locator(".toast")).to_have_text("Запись добавлена.")
        expect(page.locator(".record-head h1")).to_have_text("Кинопоиск <test> & co")
        row = sql(
            "SELECT kind||'|'||price||'|'||cycle||'|'||frequency||'|'||next_payment||'|'||notify_days_before "
            f"FROM subscriptions WHERE user_id={anna} AND name LIKE 'Кинопоиск%'"
        )
        check("saved on the website", row, f"subscription|299.5|2|2|{due}|3")
        check(
            "the name keeps its characters as text",
            page.locator(".record-head h1").inner_html(),
            "Кинопоиск &lt;test&gt; &amp; co",
        )
        shot(page, "06-card-new-light")

        print("\n# Editing")
        page.get_by_role("button", name="Изменить").click()
        expect(page.locator("input[name=name]")).to_have_value("Кинопоиск <test> & co")
        check("the MainButton saves", page.evaluate("Telegram.WebApp.MainButton.text"), "Сохранить")
        page.fill("input[name=name]", "Кинопоиск")
        tg(page, "main_button_pressed")
        expect(page.locator(".toast")).to_have_text("Изменения сохранены.")
        check(
            "the edit is on the website, the rest kept",
            sql(f"SELECT name||'|'||price||'|'||frequency FROM subscriptions WHERE user_id={anna} AND name LIKE 'Кинопоиск%'"),
            "Кинопоиск|299.5|2",
        )  # fmt: skip

        print("\n# Deleting")
        page.get_by_role("button", name="Удалить").click()
        expect(page.locator(".sheet h2")).to_have_text("Удалить «Кинопоиск»?")
        shot(page, "07-delete-sheet-light")
        tg(page, "back_button_pressed")
        check("Back closes the dialog only", (page.locator(".sheet").count(),
              page.locator(".record-head h1").inner_text()), (0, "Кинопоиск"))  # fmt: skip
        page.get_by_role("button", name="Удалить").click()
        page.locator(".sheet .btn.danger").click()
        expect(page.locator(".toast")).to_have_text("Запись удалена.")
        check(
            "deleted on the website",
            sql(f"SELECT COUNT(*) FROM subscriptions WHERE user_id={anna} AND name LIKE 'Кинопоиск%'"),
            "0",
        )

        print("\n# Soon, spending, settings")
        page.click(".tab[data-tab=soon]")
        expect(page.locator(".page-title")).to_have_text("Скоро")
        shot(page, "08-soon-light")
        page.click(".tab[data-tab=spend]")
        expect(page.locator(".page-title")).to_have_text("Расходы")
        subscriptions = sql(
            f"SELECT COUNT(*) FROM subscriptions WHERE user_id={anna} AND kind='subscription'"
            " AND inactive=0 AND price>0 AND cycle<>5"
        )
        check(
            "the monthly spending, per currency",
            page.locator(".money-line .label").first.inner_text(),
            f"{subscriptions} подписки",
        )
        shot(page, "09-spend-light")
        page.click(".tab[data-tab=settings]")
        page.click(".days button[data-days='3']")
        expect(page.locator(".toast")).to_have_text("Сохранено: напоминать за 3 дня.")
        check("the default reminder on the website", sql(
            f"SELECT days FROM notification_settings WHERE user_id={anna}"), "3")  # fmt: skip
        shot(page, "10-settings-light")
        page.click(".days button[data-days='1']")
        expect(page.locator(".toast")).to_have_text("Сохранено: напоминать за 1 день.")
        check("no script errors or blocked resources", problems, [])
        page.context.close()

        print("\n# Opened from the bot's card: ?edit=<id>")
        spotify = sql(f"SELECT id FROM subscriptions WHERE name='Spotify' AND user_id={anna} ORDER BY id LIMIT 1")
        page, problems = open_app(anna_init, query=f"?edit={spotify}")
        expect(page.locator("input[name=name]")).to_have_value("Spotify")
        tg(page, "back_button_pressed")
        expect(page.locator(".record-head h1")).to_have_text("Spotify")
        check("Back from it shows the record", problems, [])
        page.context.close()

        print("\n# Dark theme")
        page, problems = open_app(anna_init, DARK)
        expect(page.locator(".hello h1")).to_be_visible()
        check("dark background from Telegram", page.evaluate(
            "getComputedStyle(document.body).backgroundColor"), "rgb(15, 15, 15)")  # fmt: skip
        shot(page, "11-home-dark")
        page.click(".tab[data-tab=records]")
        page.click(f".row[data-record='{netflix_id}']")
        shot(page, "12-card-dark")
        tg(page, "back_button_pressed")
        page.click(".fab")
        shot(page, "13-form-dark")
        page.context.close()

        print("\n# A 320px screen")
        page, _ = open_app(anna_init, width=320)
        expect(page.locator(".hello h1")).to_be_visible()
        fits = [no_overflow(page)]
        for tab in ("records", "soon", "spend", "settings"):
            page.click(f".tab[data-tab={tab}]")
            fits.append(no_overflow(page))
        page.click(".tab[data-tab=records]")
        page.locator(".row").first.click()
        fits.append(no_overflow(page))
        page.get_by_role("button", name="Изменить").click()
        fits.append(no_overflow(page))
        check("nothing wider than the screen", fits, [True] * len(fits))
        shot(page, "14-form-320")
        page.context.close()

        print("\n# Formatting, as the bot writes it")
        page, _ = open_app(None)
        expect(page.locator(".state h1")).to_have_text("Откройте ShelfLife в Telegram")
        check(
            "amounts and dates",
            page.evaluate(
                "[ShelfLifeFormat.amount(30930.65, '₽'), ShelfLifeFormat.amount(500, '₽'),"
                " ShelfLifeFormat.amount(0.125, '$'), ShelfLifeFormat.amount(0.375, '$'),"
                " ShelfLifeFormat.relativeDays(-2), ShelfLifeFormat.relativeDays(21),"
                " ShelfLifeFormat.period(3, 3), ShelfLifeFormat.renewPeriod(4, 1)]"
            ),
            ["30\xa0930,65\xa0₽", "500\xa0₽", "0,12\xa0$", "0,38\xa0$", "2 дня назад",
             "через 21 день", "каждые 3 месяца", "год"],
        )  # fmt: skip
        print("\n# Without an account")
        shot(page, "15-outside-telegram")
        check("outside Telegram: a link to the bot", page.locator(".state a.btn").get_attribute("href"),
              "https://t.me/" + compose("exec", "-T", "web", "printenv", "TELEGRAM_BOT_USERNAME"))  # fmt: skip
        page.context.close()

        page, _ = open_app(init_data(token, 999))
        expect(page.locator(".state h1")).to_have_text("Аккаунт ещё не привязан")
        shot(page, "16-not-linked")
        page.context.close()

        page, _ = open_app(init_data(token, 555, age=3 * 86400))
        expect(page.locator(".state h1")).to_have_text("Сессия устарела")
        page.context.close()

        page, _ = open_app(init_data("654321:another-bot", 555))
        expect(page.locator(".state h1")).to_have_text("Telegram не подтвердил вход")
        page.context.close()

        print("\n# Unlinking")
        page, _ = open_app(anna_init)
        page.click(".tab[data-tab=settings]")
        page.get_by_role("button", name="Отвязать Telegram").click()
        page.locator(".sheet .btn.danger").click()
        expect(page.locator(".state h1")).to_have_text("Telegram отвязан")
        check("unlinked on the website", sql(
            f"SELECT IFNULL(telegram_id, 'none') FROM user WHERE id={anna}"), "none")  # fmt: skip
        shot(page, "17-unlinked")
        page.context.close()
        browser.close()

    print(f"\npassed={sum(RESULTS)} failed={len(RESULTS) - sum(RESULTS)}")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
