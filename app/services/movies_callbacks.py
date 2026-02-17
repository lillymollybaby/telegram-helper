from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Awaitable, Callable

from telegram import InputMediaPhoto, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app import db, word_extractor
from app.keyboards import main_menu_keyboard, movies_menu_keyboard
from app.services import movies_content, movies_ui, tmdb


@dataclass(frozen=True)
class MoviesCallbacksActions:
    build_movie_learning_suggestion: Callable[[str], Awaitable[dict]]
    send_next_english_word: Callable[[Update, ContextTypes.DEFAULT_TYPE, int], Awaitable[None]]


async def movie_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, actions: MoviesCallbacksActions) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "mv":
        return
    action, entry_id_s = parts[1], parts[2]
    try:
        entry_id = int(entry_id_s)
    except ValueError:
        return
    entry = db.get_letterboxd_entry(entry_id, query.from_user.id)
    if not entry:
        return
    film_title = entry["film_title"]
    movie = await tmdb.search_movie(film_title)
    details = await tmdb.movie_details(int(movie["id"])) if movie and movie.get("id") else None

    if action == "menu":
        txt = f"Вижу, вы посмотрели <b>{escape(film_title)}</b> 👀\nХочешь разбор по фильму? Выбери кнопку ниже."
        await query.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=movies_ui.movie_action_keyboard(entry_id))
        return
    if action == "home":
        await query.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return
    if action == "facts":
        await query.message.reply_text(
            movies_content.build_movie_facts_text(film_title, details),
            parse_mode=ParseMode.HTML,
            reply_markup=movies_ui.movie_back_keyboard(entry_id),
        )
        return
    if action == "en":
        release_date = (details or {}).get("release_date") if isinstance(details, dict) else None
        year = None
        if isinstance(release_date, str) and len(release_date) >= 4 and release_date[:4].isdigit():
            year = int(release_date[:4])

        words = await word_extractor.extract_words_from_movie_subtitles(film_title=film_title, year=year, limit=15)
        if words:
            text = word_extractor.format_words_for_telegram(film_title, year, words)
            await query.message.reply_text(
                text,
                reply_markup=movies_ui.movie_back_keyboard(entry_id),
                disable_web_page_preview=True,
            )
            return

        lesson = await actions.build_movie_learning_suggestion(film_title)
        await query.message.reply_text(
            movies_ui.build_english_text(film_title, lesson),
            parse_mode=ParseMode.HTML,
            reply_markup=movies_ui.movie_back_keyboard(entry_id),
        )
        return
    if action == "people":
        _, people = movies_content.build_people_data(film_title, details)
        if not people:
            await query.message.reply_text("Не нашел фото актеров/режиссера.", reply_markup=movies_ui.movie_back_keyboard(entry_id))
            return
        p = people[0]
        caption = f"🎭 <b>{escape(film_title)}</b>\n<b>{escape(p['name'])}</b>\n{escape(p['role'])}"
        await query.message.reply_photo(
            photo=p["photo"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=movies_ui.people_carousel_keyboard(entry_id, 0, len(people)),
        )


async def movie_people_carousel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, logger) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "mvp":
        return
    try:
        entry_id = int(parts[1])
        idx = int(parts[2])
    except ValueError:
        return
    entry = db.get_letterboxd_entry(entry_id, query.from_user.id)
    if not entry:
        return
    movie = await tmdb.search_movie(entry["film_title"])
    details = await tmdb.movie_details(int(movie["id"])) if movie and movie.get("id") else None
    _, people = movies_content.build_people_data(entry["film_title"], details)
    if not people:
        return
    idx %= len(people)
    p = people[idx]
    caption = f"🎭 <b>{escape(entry['film_title'])}</b>\n<b>{escape(p['name'])}</b>\n{escape(p['role'])}"
    try:
        await query.message.edit_media(
            media=InputMediaPhoto(media=p["photo"], caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=movies_ui.people_carousel_keyboard(entry_id, idx, len(people)),
        )
    except Exception as e:
        logger.debug("Failed to edit people carousel media entry_id=%s idx=%s: %s", entry_id, idx, e)


async def english_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, actions: MoviesCallbacksActions) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "eng":
        return

    action = parts[1]
    try:
        word_id = int(parts[2])
    except ValueError:
        word_id = 0

    user_id = query.from_user.id

    if action == "menu":
        await query.message.reply_text("Раздел Фильмы:", reply_markup=movies_menu_keyboard())
        return
    if action == "home":
        await query.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return

    row = db.get_english_word(word_id, user_id)
    if not row:
        await query.message.reply_text("Слово не найдено.", reply_markup=movies_menu_keyboard())
        return

    if action == "show":
        await query.message.reply_text(
            movies_ui.english_word_card_text(row, reveal=True),
            parse_mode=ParseMode.HTML,
            reply_markup=movies_ui.english_word_keyboard(word_id),
        )
        return
    if action == "learned":
        db.update_english_word_review(word_id, user_id, "learned")
        context.user_data.pop("awaiting_english_word_id", None)
        await actions.send_next_english_word(update, context, user_id)
        return
    if action == "hard":
        db.update_english_word_review(word_id, user_id, "hard")
        context.user_data.pop("awaiting_english_word_id", None)
        await actions.send_next_english_word(update, context, user_id)
        return
    if action == "next":
        context.user_data["awaiting_english_word_id"] = word_id
        await actions.send_next_english_word(update, context, user_id)
        return
