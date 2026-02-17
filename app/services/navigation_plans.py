from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import cleanup, config, db, planner
from app.keyboards import my_plans_menu_keyboard
from app.services.navigation_common import delete_last_nav_message


async def handle_plans_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()
    if text not in {config.BTN_ACTIVE_PLANS, config.BTN_ALL_PLANS}:
        return False

    await cleanup.cleanup_trigger_message(update, context)
    await delete_last_nav_message(update, context)
    tasks = db.list_tasks_for_user(update.effective_user.id)
    if not tasks:
        await update.effective_message.reply_text("Активных задач нет.", reply_markup=my_plans_menu_keyboard())
        return True

    lines = [f"Ваши задачи ({len(tasks)}):", ""]
    for t in tasks:
        title = planner.humanize_task_title(t.text, t.destination)
        lines.append(f"Когда: {t.event_time.strftime('%d.%m.%Y %H:%M')}")
        lines.append(f"Что: {title}")
        if t.destination:
            lines.append(f"Куда: {t.destination}")
        lines.append("")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=my_plans_menu_keyboard())
    return True

