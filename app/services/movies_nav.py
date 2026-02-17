from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, db
from app.keyboards import main_menu_keyboard, movies_menu_keyboard
from app.services import letterboxd_feed, movies_text


@dataclass(frozen=True)
class MoviesNavActions:
    movies_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_bind_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_check_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_check_wishlist_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_english_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_status_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    movies_unbind_cmd: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
    bind_letterboxd_rss_for_user: Callable[[ContextTypes.DEFAULT_TYPE, int, str], Awaitable[tuple[bool, str]]]
    send_next_english_word: Callable[[Update, ContextTypes.DEFAULT_TYPE, int], Awaitable[None]]


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, actions: MoviesNavActions) -> bool:
    raw_text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if raw_text == config.BTN_MOVIES:
        await actions.movies_cmd(update, context)
        return True
    if raw_text == config.BTN_PLANNER:
        await cleanup.cleanup_trigger_message(update, context)
        await update.message.reply_text("Режим планировщика активен. Просто отправь задачу.", reply_markup=main_menu_keyboard())
        return True
    if raw_text == config.BTN_MOVIES_BIND:
        await actions.movies_bind_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_CHECK:
        await actions.movies_check_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_CHECK_WISHLIST:
        await actions.movies_check_wishlist_cmd(update, context)
        return True
    if movies_text.is_movies_english_trigger(raw_text):
        await actions.movies_english_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_STATUS:
        await actions.movies_status_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_UNBIND:
        await actions.movies_unbind_cmd(update, context)
        return True
    if raw_text == config.BTN_BACK_MOVIES:
        await actions.movies_cmd(update, context)
        return True
    if raw_text == config.BTN_HOME_MENU:
        await cleanup.cleanup_trigger_message(update, context)
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return True

    awaiting_word_id = context.user_data.get("awaiting_english_word_id")
    if awaiting_word_id and raw_text and not raw_text.startswith("/") and not movies_text.is_menu_button_text(raw_text):
        row = db.get_english_word(int(awaiting_word_id), user_id)
        if row:
            ok = movies_text.translation_match(str(row["translation"]), raw_text)
            if ok:
                db.update_english_word_review(int(awaiting_word_id), user_id, "correct")
                await update.message.reply_text("Отлично, верно ✅", reply_markup=movies_menu_keyboard())
            else:
                db.update_english_word_review(int(awaiting_word_id), user_id, "failed")
                await update.message.reply_text(
                    f"Пока мимо ❌\nПравильный перевод: {row['translation']}",
                    reply_markup=movies_menu_keyboard(),
                )
            context.user_data.pop("awaiting_english_word_id", None)
            await actions.send_next_english_word(update, context, user_id)
            return True

    if context.user_data.get("awaiting_letterboxd_rss"):
        if not (raw_text.startswith("http://") or raw_text.startswith("https://")):
            await update.message.reply_text("Это не похоже на ссылку.", reply_markup=movies_menu_keyboard())
            return True
        ok, msg = await actions.bind_letterboxd_rss_for_user(context, user_id, raw_text)
        context.user_data["awaiting_letterboxd_rss"] = False
        await update.message.reply_text(msg, reply_markup=movies_menu_keyboard())
        return True

    if letterboxd_feed.looks_like_letterboxd_rss(raw_text):
        _, msg = await actions.bind_letterboxd_rss_for_user(context, user_id, raw_text)
        await update.message.reply_text(msg, reply_markup=movies_menu_keyboard())
        return True

    return False
