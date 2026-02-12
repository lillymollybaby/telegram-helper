from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, ContextTypes

from app import config, db
from app.keyboards import (
    main_menu_keyboard,
    profile_edit_keyboard,
    profile_menu_keyboard,
    sleep_check_keyboard,
    water_check_keyboard,
    yes_no_keyboard,
)

PROFILE_STATE_KEY = "profile_state"


def _state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(
        PROFILE_STATE_KEY,
        {
            "onboarding_active": False,
            "step": 0,
            "edit_field": None,
            "pending_water_optin": False,
            "sleep_prompt_type": None,
            "water_prompt_active": False,
        },
    )


def _all_button_labels() -> set[str]:
    out: set[str] = set()
    for key, value in vars(config).items():
        if key.startswith("BTN_") and isinstance(value, str):
            out.add(value)
    return out


def _parse_time_hhmm(value: str) -> Optional[str]:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", (value or "").strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _to_float(value: str) -> Optional[float]:
    try:
        return float((value or "").strip().replace(",", "."))
    except Exception:
        return None


def _suggest_water_goal_ml(weight_kg: Optional[float]) -> int:
    if not weight_kg or weight_kg <= 0:
        return 2200
    # Practical default: ~33 ml per kg.
    goal = int(round(weight_kg * 33))
    return min(4000, max(1600, goal))


def _onboarding_steps() -> list[dict]:
    return [
        {"key": "full_name", "prompt": "Как вас зовут?", "why": "Зачем: чтобы обращаться к вам персонально."},
        {"key": "city", "prompt": "В каком городе вы живете?", "why": "Зачем: для точной работы с адресами и маршрутами."},
        {"key": "timezone", "prompt": "Ваш часовой пояс? Пример: Asia/Bishkek", "why": "Зачем: напоминания приходят в местное время."},
        {"key": "home_address", "prompt": "Введите домашний адрес.", "why": "Зачем: это стартовая точка для поездок."},
        {"key": "work_address", "prompt": "Введите адрес работы/учебы (или '-')", "why": "Зачем: быстро строить повседневные маршруты."},
        {"key": "birth_date", "prompt": "Дата рождения (ДД.ММ.ГГГГ) или '-'", "why": "Зачем: учитывать возраст в рекомендациях."},
        {"key": "height_cm", "prompt": "Рост в см (например 178) или '-'", "why": "Зачем: считать персональную норму питания."},
        {"key": "weight_kg", "prompt": "Вес в кг (например 72) или '-'", "why": "Зачем: считать калории и норму воды."},
        {"key": "activity_level", "prompt": "Активность: низкий / средний / высокий", "why": "Зачем: корректно оценивать дневные потребности."},
        {"key": "goal", "prompt": "Цель: похудеть / поддерживать / набрать", "why": "Зачем: подбирать советы под вашу цель."},
        {"key": "dietary_restrictions", "prompt": "Ограничения в еде (аллергии/запреты) или '-'", "why": "Зачем: исключать неподходящую еду из рекомендаций."},
        {"key": "sleep_time", "prompt": "Во сколько ложитесь спать? Формат HH:MM", "why": "Зачем: напоминать о подготовке ко сну."},
        {"key": "wake_time", "prompt": "Во сколько обычно просыпаетесь? Формат HH:MM", "why": "Зачем: мягкий утренний режим."},
        {"key": "sleep_remind_before_min", "prompt": "За сколько минут напоминать до сна? (например 10)", "why": "Зачем: дать время спокойно подготовиться."},
        {"key": "wake_remind_before_min", "prompt": "За сколько минут напоминать до подъема? (например 10)", "why": "Зачем: не просыпаться в спешке."},
    ]


