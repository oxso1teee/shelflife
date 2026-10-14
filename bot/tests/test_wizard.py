"""The step-by-step /add through the real Dispatcher and FSM (see conftest.py).

The fixture account has two named categories (Музыка, Дом), so a dialog has
six steps; RUB is the main currency; today is 14.10.2026.
"""

from __future__ import annotations

from aiogram.methods import EditMessageText

from bot import screens
from bot.handlers import wizard
from bot.wallos_client import AddResult
from tests.conftest import overview


def last(tg, calls) -> str:
    return tg.texts(calls)[-1].replace("\xa0", " ")


def saved(tg) -> dict:
    name, payload = tg.wallos.calls[-1]
    assert name == "add_record"
    # As WallosClient.add_record sends it: fields left unset are not sent.
    payload = {key: value for key, value in payload.items() if value is not None}
    assert isinstance(payload.pop("update_id"), int)
    return payload


async def test_a_record_step_by_step(tg):
    calls = await tg.send("/add")
    assert last(tg, calls).startswith("<b>Новая запись</b> · шаг 1 из 6\n\nКак называется запись?")
    assert tg.buttons(calls) == [("Отмена", "w:cancel:")]

    calls = await tg.send("Spotify")
    assert last(tg, calls).startswith(
        "<b>Новая запись</b> · шаг 2 из 6\n\nЧто отслеживаем для <b>Spotify</b>?"
    )
    assert tg.buttons(calls)[:3] == [
        ("Подписка", "w:kind:sub"),
        ("Срок годности", "w:kind:exp"),
        ("Обслуживание", "w:kind:mnt"),
    ]

    calls = await tg.press("w:kind:sub", "шаг 2")
    closed = [c for c in calls if isinstance(c, EditMessageText)][0]
    assert closed.text == "шаг 2\n\n<i>Подписка</i>" and closed.reply_markup is None
    assert last(tg, calls).startswith("<b>Новая запись</b> · шаг 3 из 6\n\nКатегория")
    assert ("Музыка", "w:category:2") in tg.buttons(calls)
    assert ("Без категории", "w:category:0") in tg.buttons(calls)

    calls = await tg.press("w:category:2")
    assert "шаг 4 из 6\n\nКогда следующий платёж?" in last(tg, calls)

    calls = await tg.send("15.11")
    assert "шаг 5 из 6\n\nСумма платежа" in last(tg, calls)
    assert "Без валюты — в RUB." in last(tg, calls)
    assert not any(
        data == "w:amount:none" for _, data in tg.buttons(calls)
    )  # a subscription costs something

    calls = await tg.send("500rub")
    assert "шаг 6 из 6\n\nКак часто повторяется?" in last(tg, calls)
    assert len(tg.buttons(calls)) == 8  # six periods, back, cancel

    calls = await tg.press("w:period:3-1")
    preview = last(tg, calls)
    assert preview.startswith("<b>Проверьте и сохраните</b>")
    assert "Spotify" in preview and "15.11.2026" in preview and "500 ₽" in preview
    assert "Категория: Музыка" in preview
    assert tg.wallos.names == ["overview"]  # nothing saved before "Сохранить"

    calls = await tg.press("w:confirm:save")
    assert saved(tg) == {
        "telegram_id": 555,
        "kind": "subscription",
        "name": "Spotify",
        "next_payment": "2026-11-15",
        "price": "500",
        "currency": "RUB",
        "cycle": 3,
        "frequency": 1,
        "category_id": 2,
    }
    assert tg.answers(calls)[-1] == "Сохранено"
    assert last(tg, calls).startswith("✅ <b>Запись добавлена</b>")
    assert ("Открыть запись", "c:77:all:0") in tg.buttons(calls)
    assert await tg.dp.fsm.storage.get_state(key=_key()) is None


