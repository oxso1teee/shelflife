"""Adding a record step by step: name, kind, category, date, amount, period, confirm.

Started by /add without arguments, by /add with a name but no date, and by the
"Добавить" buttons. Each step is a message; a choice made with a button is
written into that message and its buttons are removed, so an old step cannot
be pressed again. "‹ Назад" returns to the previous step, "Отмена" (or /cancel)
leaves. A complete one-line entry ("Spotify 15.11 500rub") typed at the first
step skips straight to the confirmation.

Nothing is saved before "Сохранить"; the record is then created by Wallos with
the website's validation, once per Telegram update. Dates and amounts are read
by the /add parser (bot/parsing.py); the defaults are the web app's
(shelflife_bot_add_record()).
"""

from __future__ import annotations

import html
import logging
from calendar import monthrange
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from bot import texts
from bot.keyboards import CardCB, NavCB, WizardCB
from bot.parsing import ParseError, has_date, parse_amount, parse_date, parse_quick_add
from bot.screens import NOT_LINKED
from bot.states import AddFlow
from bot.wallos_client import Record, WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

KINDS = {"sub": "subscription", "exp": "expiry", "mnt": "maintenance"}
KIND_CODES = {kind: code for code, kind in KINDS.items()}
DEFAULT_CYCLES = {"subscription": 3, "expiry": 5, "maintenance": 3}  # as the web app's /add
PERIODS = [
    ("5-1", "Разово"),
    ("2-1", "Каждую неделю"),
    ("3-1", "Каждый месяц"),
    ("3-3", "Каждые 3 месяца"),
    ("3-6", "Каждые 6 месяцев"),
    ("4-1", "Каждый год"),
]
DUE_QUESTIONS = {
    "subscription": "Когда следующий платёж?",
    "expiry": "До какой даты годен продукт?",
    "maintenance": "Когда следующее обслуживание?",
}
STALE = "Этот шаг уже пройден."
PICK = "Выберите вариант кнопкой выше. Отменить — /cancel"
CANCELLED = "Добавление отменено."


def _button(text: str, step: str, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=WizardCB(step=step, value=value).pack())


def _footer(back: bool = True) -> list[InlineKeyboardButton]:
    row = [_button("‹ Назад", "back")] if back else []
    return row + [_button("Отмена", "cancel")]


def _steps(data: dict) -> list[str]:
    steps = ["name", "kind"]
    if data.get("categories"):
        steps.append("category")
    return steps + ["due", "amount", "period"]


def _header(data: dict, step: str) -> str:
    steps = _steps(data)
    return f"<b>Новая запись</b> · шаг {steps.index(step) + 1} из {len(steps)}\n\n"


def _plus_month(day: date) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, monthrange(year, month)[1]))


# --- entering and leaving ------------------------------------------------------


async def start(
    message: Message,
    telegram_id: int,
    state: FSMContext,
    wallos: WallosClient,
    name: str | None = None,
) -> None:
    """Begins the dialog in the chat of `message`; `name` skips the first step."""
    try:
        overview = await wallos.overview(telegram_id)
    except WallosError:
        log.exception("Overview failed for telegram_id=%d", telegram_id)
        await message.answer(texts.UNAVAILABLE)
        return
    if overview is None:
        await message.answer(NOT_LINKED)
        return

    named = [(cid, cname) for cid, cname in overview.categories if cname]
    none_id = next((cid for cid, cname in overview.categories if not cname), None)
    await state.set_state(AddFlow.name)
    await state.set_data(
        {
            "categories": named[:10],
            "none_category": none_id,
            "main_currency": overview.main_currency.code if overview.main_currency else None,
        }
    )
    if name:
        await _take_name(message, state, name)
    else:
        await _ask(message, state, "name")


async def leave(state: FSMContext) -> bool:
    """Ends the dialog if one is open; True when it was."""
    if await state.get_state() not in {s.state for s in AddFlow.__all_states__}:
        return False
    await state.clear()
    return True


# --- the steps -----------------------------------------------------------------


