from __future__ import annotations

import json
import logging

import httpx

from app import config, word_extractor
from app.services import movies_english
from app.services.script_dialogues import load_dialogues_for_film

logger = logging.getLogger(__name__)


async def build_movie_learning_suggestion(film_title: str) -> dict:
    dialogues = load_dialogues_for_film(film_title, config.SCRIPT_DB_ROOT, max_lines=80)
    fallback_pool = movies_english.extract_fallback_words_from_dialogues(film_title, dialogues, need=7)
    fallback = {
        "words": [f"{x['word']} — {x['translation']}" for x in fallback_pool[:5]],
        "phrases": dialogues[:2] if dialogues else ["Try retelling one scene in English.", "Describe the main conflict in 2-3 sentences."],
    }
    if not config.GEMINI_API_KEY:
        return fallback
    prompt = (
        "Верни JSON без пояснений: {\"words\":[\"...\"],\"phrases\":[\"...\"]}. "
        f"Фильм: {film_title}. Нужны 5 слов и 2 фразы на английском с переводом."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=18) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                logger.warning("Gemini lesson generation failed: status=%s body=%s", r.status_code, r.text[:300])
                return fallback
            text = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            data = json.loads(text)
            result = {
                "words": [str(x) for x in data.get("words", [])][:5],
                "phrases": [str(x) for x in data.get("phrases", [])][:2],
            }
            if not result["words"] and not result["phrases"]:
                return fallback
            return result
    except Exception as e:
        logger.debug("Gemini lesson parse failed for film=%s: %s", film_title, e)
        return fallback


async def generate_english_words_for_film(film_title: str) -> list[dict]:
    subtitle_words = await word_extractor.extract_words_from_movie_subtitles(film_title=film_title, year=None, limit=12)
    if subtitle_words:
        return subtitle_words

    dialogues = load_dialogues_for_film(film_title, config.SCRIPT_DB_ROOT, max_lines=120)
    fallback_words = movies_english.extract_fallback_words_from_dialogues(film_title, dialogues, need=12)
    if not config.GEMINI_API_KEY:
        return fallback_words

    if dialogues:
        dialogue_block = "\n".join(f"- {x}" for x in dialogues[:120])
        prompt = (
            "Верни ТОЛЬКО JSON-массив без пояснений.\n"
            "Возьми слова именно из переданных диалогов фильма. Нужны сложные слова уровня Upper-Intermediate/C1.\n"
            f"Фильм: {film_title}\n"
            "Формат элемента: {\"word\":\"...\",\"translation\":\"...\",\"example\":\"...\"}\n"
            "Требования: 12 слов, translation на русском, example на английском и желательно из реплик ниже.\n"
            f"Диалоги:\n{dialogue_block}"
        )
    else:
        prompt = (
            "Верни ТОЛЬКО JSON-массив без пояснений.\n"
            "Нужно 12 сложных слов уровня Upper-Intermediate/C1 по фильму.\n"
            f"Фильм: {film_title}\n"
            "Формат элемента: {\"word\":\"...\",\"translation\":\"...\",\"example\":\"...\"}\n"
            "Перевод на русском, example на английском, коротко."
        )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
    }

    try:
        async with httpx.AsyncClient(timeout=18) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                logger.warning("Gemini words generation failed: status=%s body=%s", r.status_code, r.text[:300])
                return fallback_words
            txt = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            out = movies_english.parse_json_array_maybe(txt)
            if not out:
                return fallback_words
            merged = out[:]
            used = {x.get("word", "").lower() for x in merged}
            for item in fallback_words:
                if item["word"] in used:
                    continue
                merged.append(item)
                if len(merged) >= 12:
                    break
            return merged[:12]
    except Exception as e:
        logger.warning("Gemini words generation exception: %s", e)
        return fallback_words
