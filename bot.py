from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app import cleanup, config, db, food, movies, planner, profile
from app.keyboards import (
    food_coach_keyboard,
    food_diary_keyboard,
    food_menu_keyboard,
    food_profile_keyboard,
    language_exam_keyboard,
    language_language_keyboard,
    language_level_keyboard,
    language_menu_keyboard,
    main_menu_keyboard,
    movies_menu_keyboard,
    my_plans_menu_keyboard,
    planning_menu_keyboard,
    profile_menu_keyboard,
)


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _set_screen(context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    context.user_data["screen"] = name


async def _delete_last_nav_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last_id = context.user_data.get("_last_nav_message_id")
    chat = update.effective_chat
    if not last_id or not chat:
        return
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=int(last_id))
    except Exception:
        pass
    finally:
        context.user_data.pop("_last_nav_message_id", None)


async def _send_nav_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup) -> None:
    await _delete_last_nav_message(update, context)
    msg = await update.effective_message.reply_text(text, reply_markup=reply_markup)
    context.user_data["_last_nav_message_id"] = msg.message_id
    cleanup.schedule_bot_message_cleanup(context, msg.chat_id, msg.message_id, delay_sec=20)


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _set_screen(context, "main")
    await _send_nav_message(update, context, "Main Menu", main_menu_keyboard())


async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()
    screen = context.user_data.get("screen", "main")

    if text == config.BTN_HOME_MENU:
        await cleanup.cleanup_trigger_message(update, context)
        planner.cancel_draft(context)
        await _show_main_menu(update, context)
        return True

    if text == config.BTN_BACK_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        planner.cancel_draft(context)
        if screen in {"lang_level", "lang_exam"}:
            _set_screen(context, "lang_language")
            await _send_nav_message(update, context, "Language Learning", language_menu_keyboard())
        elif screen in {"food_diary", "food_coach", "food_profile"}:
            _set_screen(context, "food_main")
            await _send_nav_message(update, context, "Food", food_menu_keyboard())
        elif screen in {"lang_language", "movie", "planning", "plans"}:
            await _show_main_menu(update, context)
        elif screen in {"food_main"}:
            await _show_main_menu(update, context)
        else:
            await _show_main_menu(update, context)
        return True

    if text == config.BTN_LANGUAGE:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "lang_language")
        await _send_nav_message(update, context, "Language Learning", language_menu_keyboard())
        return True

    if text in {config.BTN_LANG_ENGLISH, config.BTN_LANG_FRENCH, config.BTN_LANG_GERMAN}:
        await cleanup.cleanup_trigger_message(update, context)
        context.user_data["lang_selected"] = text
        _set_screen(context, "lang_language")
        await _send_nav_message(update, context, text, language_language_keyboard(text))
        return True

    if text in {config.BTN_LEVEL_A, config.BTN_LEVEL_B, config.BTN_LEVEL_C}:
        await cleanup.cleanup_trigger_message(update, context)
        context.user_data["lang_level"] = text
        _set_screen(context, "lang_level")
        await _send_nav_message(update, context, text, language_level_keyboard())
        return True

    if text in {config.BTN_SKILL_VOCAB, config.BTN_SKILL_GRAMMAR}:
        await cleanup.cleanup_trigger_message(update, context)
        lang = context.user_data.get("lang_selected", "Language")
        level = context.user_data.get("lang_level", "")
        await update.effective_message.reply_text(
            f"{lang} / {level} / {text}\nSection is ready for content.",
            reply_markup=language_level_keyboard(),
        )
        return True

    if text in {config.BTN_EXAM_IELTS, config.BTN_EXAM_DELF, config.BTN_EXAM_GOETHE}:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "lang_exam")
        context.user_data["lang_exam"] = text
        await _send_nav_message(update, context, text, language_exam_keyboard(text))
        return True

    if text in {
        config.BTN_EXAM_IELTS_LISTEN,
        config.BTN_EXAM_IELTS_WRITE,
        config.BTN_EXAM_IELTS_READ,
        config.BTN_EXAM_DELF_WRITE,
        config.BTN_EXAM_DELF_READ,
        config.BTN_EXAM_DELF_LISTEN,
        config.BTN_EXAM_GOETHE_H,
        config.BTN_EXAM_GOETHE_S,
        config.BTN_EXAM_GOETHE_L,
    }:
        await cleanup.cleanup_trigger_message(update, context)
        exam = context.user_data.get("lang_exam", "Exam")
        await update.effective_message.reply_text(
            f"{exam} / {text}\nSection is ready for content.",
            reply_markup=language_exam_keyboard(exam),
        )
        return True

    if text == config.BTN_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "movie")
        await _send_nav_message(update, context, "Movie", movies_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_IMDB_LINK:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb integration will be added next.", reply_markup=movies_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_IMDB_UNLINK:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb integration will be added next.", reply_markup=movies_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_IMDB_MOVIES:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text("IMDb movies section will be added next.", reply_markup=movies_menu_keyboard())
        return True

    if text == config.BTN_MOVIES_CREW:
        await cleanup.cleanup_trigger_message(update, context)
        await update.effective_message.reply_text(
            "Use Logged Movies or Wishlist first, then select actors/director on a movie card.",
            reply_markup=movies_menu_keyboard(),
        )
        return True

    if text == config.BTN_PLANNER:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "planning")
        await _send_nav_message(update, context, "Personal Planning", planning_menu_keyboard())
        return True

    if text == config.BTN_FOOD:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "food_main")
        await _send_nav_message(update, context, "Food", food_menu_keyboard())
        return True

    if text == config.BTN_PROFILE:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "profile")
        await _send_nav_message(update, context, "Мой профиль", profile_menu_keyboard())
        return True

    if text == config.BTN_FOOD_DIARY:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "food_diary")
        await _send_nav_message(update, context, config.BTN_FOOD_DIARY, food_diary_keyboard())
        return True

    if text == config.BTN_FOOD_COACH:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "food_coach")
        await _send_nav_message(update, context, config.BTN_FOOD_COACH, food_coach_keyboard())
        return True

    if text == config.BTN_FOOD_PROFILE:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "food_profile")
        await _send_nav_message(update, context, config.BTN_FOOD_PROFILE, food_profile_keyboard())
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

    if text == config.BTN_MY_PLANS:
        await cleanup.cleanup_trigger_message(update, context)
        _set_screen(context, "plans")
        await _send_nav_message(update, context, "My Plans", my_plans_menu_keyboard())
        return True

    if text in {config.BTN_ACTIVE_PLANS, config.BTN_ALL_PLANS}:
        await cleanup.cleanup_trigger_message(update, context)
        await _delete_last_nav_message(update, context)
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


def build_app() -> Application:
    if not config.BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в .env")

    db.init_db()
    application = Application.builder().token(config.BOT_TOKEN).build()

    planner.register_handlers(application)
    movies.register_handlers(application)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    application.add_handler(MessageHandler(filters.PHOTO, photo_router))
    application.add_handler(MessageHandler(filters.LOCATION, location_router))

    async def post_init(app: Application) -> None:
        await planner.load_pending_jobs(app)
        app.job_queue.run_repeating(
            movies.poll_letterboxd_job,
            interval=max(10, config.LETTERBOXD_POLL_SECONDS),
            first=5,
            name="letterboxd_polling",
        )
        food.schedule_jobs(app)
        profile.schedule_jobs(app)

    application.post_init = post_init
    return application


def main() -> None:
    planner.ensure_event_loop()
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
