from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, db
from app.keyboards import movies_menu_keyboard, letterboxd_menu_keyboard, imdb_menu_keyboard
from app.services import letterboxd_feed, movies_english_flow, movies_letterboxd_sync
from app.services.script_dialogues import detect_script_db_ready

logger = logging.getLogger(__name__)


async def movies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    ok, status = detect_script_db_ready(config.SCRIPT_DB_ROOT)
    script_hint = "✅ Script DB подключена" if ok else f"⚠️ Script DB: {status}"
    txt = f"Выбери категорию:\n\n{script_hint}"
    await update.message.reply_text(txt, reply_markup=movies_menu_keyboard())


async def movies_english_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    ok, msg = await movies_english_flow.ensure_user_english_pool(user_id)
    if not ok:
        await update.message.reply_text(msg, reply_markup=letterboxd_menu_keyboard())
        return
    await movies_english_flow.send_next_english_word(update, context, user_id)


async def movies_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    sub = db.get_letterboxd_subscription(update.effective_user.id)
    if not sub:
        await update.message.reply_text("Letterboxd не привязан.", reply_markup=letterboxd_menu_keyboard())
        return
    await update.message.reply_text(
        f"Дневник: {sub['rss_url']}\nWishlist: {sub['watchlist_rss_url'] or 'не задан'}",
        reply_markup=letterboxd_menu_keyboard(),
    )


async def movies_bind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    context.user_data["awaiting_letterboxd_rss"] = True
    await update.message.reply_text(
        "Пришлите RSS ссылку Letterboxd, например: https://letterboxd.com/<user>/rss/",
        reply_markup=letterboxd_menu_keyboard(),
    )


async def movies_unbind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    ok = db.disable_letterboxd_subscription(update.effective_user.id)
    await update.message.reply_text("Letterboxd отвязан." if ok else "Активной привязки нет.", reply_markup=letterboxd_menu_keyboard())


async def movies_check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    sub = db.get_letterboxd_subscription(user_id)
    if not sub:
        await update.message.reply_text("Сначала привяжите RSS.", reply_markup=letterboxd_menu_keyboard())
        return
    _, err, info = await movies_letterboxd_sync.process_letterboxd_for_user(
        context.application, user_id, sub["rss_url"], sub["last_guid"], False
    )
    if err:
        await update.message.reply_text(f"Не удалось проверить RSS: {err}", reply_markup=letterboxd_menu_keyboard())
    elif info:
        await update.message.reply_text(info, reply_markup=letterboxd_menu_keyboard())


async def movies_check_wishlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    sub = db.get_letterboxd_subscription(user_id)
    if not sub:
        await update.message.reply_text("Сначала привяжите RSS.", reply_markup=letterboxd_menu_keyboard())
        return
    wl = sub["watchlist_rss_url"] or letterboxd_feed.derive_watchlist_rss_url(sub["rss_url"])
    if not wl:
        await update.message.reply_text("Не удалось определить wishlist RSS.", reply_markup=letterboxd_menu_keyboard())
        return
    _, err, info = await movies_letterboxd_sync.process_letterboxd_watchlist_for_user(
        context.application, user_id, wl, sub["last_watchlist_guid"], False
    )
    if err:
        await update.message.reply_text(f"Не удалось проверить wishlist: {err}", reply_markup=letterboxd_menu_keyboard())
    elif info:
        await update.message.reply_text(info, reply_markup=letterboxd_menu_keyboard())


async def poll_letterboxd_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for sub in db.list_letterboxd_subscriptions():
        try:
            await movies_letterboxd_sync.process_letterboxd_for_user(
                context.application, sub["user_id"], sub["rss_url"], sub["last_guid"], True
            )
            if sub["watchlist_rss_url"]:
                await movies_letterboxd_sync.process_letterboxd_watchlist_for_user(
                    context.application,
                    sub["user_id"],
                    sub["watchlist_rss_url"],
                    sub["last_watchlist_guid"],
                    True,
                )
        except Exception as e:
            logger.exception("Letterboxd polling failed for user %s: %s", sub["user_id"], e)
