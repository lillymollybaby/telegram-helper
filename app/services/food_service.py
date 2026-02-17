from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from telegram import Update
from telegram.ext import Application, ContextTypes

from app import config, db
from app.keyboards import food_coach_keyboard, food_diary_keyboard, food_profile_keyboard
from app.services import food_analysis, food_jobs

logger = logging.getLogger(__name__)

STATE_WAIT_MEAL = food_analysis.STATE_WAIT_MEAL
STATE_WAIT_COMPOSITION = food_analysis.STATE_WAIT_COMPOSITION
STATE_WAIT_AI = food_analysis.STATE_WAIT_AI
STATE_WAIT_PARAMS = food_analysis.STATE_WAIT_PARAMS
STATE_WAIT_GOAL = food_analysis.STATE_WAIT_GOAL
STATE_WAIT_REMINDER = food_analysis.STATE_WAIT_REMINDER


async def start_add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_MEAL] = True
    await update.effective_message.reply_text(
        "Отправьте фото еды или напишите, что съели. Пример: гречка с пюре и котлетой.",
        reply_markup=food_diary_keyboard(),
    )


async def show_day_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = dict(db.get_food_profile(user_id))
    now, date_iso = food_jobs.today_in_user_tz(profile)
    meals = db.list_food_meals_for_date(user_id, date_iso)
    totals = db.get_food_daily_totals(user_id, date_iso)
    if not meals:
        await update.effective_message.reply_text("Сегодня еще нет записей о еде.", reply_markup=food_diary_keyboard())
        return
    lines = [f"Итоги за {now.strftime('%d.%m.%Y')}:"]
    for m in meals[-8:]:
        t = datetime.fromisoformat(m["meal_time"]).strftime("%H:%M")
        lines.append(f"- {t}: {m['meal_text'] or 'Прием пищи'} ({(m['calories'] or 0):.0f} ккал)")
    lines.append("")
    lines.append(
        f"Всего: {totals['calories']:.0f} ккал | Б {totals['protein']:.1f} г | Ж {totals['fat']:.1f} г | У {totals['carbs']:.1f} г"
    )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=food_diary_keyboard())


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.list_food_meals(update.effective_user.id, limit=12)
    if not rows:
        await update.effective_message.reply_text("История пуста.", reply_markup=food_diary_keyboard())
        return
    lines = ["История приемов пищи:"]
    for r in rows:
        dt = datetime.fromisoformat(r["meal_time"]).strftime("%d.%m %H:%M")
        lines.append(f"- {dt}: {r['meal_text'] or 'Прием пищи'} ({(r['calories'] or 0):.0f} ккал)")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=food_diary_keyboard())


async def suggest_dinner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = dict(db.get_food_profile(user_id))
    _, date_iso = food_jobs.today_in_user_tz(profile)
    totals = db.get_food_daily_totals(user_id, date_iso)
    if int(totals.get("meals_count", 0)) == 0:
        await update.effective_message.reply_text(
            "Пока нет записей за сегодня. Сначала добавьте прием пищи.",
            reply_markup=food_coach_keyboard(),
        )
        return
    await update.effective_message.reply_text(food_jobs.simple_dinner_suggestion(totals, profile), reply_markup=food_coach_keyboard())


async def start_composition_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_COMPOSITION] = True
    await update.effective_message.reply_text(
        "Напишите состав/этикетку продукта, я разберу плюсы и риски.",
        reply_markup=food_coach_keyboard(),
    )


async def start_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_AI] = True
    await update.effective_message.reply_text("Задайте вопрос по питанию.", reply_markup=food_coach_keyboard())


async def start_goal_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_GOAL] = True
    await update.effective_message.reply_text(
        "Напишите цель: например, похудение / поддержание / набор массы.",
        reply_markup=food_profile_keyboard(),
    )


async def start_params_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_PARAMS] = True
    await update.effective_message.reply_text(
        "Напишите параметры в одной строке. Пример: вес 74, рост 178, возраст 25, пол м.",
        reply_markup=food_profile_keyboard(),
    )


