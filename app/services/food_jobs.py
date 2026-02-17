from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from app import config, db

logger = logging.getLogger(__name__)


def today_in_user_tz(profile: dict) -> tuple[datetime, str]:
    tz_name = profile.get("timezone") or config.FOOD_DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        logger.debug("Invalid timezone '%s': %s", tz_name, e)
        tz = timezone.utc
    now = datetime.now(tz)
    return now, now.date().isoformat()


def daily_target_calories(profile: dict) -> int:
    goal = (profile.get("goal") or "").lower()
    if "похуд" in goal or "дефицит" in goal:
        return 1700
    if "набор" in goal or "мас" in goal:
        return 2400
    return config.FOOD_CALORIE_TARGET_DEFAULT


def simple_dinner_suggestion(totals: dict, profile: dict) -> str:
    target = daily_target_calories(profile)
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


async def dinner_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_utc = datetime.now(timezone.utc)
    for row in db.list_food_profiles_for_reminders():
        p = dict(row)
        try:
            tz = ZoneInfo(p.get("timezone") or config.FOOD_DEFAULT_TIMEZONE)
        except Exception as e:
            logger.debug("Invalid profile timezone '%s': %s", p.get("timezone"), e)
            tz = timezone.utc

        local_now = now_utc.astimezone(tz)
        dinner_hour = int(p.get("dinner_hour", config.FOOD_DINNER_HOUR))
        nudge_hour = (dinner_hour - 1) % 24

        if local_now.hour != nudge_hour:
            continue

        today = local_now.date().isoformat()
        if p.get("last_dinner_nudge_date") == today:
            continue

        totals = db.get_food_daily_totals(int(p["user_id"]), today)
        if int(totals.get("meals_count", 0)) == 0:
            text = "Через час ужин. Сегодня еще нет записей по еде. Добавьте прием пищи, и я подскажу рацион точнее."
        else:
            text = simple_dinner_suggestion(totals, p)
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
