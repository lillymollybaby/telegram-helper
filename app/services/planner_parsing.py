from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import dateparser
import httpx

from app import config

logger = logging.getLogger(__name__)


def parse_datetime_ru(value: str) -> Optional[datetime]:
    if not value:
        return None
    t = value.lower().strip()
    now = datetime.now()

    rel_hour_1 = re.search(r"через\s+час\b", t)
    rel_hours = re.search(r"через\s+(\d{1,2})\s*час", t)
    rel_mins = re.search(r"через\s+(\d{1,3})\s*мин", t)
    if rel_hour_1:
        return now + timedelta(hours=1)
    if rel_hours:
        return now + timedelta(hours=int(rel_hours.group(1)))
    if rel_mins:
        return now + timedelta(minutes=int(rel_mins.group(1)))

    time_cues = (
        "сегодня",
        "завтра",
        "послезавтра",
        "через",
        "в ",
        "утра",
        "дня",
        "вечера",
        "ночи",
        "час",
        "минут",
    )
    has_cue = any(c in t for c in time_cues) or bool(re.search(r"\b\d{1,2}[:.]\d{2}\b", t))
    if not has_cue:
        return None

    address_like = bool(re.search(r"\b(мкр|микрорайон|дом|кв|ул|улица|проспект|пр-т)\b", t))
    no_time_tokens = not bool(re.search(r"(через|сегодня|завтра|утра|дня|вечера|ночи|\d{1,2}[:.]\d{2})", t))
    if address_like and no_time_tokens:
        return None

    dt = dateparser.parse(
        value,
        languages=["ru"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now},
    )
    if dt and dt.year > now.year + 3:
        return None
    return dt


def humanize_task_title(text: str, destination: Optional[str] = None) -> str:
    raw = (text or "").strip()
    low = raw.lower()

    if "стоматолог" in low:
        return "Посещение стоматолога"
    if any(x in low for x in ("врач", "больниц", "поликлиник", "клиник")):
        return "Визит к врачу"
    if "встреч" in low:
        return "Встреча"
    if "аэропорт" in low or "вылет" in low:
        return "Поездка в аэропорт"
    if "кино" in low:
        return "Поход в кино"

    cleaned = re.sub(r"\b(мне|нужно|надо)\b", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(сегодня|завтра|послезавтра)\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bчерез\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bпо адресу\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?:;")

    if cleaned:
        return cleaned[:1].upper() + cleaned[1:]
    if destination:
        return "Поездка"
    return "Задача"


def is_planning_intent(raw_text: str) -> bool:
    t = (raw_text or "").lower().strip()
    if not t:
        return False
    keywords = [
        "мне ",
        "нужно",
        "надо",
        "поехать",
        "встреча",
        "запись",
        "прием",
        "к ",
        "через",
        "сегодня",
        "завтра",
        "адрес",
        "дом",
    ]
    if any(k in t for k in keywords):
        return True
    return parse_datetime_ru(t) is not None


def parse_task_input(raw_text: str) -> tuple[str, Optional[str], Optional[datetime]]:
    parts = [p.strip() for p in raw_text.split(";") if p.strip()]
    if len(parts) >= 2:
        text_part, dt_part = parts[0], parts[1]
        destination = parts[2] if len(parts) >= 3 else None
        event_dt = dateparser.parse(
            dt_part,
            languages=["ru"],
            settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()},
        )
        return text_part, destination, event_dt

    event_dt = parse_datetime_ru(raw_text)
    return raw_text, None, event_dt


def infer_destination_from_text(raw_text: str) -> Optional[str]:
    patterns = [
        r"(?:по адресу)\s+(.+)$",
        r"(?:на)\s+([А-Яа-яA-Za-z0-9\-\.,\s]+?\d+[А-Яа-яA-Za-z0-9\/\-]*)$",
        r"(?:в)\s+([А-Яа-яA-Za-z0-9\-\.,\s]+?\d+[А-Яа-яA-Za-z0-9\/\-]*)$",
    ]
    for p in patterns:
        m = re.search(p, raw_text.strip(), flags=re.IGNORECASE)
        if m:
            v = m.group(1).strip(" .,!?:;")
            if len(v) >= 5:
                return v
    return None


async def parse_task_input_gemini(raw_text: str) -> Optional[tuple[str, Optional[str], Optional[datetime]]]:
    if not config.GEMINI_API_KEY:
        return None
    prompt = (
        "Извлеки из фразы задачу и верни ТОЛЬКО JSON без пояснений.\n"
        "{\"is_task\":true|false,\"title\":\"...\",\"datetime\":\"YYYY-MM-DD HH:MM или null\",\"destination\":\"... или null\"}\n"
        f"Сейчас: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Фраза: {raw_text}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                return None
            data = r.json()
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if not text:
            return None
        obj = json.loads(text)
        if not obj.get("is_task"):
            return None
        title = (obj.get("title") or raw_text).strip()
        destination = obj.get("destination") if isinstance(obj.get("destination"), str) else None
        if destination:
            destination = destination.strip() or None
        dt = None
        if isinstance(obj.get("datetime"), str) and obj["datetime"].strip():
            try:
                dt = datetime.strptime(obj["datetime"].strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                dt = dateparser.parse(
                    obj["datetime"],
                    languages=["ru"],
                    settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()},
                )
        return title, destination, dt
    except Exception as e:
        logger.debug("Gemini parse_task_input failed for text='%s': %s", raw_text, e)
        return None


async def parse_task_fields_gemini(raw_text: str) -> dict:
    result = {"is_task": False, "title": None, "destination": None, "event_dt": None}
    if not config.GEMINI_API_KEY:
        return result
    prompt = (
        "Верни только JSON без пояснений:\n"
        "{\"is_task\":true|false,\"title\":\"... или null\",\"datetime\":\"YYYY-MM-DD HH:MM или null\",\"destination\":\"... или null\"}\n"
        f"Сейчас: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Фраза: {raw_text}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                return result
            data = r.json()
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if not text:
            return result
        obj = json.loads(text)
        result["is_task"] = bool(obj.get("is_task"))
        title = obj.get("title")
        if isinstance(title, str) and title.strip():
            result["title"] = title.strip()
        destination = obj.get("destination")
        if isinstance(destination, str) and destination.strip():
            result["destination"] = destination.strip()
        dt_raw = obj.get("datetime")
        if isinstance(dt_raw, str) and dt_raw.strip():
            try:
                result["event_dt"] = datetime.strptime(dt_raw.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                result["event_dt"] = parse_datetime_ru(dt_raw.strip())
        return result
    except Exception as e:
        logger.debug("Gemini parse_task_fields failed for text='%s': %s", raw_text, e)
        return result
