from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import dateparser
import httpx
from telegram import Update
from telegram import ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app import cleanup, config, db
from app.keyboards import main_menu_keyboard, movies_menu_keyboard, planner_origin_keyboard

logger = logging.getLogger(__name__)

PLAN_DRAFT_KEY = "plan_draft"


def _plan_draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(
        PLAN_DRAFT_KEY,
        {
            "title": None,
            "destination": None,
            "event_dt": None,
            "detected_destination": None,
            "detected_event_dt": None,
            "origin_address": None,
            "awaiting": None,
        },
    )


def _clear_plan_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(PLAN_DRAFT_KEY, None)


def cancel_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_plan_draft(context)


def _parse_datetime_ru(value: str) -> Optional[datetime]:
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

    # Don't parse obvious address-only strings like "4 мкр 20 дом".
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
    return _parse_datetime_ru(t) is not None


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

    event_dt = _parse_datetime_ru(raw_text)
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
    except Exception:
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
                result["event_dt"] = _parse_datetime_ru(dt_raw.strip())
        return result
    except Exception:
        return result


async def geocode(address: str) -> Optional[tuple[float, float]]:
    if config.ROUTING_PROVIDER in ("google", "auto") and config.GOOGLE_MAPS_API_KEY:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": config.GOOGLE_MAPS_API_KEY}
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            if r.status_code < 400:
                data = r.json()
                if data.get("status") == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return float(loc["lat"]), float(loc["lng"])
        if config.ROUTING_PROVIDER == "google":
            return None

    if config.ROUTING_PROVIDER in ("dgis", "auto") and config.DGIS_API_KEY:
        p = await _dgis_geocode(address)
        if p:
            return p
        if config.ROUTING_PROVIDER == "dgis":
            return None

    yandex_key = config.YANDEX_API_KEY or config.YANDEX_ROUTING_API_KEY or config.YANDEX_DISTANCE_MATRIX_API_KEY
    if not yandex_key:
        return None
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {"apikey": yandex_key, "format": "json", "geocode": address, "results": 1}
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, params=params)
        if r.status_code >= 400:
            return None
        data = r.json()
    members = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
    if not members:
        return None
    lon_s, lat_s = members[0]["GeoObject"]["Point"]["pos"].split()
    return float(lat_s), float(lon_s)


