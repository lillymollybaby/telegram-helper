from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from html import escape
from typing import Awaitable, Callable

from telegram import InputMediaPhoto, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app import db, word_extractor
from app.keyboards import main_menu_keyboard, movies_menu_keyboard
from app.services import movies_content, movies_ui, tmdb

logger = logging.getLogger(__name__)


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
    if len(parts) < 3 or parts[0] != "mv":
        return
    
    # Default values
    page = 0
    details = None
    
    # Handle both 3-part (mv:action:entry_id) and 4-part (mv:words:entry_id:page) formats
    if len(parts) == 4 and parts[1] == "words":
        # Handle word navigation
        action = "words"
        try:
            entry_id = int(parts[2])
            page = int(parts[3])
        except ValueError:
            logger.warning("Invalid words callback format: %s", query.data)
            return
    elif len(parts) == 3:
        action, entry_id_s = parts[1], parts[2]
        try:
            entry_id = int(entry_id_s)
        except ValueError:
            logger.warning("Invalid callback format: %s", query.data)
            return
    else:
        logger.warning("Unknown callback format: %s", query.data)
        return
    
    entry = db.get_letterboxd_entry(entry_id, query.from_user.id)
    if not entry:
        logger.warning("No entry found for entry_id=%s user_id=%s", entry_id, query.from_user.id)
        return
    film_title = entry["film_title"]
    
    # Get movie details (not always needed)
    if action != "words":
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
        try:
            release_date = (details or {}).get("release_date") if isinstance(details, dict) else None
            year = None
            if isinstance(release_date, str) and len(release_date) >= 4 and release_date[:4].isdigit():
                year = int(release_date[:4])

            words = await word_extractor.extract_words_from_movie_subtitles(film_title=film_title, year=year, limit=40)
            if words:
                # Save words to context for pagination
                context.user_data[f"words_{entry_id}"] = words
                context.user_data[f"film_year_{entry_id}"] = year
                
                text = word_extractor.format_words_for_telegram(film_title, year, words, page=0, per_page=5)
                if text:  # Check that formatted text is not empty
                    total_pages = (len(words) + 4) // 5  # Calculate total pages (5 words per page)
                    keyboard = movies_ui.words_keyboard(entry_id, page=0, total_pages=total_pages)
                    await query.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_web_page_preview=True,
                    )
                    return
                else:
                    logger.warning("Words found but formatted text is empty for film=%s", film_title)

            lesson = await actions.build_movie_learning_suggestion(film_title)
            await query.message.reply_text(
                movies_ui.build_english_text(film_title, lesson),
                parse_mode=ParseMode.HTML,
                reply_markup=movies_ui.movie_back_keyboard(entry_id),
            )
            return
        except Exception as e:
            logger.exception("Error handling English button for film=%s: %s", film_title, e)
            try:
                await query.message.reply_text(
                    "Ошибка при обработке запроса. Попробуй позже.",
                    reply_markup=movies_ui.movie_back_keyboard(entry_id),
                )
            except Exception as send_err:
                logger.exception("Failed to send error message: %s", send_err)
            return
    if action == "words":
        try:
            # Get cached words from context
            words_key = f"words_{entry_id}"
            year_key = f"film_year_{entry_id}"
            
            words = context.user_data.get(words_key, [])
            year = context.user_data.get(year_key)
            
            if not words:
                logger.warning("No words found in context for word navigation: entry_id=%s", entry_id)
                await query.message.reply_text(
                    "Слова больше не в памяти. Нажми English заново.",
                    reply_markup=movies_ui.movie_back_keyboard(entry_id),
                )
                return
            
            # Format words for current page
            text = word_extractor.format_words_for_telegram(film_title, year, words, page=page, per_page=5)
            if text:
                total_pages = (len(words) + 4) // 5
                keyboard = movies_ui.words_keyboard(entry_id, page=page, total_pages=total_pages)
                try:
                    await query.message.edit_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                except Exception as edit_err:
                    logger.debug("Could not edit message, sending new one: %s", edit_err)
                    await query.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
            return
        except Exception as e:
            logger.exception("Error handling words pagination for entry_id=%s page=%s: %s", entry_id, page, e)
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
