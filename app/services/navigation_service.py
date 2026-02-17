from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import food, movies, planner, profile
from app.keyboards import main_menu_keyboard
from app.services.navigation_core import handle_core_navigation
from app.services.navigation_food import handle_food_navigation
from app.services.navigation_language import handle_language_navigation
from app.services.navigation_movies import handle_movies_navigation
from app.services.navigation_plans import handle_plans_navigation


async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    handlers = (
        handle_core_navigation,
        handle_language_navigation,
        handle_movies_navigation,
        handle_food_navigation,
        handle_plans_navigation,
    )
    for handler in handlers:
        if await handler(update, context):
            return True
    return False


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await handle_navigation(update, context):
        return
    if await profile.handle_text(update, context):
        return
    if await food.handle_text_input(update, context):
        return
    if await movies.handle_text(update, context):
        return
    if await planner.add_task_from_text(update, context):
        return
    await update.message.reply_text(
        "Use menu buttons.",
        reply_markup=main_menu_keyboard(),
    )


async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await food.handle_photo_input(update, context):
        return


async def location_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await planner.handle_location(update, context):
        return

