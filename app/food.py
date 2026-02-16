from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import Application, ContextTypes

from app import config, db
from app.keyboards import food_coach_keyboard, food_diary_keyboard, food_profile_keyboard

logger = logging.getLogger(__name__)

STATE_WAIT_MEAL = "food_wait_meal"
STATE_WAIT_COMPOSITION = "food_wait_composition"
STATE_WAIT_AI = "food_wait_ai"
STATE_WAIT_PARAMS = "food_wait_params"
STATE_WAIT_GOAL = "food_wait_goal"
STATE_WAIT_REMINDER = "food_wait_reminder"


FOOD_HINTS = {
    "гречк": {"calories": 180, "protein": 6, "fat": 2, "carbs": 36, "fiber": 5},
    "пюре": {"calories": 150, "protein": 3, "fat": 5, "carbs": 24, "fiber": 2},
    "котлет": {"calories": 260, "protein": 16, "fat": 18, "carbs": 8, "fiber": 1},
    "рис": {"calories": 200, "protein": 4, "fat": 1, "carbs": 44, "fiber": 1},
    "куриц": {"calories": 220, "protein": 30, "fat": 10, "carbs": 0, "fiber": 0},
    "рыб": {"calories": 210, "protein": 26, "fat": 11, "carbs": 0, "fiber": 0},
    "салат": {"calories": 120, "protein": 4, "fat": 7, "carbs": 10, "fiber": 4},
    "хлеб": {"calories": 90, "protein": 3, "fat": 1, "carbs": 17, "fiber": 1},
    "яйц": {"calories": 80, "protein": 7, "fat": 6, "carbs": 1, "fiber": 0},
    "суп": {"calories": 180, "protein": 8, "fat": 7, "carbs": 22, "fiber": 3},
}


def _normalize_advice_text(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return ""
    has_latin = bool(re.search(r"[A-Za-z]", s))
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", s))
    if has_latin and not has_cyrillic:
        return "Старайтесь соблюдать баланс: меньше сахара, больше белка и овощей."
    return s


def _clear_food_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in (STATE_WAIT_MEAL, STATE_WAIT_COMPOSITION, STATE_WAIT_AI, STATE_WAIT_PARAMS, STATE_WAIT_GOAL, STATE_WAIT_REMINDER):
        context.user_data.pop(k, None)


def _extract_json(text: str) -> dict | None:
    raw = (text or "").strip().replace("```json", "").replace("```", "").strip()
    if not raw:
        return None
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _sum_items(items: list[dict]) -> dict:
    out = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "fiber": 0.0}
    for it in items:
        out["calories"] += float(it.get("calories", 0) or 0)
        out["protein"] += float(it.get("protein", 0) or 0)
        out["fat"] += float(it.get("fat", 0) or 0)
        out["carbs"] += float(it.get("carbs", 0) or 0)
        out["fiber"] += float(it.get("fiber", 0) or 0)
    return out


def _fallback_analyze_text(text: str) -> dict:
    t = (text or "").lower()
    items = []
    for key, vals in FOOD_HINTS.items():
        if key in t:
            items.append({"name": key, **vals})
    if not items:
        items = [{"name": "meal", "calories": 450, "protein": 18, "fat": 16, "carbs": 52, "fiber": 4}]
    totals = _sum_items(items)
    return {
        "meal_name": text or "Прием пищи",
        "items": items,
        "calories_kcal": round(totals["calories"], 1),
        "protein_g": round(totals["protein"], 1),
        "fat_g": round(totals["fat"], 1),
        "carbs_g": round(totals["carbs"], 1),
        "fiber_g": round(totals["fiber"], 1),
        "advice": ["Добавьте овощи или зелень для клетчатки.", "Пейте воду после еды."],
        "confidence": 0.55,
    }


async def _gemini_meal_json(prompt: str, image_bytes: bytes | None = None) -> dict | None:
    if not config.GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY}
    parts = [{"text": prompt}]
    if image_bytes:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                logger.warning("Gemini meal analysis failed: %s %s", r.status_code, r.text[:300])
                return None
            text = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return _extract_json(text)
    except Exception as e:
        logger.warning("Gemini meal analysis exception: %s", e)
        return None


def _normalized_analysis(obj: dict, fallback_name: str) -> dict:
    advice_raw = [str(x) for x in (obj.get("advice") or [])][:3] if isinstance(obj.get("advice"), list) else []
    advice = [x for x in (_normalize_advice_text(v) for v in advice_raw) if x]
    return {
        "meal_name": str(obj.get("meal_name") or fallback_name or "Прием пищи"),
        "items": obj.get("items") if isinstance(obj.get("items"), list) else [],
        "calories_kcal": float(obj.get("calories_kcal") or 0),
        "protein_g": float(obj.get("protein_g") or 0),
        "fat_g": float(obj.get("fat_g") or 0),
        "carbs_g": float(obj.get("carbs_g") or 0),
        "fiber_g": float(obj.get("fiber_g") or 0),
        "advice": advice,
        "confidence": float(obj.get("confidence") or 0.0),
    }


