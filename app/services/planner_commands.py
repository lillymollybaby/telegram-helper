from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, db
from app.keyboards import main_menu_keyboard
from app.services import planner_parsing


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    from app import profile

    if not db.is_onboarding_completed(update.effective_user.id):
        await profile.start_onboarding(update, context, force=False)
        return
    await update.message.reply_text(
        "Я бот-помощник. Кнопка «Планировщик» — задачи, «Фильмы» — Letterboxd.",
        reply_markup=main_menu_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    txt = (
        "Планировщик:\n"
        "- Просто напишите задачу: завтра к стоматологу в 16:00 на Ленина 10\n"
        "- /home <адрес>\n"
        "- /list\n"
        "- /delete <id>\n"
        "- /delete_last"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_keyboard())


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    address = " ".join(context.args).strip()
    if not address:
        cur = db.get_home_address(user_id)
        await update.message.reply_text(cur or "Укажите: /home <адрес>", reply_markup=main_menu_keyboard())
        return
    db.set_home_address(user_id, address)
    await update.message.reply_text(f"Сохранил домашний адрес: {address}", reply_markup=main_menu_keyboard())


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    tasks = db.list_tasks_for_user(user_id)
    if not tasks:
        await update.message.reply_text("Активных задач нет.", reply_markup=main_menu_keyboard())
        return

    lines = [f"Ваши задачи ({len(tasks)}):", ""]
    for t in tasks:
        title = planner_parsing.humanize_task_title(t.text, t.destination)
        lines.append(f"#{t.id} | {t.event_time.strftime('%d.%m.%Y %H:%M')}")
        lines.append(f"Что: {title}")
        if t.destination:
            lines.append(f"Куда: {t.destination}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Использование: /delete <id>", reply_markup=main_menu_keyboard())
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.", reply_markup=main_menu_keyboard())
        return

    if db.delete_task(user_id, task_id):
        for job in context.application.job_queue.get_jobs_by_name(f"task_{task_id}"):
            job.schedule_removal()
        await update.message.reply_text(f"Задача #{task_id} удалена.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("Задача не найдена.", reply_markup=main_menu_keyboard())


async def delete_last_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    task_id = db.delete_last_task(user_id)
    if not task_id:
        await update.message.reply_text("Удалять нечего.", reply_markup=main_menu_keyboard())
        return
    for job in context.application.job_queue.get_jobs_by_name(f"task_{task_id}"):
        job.schedule_removal()
    await update.message.reply_text(f"Удалил последнюю задачу #{task_id}.", reply_markup=main_menu_keyboard())
