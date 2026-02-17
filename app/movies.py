from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.services import (
    movies_callbacks,
    movies_commands,
    movies_english_flow,
    movies_generation,
    movies_letterboxd_sync,
    movies_nav,
)

logger = logging.getLogger(__name__)


async def movie_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actions = movies_callbacks.MoviesCallbacksActions(
        build_movie_learning_suggestion=movies_generation.build_movie_learning_suggestion,
        send_next_english_word=movies_english_flow.send_next_english_word,
    )
    await movies_callbacks.movie_action_callback(update, context, actions)


async def movie_people_carousel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await movies_callbacks.movie_people_carousel_callback(update, context, logger)


async def english_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actions = movies_callbacks.MoviesCallbacksActions(
        build_movie_learning_suggestion=movies_generation.build_movie_learning_suggestion,
        send_next_english_word=movies_english_flow.send_next_english_word,
    )
    await movies_callbacks.english_word_callback(update, context, actions)


async def poll_letterboxd_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await movies_commands.poll_letterboxd_job(context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    actions = movies_nav.MoviesNavActions(
        movies_cmd=movies_commands.movies_cmd,
        movies_bind_cmd=movies_commands.movies_bind_cmd,
        movies_check_cmd=movies_commands.movies_check_cmd,
        movies_check_wishlist_cmd=movies_commands.movies_check_wishlist_cmd,
        movies_english_cmd=movies_commands.movies_english_cmd,
        movies_status_cmd=movies_commands.movies_status_cmd,
        movies_unbind_cmd=movies_commands.movies_unbind_cmd,
        bind_letterboxd_rss_for_user=movies_letterboxd_sync.bind_letterboxd_rss_for_user,
        send_next_english_word=movies_english_flow.send_next_english_word,
    )
    return await movies_nav.handle_text(update, context, actions)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("movies", movies_commands.movies_cmd))
    application.add_handler(CommandHandler("movies_bind", movies_commands.movies_bind_cmd))
    application.add_handler(CommandHandler("movies_check", movies_commands.movies_check_cmd))
    application.add_handler(CommandHandler("movies_wishlist", movies_commands.movies_check_wishlist_cmd))
    application.add_handler(CommandHandler("movies_english", movies_commands.movies_english_cmd))
    application.add_handler(CommandHandler("movies_status", movies_commands.movies_status_cmd))
    application.add_handler(CommandHandler("movies_unbind", movies_commands.movies_unbind_cmd))
    application.add_handler(CallbackQueryHandler(english_word_callback, pattern=r"^eng:"))
    application.add_handler(CallbackQueryHandler(movie_people_carousel_callback, pattern=r"^mvp:"))
    application.add_handler(CallbackQueryHandler(movie_action_callback, pattern=r"^mv:"))
