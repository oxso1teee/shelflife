"""Reading the web app's overview (bot/overview.py): what is trusted, what is refused."""

from __future__ import annotations

import json

import pytest

from bot.overview import Overview
from bot.wallos_client import WallosError
from tests.conftest import FIXTURE


def data():
    return json.loads(json.dumps(FIXTURE["overview"]))


def test_the_fixture_is_read_whole():
    ov = Overview.from_json(data(), FIXTURE["site_url"])
    assert len(ov.items) == 8 and len(ov.active) == 7
    assert [key for key, _ in ov.upcoming] == ["overdue", "today", "tomorrow", "week", "month"]
    assert ov.later == 2
    assert ov.categories == [(1, None), (2, "Музыка"), (3, "Дом")]
    assert ov.item(8).name.startswith("Tom & <Jerry>")  # raw; screens escape it
    assert ov.item(999) is None
    old = ov.item(7)
    assert (old.inactive, old.status, old.monthly) == (True, "inactive", None)


@pytest.mark.parametrize(
    "site_url", [None, "", "http://shelflife.example.com", "javascript:alert(1)", 5]
)
def test_only_an_https_site_address_is_kept(site_url):
    assert Overview.from_json(data(), site_url).site_url is None


@pytest.mark.parametrize(
    "breaks",
    [
        lambda d: d.pop("account"),
        lambda d: d["records"][0].pop("id"),
        lambda d: d["records"][0].update(price="lots"),
        lambda d: d["upcoming"]["groups"][0]["records"][0].update(id=12345),
        lambda d: d["expenses"].pop("per_currency"),
        lambda d: d.update(records=None),
    ],
)
def test_a_malformed_overview_is_an_error_not_a_crash(breaks):
    broken = data()
    breaks(broken)
    with pytest.raises(WallosError):
        Overview.from_json(broken)


def test_not_a_dict_is_an_error():
    with pytest.raises(WallosError):
        Overview.from_json(None)
