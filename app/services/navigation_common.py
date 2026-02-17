from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup
from app.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


def set_screen(context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    context.user_data["screen"] = name


async def delete_last_nav_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last_id = context.user_data.get("_last_nav_message_id")
    chat = update.effective_chat
    if not last_id or not chat:
        return
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=int(last_id))
    except Exception as e:
        logger.debug("Failed to delete previous nav message chat_id=%s message_id=%s: %s", chat.id, last_id, e)
    finally:
        context.user_data.pop("_last_nav_message_id", None)


async def send_nav_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup) -> None:
    await delete_last_nav_message(update, context)
    msg = await update.effective_message.reply_text(text, reply_markup=reply_markup)
    context.user_data["_last_nav_message_id"] = msg.message_id
    cleanup.schedule_bot_message_cleanup(context, msg.chat_id, msg.message_id, delay_sec=20)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_screen(context, "main")
    await send_nav_message(update, context, "Main Menu", main_menu_keyboard())