async def test_an_expiry_date_with_the_quick_buttons_and_no_amount(tg):
    await tg.send("/add")
    await tg.send("Молоко")
    await tg.press("w:kind:exp")
    calls = await tg.press("w:category:0")
    assert "До какой даты годен продукт?" in last(tg, calls)
    calls = await tg.press("w:due:m")
    assert "Сумма, если есть" in last(tg, calls)
    closed = [c for c in calls if isinstance(c, EditMessageText)][0]
    assert "14.11.2026 — через 31 день" in closed.text.replace("\xa0", " ")
    assert ("Без суммы", "w:amount:none") in tg.buttons(calls)
    await tg.press("w:amount:none")
    await tg.press("w:period:5-1")
    await tg.press("w:confirm:save")
    assert saved(tg) == {
        "telegram_id": 555,
        "kind": "expiry",
        "name": "Молоко",
        "next_payment": "2026-11-14",
        "cycle": 5,
        "frequency": 1,
        "category_id": 1,  # the account's "no category"
    }


async def test_a_one_line_entry_skips_to_the_confirmation(tg):
    await tg.send("/add")
    calls = await tg.send("Netflix 01.12.2026 9.99$ год")
    preview = last(tg, calls)
    assert preview.startswith("<b>Проверьте и сохраните</b>")
    assert "9,99 $" in preview and "01.12.2026" in preview
    await tg.press("w:confirm:save")
    assert saved(tg) == {
        "telegram_id": 555,
        "kind": "subscription",
        "name": "Netflix",
        "next_payment": "2026-12-01",
        "price": "9.99",
        "currency": "USD",
        "cycle": 4,
        "frequency": 1,
    }


async def test_back_from_a_one_line_confirmation_goes_through_the_steps(tg):
    await tg.send("/add")
    await tg.send("Spotify 15.11 500rub")
    calls = await tg.press("w:back:")
    assert "Как часто повторяется?" in last(tg, calls)
    calls = await tg.press("w:period:4-1")
    assert last(tg, calls).startswith("<b>Проверьте и сохраните</b>")
    await tg.press("w:confirm:save")
    assert saved(tg)["cycle"] == 4


async def test_add_with_a_name_only_starts_at_the_second_step(tg):
    calls = await tg.send("/add Фильтр для воды")
    assert "шаг 2 из 6" in last(tg, calls) and "<b>Фильтр для воды</b>" in last(tg, calls)


async def test_quick_add_with_a_date_still_saves_at_once(tg):
    await tg.send("/add Spotify 15.11 500rub")
    assert tg.wallos.names == ["add_record"]


async def test_back_returns_to_the_previous_step(tg):
    await tg.send("/add")
    await tg.send("Spotify")
    calls = await tg.press("w:back:")
    assert "шаг 1 из 6" in last(tg, calls)
    calls = await tg.send("Netflix")
    assert "<b>Netflix</b>" in last(tg, calls)


async def test_cancel_by_button_and_by_command(tg):
    await tg.send("/add")
    calls = await tg.press("w:cancel:")
    assert last(tg, calls) == wizard.CANCELLED
    assert tg.buttons(calls) == [("🏠 Главная", "n:home:all:0")]
    assert await tg.dp.fsm.storage.get_state(key=_key()) is None

    await tg.send("/add")
    calls = await tg.send("/cancel")
    assert last(tg, calls) == wizard.CANCELLED


async def test_a_wrong_date_or_amount_is_explained_and_asked_again(tg):
    await tg.send("/add Spotify")
    await tg.press("w:kind:sub")
    await tg.press("w:category:0")
    assert last(tg, await tg.send("31.02.2027")) == "⚠️ Такой даты нет: 31.02.2027."
    assert last(tg, await tg.send("01.01.2020")) == "⚠️ Дата 01.01.2020 уже прошла."
    assert "Сумма платежа" in last(tg, await tg.send("15.11"))
    assert last(tg, await tg.send("сто рублей")).startswith("⚠️ Не понял сумму.")
    assert last(tg, await tg.send("500 тугриков")).startswith("⚠️ Не знаю валюту")
    assert "Как часто повторяется?" in last(tg, await tg.send("500"))