def _normalize_address(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("мкр.", "мкр").replace("г.", "г ")
    text = text.replace("/", " ")
    text = re.sub(r"\bдом\s+(\d+)\b", r"\1", text, flags=re.IGNORECASE)
    return text.strip(" ,")


def _guess_city_from_address(address: str) -> Optional[str]:
    if not address:
        return None
    low = address.lower()
    known = [
        "бишкек",
        "ош",
        "алматы",
        "астана",
        "москва",
        "санкт-петербург",
        "минск",
        "киев",
        "ташкент",
    ]
    for c in known:
        if c in low:
            return c
    return None


def _coords_match_city_hint(coords: tuple[float, float], address_hint: str) -> bool:
    hint = (address_hint or "").lower()
    if not hint:
        return True
    lat, lon = coords
    # Rough city bounding boxes to avoid obvious false positives from fallback geocoders.
    boxes = {
        "бишкек": (42.74, 43.01, 74.45, 74.75),
        "bishkek": (42.74, 43.01, 74.45, 74.75),
        "ош": (40.45, 40.65, 72.70, 72.95),
        "osh": (40.45, 40.65, 72.70, 72.95),
        "алматы": (43.10, 43.38, 76.75, 77.15),
        "almaty": (43.10, 43.38, 76.75, 77.15),
    }
    for city, (lat_min, lat_max, lon_min, lon_max) in boxes.items():
        if city in hint:
            return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max
    return True


async def geocode_with_fallback(address: str, context_address: Optional[str] = None) -> Optional[tuple[float, float]]:
    raw = _normalize_address(address)
    if not raw:
        return None

    # Accept direct coordinates from geo flow: "lat, lon"
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", raw)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            pass

    candidates: list[str] = [raw]
    city = _guess_city_from_address(raw) or _guess_city_from_address(context_address or "")
    if "мкр" in raw.lower() and "бишкек" not in raw.lower():
        candidates.append(f"Бишкек, {raw}")
    if city and city not in raw.lower():
        candidates.append(f"{raw}, {city}")
    candidates.append(f"{raw}, Кыргызстан")
    candidates.append(f"{raw}, Kyrgyzstan")

    seen: set[str] = set()
    for c in candidates:
        q = c.strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        p = await geocode(q)
        if p and _coords_match_city_hint(p, q):
            return p

    # Reserve fallback when Yandex geocoder key is missing/rejected.
    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await _nominatim_geocode(q, countrycodes="kg")
        if p and _coords_match_city_hint(p, q):
            return p
    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await _nominatim_geocode(q, countrycodes="")
        if p and _coords_match_city_hint(p, q):
            return p
    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await _photon_geocode(q)
        if p and _coords_match_city_hint(p, q):
            return p
    return None


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    if not config.YANDEX_API_KEY:
        return None
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {
        "apikey": config.YANDEX_API_KEY,
        "format": "json",
        "geocode": f"{lon},{lat}",
        "kind": "house",
        "results": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            if r.status_code >= 400:
                return None
            data = r.json()
        members = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
        if not members:
            return None
        addr = members[0]["GeoObject"]["metaDataProperty"]["GeocoderMetaData"].get("text")
        if isinstance(addr, str) and addr.strip():
            return addr.strip()
    except Exception:
        return None
    return None


async def _nominatim_geocode(query: str, countrycodes: str = "kg") -> Optional[tuple[float, float]]:
    q = (query or "").strip()
    if not q:
        return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 1,
    }
    if countrycodes:
        params["countrycodes"] = countrycodes
    headers = {"User-Agent": "tg-reminder-bot/1.0 (local)"}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code >= 400:
                return None
            arr = r.json()
        if not isinstance(arr, list) or not arr:
            return None
        lat = float(arr[0].get("lat"))
        lon = float(arr[0].get("lon"))
        return lat, lon
    except Exception:
        return None


async def _dgis_geocode(query: str) -> Optional[tuple[float, float]]:
    q = (query or "").strip()
    if not q or not config.DGIS_API_KEY:
        return None
    url = "https://catalog.api.2gis.com/3.0/items/geocode"
    params = {
        "q": q,
        "fields": "items.point",
        "key": config.DGIS_API_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            if r.status_code >= 400:
                return None
            data = r.json()
        items = data.get("result", {}).get("items", [])
        if not isinstance(items, list) or not items:
            return None
        point = items[0].get("point", {})
        lat = point.get("lat")
        lon = point.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return None
        return float(lat), float(lon)
    except Exception:
        return None


async def _photon_geocode(query: str) -> Optional[tuple[float, float]]:
    q = (query or "").strip()
    if not q:
        return None
    url = "https://photon.komoot.io/api/"
    params = {"q": q, "limit": 1}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            if r.status_code >= 400:
                return None
            data = r.json()
        features = data.get("features", [])
        if not isinstance(features, list) or not features:
            return None
        coords = features[0].get("geometry", {}).get("coordinates", [])
        if not isinstance(coords, list) or len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        return lat, lon
    except Exception:
        return None


def _extract_duration_seconds(route: dict) -> Optional[float]:
    vals = []
    for key in ("time", "duration"):
        v = route.get(key)
        if isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
            vals.append(float(v["value"]))
        elif isinstance(v, (int, float)):
            vals.append(float(v))
    for k in ("duration_with_traffic", "durationInTraffic", "timeWithTraffic"):
        v = route.get(k)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    vals = [x for x in vals if x > 0]
    return min(vals) if vals else None


async def taxi_duration_minutes(origin: tuple[float, float], destination: tuple[float, float]) -> tuple[Optional[int], Optional[str]]:
    provider = config.ROUTING_PROVIDER if config.ROUTING_PROVIDER in ("google", "dgis", "yandex", "yandex_matrix") else "auto"

    async def google_route() -> tuple[Optional[int], Optional[str]]:
        if not config.GOOGLE_MAPS_API_KEY:
            return None, "не задан GOOGLE_MAPS_API_KEY"
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "routes.duration",
            "Content-Type": "application/json",
        }
        payload = {
            "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
            "destination": {"location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    return None, f"Google Routes API вернул {r.status_code}"
                data = r.json()
        except Exception:
            return None, "Google Routes API недоступен"
        routes = data.get("routes", [])
        if not routes:
            return None, "Google Routes: маршрут не найден"
        s = routes[0].get("duration", "")
        if isinstance(s, str) and s.endswith("s"):
            try:
                return max(1, int(float(s[:-1]) // 60)), None
            except Exception:
                pass
        return None, "Google Routes: маршрут не вернул время"

    async def yandex_route() -> tuple[Optional[int], Optional[str]]:
        key = config.YANDEX_ROUTING_API_KEY or config.YANDEX_API_KEY
        if not key:
            return None, "не задан Yandex ключ"
        url = "https://api.routing.yandex.net/v2/route"
        params = {
            "apikey": key,
            "waypoints": f"{origin[0]},{origin[1]}|{destination[0]},{destination[1]}",
            "mode": "driving",
            "traffic": "disabled",
        }
        headers = {"Authorization": f"Api-Key {key}"}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url, params=params, headers=headers)
                if r.status_code >= 400:
                    return None, f"Yandex Routing API вернул {r.status_code}"
                data = r.json()
        except Exception:
            return None, "Yandex Routing API недоступен"
        routes = data.get("routes", [])
        if not routes:
            return None, "маршрут не найден"
        sec = _extract_duration_seconds(routes[0])
        if not sec:
            return None, "маршрут не вернул время"
        return max(1, int(sec // 60)), None

    async def yandex_matrix_route() -> tuple[Optional[int], Optional[str]]:
        key = config.YANDEX_DISTANCE_MATRIX_API_KEY or config.YANDEX_ROUTING_API_KEY or config.YANDEX_API_KEY
        if not key:
            return None, "не задан Yandex ключ"
        url = "https://api.routing.yandex.net/v2/distancematrix"
        params = {
            "apikey": key,
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{destination[0]},{destination[1]}",
            "mode": "driving",
            "units": "metric",
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url, params=params)
                if r.status_code >= 400:
                    return None, f"Yandex Distance Matrix API вернул {r.status_code}"
                data = r.json()
        except Exception:
            return None, "Yandex Distance Matrix API недоступен"
        rows = data.get("rows", [])
        if not rows or not isinstance(rows[0], dict):
            return None, "Yandex Matrix: пустой ответ"
        elements = rows[0].get("elements", [])
        if not elements or not isinstance(elements[0], dict):
            return None, "Yandex Matrix: маршрут не найден"
        e0 = elements[0]
        status = str(e0.get("status", "OK")).upper()
        if status not in {"OK", "SUCCESS"}:
            return None, f"Yandex Matrix: status={status}"
        duration = e0.get("duration")
        sec = None
        if isinstance(duration, dict):
            for k in ("value", "duration"):
                if isinstance(duration.get(k), (int, float)):
                    sec = float(duration[k])
                    break
        elif isinstance(duration, (int, float)):
            sec = float(duration)
        if not sec:
            return None, "Yandex Matrix: маршрут не вернул время"
        return max(1, int(sec // 60)), None

    async def dgis_route() -> tuple[Optional[int], Optional[str]]:
        if not config.DGIS_API_KEY:
            return None, "не задан DGIS_API_KEY"
        url = "https://routing.api.2gis.com/routing/7.0.0/global"
        payload = {
            "points": [
                {"lat": origin[0], "lon": origin[1], "type": "stop", "start": True},
                {"lat": destination[0], "lon": destination[1], "type": "stop", "start": False},
            ],
            "transport": "driving",
            "route_mode": "fastest",
            "traffic_mode": "jam",
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.post(url, params={"key": config.DGIS_API_KEY}, json=payload)
                if r.status_code >= 400:
                    return None, f"2GIS Routing API вернул {r.status_code}"
                data = r.json()
        except Exception:
            return None, "2GIS Routing API недоступен"
        routes = data.get("result", [])
        if not isinstance(routes, list) or not routes:
            return None, "2GIS: маршрут не найден"
        total = routes[0].get("total_duration")
        sec = None
        if isinstance(total, dict) and isinstance(total.get("value"), (int, float)):
            sec = float(total["value"])
        elif isinstance(total, (int, float)):
            sec = float(total)
        if not sec:
            return None, "2GIS: маршрут не вернул время"
        return max(1, int(sec // 60)), None

    async def osrm_route() -> tuple[Optional[int], Optional[str]]:
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        )
        params = {"overview": "false"}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url, params=params)
                if r.status_code >= 400:
                    return None, f"OSRM API вернул {r.status_code}"
                data = r.json()
        except Exception:
            return None, "OSRM API недоступен"
        routes = data.get("routes", [])
        if not routes:
            return None, "OSRM: маршрут не найден"
        sec = routes[0].get("duration")
        if not isinstance(sec, (int, float)) or sec <= 0:
            return None, "OSRM: маршрут не вернул время"
        return max(1, int(float(sec) // 60)), None

    if provider in ("google", "auto"):
        m, e = await google_route()
        if m is not None or provider == "google":
            return m, e
    if provider in ("dgis", "auto"):
        m, e = await dgis_route()
        if m is not None or provider == "dgis":
            return m, e
    if provider in ("yandex_matrix", "auto"):
        m, e = await yandex_matrix_route()
        if m is not None or provider == "yandex_matrix":
            return m, e
    m, e = await yandex_route()
    if m is not None:
        return m, e
    if provider == "auto":
        return await osrm_route()
    return m, e


async def get_traffic_duration(origin: tuple[float, float], destination: tuple[float, float]) -> Optional[int]:
    """Get travel time with CURRENT traffic conditions"""
    if config.DGIS_API_KEY:
        try:
            url = "https://routing.api.2gis.com/routing/7.0.0/global"
            payload = {
                "points": [
                    {"lat": origin[0], "lon": origin[1], "type": "stop", "start": True},
                    {"lat": destination[0], "lon": destination[1], "type": "stop", "start": False},
                ],
                "transport": "driving",
                "route_mode": "fastest",
                "traffic_mode": "jam",
            }
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.post(url, params={"key": config.DGIS_API_KEY}, json=payload)
                if r.status_code < 400:
                    data = r.json()
                    routes = data.get("result", [])
                    if isinstance(routes, list) and routes:
                        total = routes[0].get("total_duration")
                        sec = None
                        if isinstance(total, dict) and isinstance(total.get("value"), (int, float)):
                            sec = float(total["value"])
                        elif isinstance(total, (int, float)):
                            sec = float(total)
                        if sec:
                            return max(1, int(sec // 60))
        except Exception:
            pass

    key = config.YANDEX_DISTANCE_MATRIX_API_KEY or config.YANDEX_ROUTING_API_KEY or config.YANDEX_API_KEY
    if not key:
        return None
    url = "https://api.routing.yandex.net/v2/distancematrix"
    params = {
        "apikey": key,
        "origins": f"{origin[0]},{origin[1]}",
        "destinations": f"{destination[0]},{destination[1]}",
        "mode": "driving",
        "units": "metric",
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            if r.status_code >= 400:
                return None
            data = r.json()
        rows = data.get("rows", [])
        if not rows or not isinstance(rows[0], dict):
            return None
        elements = rows[0].get("elements", [])
        if not elements or not isinstance(elements[0], dict):
            return None
        e0 = elements[0]
        status = str(e0.get("status", "OK")).upper()
        if status not in {"OK", "SUCCESS"}:
            return None
        duration = e0.get("duration")
        sec = None
        if isinstance(duration, dict):
            for k in ("value", "duration"):
                if isinstance(duration.get(k), (int, float)):
                    sec = float(duration[k])
                    break
        elif isinstance(duration, (int, float)):
            sec = float(duration)
        if not sec:
            return None
        return max(1, int(sec // 60))
    except Exception:
        return None


async def monitor_and_alert_traffic(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Постоянно проверяет пробки и говорит когда надо выезжать.
    Срабатывает каждые 5-10 минут до события.
    """
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    baseline_duration = d.get("duration")
    task_id = d["task_id"]
    
    # Если событие уже прошло, отменяем мониторинг
    if event_time <= datetime.now():
        return
    
    # Если нет маршрута, ничего не делаем
    if not (baseline_duration and d.get("origin") and d.get("destination")):
        return
    
    try:
        origin = tuple(d["origin"])
        destination = tuple(d["destination"])
        current_duration = await get_traffic_duration(origin, destination)
        
        if not current_duration:
            return
        
        # Расчитываем: если выехать СЕЙЧАС, будем ли мы вовремя?
        time_to_event = (event_time - datetime.now()).total_seconds() / 60
        buffer_minutes = config.DEFAULT_BUFFER_MIN
        
        # Нужно выехать с буфером
        needed_time = current_duration + buffer_minutes
        
        # Если осталось времени ровно столько, сколько нужно - ВЫЕЗЖайте!
        if needed_time <= time_to_event <= needed_time + 10:
            lines = [
                f"🚗 <b>ВЫЕЗЖАЙТЕ СЕЙЧАС!</b>",
                f"",
                f"Событие: {event_time.strftime('%H:%M')}",
                f"Текущая дорога: <b>{current_duration} мин</b>",
                f"С буфером: {current_duration + buffer_minutes} мин",
                f"",
            ]
            
            if current_duration > baseline_duration:
                delay = current_duration - baseline_duration
                lines.append(f"🔴 Пробки! Задержка: +{delay} мин")
            else:
                lines.append(f"🟢 Дорога в норме")
            
            lines.append(f"⏰ На дороге: {current_duration} мин, буфер: {buffer_minutes} мин")
            
            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)
            
            # Удаляем мониторинг после отправки
            for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
                job.schedule_removal()
        
        # Если мало времени - разбираемся срочно
        elif time_to_event < needed_time:
            # Вычисляем на сколько минут опаздываем
            shortage = needed_time - time_to_event
            
            if shortage > 30:
                # Слишком поздно, можем не успеть
                lines = [
                    f"🚨 <b>КРИТИЧНО! ВЫЕЗЖАЙТЕ ПРЯМО СЕЙЧАС!</b>",
                    f"",
                    f"Осталось времени: {int(time_to_event)} мин",
                    f"Нужно времени: {int(needed_time)} мин",
                    f"Нехватка: {int(shortage)} мин",
                    f"",
                    f"Заказывайте такси или срочно выезжайте!",
                ]
            else:
                # Ещё можно успеть, но надо торопиться
                lines = [
                    f"⏰ <b>Торопитесь выезжать!</b>",
                    f"Событие: {event_time.strftime('%H:%M')}",
                    f"Осталось времени: {int(time_to_event)} мин",
                    f"Дорога: {current_duration} мин",
                ]
            
            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)
            
            # Удаляем мониторинг
            for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
                job.schedule_removal()
    
    except Exception as e:
        logger.error(f"Ошибка при мониторинге пробок: {e}")


async def check_traffic_early(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет пробки за час до события и напоминает, если задержка серьёзная"""
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    leave_time = db.from_iso(d.get("leave_time"))
    baseline_duration = d.get("duration")
    
    # Если нет маршрута, ничего не делаем
    if not (leave_time and baseline_duration and d.get("origin") and d.get("destination")):
        return
    
    try:
        origin = tuple(d["origin"])
        destination = tuple(d["destination"])
        current_duration = await get_traffic_duration(origin, destination)
        
        if not current_duration:
            return
        
        delay = current_duration - baseline_duration
        
        # Если задержка > 20 минут, отправляем срочное напоминание
        if delay > 20:
            lines = [
                f"⚠️ <b>ВНИМАНИЕ: Серьёзные пробки!</b>",
                f"Событие: {event_time.strftime('%H:%M')}",
                f"",
                f"Обычно в пути: {baseline_duration} мин",
                f"🔴 <b>Сейчас в пути: {current_duration} мин</b> (задержка +{delay} мин)",
                f"",
            ]
            
            # Расчитываем новое время выезда
            new_leave_time = event_time - timedelta(minutes=current_duration + config.DEFAULT_BUFFER_MIN)
            
            if new_leave_time > datetime.now():
                lines.append(f"Запланированный выезд был: {leave_time.strftime('%H:%M')}")
                lines.append(f"<b>По пробкам нужно выехать: {new_leave_time.strftime('%H:%M')}</b>")
            else:
                lines.append(f"<b>Выезжайте ПРЯМО СЕЙЧАС!</b>")
                lines.append(f"Времени критически мало!")
            
            msg = await context.bot.send_message(
                chat_id=d["chat_id"],
                text="\n".join(lines),
                parse_mode=ParseMode.HTML
            )
            cleanup.schedule_bot_message_cleanup_at(context, int(d["chat_id"]), int(msg.message_id), event_time)
    except Exception:
        pass


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.job.data or {}
    event_time = datetime.fromisoformat(d["event_time"])
    leave_time = db.from_iso(d.get("leave_time"))
    taxi_order_time = db.from_iso(d.get("taxi_order_time"))
    baseline_duration = d.get("duration")
    task_id = d["task_id"]
    
    # Удаляем мониторинг если он ещё работает
    for job in context.application.job_queue.get_jobs_by_name(f"monitor_{task_id}"):
        job.schedule_removal()
    
    lines = [f"Напоминание: <b>{d['text']}</b>", f"Время: {event_time.strftime('%d.%m.%Y %H:%M')}"]
    
    # Если есть маршрут, проверяем пробки и даём рекомендацию
    if leave_time and baseline_duration and d.get("origin") and d.get("destination"):
        try:
            origin = tuple(d["origin"])
            destination = tuple(d["destination"])
            current_duration = await get_traffic_duration(origin, destination)
            
            if current_duration:
                lines.append(f"Обычно в пути: {baseline_duration} мин")
                
                # Анализируем дорожную ситуацию
                delay = current_duration - baseline_duration if baseline_duration else 0
                
                if delay <= 5:  # Дорога свободна
                    lines.append("🟢 Дорога свободна! Не торопитесь.")
                    lines.append(f"Выезжайте в: <b>{leave_time.strftime('%H:%M')}</b>")
                elif delay <= 15:  # Небольшие пробки
                    lines.append(f"🟡 Легкие пробки (+{delay} мин).")
                    suggested_time = leave_time - timedelta(minutes=delay//2)
                    lines.append(f"Лучше выехать в: <b>{suggested_time.strftime('%H:%M')}</b>")
                else:  # Серьёзные пробки
                    lines.append(f"🔴 Пробки! Задержка: +{delay} мин.")
                    if taxi_order_time:
                        lines.append(f"Заказывайте такси сейчас: <b>{taxi_order_time.strftime('%H:%M')}</b>")
                        lines.append("(такси приедет ~15 мин, надо собраться)")
                    else:
                        urgent_time = leave_time - timedelta(minutes=delay - 5)
                        lines.append(f"Срочно выезжайте в: <b>{urgent_time.strftime('%H:%M')}</b>")
            else:
                # Если не смогли получить текущие пробки, используем стандартный совет
                lines.append(f"В пути примерно: {baseline_duration} мин")
                lines.append(f"Лучше выехать в: <b>{leave_time.strftime('%H:%M')}</b>")
        except Exception:
            # На случай ошибки, используем стандартный совет
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
        # If bot restarted after planned reminder time, send a catch-up reminder soon.
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
    
    # Если есть маршрут, запланировать постоянный мониторинг пробок
    if origin and destination and duration:
        # Начинаем мониторинг за 90 минут до события
        monitor_start = event_time - timedelta(minutes=90)
        
        if monitor_start > datetime.now():
            # Мониторим каждые 5-10 минут до выезда
            application.job_queue.run_repeating(
                monitor_and_alert_traffic,
                interval=300,  # каждые 5 минут
                first=monitor_start,
                data=job_data,
                name=f"monitor_{task_id}",
            )
        else:
            # Если до мониторинга осталось < 90 минут, начинаем сразу
            application.job_queue.run_repeating(
                monitor_and_alert_traffic,
                interval=300,  # каждые 5 минут
                first=0.5,
                data=job_data,
                name=f"monitor_{task_id}",
            )
    
    # Также запланировать финальное напоминание (перед выездом) как fallback
    application.job_queue.run_once(
        send_reminder,
        when=remind_time,
        data=job_data,
        name=f"task_{task_id}",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    from app import profile

    if not db.is_onboarding_completed(update.effective_user.id):
        await profile.start_onboarding(update, context, force=False)
        return
    await update.message.reply_text(
        "Я бот-помощник. Кнопка Планировщик - задачи, Фильмы - Letterboxd.",
        reply_markup=main_menu_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    txt = (
        "Планировщик:\n"
        "- Просто напиши задачу: завтра к стоматологу в 16:00 на Ленина 10\n"
        "- /home <адрес>\n- /list\n- /delete <id>\n- /delete_last"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_keyboard())


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    address = " ".join(context.args).strip()
    if not address:
        cur = db.get_home_address(user_id)
        await update.message.reply_text(cur or "Укажите /home <адрес>", reply_markup=main_menu_keyboard())
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
    lines = ["Ваши задачи:"]
    for t in tasks:
        line = f"#{t.id} | {t.event_time.strftime('%d.%m %H:%M')} | {t.text}"
        if t.destination:
            line += f" | куда: {t.destination}"
        lines.append(line)
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


async def _ask_next_plan_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    d = _plan_draft(context)
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


async def _finalize_planning_task(
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
            origin = await geocode_with_fallback(origin_address, context_address=destination)
            dest_coords = await geocode_with_fallback(destination, context_address=origin_address)
            if origin and dest_coords:
                duration, err = await taxi_duration_minutes(origin, dest_coords)
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
        except Exception:
            route_issues.append("ошибка расчета маршрута")

    # Do not save half-broken tasks; ask user to уточнить проблемный адрес и продолжить диалог.
    if route_issues:
        draft = _plan_draft(context)
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
    await schedule_task_job(
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
    draft = context.user_data.get(PLAN_DRAFT_KEY)

    if draft:
        d = _plan_draft(context)
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
            # User can type the start address directly at the first step.
            d["origin_address"] = raw_text
            d["awaiting"] = None
        elif awaiting == "origin_text":
            d["origin_address"] = raw_text
            d["awaiting"] = None
        elif awaiting == "destination_text":
            d["destination"] = raw_text
            d["awaiting"] = None
        elif awaiting == "time_text":
            dt = _parse_datetime_ru(raw_text)
            if not dt:
                await update.effective_message.reply_text("Не понял время. Пример: сегодня 16:00 или через 1 час.")
                return True
            d["event_dt"] = dt
            d["awaiting"] = None
        else:
            # If user sends free text while draft exists, try to fill missing values.
            maybe_dt = _parse_datetime_ru(raw_text)
            if maybe_dt and not d.get("event_dt"):
                d["event_dt"] = maybe_dt
            elif not d.get("destination"):
                d["destination"] = infer_destination_from_text(raw_text) or raw_text

        need_more = await _ask_next_plan_question(update, context)
        if need_more:
            return True

        ok = await _finalize_planning_task(
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
            _clear_plan_draft(context)
        return ok

    ai_fields = await parse_task_fields_gemini(raw_text)
    ai_parsed = await parse_task_input_gemini(raw_text)
    if ai_parsed:
        text, destination, event_dt = ai_parsed
    else:
        text, destination, event_dt = parse_task_input(raw_text)
        if ai_fields.get("title"):
            text = ai_fields["title"]
        if ai_fields.get("destination"):
            destination = ai_fields["destination"]
        if ai_fields.get("event_dt"):
            event_dt = ai_fields["event_dt"]

    destination = destination or infer_destination_from_text(raw_text)

    intent = bool(ai_fields.get("is_task")) or is_planning_intent(raw_text) or bool(event_dt)
    if not intent:
        return False

    d = _plan_draft(context)
    d["title"] = humanize_task_title(text or raw_text, destination)
    # Always run full flow: from where -> destination -> time.
    d["destination"] = None
    d["event_dt"] = None
    d["detected_destination"] = destination
    d["detected_event_dt"] = event_dt
    d["origin_address"] = None
    d["awaiting"] = None

    need_more = await _ask_next_plan_question(update, context)
    if need_more:
        return True

    ok = await _finalize_planning_task(
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
        _clear_plan_draft(context)
    return ok


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if PLAN_DRAFT_KEY not in context.user_data:
        return False
    d = _plan_draft(context)
    loc = update.effective_message.location if update.effective_message else None
    if not loc:
        return False
    addr = await reverse_geocode(float(loc.latitude), float(loc.longitude))
    if not addr:
        addr = f"{loc.latitude:.6f}, {loc.longitude:.6f}"
    d["origin_address"] = addr
    d["awaiting"] = None

    need_more = await _ask_next_plan_question(update, context)
    if need_more:
        return True

    ok = await _finalize_planning_task(
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
        _clear_plan_draft(context)
    return ok


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
            except Exception:
                duration = None
        
        # Пытаемся геокодировать адреса для проверки пробок (если есть маршрут)
        if r["destination"]:
            try:
                home_address = db.get_home_address(r["user_id"])
                if home_address:
                    origin = await geocode_with_fallback(home_address, context_address=home_address)
                    dest_coords = await geocode_with_fallback(r["destination"], context_address=home_address)
            except Exception:
                pass
        
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


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("home", home))
    application.add_handler(CommandHandler("list", list_cmd))
    application.add_handler(CommandHandler("delete", delete_cmd))
    application.add_handler(CommandHandler("delete_last", delete_last_cmd))


def ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