def _parse_step_value(key: str, text: str) -> tuple[bool, Optional[object], Optional[str]]:
    raw = (text or "").strip()
    if raw == "-":
        return True, None, None
    if key in {"sleep_time", "wake_time"}:
        v = _parse_time_hhmm(raw)
        return (True, v, None) if v else (False, None, "Формат HH:MM, например 23:00")
    if key in {"sleep_remind_before_min", "wake_remind_before_min"}:
        if not raw.isdigit():
            return False, None, "Введите число минут, например 10"
        n = int(raw)
        if not 1 <= n <= 180:
            return False, None, "Допустимо от 1 до 180 минут"
        return True, n, None
    if key in {"height_cm", "weight_kg"}:
        n = _to_float(raw)
        if n is None:
            return False, None, "Введите число"
        return True, n, None
    if key == "birth_date":
        try:
            dt = datetime.strptime(raw, "%d.%m.%Y")
            age = max(0, datetime.now().year - dt.year)
            return True, {"birth_date": dt.date().isoformat(), "age": age}, None
        except Exception:
            return False, None, "Формат даты: ДД.ММ.ГГГГ"
    return True, raw, None


async def _ask_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = _state(context)
    steps = _onboarding_steps()
    idx = int(st.get("step", 0))
    if idx >= len(steps):
        user_id = update.effective_user.id
        db.update_user_profile(user_id, onboarding_completed=1)
        st["onboarding_active"] = False
        profile = db.get_user_profile(user_id)
        goal_ml = int(profile["water_goal_ml"] or _suggest_water_goal_ml(profile["weight_kg"]))
        db.update_user_profile(user_id, water_goal_ml=goal_ml)
        st["pending_water_optin"] = True
        liters = goal_ml / 1000
        await update.effective_message.reply_text(
            f"Мы заботимся о вас. Для вашего веса полезно пить около {liters:.1f} л воды в день.\n"
            "Включить напоминания о воде?",
            reply_markup=yes_no_keyboard(),
        )
        return

    s = steps[idx]
    await update.effective_message.reply_text(f"{s['prompt']}\n{s['why']}", reply_markup=main_menu_keyboard())


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> bool:
    user_id = update.effective_user.id
    db.ensure_user_profile(user_id)
    if db.is_onboarding_completed(user_id) and not force:
        return False
    st = _state(context)
    st["onboarding_active"] = True
    st["step"] = 0
    st["edit_field"] = None
    st["pending_water_optin"] = False
    await update.effective_message.reply_text(
        "Перед началом давайте узнаем друг друга. Это займет 1-2 минуты.",
        reply_markup=main_menu_keyboard(),
    )
    await _ask_step(update, context)
    return True


async def show_profile_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = db.get_user_profile(update.effective_user.id)
    lines = [
        "Ваш профиль:",
        f"Имя: {p['full_name'] or '-'}",
        f"Город: {p['city'] or '-'}",
        f"Часовой пояс: {p['timezone'] or '-'}",
        f"Дом: {p['home_address'] or '-'}",
        f"Работа/учеба: {p['work_address'] or '-'}",
        f"Рост/вес: {p['height_cm'] or '-'} см / {p['weight_kg'] or '-'} кг",
        f"Цель: {p['goal'] or '-'}",
        f"Сон: {p['sleep_time'] or '-'} | Подъем: {p['wake_time'] or '-'}",
        f"Вода: {(p['water_goal_ml'] or 0) / 1000:.1f} л/день" if p["water_goal_ml"] else "Вода: -",
    ]
    await update.effective_message.reply_text("\n".join(lines), reply_markup=profile_menu_keyboard())


async def show_profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Раздел 'Мой профиль':", reply_markup=profile_menu_keyboard())


async def _start_field_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, prompt: str, why: str) -> None:
    st = _state(context)
    st["onboarding_active"] = False
    st["edit_field"] = field
    await update.effective_message.reply_text(f"{prompt}\n{why}", reply_markup=main_menu_keyboard())


