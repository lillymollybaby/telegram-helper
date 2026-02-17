from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, ContextTypes

from app import config

logger = logging.getLogger(__name__)


async def _delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if not chat_id or not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("Failed to delete message %s in chat %s: %s", message_id, chat_id, e)


def _schedule_delete(application: Application, chat_id: int, message_id: int, delay_sec: int) -> None:
    if not application.job_queue:
        return
    delay = max(0, int(delay_sec))
    application.job_queue.run_once(
        _delete_message_job,
        when=delay,
        data={"chat_id": chat_id, "message_id": message_id},
        name=f"cleanup_{chat_id}_{message_id}",
    )


def schedule_bot_message_cleanup(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay_sec: int | None = None) -> None:
    if not config.AUTO_DELETE_ALL_MESSAGES:
        return
    delay = config.AUTO_DELETE_ALL_DELAY_SEC if delay_sec is None else max(0, int(delay_sec))
    _schedule_delete(context.application, chat_id, message_id, delay)


def schedule_bot_message_cleanup_at(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    when_dt: datetime,
    min_delay_sec: int = 30,
) -> None:
    now = datetime.now()
    delay = max(min_delay_sec, int((when_dt - now).total_seconds()))
    _schedule_delete(context.application, chat_id, message_id, delay)


async def cleanup_trigger_message(update: Update, context: ContextTypes.DEFAULT_TYPE, delay_sec: int | None = None) -> None:
    if not config.AUTO_DELETE_TRIGGER_MESSAGES:
        return
    msg = update.effective_message
    if not msg:
        return
    delay = config.AUTO_DELETE_DELAY_SEC if delay_sec is None else max(0, int(delay_sec))
    if delay > 0 and context.job_queue:
        context.job_queue.run_once(
            _delete_message_job,
            when=delay,
            data={"chat_id": msg.chat_id, "message_id": msg.message_id},
            name=f"cleanup_{msg.chat_id}_{msg.message_id}",
        )
        return
    try:
        await msg.delete()
    except Exception as e:
        logger.debug("Failed to delete trigger message %s in chat %s: %s", msg.message_id, msg.chat_id, e)
