from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, food
from app.keyboards import food_coach_keyboard, food_diary_keyboard, food_profile_keyboard
from app.services.navigation_common import send_nav_message, set_screen


async def handle_food_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()

    if text == config.BTN_FOOD_DIARY:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "food_diary")
        await send_nav_message(update, context, config.BTN_FOOD_DIARY, food_diary_keyboard())
        return True

    if text == config.BTN_FOOD_COACH:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "food_coach")
        await send_nav_message(update, context, config.BTN_FOOD_COACH, food_coach_keyboard())
        return True

    if text == config.BTN_FOOD_PROFILE:
        await cleanup.cleanup_trigger_message(update, context)
        set_screen(context, "food_profile")
        await send_nav_message(update, context, config.BTN_FOOD_PROFILE, food_profile_keyboard())
        return True

    if text in {config.BTN_FOOD_ADD_MEAL, config.BTN_FOOD_DAY_SUMMARY, config.BTN_FOOD_HISTORY}:
        await cleanup.cleanup_trigger_message(update, context)
        if text == config.BTN_FOOD_ADD_MEAL:
            await food.start_add_meal(update, context)
        elif text == config.BTN_FOOD_DAY_SUMMARY:
            await food.show_day_summary(update, context)
        else:
            await food.show_history(update, context)
        return True

    if text in {config.BTN_FOOD_DINNER, config.BTN_FOOD_COMPOSITION, config.BTN_FOOD_ASK_AI}:
        await cleanup.cleanup_trigger_message(update, context)
        if text == config.BTN_FOOD_DINNER:
            await food.suggest_dinner(update, context)
        elif text == config.BTN_FOOD_COMPOSITION:
            await food.start_composition_analysis(update, context)
        else:
            await food.start_ai_question(update, context)
        return True

    if text in {config.BTN_FOOD_PARAMS, config.BTN_FOOD_GOAL, config.BTN_FOOD_REMINDERS}:
        await cleanup.cleanup_trigger_message(update, context)
        if text == config.BTN_FOOD_PARAMS:
            await food.start_params_update(update, context)
        elif text == config.BTN_FOOD_GOAL:
            await food.start_goal_update(update, context)
        else:
            await food.start_reminder_update(update, context)
        return True

    return False