def _is_quiet_hours(now_local: datetime, start_hhmm: Optional[str], end_hhmm: Optional[str]) -> bool:
    if not start_hhmm or not end_hhmm:
        return False
    try:
        sh, sm = [int(x) for x in start_hhmm.split(":")]
        eh, em = [int(x) for x in end_hhmm.split(":")]
    except Exception:
        return False
    cur = now_local.hour * 60 + now_local.minute
    s = sh * 60 + sm
    e = eh * 60 + em
    if s == e:
        return False
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.effective_message.text or "").strip()
    user_id = update.effective_user.id
    st = _state(context)

    if text == config.BTN_PROFILE_OVERVIEW:
        await show_profile_summary(update, context)
        return True
    if text == config.BTN_PROFILE_EDIT:
        await update.effective_message.reply_text("Что хотите изменить?", reply_markup=profile_edit_keyboard())
        return True
    if text == config.BTN_PROFILE_SLEEP:
        p = db.get_user_profile(user_id)
        await update.effective_message.reply_text(
            f"Сон: {p['sleep_time'] or '-'}\nПодъем: {p['wake_time'] or '-'}\n"
            f"До сна: {p['sleep_remind_before_min']} мин\nДо подъема: {p['wake_remind_before_min']} мин",
            reply_markup=profile_menu_keyboard(),
        )
        return True
    if text == config.BTN_PROFILE_RESET:
        db.reset_onboarding(user_id)
        await start_onboarding(update, context, force=True)
        return True
    if text == config.BTN_PROFILE_START:
        await start_onboarding(update, context, force=True)
        return True

    if text == config.BTN_PROFILE_EDIT_NAME:
        await _start_field_edit(update, context, "full_name", "Введите имя.", "Зачем: для персональных обращений.")
        return True
    if text == config.BTN_PROFILE_EDIT_HOME:
        await _start_field_edit(update, context, "home_address", "Введите домашний адрес.", "Зачем: откуда выезжать по умолчанию.")
        return True
    if text == config.BTN_PROFILE_EDIT_WORK:
        await _start_field_edit(update, context, "work_address", "Введите адрес работы/учебы.", "Зачем: быстрые маршруты дом-работа.")
        return True
    if text == config.BTN_PROFILE_EDIT_BODY:
        await _start_field_edit(update, context, "body_pair", "Введите рост и вес: например `178 72`", "Зачем: расчет калорий и воды.")
        return True
    if text == config.BTN_PROFILE_EDIT_GOAL:
        await _start_field_edit(update, context, "goal", "Введите цель: похудеть / поддерживать / набрать", "Зачем: персональные советы.")
        return True
    if text == config.BTN_PROFILE_EDIT_SLEEP:
        await _start_field_edit(update, context, "sleep_pair", "Введите сон и подъем: например `23:00 07:00`", "Зачем: напоминания ко сну и подъему.")
        return True
    if text == config.BTN_PROFILE_EDIT_WATER:
        await _start_field_edit(update, context, "water_goal_ml", "Введите цель воды в мл, например `2300`", "Зачем: контроль гидратации в течение дня.")
        return True

    if st.get("pending_water_optin") and text in {config.BTN_SLEEP_YES, config.BTN_SLEEP_NO}:
        st["pending_water_optin"] = False
        enabled = text == config.BTN_SLEEP_YES
        db.update_user_profile(user_id, reminders_enabled=1 if enabled else 0)
        await update.effective_message.reply_text(
            "Отлично, напоминания о воде включены." if enabled else "Ок, напоминания о воде выключены.",
            reply_markup=profile_menu_keyboard(),
        )
        return True

    if text in {config.BTN_SLEEP_YES, config.BTN_SLEEP_NO, config.BTN_SLEEP_LATER} and st.get("sleep_prompt_type"):
        kind = st["sleep_prompt_type"]
        st["sleep_prompt_type"] = None
        if text == config.BTN_SLEEP_LATER:
            context.job_queue.run_once(
                _sleep_followup_job,
                when=900,
                data={"chat_id": update.effective_chat.id, "kind": kind},
                name=f"sleep_followup_{user_id}_{kind}",
            )
            await update.effective_message.reply_text("Ок, напомню позже.", reply_markup=main_menu_keyboard())
        elif text == config.BTN_SLEEP_YES:
            await update.effective_message.reply_text("Отлично.", reply_markup=main_menu_keyboard())
        else:
            await update.effective_message.reply_text("Понял, постарайтесь не пропускать режим.", reply_markup=main_menu_keyboard())
        return True

    if text in {config.BTN_WATER_YES, config.BTN_WATER_NO} and st.get("water_prompt_active"):
        st["water_prompt_active"] = False
        today = datetime.now().date().isoformat()
        p = db.get_user_profile(user_id)
        goal = int(p["water_goal_ml"] or 2200)
        drank = db.get_water_daily_total(user_id, today)
        if text == config.BTN_WATER_YES:
            db.save_water_intake(user_id, 250)
            drank += 250
            left = max(0, goal - drank)
            await update.effective_message.reply_text(
                f"Отлично. Учел 250 мл. Осталось {left} мл до цели.",
                reply_markup=main_menu_keyboard(),
            )
        else:
            now = datetime.now()
            hours_left = max(1, 22 - now.hour)
            left = max(0, goal - drank)
            per_hour = int((left + hours_left - 1) // hours_left)
            await update.effective_message.reply_text(
                f"Ок, пересчитал. До конца дня осталось {left} мл.\n"
                f"Чтобы успеть, пейте примерно по {per_hour} мл в час.",
                reply_markup=main_menu_keyboard(),
            )
        return True

    edit_field = st.get("edit_field")
    if edit_field:
        if text in _all_button_labels():
            st["edit_field"] = None
            return False
        if edit_field == "body_pair":
            m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s*$", text)
            if not m:
                await update.effective_message.reply_text("Нужно в формате: `рост вес`, например `178 72`")
                return True
            h = float(m.group(1).replace(",", "."))
            w = float(m.group(2).replace(",", "."))
            db.update_user_profile(user_id, height_cm=h, weight_kg=w, water_goal_ml=_suggest_water_goal_ml(w))
            st["edit_field"] = None
            await update.effective_message.reply_text("Параметры обновлены.", reply_markup=profile_menu_keyboard())
            return True
        if edit_field == "sleep_pair":
            m = re.match(r"^\s*([0-2]?\d:[0-5]\d)\s+([0-2]?\d:[0-5]\d)\s*$", text)
            if not m:
                await update.effective_message.reply_text("Нужно в формате: `23:00 07:00`")
                return True
            stime = _parse_time_hhmm(m.group(1))
            wtime = _parse_time_hhmm(m.group(2))
            if not stime or not wtime:
                await update.effective_message.reply_text("Проверьте формат времени HH:MM")
                return True
            db.update_user_profile(user_id, sleep_time=stime, wake_time=wtime)
            st["edit_field"] = None
            await update.effective_message.reply_text("Режим сна обновлен.", reply_markup=profile_menu_keyboard())
            return True
        if edit_field == "water_goal_ml":
            if not text.isdigit():
                await update.effective_message.reply_text("Введите число, например 2300")
                return True
            ml = int(text)
            if ml < 500 or ml > 6000:
                await update.effective_message.reply_text("Введите значение от 500 до 6000 мл")
                return True
            db.update_user_profile(user_id, water_goal_ml=ml)
            st["edit_field"] = None
            await update.effective_message.reply_text("Цель воды обновлена.", reply_markup=profile_menu_keyboard())
            return True
        if edit_field in {"full_name", "home_address", "work_address", "goal"}:
            db.update_user_profile(user_id, **{edit_field: text})
            if edit_field == "home_address":
                db.set_home_address(user_id, text)
            st["edit_field"] = None
            await update.effective_message.reply_text("Готово, обновил.", reply_markup=profile_menu_keyboard())
            return True

    if st.get("onboarding_active"):
        if text in _all_button_labels():
            st["onboarding_active"] = False
            return False
        steps = _onboarding_steps()
        idx = int(st.get("step", 0))
        if idx >= len(steps):
            st["onboarding_active"] = False
            return False
        step = steps[idx]
        ok, value, err = _parse_step_value(step["key"], text)
        if not ok:
            await update.effective_message.reply_text(err or "Проверьте формат и попробуйте снова.")
            await _ask_step(update, context)
            return True
        if step["key"] == "birth_date" and isinstance(value, dict):
            db.update_user_profile(user_id, **value)
        else:
            db.update_user_profile(user_id, **{step["key"]: value})
            if step["key"] == "home_address" and isinstance(value, str):
                db.set_home_address(user_id, value)
        st["step"] = idx + 1
        await _ask_step(update, context)
        return True

    return False


async def _sleep_followup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.job.data or {}
    kind = d.get("kind", "sleep")
    text = "Напоминаю: скоро сон. Уже в постели?" if kind == "sleep" else "Напоминаю: скоро подъем. Уже встаете?"
    await context.bot.send_message(chat_id=d["chat_id"], text=text, reply_markup=sleep_check_keyboard())


async def sleep_reminders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_utc = datetime.now(timezone.utc)
    for row in db.list_profiles_for_sleep_reminders():
        p = dict(row)
        try:
            tz = ZoneInfo(p.get("timezone") or config.FOOD_DEFAULT_TIMEZONE)
        except Exception:
            tz = timezone.utc
        local_now = now_utc.astimezone(tz)
        today = local_now.date().isoformat()
        sleep_time = p.get("sleep_time")
        wake_time = p.get("wake_time")
        chat_id = int(p["user_id"])

        if sleep_time and p.get("last_sleep_nudge_date") != today:
            sh, sm = [int(x) for x in str(sleep_time).split(":")]
            before = int(p.get("sleep_remind_before_min") or 10)
            target = local_now.replace(hour=sh, minute=sm, second=0, microsecond=0) - timedelta(minutes=before)
            if abs((local_now - target).total_seconds()) <= 90:
                await context.bot.send_message(chat_id=chat_id, text="Скоро спать. Вы уже в постели?", reply_markup=sleep_check_keyboard())
                db.update_user_profile(chat_id, last_sleep_nudge_date=today)
                u = context.application.user_data.setdefault(chat_id, {})
                st = u.setdefault(PROFILE_STATE_KEY, {})
                st["sleep_prompt_type"] = "sleep"

        if wake_time and p.get("last_wake_nudge_date") != today:
            wh, wm = [int(x) for x in str(wake_time).split(":")]
            before = int(p.get("wake_remind_before_min") or 10)
            target = local_now.replace(hour=wh, minute=wm, second=0, microsecond=0) - timedelta(minutes=before)
            if abs((local_now - target).total_seconds()) <= 90:
                await context.bot.send_message(chat_id=chat_id, text="Скоро подъем. Уже встаете?", reply_markup=sleep_check_keyboard())
                db.update_user_profile(chat_id, last_wake_nudge_date=today)
                u = context.application.user_data.setdefault(chat_id, {})
                st = u.setdefault(PROFILE_STATE_KEY, {})
                st["sleep_prompt_type"] = "wake"


async def water_reminders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now_utc = datetime.now(timezone.utc)
    for row in db.list_profiles_for_water_reminders():
        p = dict(row)
        if int(p.get("reminders_enabled") or 0) != 1:
            continue
        goal_ml = int(p.get("water_goal_ml") or 0)
        if goal_ml <= 0:
            continue
        try:
            tz = ZoneInfo(p.get("timezone") or config.FOOD_DEFAULT_TIMEZONE)
        except Exception:
            tz = timezone.utc
        local_now = now_utc.astimezone(tz)
        if not (8 <= local_now.hour <= 22):
            continue
        if _is_quiet_hours(local_now, p.get("quiet_hours_start"), p.get("quiet_hours_end")):
            continue
        if local_now.minute not in (0, 30):
            continue

        user_id = int(p["user_id"])
        today = local_now.date().isoformat()
        drank = db.get_water_daily_total(user_id, today)

        active_minutes = max(1, (22 - 8) * 60)
        passed = max(0, min(active_minutes, (local_now.hour - 8) * 60 + local_now.minute))
        expected = int(goal_ml * (passed / active_minutes))
        if drank >= expected:
            continue

        left = max(0, goal_ml - drank)
        hours_left = max(1, 22 - local_now.hour)
        per_hour = int((left + hours_left - 1) // hours_left)
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"Пора пить воду. Сегодня выпито {drank} мл из {goal_ml} мл.\n"
                f"До конца дня осталось {left} мл (~{per_hour} мл/час).\n"
                "Вы выпили? Только честно, это важно для вашего здоровья."
            ),
            reply_markup=water_check_keyboard(),
        )
        u = context.application.user_data.setdefault(user_id, {})
        st = u.setdefault(PROFILE_STATE_KEY, {})
        st["water_prompt_active"] = True


def schedule_jobs(application: Application) -> None:
    application.job_queue.run_repeating(
        sleep_reminders_job,
        interval=60,
        first=20,
        name="profile_sleep_reminders",
    )
    application.job_queue.run_repeating(
        water_reminders_job,
        interval=60,
        first=40,
        name="profile_water_reminders",
    )
