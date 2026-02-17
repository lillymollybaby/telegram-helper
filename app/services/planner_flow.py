from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import config, db
from app.keyboards import main_menu_keyboard, planner_origin_keyboard
from app.services import planner_draft, planner_jobs, planner_parsing, planner_routing

logger = logging.getLogger(__name__)


async def ask_next_plan_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    d = planner_draft.plan_draft(context)
    user_id = update.effective_user.id

    if not d.get("origin_address"):
        d["awaiting"] = "origin_choice"
        has_home = bool(db.get_home_address(user_id))
        await update.effective_message.reply_text(
            "С какого адреса выезжаем?",
            reply_markup=planner_origin_keyboard(has_home),
        )
        return True

    if not d.get("destination"):
        d["awaiting"] = "destination_text"
        detected = d.get("detected_destination")
        if detected:
            kb = ReplyKeyboardMarkup(
                [[config.BTN_PLAN_USE_DETECTED_DEST], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
                resize_keyboard=True,
            )
            await update.effective_message.reply_text(
                f"Куда едем? Я распознал: {detected}\n"
                f"Нажмите '{config.BTN_PLAN_USE_DETECTED_DEST}' или напишите другой адрес.",
                reply_markup=kb,
            )
        else:
            await update.effective_message.reply_text(
                "Куда едем? Напишите адрес места назначения.",
                reply_markup=main_menu_keyboard(),
            )
        return True

    if not d.get("event_dt"):
        d["awaiting"] = "time_text"
        detected_dt = d.get("detected_event_dt")
        if detected_dt:
            pretty = detected_dt.strftime("%d.%m.%Y %H:%M")
            kb = ReplyKeyboardMarkup(
                [[config.BTN_PLAN_USE_DETECTED_TIME], [config.BTN_BACK_MOVIES, config.BTN_HOME_MENU]],
                resize_keyboard=True,
            )
            await update.effective_message.reply_text(
                f"Во сколько нужно быть? Я распознал: {pretty}\n"
                f"Нажмите '{config.BTN_PLAN_USE_DETECTED_TIME}' или напишите другое время.",
                reply_markup=kb,
            )
        else:
            await update.effective_message.reply_text(
                "Во сколько нужно быть на месте? Например: сегодня 16:00 или через час.",
                reply_markup=main_menu_keyboard(),
            )
        return True

    d["awaiting"] = None
    return False


async def finalize_planning_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    text: str,
    destination: Optional[str],
    event_dt: datetime,
    origin_address: Optional[str],
) -> bool:
    if event_dt <= datetime.now():
        await update.effective_message.reply_text("Время уже прошло.", reply_markup=main_menu_keyboard())
        return True

    leave_time = None
    taxi_order_time = None
    duration = None
    origin = None
    dest_coords = None
    remind_time = event_dt - timedelta(minutes=config.DEFAULT_REMIND_BEFORE_MIN)

    route_issues: list[str] = []
    origin_address = (origin_address or db.get_home_address(user_id) or "").strip()
    if not origin_address:
        route_issues.append("не задан адрес отправления")
    if not destination:
        route_issues.append("не указан адрес назначения")

    if not route_issues:
        try:
            origin = await planner_routing.geocode_with_fallback(origin_address, context_address=destination)
            dest_coords = await planner_routing.geocode_with_fallback(destination, context_address=origin_address)
            if origin and dest_coords:
                duration, err = await planner_routing.taxi_duration_minutes(origin, dest_coords)
                if duration:
                    leave_time = event_dt - timedelta(minutes=duration + config.DEFAULT_BUFFER_MIN)
                    taxi_order_time = leave_time - timedelta(minutes=5)
                    remind_time = leave_time
                elif err:
                    route_issues.append(err)
            else:
                if not origin and not dest_coords:
                    route_issues.append("не удалось геокодировать адрес отправления и назначения")
                elif not origin:
                    route_issues.append("не удалось геокодировать адрес отправления")
                else:
                    route_issues.append("не удалось геокодировать адрес назначения")
        except Exception as e:
            logger.debug("Route calculation failed for user_id=%s destination='%s': %s", user_id, destination, e)
            route_issues.append("ошибка расчета маршрута")

    if route_issues:
        draft = planner_draft.plan_draft(context)
        if any("адрес отправления" in x for x in route_issues):
            draft["origin_address"] = None
            draft["awaiting"] = "origin_text"
            has_home = bool(db.get_home_address(user_id))
            await update.effective_message.reply_text(
                "Не смог распознать адрес отправления. Напишите полный адрес с городом "
                "или выберите геолокацию.\n"
                "Если адрес полный, проверьте API-ключи карт в .env.",
                reply_markup=planner_origin_keyboard(has_home),
            )
            return False
        if any("адрес назначения" in x for x in route_issues):
            draft["destination"] = None
            draft["awaiting"] = "destination_text"
            await update.effective_message.reply_text(
                "Не смог распознать адрес назначения. Напишите полный адрес с городом, "
                "например: Бишкек, 4 мкр, дом 20.",
                reply_markup=main_menu_keyboard(),
            )
            return False
        await update.effective_message.reply_text(
            "Не удалось посчитать маршрут. Уточните адреса и попробуйте снова.",
            reply_markup=main_menu_keyboard(),
        )
        return False

    if remind_time <= datetime.now():
        remind_time = datetime.now() + timedelta(minutes=1)

    task_id = db.save_task(user_id, text, destination, event_dt, remind_time, leave_time, taxi_order_time)
    await planner_jobs.schedule_task_job(
        context.application,
        chat_id,
        task_id,
        text,
        event_dt,
        remind_time,
        leave_time,
        taxi_order_time,
        duration,
        origin,
        dest_coords,
    )

    lines = [
        f"Задача сохранена: #{task_id}",
        f"Событие: {event_dt.strftime('%d.%m.%Y %H:%M')}",
        f"Напомню: {remind_time.strftime('%d.%m.%Y %H:%M')}",
    ]
    if duration:
        lines.append(f"Дорога: ~{duration} мин")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())
    return True