async def start_reminder_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    food_analysis.clear_food_states(context)
    context.user_data[STATE_WAIT_REMINDER] = True
    profile = dict(db.get_food_profile(update.effective_user.id))
    await update.effective_message.reply_text(
        f"Текущий ужин: {profile.get('dinner_hour', config.FOOD_DINNER_HOUR)}:00. Введите новый час (0-23).",
        reply_markup=food_profile_keyboard(),
    )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    raw_text = (update.effective_message.text or "").strip()
    if not raw_text:
        return False
    user_id = update.effective_user.id

    if context.user_data.get(STATE_WAIT_MEAL):
        analysis = await food_analysis.analyze_meal_text(raw_text)
        meal_time = datetime.now()
        db.save_food_meal(
            user_id=user_id,
            meal_text=raw_text,
            meal_time=meal_time,
            calories=analysis.get("calories_kcal"),
            protein=analysis.get("protein_g"),
            fat=analysis.get("fat_g"),
            carbs=analysis.get("carbs_g"),
            fiber=analysis.get("fiber_g"),
            analysis=analysis,
            source="text",
        )
        food_analysis.clear_food_states(context)
        await update.effective_message.reply_text(food_analysis.format_meal_saved_text(analysis, meal_time), reply_markup=food_diary_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_COMPOSITION):
        food_analysis.clear_food_states(context)
        prompt = (
            "Разбери состав продукта и ответь кратко по-русски: что ок, что спорно, как часто есть.\n"
            f"Состав: {raw_text}"
        )
        obj = await food_analysis.gemini_meal_json(prompt)
        txt = "Разбор состава: " + (json.dumps(obj, ensure_ascii=False) if obj else "состав выглядит приемлемо, но контролируйте сахар/соль.")
        await update.effective_message.reply_text(txt, reply_markup=food_coach_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_AI):
        food_analysis.clear_food_states(context)
        prompt = f"Ответь как нутрициолог кратко и по делу на вопрос: {raw_text}"
        obj = await food_analysis.gemini_meal_json(prompt)
        text = str(obj.get("answer")) if obj and obj.get("answer") else "Рекомендую баланс: белок + овощи + сложные углеводы и контроль общего калоража."
        await update.effective_message.reply_text(text, reply_markup=food_coach_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_GOAL):
        food_analysis.clear_food_states(context)
        db.update_food_goal(user_id, raw_text)
        await update.effective_message.reply_text("Цель сохранена.", reply_markup=food_profile_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_PARAMS):
        food_analysis.clear_food_states(context)
        params = {"raw": raw_text}
        m_weight = re.search(r"(вес|weight)\D*(\d{2,3})", raw_text, flags=re.IGNORECASE)
        m_height = re.search(r"(рост|height)\D*(\d{2,3})", raw_text, flags=re.IGNORECASE)
        m_age = re.search(r"(возраст|age)\D*(\d{1,2})", raw_text, flags=re.IGNORECASE)
        if m_weight:
            params["weight_kg"] = int(m_weight.group(2))
        if m_height:
            params["height_cm"] = int(m_height.group(2))
        if m_age:
            params["age"] = int(m_age.group(2))
        db.update_food_params(user_id, params)
        await update.effective_message.reply_text("Параметры сохранены.", reply_markup=food_profile_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_REMINDER):
        hour_match = re.search(r"\b([01]?\d|2[0-3])\b", raw_text)
        if not hour_match:
            await update.effective_message.reply_text("Введите час от 0 до 23.", reply_markup=food_profile_keyboard())
            return True
        hour = int(hour_match.group(1))
        food_analysis.clear_food_states(context)
        db.update_food_reminder(user_id, dinner_hour=hour)
        await update.effective_message.reply_text(f"Напоминание на ужин обновлено: {hour:02d}:00.", reply_markup=food_profile_keyboard())
        return True

    return False


async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get(STATE_WAIT_MEAL):
        return False
    photos = update.effective_message.photo or []
    if not photos:
        return False
    best = photos[-1]
    tf = await context.bot.get_file(best.file_id)
    data = await tf.download_as_bytearray()
    caption = (update.effective_message.caption or "").strip()
    analysis = await food_analysis.analyze_meal_photo(caption, bytes(data))
    meal_time = datetime.now()
    db.save_food_meal(
        user_id=update.effective_user.id,
        meal_text=caption or analysis.get("meal_name") or "Прием пищи (по фото)",
        meal_time=meal_time,
        calories=analysis.get("calories_kcal"),
        protein=analysis.get("protein_g"),
        fat=analysis.get("fat_g"),
        carbs=analysis.get("carbs_g"),
        fiber=analysis.get("fiber_g"),
        analysis=analysis,
        image_file_id=best.file_id,
        source="photo",
    )
    food_analysis.clear_food_states(context)
    await update.effective_message.reply_text(food_analysis.format_meal_saved_text(analysis, meal_time), reply_markup=food_diary_keyboard())
    return True


async def dinner_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await food_jobs.dinner_nudge_job(context)


def schedule_jobs(application: Application) -> None:
    food_jobs.schedule_jobs(application)
