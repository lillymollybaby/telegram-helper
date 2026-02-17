from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.services import planner_commands, planner_draft, planner_flow, planner_jobs, planner_parsing


def cancel_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    planner_draft.cancel_draft(context)


def humanize_task_title(text: str, destination: str | None = None) -> str:
    return planner_parsing.humanize_task_title(text, destination)


async def add_task_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await planner_flow.add_task_from_text(update, context)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await planner_flow.handle_location(update, context)


async def load_pending_jobs(application: Application) -> None:
    await planner_jobs.load_pending_jobs(application)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", planner_commands.start))
    application.add_handler(CommandHandler("help", planner_commands.help_cmd))
    application.add_handler(CommandHandler("home", planner_commands.home))
    application.add_handler(CommandHandler("list", planner_commands.list_cmd))
    application.add_handler(CommandHandler("delete", planner_commands.delete_cmd))
    application.add_handler(CommandHandler("delete_last", planner_commands.delete_last_cmd))


def ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
