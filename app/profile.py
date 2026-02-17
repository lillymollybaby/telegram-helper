from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ContextTypes

from app.services import profile_service


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> bool:
    return await profile_service.start_onboarding(update, context, force=force)


async def show_profile_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_service.show_profile_summary(update, context)


async def show_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_service.show_profile_menu(update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await profile_service.handle_text(update, context)


def schedule_jobs(application: Application) -> None:
    profile_service.schedule_jobs(application)
