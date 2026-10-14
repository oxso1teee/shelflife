"""WallosClient against a real HTTP server standing in for the Wallos internal API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.wallos_client import Account, LinkResult, WallosClient, WallosError

KEY = "k" * 40
VALID_TOKEN = "a" * 32
# Wallos answers an update id already processed for another Telegram account
# with a bare {"status": "invalid"} (includes/shelflife/bot_actions.php).
REPLAYED_UPDATE = 99
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "overview.json").read_text())


@pytest.fixture
async def wallos():
    calls: list[tuple[str, str | None, dict]] = []

    async def link(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("link", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if request.headers.get("X-ShelfLife-Service-Key") != KEY:
            return web.json_response({"error": "unauthorized"}, status=401)
        if payload["token"] == VALID_TOKEN:
            return web.json_response({"status": "linked", "username": "alice"})
        if payload["token"] == "b" * 32:
            return web.json_response({"status": "surprise", "username": None})
        return web.json_response({"status": "invalid_token", "username": None})

    async def me(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("me", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if payload["telegram_id"] == 555:
            return web.json_response({"linked": True, "username": "alice"})
        return web.json_response({"linked": False, "username": None})

    record = {
        "id": 7,
        "kind": "subscription",
        "name": "Spotify",
        "next_payment": "2026-11-15",
        "price": 500.0,
        "currency": "RUB",
        "cycle": 3,
        "frequency": 1,
        "inactive": False,
        "snoozed_until": None,
    }

    async def item_add(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("item_add", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if payload["update_id"] == REPLAYED_UPDATE:
            return web.json_response({"status": "invalid"})
        if "price" not in payload:
            return web.json_response({"status": "invalid", "field": "price", "message": "x"})
        return web.json_response({"status": "created", "record": record})

    async def item_action(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("item_action", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if payload["update_id"] == REPLAYED_UPDATE:
            return web.json_response({"status": "invalid"})
        if payload["subscription_id"] != 7:
            return web.json_response({"status": "not_found"})
        return web.json_response(
            {
                "status": "done",
                "action": payload["action"],
                "record": record | {"next_payment": "2026-12-15"},
            }
        )

    async def overview(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("overview", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if payload["telegram_id"] == 555:
            return web.json_response(FIXTURE)
        if payload["telegram_id"] == 666:
            return web.json_response({"status": "linked", "overview": {"records": "broken"}})
        return web.json_response({"status": "not_linked"})

    async def settings(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(("settings", request.headers.get("X-ShelfLife-Service-Key"), payload))
        if payload["op"] == "unlink":
            return web.json_response({"status": "unlinked"})
        if payload.get("days") == 9:
            return web.json_response({"status": "invalid", "field": "reminder_days"})
        if payload["op"] == "reminder_days":
            return web.json_response({"status": "saved", "reminder_days": payload["days"]})
        return web.json_response({"status": "surprise"})

    app = web.Application()
    app.router.add_post("/api/internal/telegram/overview.php", overview)
    app.router.add_post("/api/internal/telegram/settings.php", settings)
    app.router.add_post("/api/internal/telegram/link.php", link)
    app.router.add_post("/api/internal/telegram/me.php", me)
    app.router.add_post("/api/internal/telegram/item_add.php", item_add)
    app.router.add_post("/api/internal/telegram/item_action.php", item_action)
    server = TestServer(app)
    await server.start_server()
    base_url = str(server.make_url("/api/internal/telegram"))
    yield base_url, calls
    await server.close()


async def test_link_sends_the_key_and_the_telegram_identity(wallos):
    base_url, calls = wallos
    client = WallosClient(base_url, KEY)
    try:
        result = await client.link(VALID_TOKEN, 555, "alice_tg")
    finally:
        await client.close()

    assert result == LinkResult(status="linked", username="alice")
    name, key, payload = calls[0]
    assert name == "link"
    assert key == KEY
    assert payload == {"token": VALID_TOKEN, "telegram_id": 555, "telegram_username": "alice_tg"}


async def test_a_refused_token_is_reported_not_raised(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        result = await client.link("c" * 32, 555, None)
    finally:
        await client.close()

    assert result == LinkResult(status="invalid_token", username=None)


async def test_a_wrong_key_raises_without_leaking_it(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, "w" * 40)
    try:
        with pytest.raises(WallosError) as error:
            await client.link(VALID_TOKEN, 555, None)
    finally:
        await client.close()

    assert "401" in str(error.value)
    assert "w" * 40 not in str(error.value)


async def test_an_unknown_status_is_an_error(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        with pytest.raises(WallosError):
            await client.link("b" * 32, 555, None)
    finally:
        await client.close()


async def test_account_lookup(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        assert await client.account(555) == Account(linked=True, username="alice")
        assert await client.account(777) == Account(linked=False, username=None)
    finally:
        await client.close()


async def test_an_unreachable_server_is_an_error():
    client = WallosClient("http://127.0.0.1:9/api/internal/telegram", KEY, timeout=2)
    try:
        with pytest.raises(WallosError):
            await client.account(555)
    finally:
        await client.close()


async def test_add_record_sends_only_the_given_fields(wallos):
    base_url, calls = wallos
    client = WallosClient(base_url, KEY)
    try:
        result = await client.add_record(
            telegram_id=555,
            update_id=1,
            kind="subscription",
            name="Spotify",
            next_payment="2026-11-15",
            price="500",
            currency="RUB",
        )
    finally:
        await client.close()

    assert result.status == "created"
    assert result.record is not None and result.record.name == "Spotify"
    assert calls[-1][2] == {
        "telegram_id": 555,
        "update_id": 1,
        "kind": "subscription",
        "name": "Spotify",
        "next_payment": "2026-11-15",
        "price": "500",
        "currency": "RUB",
    }


async def test_add_record_passes_validation_errors_through(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        result = await client.add_record(
            telegram_id=555, update_id=2, kind="subscription", name="X", next_payment="2026-11-15"
        )
    finally:
        await client.close()

    assert (result.status, result.field, result.record) == ("invalid", "price", None)


async def test_act_returns_the_record_after_the_change(wallos):
    base_url, calls = wallos
    client = WallosClient(base_url, KEY)
    try:
        done = await client.act(
            telegram_id=555,
            update_id=3,
            subscription_id=7,
            action="renew",
            expected_due="2026-11-15",
        )
        missing = await client.act(
            telegram_id=555,
            update_id=4,
            subscription_id=8,
            action="renew",
            expected_due="2026-11-15",
        )
    finally:
        await client.close()

    assert done.status == "done" and done.record is not None
    assert done.record.next_payment == "2026-12-15"
    assert (missing.status, missing.record) == ("not_found", None)
    assert calls[-2][2]["expected_due"] == "2026-11-15"


async def test_a_refused_repeated_update_carries_no_record(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        added = await client.add_record(
            telegram_id=556,
            update_id=REPLAYED_UPDATE,
            kind="subscription",
            name="X",
            next_payment="2026-11-15",
            price=5.0,
        )
        acted = await client.act(
            telegram_id=556,
            update_id=REPLAYED_UPDATE,
            subscription_id=7,
            action="renew",
            expected_due="2026-11-15",
        )
    finally:
        await client.close()

    assert (added.status, added.record, added.field, added.message) == ("invalid", None, None, None)
    assert (acted.status, acted.action, acted.record) == ("invalid", None, None)


async def test_overview_is_parsed_from_what_wallos_sends(wallos):
    base_url, calls = wallos
    client = WallosClient(base_url, KEY)
    try:
        ov = await client.overview(555)
        stranger = await client.overview(777)
    finally:
        await client.close()

    assert stranger is None
    assert calls[0][1:] == (KEY, {"telegram_id": 555})
    assert (ov.username, ov.first_name, ov.reminder_days) == ("anna", "Анна", 2)
    assert ov.site_url == "https://shelflife.example.com"
    assert ov.main_currency.code == "RUB"
    spotify = ov.item(1)
    assert (spotify.name, spotify.next_payment, spotify.status) == ("Spotify", "2026-10-15", "soon")
    assert spotify.currency.code == "RUB" and spotify.category == "Музыка"
    # Different currencies and no rates: per currency, no made-up total.
    assert [(m.currency.code, m.count) for m in ov.expenses.per_currency] == [
        ("RUB", 3),
        ("USD", 1),
    ]
    assert ov.expenses.total is None and ov.expenses.convertible is False


async def test_a_malformed_overview_is_an_error(wallos):
    base_url, _ = wallos
    client = WallosClient(base_url, KEY)
    try:
        with pytest.raises(WallosError):
            await client.overview(666)
    finally:
        await client.close()


async def test_settings_send_the_operation_and_read_the_result(wallos):
    base_url, calls = wallos
    client = WallosClient(base_url, KEY)
    try:
        saved = await client.settings(telegram_id=555, update_id=1, op="reminder_days", days=3)
        refused = await client.settings(telegram_id=555, update_id=2, op="reminder_days", days=9)
        unlinked = await client.settings(telegram_id=555, update_id=3, op="unlink")
        with pytest.raises(WallosError):
            await client.settings(telegram_id=555, update_id=4, op="other")
    finally:
        await client.close()

    assert (saved.status, saved.reminder_days) == ("saved", 3)
    assert (refused.status, refused.reminder_days) == ("invalid", None)
    assert unlinked.status == "unlinked"
    assert calls[0][2] == {"telegram_id": 555, "update_id": 1, "op": "reminder_days", "days": 3}
    assert calls[2][2] == {"telegram_id": 555, "update_id": 3, "op": "unlink"}