async def _ask(message: Message, state: FSMContext, step: str) -> None:
    data = await state.get_data()
    kind = data.get("kind", "subscription")
    header = _header(data, step) if step != "confirm" else ""
    keyboard: list[list[InlineKeyboardButton]] = []

    if step == "name":
        text = (
            "Как называется запись? Например: Spotify, Молоко, Фильтр для воды.\n\n"
            "Можно сразу одной строкой: <code>Spotify 15.11 500rub</code>"
        )
        keyboard.append(_footer(back=False))
    elif step == "kind":
        text = f"Что отслеживаем для <b>{html.escape(data['name'])}</b>?"
        keyboard.append([_button(texts.KIND_NAMES[k], "kind", c) for c, k in KINDS.items()])
        keyboard.append(_footer())
    elif step == "category":
        text = "Категория — как на сайте:"
        row: list[InlineKeyboardButton] = []
        for cid, cname in data["categories"]:
            row.append(_button(texts.shorten(cname, 24), "category", str(cid)))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([_button("Без категории", "category", "0")])
        keyboard.append(_footer())
    elif step == "due":
        text = f"{DUE_QUESTIONS[kind]}\nНапишите дату (ДД.ММ или ДД.ММ.ГГГГ) или выберите:"
        keyboard.append([_button("Сегодня", "due", "0"), _button("Завтра", "due", "1")])
        keyboard.append([_button("Через неделю", "due", "7"), _button("Через месяц", "due", "m")])
        keyboard.append(_footer())
    elif step == "amount":
        main = data.get("main_currency") or "основной валюте"
        if kind == "subscription":
            text = f"Сумма платежа, например <code>500</code>, <code>500rub</code> или <code>9.99$</code>.\nБез валюты — в {main}."
        else:
            text = f"Сумма, если есть (например, стоимость обслуживания): <code>1500</code> или <code>20$</code>.\nБез валюты — в {main}."
            keyboard.append([_button("Без суммы", "amount", "none")])
        keyboard.append(_footer())
    elif step == "period":
        text = "Как часто повторяется?"
        row = []
        for value, label in PERIODS:
            row.append(_button(label, "period", value))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append(_footer())
    else:  # confirm
        text = "<b>Проверьте и сохраните</b>\n\n" + _preview(data)
        keyboard.append([_button("✅ Сохранить", "confirm", "save")])
        keyboard.append(_footer())

    await state.set_state(getattr(AddFlow, step))
    await message.answer(header + text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


def _record(data: dict) -> Record:
    kind = data["kind"]
    cycle = data.get("cycle") or DEFAULT_CYCLES[kind]
    return Record(
        id=0,
        kind=kind,
        name=data["name"],
        next_payment=data["due"],
        price=float(data.get("price") or 0),
        currency=data.get("currency") or data.get("main_currency"),
        cycle=cycle,
        frequency=1 if cycle == 5 else (data.get("frequency") or 1),
        inactive=False,
        snoozed_until=None,
    )


def _preview(data: dict) -> str:
    card = texts.record_card(_record(data), texts.today())
    category = dict(data.get("categories") or []).get(data.get("category_id"))
    if category:
        card += f"\nКатегория: {html.escape(texts.shorten(category, 40))}"
    return card + "\nНапоминание: по умолчанию, как в настройках"


async def _next(message: Message, state: FSMContext, after: str) -> None:
    data = await state.get_data()
    if data.get("complete"):
        await _ask(message, state, "confirm")
        return
    steps = _steps(data) + ["confirm"]
    await _ask(message, state, steps[steps.index(after) + 1])


async def _take_name(message: Message, state: FSMContext, text: str) -> None:
    text = text.strip()
    today = texts.today()
    try:
        parsed = parse_quick_add(text, today)
    except ParseError as exc:
        if has_date(text):  # meant as a one-line entry: say what is wrong with it
            await message.answer(
                f"⚠️ {html.escape(str(exc))}\nИсправьте строку или напишите только название."
            )
            return
        parsed = None

    if parsed is not None:
        await state.update_data(
            name=parsed.name, kind=parsed.kind, due=parsed.due.isoformat(), price=parsed.price,
            currency=parsed.currency, cycle=parsed.cycle, frequency=parsed.frequency, complete=True,
        )  # fmt: skip
        await _ask(message, state, "confirm")
        return

    if not text or len(text) > 100:
        await message.answer("⚠️ Название должно быть от 1 до 100 символов. Напишите его ещё раз.")
        return
    await state.update_data(name=text)
    await _next(message, state, "name")


@router.message(AddFlow.name, F.text, ~F.text.startswith("/"))
async def on_name(message: Message, state: FSMContext) -> None:
    await _take_name(message, state, message.text or "")


@router.message(AddFlow.due, F.text, ~F.text.startswith("/"))
async def on_due(message: Message, state: FSMContext) -> None:
    try:
        due = parse_date(message.text or "", texts.today())
    except ParseError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    await state.update_data(due=due.isoformat())
    await _next(message, state, "due")


@router.message(AddFlow.amount, F.text, ~F.text.startswith("/"))
async def on_amount(message: Message, state: FSMContext) -> None:
    try:
        price, currency = parse_amount(message.text or "")
    except ParseError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    await state.update_data(price=price, currency=currency)
    await _next(message, state, "amount")


@router.message(StateFilter(AddFlow.name, AddFlow.due, AddFlow.amount), ~F.text.startswith("/"))
async def on_not_text(message: Message) -> None:
    await message.answer("Напишите ответ текстом. Отменить — /cancel")


@router.message(
    StateFilter(AddFlow.kind, AddFlow.category, AddFlow.period, AddFlow.confirm),
    ~F.text.startswith("/"),
)
async def on_text_instead_of_button(message: Message) -> None:
    await message.answer(PICK)


# --- buttons -------------------------------------------------------------------


async def _close_step(query: CallbackQuery, note: str) -> None:
    """Writes the choice into the step's message and removes its buttons."""
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                f"{query.message.html_text}\n\n<i>{html.escape(note)}</i>", reply_markup=None
            )
        except Exception:  # an edit that fails (too old, unchanged) must not stop the dialog
            log.debug("Could not close the step message", exc_info=True)


