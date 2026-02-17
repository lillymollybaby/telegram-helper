from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, planner
from app.keyboards import (
    food_menu_keyboard,
    language_menu_keyboard,
    movies_menu_keyboard,
    my_plans_menu_keyboard,
    planning_menu_keyboard,
    profile_menu_keyboard,
)
from app.services.navigation_common import send_nav_message, set_screen, show_main_menu


async def handle_core_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()
    screen = context.user_data.get("screen", "main")

    if text == config.BTN_HOME_MENU:
        await cleanup.cleanup_trigger_message(update, context)
        planner.cancel_draft(context)
        await show_main_menu(update, context)
        return True

    if text == config.BTN_BACK_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        planner.cancel_draft(context)
        if screen in {"lang_level", "lang_exam", "lang_grammar_topics"}:
            set_screen(context, "lang_language")
            await send_nav_message(update, context, "Language Learning", language_menu_keyboard())
        elif screen in {"food_diary", "food_coach", "food_profile"}:
            set_screen(context, "food_main")
            await send_nav_message(update, context, "Food", food_menu_keyboard())
        else:
            await show_main_menu(update, context)
        return True

    if text == config.BTN_LANGUAGE:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "lang_language")
        await send_nav_message(update, context, "Language Learning", language_menu_keyboard())
        return True

    if text == config.BTN_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "movie")
        await send_nav_message(update, context, "Movie", movies_menu_keyboard())
        return True

    if text == config.BTN_PLANNER:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "planning")
        await send_nav_message(update, context, "Personal Planning", planning_menu_keyboard())
        return True

    if text == config.BTN_FOOD:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "food_main")
        await send_nav_message(update, context, "Food", food_menu_keyboard())
        return True

    if text == config.BTN_PROFILE:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "profile")
        await send_nav_message(update, context, "Мой профиль", profile_menu_keyboard())
        return True

    if text == config.BTN_MY_PLANS:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "plans")
        await send_nav_message(update, context, "My Plans", my_plans_menu_keyboard())
        return True

    return False

