from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from app import cleanup, config, db
from app.services import planner_routing

logger = logging.getLogger(__name__)


async def monitor_and_alert_traffic(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Постоянно проверяет пробки и говорит когда надо выезжать.
    Срабатывает каждые 5-10 минут до события.
    """
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    baseline_duration = d.get("duration")
    task_id = d["task_id"]

    if event_time <= datetime.now():
        return

    if not (baseline_duration and d.get("origin") and d.get("destination")):
        return

    try:
        origin = tuple(d["origin"])
        destination = tuple(d["destination"])
        current_duration = await planner_routing.get_traffic_duration(origin, destination)

        if not current_duration:
            return

        buffer_minutes = config.DEFAULT_BUFFER_MIN
        time_to_event = (event_time - datetime.now()).total_seconds() / 60
        needed_time = current_duration + buffer_minutes

        if needed_time <= time_to_event <= needed_time + 10:
            lines = [
                "🚗 <b>ВЫЕЗЖАЙТЕ СЕЙЧАС!</b>",
                "",
                f"Событие: {event_time.strftime('%H:%M')}",
                f"Текущая дорога: <b>{current_duration} мин</b>",
                f"С буфером: {current_duration + buffer_minutes} мин",
                "",
            ]

            if current_duration > baseline_duration:
                delay = current_duration - baseline_duration
                lines.append(f"🔴 Пробки! Задержка: +{delay} мин")
            else:
                lines.append("🟢 Дорога в норме")

            lines.append(f"⏰ На дороге: {current_duration} мин, буфер: {buffer_minutes} мин")

            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)

            for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
                job.schedule_removal()

        elif time_to_event < needed_time:
            shortage = needed_time - time_to_event

            if shortage > 30:
                lines = [
                    "🚨 <b>КРИТИЧНО! ВЫЕЗЖАЙТЕ ПРЯМО СЕЙЧАС!</b>",
                    "",
                    f"Осталось времени: {int(time_to_event)} мин",
                    f"Нужно времени: {int(needed_time)} мин",
                    f"Нехватка: {int(shortage)} мин",
                    "",
                    "Заказывайте такси или срочно выезжайте!",
                ]
            else:
                lines = [
                    "⏰ <b>Торопитесь выезжать!</b>",
                    f"Событие: {event_time.strftime('%H:%M')}",
                    f"Осталось времени: {int(time_to_event)} мин",
                    f"Дорога: {current_duration} мин",
                ]

            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)

            for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
                job.schedule_removal()

    except Exception as e:
        logger.error("Ошибка при мониторинге пробок: %s", e)


async def check_traffic_early(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет пробки за час до события и напоминает, если задержка серьёзная"""
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    leave_time = db.from_iso(d.get("leave_time"))
    baseline_duration = d.get("duration")

    if not (leave_time and baseline_duration and d.get("origin") and d.get("destination")):
        return

    try:
        origin = tuple(d["origin"])
        destination = tuple(d["destination"])
        current_duration = await planner_routing.get_traffic_duration(origin, destination)

        if not current_duration:
            return

        delay = current_duration - baseline_duration

        if delay > 20:
            lines = [
                "⚠️ <b>ВНИМАНИЕ: Серьёзные пробки!</b>",
                f"Событие: {event_time.strftime('%H:%M')}",
                "",
                f"Обычно в пути: {baseline_duration} мин",
                f"🔴 <b>Сейчас в пути: {current_duration} мин</b> (задержка +{delay} мин)",
                "",
            ]

            new_leave_time = event_time - timedelta(minutes=current_duration + config.DEFAULT_BUFFER_MIN)

            if new_leave_time > datetime.now():
                lines.append(f"Запланированный выезд был: {leave_time.strftime('%H:%M')}")
                lines.append(f"<b>По пробкам нужно выехать: {new_leave_time.strftime('%H:%M')}</b>")
            else:
                lines.append("<b>Выезжайте ПРЯМО СЕЙЧАС!</b>")
                lines.append("Времени критически мало!")

            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)
    except Exception as e:
        logger.debug("Traffic early-check failed for task_id=%s: %s", d.get("task_id"), e)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    leave_time = db.from_iso(d.get("leave_time"))
    taxi_order_time = db.from_iso(d.get("taxi_order_time"))
    baseline_duration = d.get("duration")
    task_id = d["task_id"]

    for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
        job.schedule_removal()

    lines = [f"Напоминание: <b>{d['text']}</b>", f"Время: {event_time.strftime('%d.%m.%Y %H:%M')}"]

    if leave_time and baseline_duration and d.get("origin") and d.get("destination"):
        try:
            origin = tuple(d["origin"])
            destination = tuple(d["destination"])
            current_duration = await planner_routing.get_traffic_duration(origin, destination)

            if current_duration:
                lines.append(f"Обычно в пути: {baseline_duration} мин")

                delay = current_duration - baseline_duration if baseline_duration else 0

                if delay <= 5:
                    lines.append("🟢 Дорога свободна! Не торопитесь.")
                    lines.append(f"Выезжайте в: <b>{leave_time.strftime('%H:%M')}</b>")
                elif delay <= 15:
                    lines.append(f"🟡 Легкие пробки (+{delay} мин).")
                    suggested_time = leave_time - timedelta(minutes=delay // 2)
                    lines.append(f"Лучше выехать в: <b>{suggested_time.strftime('%H:%M')}</b>")
                else:
                    lines.append(f"🔴 Пробки! Задержка: +{delay} мин.")
                    if taxi_order_time:
                        lines.append(f"Заказывайте такси сейчас: <b>{taxi_order_time.strftime('%H:%M')}</b>")
                        lines.append("(такси приедет ~15 мин, надо собраться)")
                    else:
                        urgent_time = leave_time - timedelta(minutes=delay - 5)
                        lines.append(f"Срочно выезжайте в: <b>{urgent_time.strftime('%H:%M')}</b>")
            else:
                lines.append(f"В пути примерно: {baseline_duration} мин")
                lines.append(f"Лучше выехать в: <b>{leave_time.strftime('%H:%M')}</b>")
        except Exception as e:
            logger.debug("send_reminder traffic analysis failed task_id=%s: %s", d.get("task_id"), e)
            lines.append(f"В пути примерно: {baseline_duration} мин")
            lines.append(f"Лучше выехать в: <b>{leave_time.strftime('%H:%M')}</b>")
    elif leave_time and baseline_duration:
        lines.append(f"В пути примерно: {baseline_duration} мин")
        lines.append(f"Лучше выехать в: <b>{leave_time.strftime('%H:%M')}</b>")

    if taxi_order_time and not (leave_time and baseline_duration):
        lines.append(f"Заказать такси: <b>{taxi_order_time.strftime('%H:%M')}</b>")

    msg = await context.bot.send_message(chat_id=d["chat_id"], text="\n".join(lines), parse_mode=ParseMode.HTML)
    cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)
    db.mark_task_sent(d["task_id"])


