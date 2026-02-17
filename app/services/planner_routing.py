from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from app import config

logger = logging.getLogger(__name__)


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
        p = await dgis_geocode(address)
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


def normalize_address(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("мкр.", "мкр").replace("г.", "г ")
    text = text.replace("/", " ")
    text = re.sub(r"\bдом\s+(\d+)\b", r"\1", text, flags=re.IGNORECASE)
    return text.strip(" ,")


def guess_city_from_address(address: str) -> Optional[str]:
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


def coords_match_city_hint(coords: tuple[float, float], address_hint: str) -> bool:
    hint = (address_hint or "").lower()
    if not hint:
        return True
    lat, lon = coords
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
    raw = normalize_address(address)
    if not raw:
        return None

    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", raw)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception as e:
            logger.debug("Failed to parse direct coordinates from '%s': %s", raw, e)

    candidates: list[str] = [raw]
    city = guess_city_from_address(raw) or guess_city_from_address(context_address or "")
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
        if p and coords_match_city_hint(p, q):
            return p

    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await nominatim_geocode(q, countrycodes="kg")
        if p and coords_match_city_hint(p, q):
            return p
    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await nominatim_geocode(q, countrycodes="")
        if p and coords_match_city_hint(p, q):
            return p
    for c in candidates:
        q = c.strip()
        if not q:
            continue
        p = await photon_geocode(q)
        if p and coords_match_city_hint(p, q):
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
    except Exception as e:
        logger.debug("Yandex reverse geocode failed lat=%s lon=%s: %s", lat, lon, e)
        return None
    return None


async def nominatim_geocode(query: str, countrycodes: str = "kg") -> Optional[tuple[float, float]]:
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
    except Exception as e:
        logger.debug("Nominatim geocode failed for query='%s': %s", query, e)
        return None


async def dgis_geocode(query: str) -> Optional[tuple[float, float]]:
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
    except Exception as e:
        logger.debug("Photon geocode failed for query='%s': %s", query, e)
        return None


async def photon_geocode(query: str) -> Optional[tuple[float, float]]:
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
    except Exception as e:
        logger.debug("2GIS geocode failed for query='%s': %s", query, e)
        return None


def extract_duration_seconds(route: dict) -> Optional[float]:
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
        except Exception as e:
            logger.debug("Google route request failed origin=%s destination=%s: %s", origin, destination, e)
            return None, "Google Routes API недоступен"
        routes = data.get("routes", [])
        if not routes:
            return None, "Google Routes: маршрут не найден"
        s = routes[0].get("duration", "")
        if isinstance(s, str) and s.endswith("s"):
            try:
                return max(1, int(float(s[:-1]) // 60)), None
            except Exception as e:
                logger.debug("Failed to parse Google route duration '%s': %s", s, e)
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
        except Exception as e:
            logger.debug("Yandex routing request failed origin=%s destination=%s: %s", origin, destination, e)
            return None, "Yandex Routing API недоступен"
        routes = data.get("routes", [])
        if not routes:
            return None, "маршрут не найден"
        sec = extract_duration_seconds(routes[0])
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
        except Exception as e:
            logger.debug("Yandex matrix request failed origin=%s destination=%s: %s", origin, destination, e)
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
        except Exception as e:
            logger.debug("2GIS routing request failed origin=%s destination=%s: %s", origin, destination, e)
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
        except Exception as e:
            logger.debug("OSRM routing request failed origin=%s destination=%s: %s", origin, destination, e)
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
        except Exception as e:
            logger.debug("2GIS traffic request failed for origin=%s destination=%s: %s", origin, destination, e)

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
    except Exception as e:
        logger.debug("Yandex matrix traffic duration parse failed origin=%s destination=%s: %s", origin, destination, e)
        return None
