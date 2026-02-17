from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app import db
from app.keyboards import movies_menu_keyboard
from app.services import movies_generation, movies_ui


async def ensure_user_english_pool(user_id: int) -> tuple[bool, str]:
    due = db.get_due_english_word(user_id) or db.get_any_english_word(user_id)
    if due:
        return True, ""
    film_title = db.get_latest_film_title_for_user(user_id)
    if not film_title:
        return False, "Пока нет фильмов в логах/wishlist. Сначала добавь или залогай фильм."
    words = await movies_generation.generate_english_words_for_film(film_title)
    if not words:
        return False, "Не удалось сгенерировать слова сейчас. Попробуй позже."
    db.save_english_words(user_id, film_title, words)
    return True, ""


async def send_next_english_word(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    row = db.get_due_english_word(user_id) or db.get_any_english_word(user_id)
    if not row:
        await update.effective_message.reply_text(
            "Пока нет слов для повторения.",
            reply_markup=movies_menu_keyboard(),
        )
        return
    context.user_data["awaiting_english_word_id"] = int(row["id"])
    await update.effective_message.reply_text(
        movies_ui.english_word_card_text(row, reveal=False),
        parse_mode=ParseMode.HTML,
        reply_markup=movies_ui.english_word_keyboard(int(row["id"])),
    )
