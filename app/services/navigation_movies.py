from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config
from app.keyboards import movies_menu_keyboard, letterboxd_menu_keyboard, imdb_menu_keyboard


async def handle_movies_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()

    # Main category selection
    if text == "Letterboxd":
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text(
            "Выбери действие для Letterboxd:",
            reply_markup=letterboxd_menu_keyboard(),
        )
        return True

    if text == "IMDB":
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text(
            "Выбери действие для IMDB:",
            reply_markup=imdb_menu_keyboard(),
        )
        return True

    # Back button from Letterboxd/IMDB menu
    if text == "Back":
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text(
            "Выбери категорию:",
            reply_markup=movies_menu_keyboard(),
        )
        return True

    if text == config.BTN_MOVIES_IMDB_LINK:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb integration will be added next.", reply_markup=imdb_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_IMDB_UNLINK:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb integration will be added next.", reply_markup=imdb_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_IMDB_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb movies section will be added next.", reply_markup=imdb_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_CREW:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text(
            "Use Logged Movies or Wishlist first, then select actors/director on a movie card.",
            reply_markup=letterboxd_menu_keyboard(),
        )
        return True

    return False
