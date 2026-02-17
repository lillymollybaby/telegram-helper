from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ContextTypes

from app.services import food_service


async def start_add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_add_meal(update, context)


async def show_day_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.show_day_summary(update, context)


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.show_history(update, context)


async def suggest_dinner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.suggest_dinner(update, context)


async def start_composition_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_composition_analysis(update, context)


async def start_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_ai_question(update, context)


async def start_goal_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_goal_update(update, context)


async def start_params_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_params_update(update, context)


async def start_reminder_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_service.start_reminder_update(update, context)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await food_service.handle_text_input(update, context)


async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await food_service.handle_photo_input(update, context)


def schedule_jobs(application: Application) -> None:
    food_service.schedule_jobs(application)
