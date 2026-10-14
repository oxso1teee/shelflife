"""Navigation: the home screen, the sections, record cards and their actions, settings.

Commands (/start, /list, /soon, /spend, /settings, /help) send a section as a new
message; the buttons in it edit that one message from section to section, so the
chat does not fill with menus. Every screen is drawn from a fresh overview of the
account (bot/screens.py), so what the bot shows is what the website shows.

Record actions carry the due date the card showed: Wallos applies them only to
the user's own record and only while it still has that date, once per update.
Deleting asks first.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, Update

from bot import screens, texts
from bot.handlers import callbacks, wizard
from bot.keyboards import CARD_ACTIONS, CardActionCB, CardCB, NavCB, SettingsCB, due_from_callback
from bot.overview import Overview
from bot.screens import Screen
from bot.wallos_client import ActionResult, WallosClient, WallosError

log = logging.getLogger(__name__)
router = Router()

GONE = "Запись не найдена — возможно, её удалили на сайте."


async def _send(message: Message, screen: Screen) -> None:
    await message.answer(screen.text, reply_markup=screen.markup)


async def _edit(query: CallbackQuery, screen: Screen) -> None:
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(screen.text, reply_markup=screen.markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            # Too old or otherwise not editable: show the screen as a new message.
            await query.message.answer(screen.text, reply_markup=screen.markup)


def _screen(
    to: str, ov: Overview, miniapp_url: str | None, username: str | None, flt: str, page: int
) -> Screen:
    if to == "list":
        return screens.records(ov, flt, page)
    if to == "soon":
        return screens.soon(ov)
    if to == "spend":
        return screens.spend(ov)
    if to == "set":
        return screens.settings(ov, username, miniapp_url)
    return screens.home(ov, miniapp_url)


async def _overview(wallos: WallosClient, telegram_id: int) -> Overview | None:
    return await wallos.overview(telegram_id)


# --- commands ------------------------------------------------------------------


async def _show_section(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None, to: str
) -> None:
    if message.from_user is None:
        return
    await wizard.leave(state)  # going to a section ends an unfinished /add
    try:
        ov = await _overview(wallos, message.from_user.id)
    except WallosError:
        log.exception("Overview failed for telegram_id=%d", message.from_user.id)
        await message.answer(texts.UNAVAILABLE)
        return
    if ov is None:
        await _send(message, screens.not_linked())
        return
    await _send(message, _screen(to, ov, miniapp_url, message.from_user.username, "all", 0))


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "home")


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "home")


@router.message(Command("list"))
async def cmd_list(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "list")


@router.message(Command("soon"))
async def cmd_soon(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "soon")


@router.message(Command("spend"))
async def cmd_spend(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "spend")


@router.message(Command("settings"))
async def cmd_settings(
    message: Message, state: FSMContext, wallos: WallosClient, miniapp_url: str | None
) -> None:
    await _show_section(message, state, wallos, miniapp_url, "set")


@router.message(Command("help"))
async def cmd_help(message: Message, miniapp_url: str | None) -> None:
    # Help does not end an unfinished /add: it may be what the user needed for it.
    await _send(message, screens.help_screen(miniapp_url))


# --- section buttons -----------------------------------------------------------


@router.callback_query(NavCB.filter())
async def on_nav(
    query: CallbackQuery,
    callback_data: NavCB,
    state: FSMContext,
    wallos: WallosClient,
    miniapp_url: str | None,
) -> None:
    if query.from_user is None:
        await query.answer()
        return

    if callback_data.to == "add":
        await query.answer()
        if isinstance(query.message, Message):
            await wizard.start(query.message, query.from_user.id, state, wallos)
        return
    if callback_data.to == "help":
        await query.answer()
        await _edit(query, screens.help_screen(miniapp_url))
        return

    await wizard.leave(state)
    try:
        ov = await _overview(wallos, query.from_user.id)
    except WallosError:
        log.exception("Overview failed for telegram_id=%d", query.from_user.id)
        await query.answer(texts.UNAVAILABLE, show_alert=True)
        return
    await query.answer()
    if ov is None:
        await _edit(query, screens.not_linked())
        return
    await _edit(
        query,
        _screen(
            callback_data.to,
            ov,
            miniapp_url,
            query.from_user.username,
            callback_data.flt,
            callback_data.page,
        ),
    )


@router.callback_query(CardCB.filter())
async def on_card(
    query: CallbackQuery, callback_data: CardCB, wallos: WallosClient, miniapp_url: str | None
) -> None:
    if query.from_user is None:
        await query.answer()
        return
    try:
        ov = await _overview(wallos, query.from_user.id)
    except WallosError:
        log.exception("Overview failed for telegram_id=%d", query.from_user.id)
        await query.answer(texts.UNAVAILABLE, show_alert=True)
        return
    if ov is None:
        await query.answer()
        await _edit(query, screens.not_linked())
        return
    item = ov.item(callback_data.id)
    if item is None:
        await query.answer(GONE, show_alert=True)
        await _edit(query, screens.records(ov, callback_data.flt, callback_data.page))
        return
    await query.answer()
    await _edit(query, screens.card(ov, item, miniapp_url, callback_data.flt, callback_data.page))


@router.callback_query(CardActionCB.filter())
async def on_card_action(
    query: CallbackQuery,
    callback_data: CardActionCB,
    wallos: WallosClient,
    miniapp_url: str | None,
    event_update: Update,
) -> None:
    if query.from_user is None:
        await query.answer()
        return
    due = due_from_callback(callback_data.due)
    flt, page = callback_data.flt, callback_data.page

    try:
        if callback_data.act == "d":  # delete: ask first
            ov = await _overview(wallos, query.from_user.id)
            item = ov.item(callback_data.id) if ov else None
            if item is None or item.next_payment != due:
                await query.answer(
                    GONE if item is None else "Запись уже изменилась.", show_alert=True
                )
                if ov is not None:
                    await _edit(
                        query,
                        (
                            screens.card(ov, item, miniapp_url, flt, page)
                            if item
                            else screens.records(ov, flt, page)
                        ),
                    )
                return
            await query.answer()
            await _edit(query, screens.delete_confirm(item, flt, page))
            return

        action = CARD_ACTIONS.get(callback_data.act)
        if action is None or due is None:
            await query.answer(callbacks.UNKNOWN_BUTTON, show_alert=True)
            return
        result: ActionResult = await wallos.act(
            telegram_id=query.from_user.id,
            update_id=event_update.update_id,
            subscription_id=callback_data.id,
            action=action,
            expected_due=due,
        )
        ov = await _overview(wallos, query.from_user.id)
    except WallosError:
        log.exception(
            "Card action %s failed for telegram_id=%d", callback_data.act, query.from_user.id
        )
        await query.answer(texts.UNAVAILABLE, show_alert=True)
        return

    await query.answer(callbacks.outcome_text(result))
    if ov is None:
        await _edit(query, screens.not_linked())
        return
    item = ov.item(callback_data.id)
    await _edit(
        query,
        screens.card(ov, item, miniapp_url, flt, page) if item else screens.records(ov, flt, page),
    )


@router.callback_query(SettingsCB.filter())
async def on_settings(
    query: CallbackQuery,
    callback_data: SettingsCB,
    state: FSMContext,
    wallos: WallosClient,
    miniapp_url: str | None,
    event_update: Update,
) -> None:
    if query.from_user is None:
        await query.answer()
        return
    try:
        if callback_data.key == "unlink_ok":
            result = await wallos.settings(
                telegram_id=query.from_user.id, update_id=event_update.update_id, op="unlink"
            )
            await query.answer()
            if result.status in {"unlinked", "not_linked"}:
                await state.clear()
                if isinstance(query.message, Message):
                    try:
                        await query.message.edit_text(screens.UNLINKED, reply_markup=None)
                    except TelegramBadRequest:
                        await query.message.answer(screens.UNLINKED)
            return

        note = None
        if callback_data.key == "days":
            result = await wallos.settings(
                telegram_id=query.from_user.id,
                update_id=event_update.update_id,
                op="reminder_days",
                days=callback_data.value,
            )
            if result.status == "saved" and result.reminder_days is not None:
                days = result.reminder_days
                note = "Сохранено: напоминать " + (
                    "в день даты" if days == 0 else f"за {texts.days(days)}"
                )
            elif result.status == "invalid":
                note = "Такое значение нельзя выбрать."
        ov = await _overview(wallos, query.from_user.id)
    except WallosError:
        log.exception(
            "Settings %s failed for telegram_id=%d", callback_data.key, query.from_user.id
        )
        await query.answer(texts.UNAVAILABLE, show_alert=True)
        return

    await query.answer(note)
    if ov is None:
        await _edit(query, screens.not_linked())
        return
    if callback_data.key == "unlink":
        await _edit(query, screens.unlink_confirm(ov))
        return
    await _edit(query, screens.settings(ov, query.from_user.username, miniapp_url))