async def add_task_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    raw_text = (update.message.text or "").strip()
    draft = context.user_data.get(planner_draft.PLAN_DRAFT_KEY)

    if draft:
        d = planner_draft.plan_draft(context)
        awaiting = d.get("awaiting")
        if raw_text == config.BTN_PLAN_USE_HOME:
            home_address = db.get_home_address(user_id)
            if not home_address:
                await update.effective_message.reply_text("Домашний адрес не задан. Используйте /home <адрес> или отправьте свой адрес.")
                return True
            d["origin_address"] = home_address
            d["awaiting"] = None
        elif raw_text == config.BTN_PLAN_SET_START:
            d["awaiting"] = "origin_text"
            await update.effective_message.reply_text("Напишите адрес отправления.")
            return True
        elif raw_text == config.BTN_PLAN_SHARE_GEO:
            d["awaiting"] = "origin_geo"
            await update.effective_message.reply_text("Отправьте геопозицию через кнопку гео.")
            return True
        elif raw_text == config.BTN_PLAN_USE_DETECTED_DEST and d.get("detected_destination"):
            d["destination"] = d.get("detected_destination")
            d["awaiting"] = None
        elif raw_text == config.BTN_PLAN_USE_DETECTED_TIME and d.get("detected_event_dt"):
            d["event_dt"] = d.get("detected_event_dt")
            d["awaiting"] = None
        elif awaiting == "origin_choice":
            d["origin_address"] = raw_text
            d["awaiting"] = None
        elif awaiting == "origin_text":
            d["origin_address"] = raw_text
            d["awaiting"] = None
        elif awaiting == "destination_text":
            d["destination"] = raw_text
            d["awaiting"] = None
        elif awaiting == "time_text":
            dt = planner_parsing.parse_datetime_ru(raw_text)
            if not dt:
                await update.effective_message.reply_text("Не понял время. Пример: сегодня 16:00 или через 1 час.")
                return True
            d["event_dt"] = dt
            d["awaiting"] = None
        else:
            maybe_dt = planner_parsing.parse_datetime_ru(raw_text)
            if maybe_dt and not d.get("event_dt"):
                d["event_dt"] = maybe_dt
            elif not d.get("destination"):
                d["destination"] = planner_parsing.infer_destination_from_text(raw_text) or raw_text

        need_more = await ask_next_plan_question(update, context)
        if need_more:
            return True

        ok = await finalize_planning_task(
            update,
            context,
            user_id,
            chat_id,
            text=d.get("title") or "Задача",
            destination=d.get("destination"),
            event_dt=d.get("event_dt"),
            origin_address=d.get("origin_address"),
        )
        if ok:
            planner_draft.clear_plan_draft(context)
        return ok

    ai_fields = await planner_parsing.parse_task_fields_gemini(raw_text)
    ai_parsed = await planner_parsing.parse_task_input_gemini(raw_text)
    if ai_parsed:
        text, destination, event_dt = ai_parsed
    else:
        text, destination, event_dt = planner_parsing.parse_task_input(raw_text)
        if ai_fields.get("title"):
            text = ai_fields["title"]
        if ai_fields.get("destination"):
            destination = ai_fields["destination"]
        if ai_fields.get("event_dt"):
            event_dt = ai_fields["event_dt"]

    destination = destination or planner_parsing.infer_destination_from_text(raw_text)

    intent = bool(ai_fields.get("is_task")) or planner_parsing.is_planning_intent(raw_text) or bool(event_dt)
    if not intent:
        return False

    d = planner_draft.plan_draft(context)
    d["title"] = planner_parsing.humanize_task_title(text or raw_text, destination)
    d["destination"] = None
    d["event_dt"] = None
    d["detected_destination"] = destination
    d["detected_event_dt"] = event_dt
    d["origin_address"] = None
    d["awaiting"] = None

    need_more = await ask_next_plan_question(update, context)
    if need_more:
        return True

    ok = await finalize_planning_task(
        update,
        context,
        user_id,
        chat_id,
        text=d.get("title") or raw_text,
        destination=d.get("destination"),
        event_dt=d.get("event_dt"),
        origin_address=d.get("origin_address"),
    )
    if ok:
        planner_draft.clear_plan_draft(context)
    return ok


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if planner_draft.PLAN_DRAFT_KEY not in context.user_data:
        return False
    d = planner_draft.plan_draft(context)
    loc = update.effective_message.location if update.effective_message else None
    if not loc:
        return False
    addr = await planner_routing.reverse_geocode(float(loc.latitude), float(loc.longitude))
    if not addr:
        addr = f"{loc.latitude:.6f}, {loc.longitude:.6f}"
    d["origin_address"] = addr
    d["awaiting"] = None

    need_more = await ask_next_plan_question(update, context)
    if need_more:
        return True

    ok = await finalize_planning_task(
        update,
        context,
        update.effective_user.id,
        update.effective_chat.id,
        text=d.get("title") or "Задача",
        destination=d.get("destination"),
        event_dt=d.get("event_dt"),
        origin_address=d.get("origin_address"),
    )
    if ok:
        planner_draft.clear_plan_draft(context)
    return ok