async def analyze_meal_text(text: str) -> dict:
    prompt = (
        "Ты диет-ассистент. Верни только JSON. Все поля и советы пиши только по-русски:\n"
        "{\"meal_name\":\"...\",\"items\":[{\"name\":\"...\",\"portion_g\":0,\"calories\":0,\"protein\":0,\"fat\":0,\"carbs\":0,\"fiber\":0}],"
        "\"calories_kcal\":0,\"protein_g\":0,\"fat_g\":0,\"carbs_g\":0,\"fiber_g\":0,"
        "\"advice\":[\"...\",\"...\"],\"confidence\":0.0}\n"
        f"Оцени прием пищи: {text}\n"
        "Если данных мало, дай разумную оценку."
    )
    obj = await _gemini_meal_json(prompt)
    if obj:
        norm = _normalized_analysis(obj, text)
        if norm.get("calories_kcal", 0) > 0:
            return norm
    return _fallback_analyze_text(text)


async def analyze_meal_photo(caption: str, image_bytes: bytes) -> dict:
    prompt = (
        "Ты диет-ассистент. Проанализируй фото еды и подпись. Верни только JSON. Все поля и советы пиши только по-русски:\n"
        "{\"meal_name\":\"...\",\"items\":[{\"name\":\"...\",\"portion_g\":0,\"calories\":0,\"protein\":0,\"fat\":0,\"carbs\":0,\"fiber\":0}],"
        "\"calories_kcal\":0,\"protein_g\":0,\"fat_g\":0,\"carbs_g\":0,\"fiber_g\":0,"
        "\"advice\":[\"...\",\"...\"],\"confidence\":0.0}\n"
        f"Подпись: {caption or 'без подписи'}"
    )
    obj = await _gemini_meal_json(prompt, image_bytes=image_bytes)
    if obj:
        norm = _normalized_analysis(obj, caption or "Прием пищи")
        if norm.get("calories_kcal", 0) > 0:
            return norm
    return _fallback_analyze_text(caption or "еда по фото")


def _format_meal_saved_text(analysis: dict, meal_time: datetime) -> str:
    advice = analysis.get("advice") or []
    lines = [
        f"Записал прием пищи: {analysis.get('meal_name', 'Прием пищи')}",
        f"Дата/время: {meal_time.strftime('%d.%m.%Y %H:%M')}",
        (
            "Оценка: "
            f"{analysis.get('calories_kcal', 0):.0f} ккал | "
            f"Б {analysis.get('protein_g', 0):.1f} г | "
            f"Ж {analysis.get('fat_g', 0):.1f} г | "
            f"У {analysis.get('carbs_g', 0):.1f} г"
        ),
        "Приятного аппетита!",
    ]
    if advice:
        lines.append(f"Совет: {advice[0]}")
    return "\n".join(lines)


def _today_in_user_tz(profile: dict) -> tuple[datetime, str]:
    tz_name = profile.get("timezone") or config.FOOD_DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    return now, now.date().isoformat()


def _daily_target_calories(profile: dict) -> int:
    goal = (profile.get("goal") or "").lower()
    if "похуд" in goal or "дефицит" in goal:
        return 1700
    if "набор" in goal or "мас" in goal:
        return 2400
    return config.FOOD_CALORIE_TARGET_DEFAULT


def _simple_dinner_suggestion(totals: dict, profile: dict) -> str:
    target = _daily_target_calories(profile)
    remaining = max(0, target - int(float(totals.get("calories", 0) or 0)))
    protein = float(totals.get("protein", 0) or 0)
    tips = []
    if remaining < 300:
        tips.append("ужин сделать легким: овощи + нежирный белок")
    else:
        tips.append("добавьте белок (рыба/курица/творог) и овощи")
    if protein < 70:
        tips.append("доберите белок")
    tips.append("сведите быстрые углеводы к минимуму вечером")
    return f"Через час ужин. Сегодня у вас {totals.get('calories', 0):.0f} ккал. Можно добрать ~{remaining} ккал: " + "; ".join(tips[:2]) + "."


async def start_add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
    context.user_data[STATE_WAIT_MEAL] = True
    await update.effective_message.reply_text(
        "Отправьте фото еды или напишите, что съели. Пример: гречка с пюре и котлетой.",
        reply_markup=food_diary_keyboard(),
    )


