from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime

import httpx
from telegram.ext import ContextTypes

from app import config

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


def clear_food_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in (STATE_WAIT_MEAL, STATE_WAIT_COMPOSITION, STATE_WAIT_AI, STATE_WAIT_PARAMS, STATE_WAIT_GOAL, STATE_WAIT_REMINDER):
        context.user_data.pop(k, None)


def normalize_advice_text(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return ""
    has_latin = bool(re.search(r"[A-Za-z]", s))
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", s))
    if has_latin and not has_cyrillic:
        return "Старайтесь соблюдать баланс: меньше сахара, больше белка и овощей."
    return s


def extract_json(text: str) -> dict | None:
    raw = (text or "").strip().replace("```json", "").replace("```", "").strip()
    if not raw:
        return None
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
    try:
        obj = json.loads(raw)
    except Exception as e:
        logger.debug("Failed to parse meal JSON payload: %s", e)
        return None
    return obj if isinstance(obj, dict) else None


def sum_items(items: list[dict]) -> dict:
    out = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "fiber": 0.0}
    for it in items:
        out["calories"] += float(it.get("calories", 0) or 0)
        out["protein"] += float(it.get("protein", 0) or 0)
        out["fat"] += float(it.get("fat", 0) or 0)
        out["carbs"] += float(it.get("carbs", 0) or 0)
        out["fiber"] += float(it.get("fiber", 0) or 0)
    return out


def fallback_analyze_text(text: str) -> dict:
    t = (text or "").lower()
    items = []
    for key, vals in FOOD_HINTS.items():
        if key in t:
            items.append({"name": key, **vals})
    if not items:
        items = [{"name": "meal", "calories": 450, "protein": 18, "fat": 16, "carbs": 52, "fiber": 4}]
    totals = sum_items(items)
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


async def gemini_meal_json(prompt: str, image_bytes: bytes | None = None) -> dict | None:
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
            return extract_json(text)
    except Exception as e:
        logger.warning("Gemini meal analysis exception: %s", e)
        return None


def normalized_analysis(obj: dict, fallback_name: str) -> dict:
    advice_raw = [str(x) for x in (obj.get("advice") or [])][:3] if isinstance(obj.get("advice"), list) else []
    advice = [x for x in (normalize_advice_text(v) for v in advice_raw) if x]
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
    obj = await gemini_meal_json(prompt)
    if obj:
        norm = normalized_analysis(obj, text)
        if norm.get("calories_kcal", 0) > 0:
            return norm
    return fallback_analyze_text(text)


async def analyze_meal_photo(caption: str, image_bytes: bytes) -> dict:
    prompt = (
        "Ты диет-ассистент. Проанализируй фото еды и подпись. Верни только JSON. Все поля и советы пиши только по-русски:\n"
        "{\"meal_name\":\"...\",\"items\":[{\"name\":\"...\",\"portion_g\":0,\"calories\":0,\"protein\":0,\"fat\":0,\"carbs\":0,\"fiber\":0}],"
        "\"calories_kcal\":0,\"protein_g\":0,\"fat_g\":0,\"carbs_g\":0,\"fiber_g\":0,"
        "\"advice\":[\"...\",\"...\"],\"confidence\":0.0}\n"
        f"Подпись: {caption or 'без подписи'}"
    )
    obj = await gemini_meal_json(prompt, image_bytes=image_bytes)
    if obj:
        norm = normalized_analysis(obj, caption or "Прием пищи")
        if norm.get("calories_kcal", 0) > 0:
            return norm
    return fallback_analyze_text(caption or "еда по фото")


def format_meal_saved_text(analysis: dict, meal_time: datetime) -> str:
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