async def schedule_task_job(
    application: Application,
    chat_id: int,
    task_id: int,
    text: str,
    event_time: datetime,
    remind_time: datetime,
    leave_time: Optional[datetime],
    taxi_order_time: Optional[datetime],
    duration: Optional[int],
    origin: Optional[tuple[float, float]] = None,
    destination: Optional[tuple[float, float]] = None,
) -> None:
    now = datetime.now()
    if event_time <= now:
        return
    if remind_time <= now:
        remind_time = now + timedelta(minutes=1)

    job_data = {
        "chat_id": chat_id,
        "task_id": task_id,
        "text": text,
        "event_time": db.iso(event_time),
        "leave_time": db.iso(leave_time),
        "taxi_order_time": db.iso(taxi_order_time),
        "duration": duration,
        "origin": origin,
        "destination": destination,
    }

    if origin and destination and duration:
        monitor_start = event_time - timedelta(minutes=90)
        if monitor_start > datetime.now():
            application.job_queue.run_repeating(
                monitor_and_alert_traffic,
                interval=300,
                first=monitor_start,
                data=job_data,
                name=f"monitor_{task_id}",
            )
        else:
            application.job_queue.run_repeating(
                monitor_and_alert_traffic,
                interval=300,
                first=0.5,
                data=job_data,
                name=f"monitor_{task_id}",
            )

    application.job_queue.run_once(
        send_reminder,
        when=remind_time,
        data=job_data,
        name=f"task_{task_id}",
    )


async def load_pending_jobs(application: Application) -> None:
    for r in db.list_pending_tasks():
        remind = datetime.fromisoformat(r["remind_time"])
        event_dt = datetime.fromisoformat(r["event_time"])
        if event_dt <= datetime.now():
            continue
        duration = None
        origin = None
        dest_coords = None

        if r["leave_time"] and r["event_time"]:
            try:
                leave_dt = datetime.fromisoformat(r["leave_time"])
                duration = max(1, int((event_dt - leave_dt).total_seconds() // 60) - config.DEFAULT_BUFFER_MIN)
            except Exception as e:
                logger.debug("Failed to rebuild duration for task_id=%s: %s", r["id"], e)
                duration = None

        if r["destination"]:
            try:
                home_address = db.get_home_address(r["user_id"])
                if home_address:
                    origin = await planner_routing.geocode_with_fallback(home_address, context_address=home_address)
                    dest_coords = await planner_routing.geocode_with_fallback(r["destination"], context_address=home_address)
            except Exception as e:
                logger.debug(
                    "Failed to restore route coords for pending task_id=%s user_id=%s: %s",
                    r["id"],
                    r["user_id"],
                    e,
                )

        await schedule_task_job(
            application,
            r["user_id"],
            r["id"],
            r["text"],
            event_dt,
            remind,
            db.from_iso(r["leave_time"]),
            db.from_iso(r["taxi_order_time"]),
            duration,
            origin,
            dest_coords,
        )