async def show_day_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = dict(db.get_food_profile(user_id))
    now, date_iso = _today_in_user_tz(profile)
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
    _, date_iso = _today_in_user_tz(profile)
    totals = db.get_food_daily_totals(user_id, date_iso)
    if int(totals.get("meals_count", 0)) == 0:
        await update.effective_message.reply_text(
            "Пока нет записей за сегодня. Сначала добавьте прием пищи.",
            reply_markup=food_coach_keyboard(),
        )
        return
    await update.effective_message.reply_text(_simple_dinner_suggestion(totals, profile), reply_markup=food_coach_keyboard())


async def start_composition_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
    context.user_data[STATE_WAIT_COMPOSITION] = True
    await update.effective_message.reply_text(
        "Напишите состав/этикетку продукта, я разберу плюсы и риски.",
        reply_markup=food_coach_keyboard(),
    )


async def start_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
    context.user_data[STATE_WAIT_AI] = True
    await update.effective_message.reply_text("Задайте вопрос по питанию.", reply_markup=food_coach_keyboard())


async def start_goal_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
    context.user_data[STATE_WAIT_GOAL] = True
    await update.effective_message.reply_text(
        "Напишите цель: например, похудение / поддержание / набор массы.",
        reply_markup=food_profile_keyboard(),
    )


async def start_params_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
    context.user_data[STATE_WAIT_PARAMS] = True
    await update.effective_message.reply_text(
        "Напишите параметры в одной строке. Пример: вес 74, рост 178, возраст 25, пол м.",
        reply_markup=food_profile_keyboard(),
    )


async def start_reminder_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_food_states(context)
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
        analysis = await analyze_meal_text(raw_text)
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
        _clear_food_states(context)
        await update.effective_message.reply_text(_format_meal_saved_text(analysis, meal_time), reply_markup=food_diary_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_COMPOSITION):
        _clear_food_states(context)
        prompt = (
            "Разбери состав продукта и ответь кратко по-русски: что ок, что спорно, как часто есть.\n"
            f"Состав: {raw_text}"
        )
        obj = await _gemini_meal_json(prompt)
        txt = "Разбор состава: " + (json.dumps(obj, ensure_ascii=False) if obj else "состав выглядит приемлемо, но контролируйте сахар/соль.")
        await update.effective_message.reply_text(txt, reply_markup=food_coach_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_AI):
        _clear_food_states(context)
        prompt = f"Ответь как нутрициолог кратко и по делу на вопрос: {raw_text}"
        obj = await _gemini_meal_json(prompt)
        if obj and obj.get("answer"):
            text = str(obj.get("answer"))
        else:
            text = "Рекомендую держать баланс: белок + овощи + сложные углеводы, и контролировать общий калораж."
        await update.effective_message.reply_text(text, reply_markup=food_coach_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_GOAL):
        _clear_food_states(context)
        db.update_food_goal(user_id, raw_text)
        await update.effective_message.reply_text("Цель сохранена.", reply_markup=food_profile_keyboard())
        return True

    if context.user_data.get(STATE_WAIT_PARAMS):
        _clear_food_states(context)
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
        _clear_food_states(context)
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
    analysis = await analyze_meal_photo(caption, bytes(data))
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
    _clear_food_states(context)
    await update.effective_message.reply_text(_format_meal_saved_text(analysis, meal_time), reply_markup=food_diary_keyboard())
    return True


async def dinner_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_utc = datetime.now(timezone.utc)
    for row in db.list_food_profiles_for_reminders():
        p = dict(row)
        try:
            tz = ZoneInfo(p.get("timezone") or config.FOOD_DEFAULT_TIMEZONE)
        except Exception:
            tz = timezone.utc

        local_now = now_utc.astimezone(tz)
        dinner_hour = int(p.get("dinner_hour", config.FOOD_DINNER_HOUR))
        nudge_hour = (dinner_hour - 1) % 24

        # Send one nudge in the target hour (e.g. 18:xx for 19:00 dinner).
        if local_now.hour != nudge_hour:
            continue

        today = local_now.date().isoformat()
        if p.get("last_dinner_nudge_date") == today:
            continue

        totals = db.get_food_daily_totals(int(p["user_id"]), today)
        if int(totals.get("meals_count", 0)) == 0:
            text = "Через час ужин. Сегодня еще нет записей по еде. Добавьте прием пищи, и я подскажу рацион точнее."
        else:
            text = _simple_dinner_suggestion(totals, p)
        try:
            await context.bot.send_message(chat_id=int(p["user_id"]), text=text)
            db.mark_food_nudge_sent(int(p["user_id"]), today)
        except Exception as e:
            logger.warning("Failed to send dinner nudge to %s: %s", p["user_id"], e)

def schedule_jobs(application: Application) -> None:
    application.job_queue.run_repeating(
        dinner_nudge_job,
        interval=max(60, config.FOOD_REMINDER_INTERVAL_SEC),
        first=20,
        name="food_dinner_nudges",
    )