@router.callback_query(WizardCB.filter())
async def on_choice(
    query: CallbackQuery,
    callback_data: WizardCB,
    state: FSMContext,
    wallos: WallosClient,
    event_update: Update,
) -> None:
    current = await state.get_state()
    step, value = callback_data.step, callback_data.value
    message = query.message if isinstance(query.message, Message) else None
    if (
        current is None
        or not current.startswith("AddFlow:")
        or message is None
        or query.from_user is None
    ):
        await query.answer(STALE)
        return
    current_step = current.split(":", 1)[1]

    if step == "cancel":
        await state.clear()
        await query.answer()
        await _close_step(query, CANCELLED)
        home = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главная", callback_data=NavCB(to="home").pack())]
            ]
        )
        await message.answer(CANCELLED, reply_markup=home)
        return

    if step == "back":
        data = await state.get_data()
        if current_step == "confirm" and data.get("complete"):
            await state.update_data(complete=False)
            data = await state.get_data()
        steps = _steps(data) + ["confirm"]
        index = steps.index(current_step) if current_step in steps else 0
        await query.answer()
        await _close_step(query, "‹ Назад")
        await _ask(message, state, steps[max(0, index - 1)])
        return

    if step != current_step:
        await query.answer(STALE)
        return

    data = await state.get_data()
    if step == "kind" and value in KINDS:
        kind = KINDS[value]
        await state.update_data(kind=kind)
        await query.answer()
        await _close_step(query, texts.KIND_NAMES[kind])
        await _next(message, state, "kind")
    elif step == "category":
        chosen = (
            dict(data.get("categories") or []).get(int(value))
            if value.isdigit() and value != "0"
            else None
        )
        await state.update_data(category_id=int(value) if chosen else data.get("none_category"))
        await query.answer()
        await _close_step(query, chosen or "Без категории")
        await _next(message, state, "category")
    elif step == "due" and value in {"0", "1", "7", "m"}:
        today = texts.today()
        due = _plus_month(today) if value == "m" else today + timedelta(days=int(value))
        await state.update_data(due=due.isoformat())
        await query.answer()
        await _close_step(query, f"{texts.format_date(due)} — {texts.relative(due, today)}")
        await _next(message, state, "due")
    elif step == "amount" and value == "none" and data.get("kind") != "subscription":
        await state.update_data(price=None, currency=None)
        await query.answer()
        await _close_step(query, "Без суммы")
        await _next(message, state, "amount")
    elif step == "period" and value in dict(PERIODS):
        cycle, frequency = (int(part) for part in value.split("-"))
        await state.update_data(cycle=cycle, frequency=frequency)
        await query.answer()
        await _close_step(query, dict(PERIODS)[value])
        await _next(message, state, "period")
    elif step == "confirm" and value == "save":
        await _save(query, message, state, wallos, event_update)
    else:
        await query.answer(STALE)


async def _save(
    query: CallbackQuery,
    message: Message,
    state: FSMContext,
    wallos: WallosClient,
    event_update: Update,
) -> None:
    data = await state.get_data()
    record = _record(data)
    try:
        result = await wallos.add_record(
            telegram_id=query.from_user.id,
            update_id=event_update.update_id,
            kind=record.kind,
            name=record.name,
            next_payment=record.next_payment,
            price=data.get("price"),
            currency=data.get("currency"),
            cycle=record.cycle,
            frequency=record.frequency,
            category_id=data.get("category_id"),
        )
    except WallosError:
        log.exception("Saving a record failed for telegram_id=%d", query.from_user.id)
        await query.answer(texts.UNAVAILABLE, show_alert=True)
        return

    if result.status == "created" and result.record is not None:
        await state.clear()
        await query.answer("Сохранено")
        keyboard = [
            [
                InlineKeyboardButton(
                    text="Открыть запись", callback_data=CardCB(id=result.record.id).pack()
                )
            ],
            [
                InlineKeyboardButton(text="➕ Добавить ещё", callback_data=NavCB(to="add").pack()),
                InlineKeyboardButton(text="🏠 Главная", callback_data=NavCB(to="home").pack()),
            ],
        ]
        text = "✅ <b>Запись добавлена</b>\n\n" + texts.record_card(result.record, texts.today())
        try:
            await message.edit_text(
                text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        except Exception:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        return

    if result.status == "not_linked":
        await state.clear()
        await query.answer()
        await message.answer(NOT_LINKED)
        return

    # Refused by the website's validation: back to the step that can fix it.
    fix = {"price": "amount", "currency": "amount", "next_payment": "due", "name": "name"}.get(
        result.field or ""
    )
    reasons = {
        "amount": f"Сумма не подошла{' — валюты ' + html.escape(data.get('currency') or '') + ' нет в аккаунте' if result.field == 'currency' else ''}.",
        "due": "Дата не подошла.",
        "name": "Название не подошло.",
    }
    await query.answer()
    if fix is None:
        await message.answer(
            "⚠️ Не удалось сохранить запись. Проверьте данные или добавьте её на сайте."
        )
        return
    await state.update_data(complete=False)
    await message.answer(f"⚠️ {reasons[fix]} Исправьте, пожалуйста.")
    await _ask(message, state, fix)