async def test_a_wrong_one_line_entry_is_explained(tg):
    await tg.send("/add")
    assert last(tg, await tg.send("Spotify 31.02.2027")).startswith("⚠️ Такой даты нет")
    assert "шаг 2" in last(tg, await tg.send("Spotify"))


async def test_a_name_too_long_is_refused(tg):
    await tg.send("/add")
    assert "от 1 до 100 символов" in last(tg, await tg.send("x" * 101))


async def test_text_where_a_button_is_expected_and_a_sticker_where_text_is(tg):
    await tg.send("/add")
    assert last(tg, await tg.send(None)) == "Напишите ответ текстом. Отменить — /cancel"
    await tg.send("Spotify")
    assert last(tg, await tg.send("подписка")) == wizard.PICK


async def test_old_and_out_of_turn_buttons_do_nothing(tg):
    assert tg.answers(await tg.press("w:kind:sub")) == [wizard.STALE]  # no dialog

    await tg.send("/add Spotify")
    assert tg.answers(await tg.press("w:due:1")) == [wizard.STALE]  # a later step
    assert tg.answers(await tg.press("w:kind:zzz")) == [wizard.STALE]  # not a choice
    await tg.press("w:kind:sub")
    assert tg.answers(await tg.press("w:kind:exp")) == [wizard.STALE]  # an earlier step
    await tg.press("w:category:0")
    await tg.press("w:due:1")
    assert tg.answers(await tg.press("w:amount:none")) == [wizard.STALE]  # subscriptions need one


async def test_a_refusal_returns_to_the_step_that_can_fix_it(tg):
    await tg.send("/add")
    await tg.send("Spotify 15.11 500xyz")
    tg.wallos.add_result = AddResult("invalid", field="currency", message="Unknown currency")
    calls = await tg.press("w:confirm:save")
    shown = tg.texts(calls)
    assert "⚠️ Сумма не подошла — валюты XYZ нет в аккаунте. Исправьте, пожалуйста." in shown
    assert "Сумма платежа" in last(tg, calls)

    tg.wallos.add_result = None
    await tg.send("500rub")
    calls = await tg.press("w:period:3-1")
    await tg.press("w:confirm:save")
    assert saved(tg)["currency"] == "RUB"


async def test_an_unexplained_refusal_points_to_the_website(tg):
    await tg.send("/add")
    await tg.send("Spotify 15.11 500rub")
    tg.wallos.add_result = AddResult("invalid", field="kind")
    calls = await tg.press("w:confirm:save")
    assert last(tg, calls).startswith("⚠️ Не удалось сохранить запись.")


async def test_saving_is_retried_after_wallos_comes_back(tg):
    await tg.send("/add")
    await tg.send("Spotify 15.11 500rub")
    tg.wallos.error = True
    calls = await tg.press("w:confirm:save")
    assert tg.answers(calls) == ["Сервис временно недоступен. Попробуйте ещё раз через минуту."]
    tg.wallos.error = False
    calls = await tg.press("w:confirm:save")
    assert last(tg, calls).startswith("✅ <b>Запись добавлена</b>")


async def test_adding_needs_a_linked_account(tg):
    tg.wallos.linked = False
    assert tg.texts(await tg.send("/add")) == [screens.NOT_LINKED]
    assert tg.texts(await tg.press("n:add:all:0")) == [screens.NOT_LINKED]


async def test_without_named_categories_the_category_step_is_skipped(tg):
    tg.wallos.overview_data = overview(categories=[{"id": 1, "name": None}])
    calls = await tg.send("/add Spotify")
    assert "шаг 2 из 5" in last(tg, calls)
    calls = await tg.press("w:kind:sub")
    assert "шаг 3 из 5\n\nКогда следующий платёж?" in last(tg, calls)


async def test_the_add_button_starts_the_dialog(tg):
    calls = await tg.press("n:add:all:0")
    assert "шаг 1 из 6" in last(tg, calls)


def _key():
    from aiogram.fsm.storage.base import StorageKey

    return StorageKey(bot_id=123456, chat_id=555, user_id=555)
