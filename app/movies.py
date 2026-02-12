from __future__ import annotations

import logging
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from html import escape, unescape
from typing import Optional

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app import cleanup, config, db
from app.keyboards import main_menu_keyboard, movies_menu_keyboard
from app.services.script_dialogues import detect_script_db_ready, load_dialogues_for_film

logger = logging.getLogger(__name__)


def _safe_child_text(item: ET.Element, tag: str) -> Optional[str]:
    node = item.find(tag)
    if node is not None and node.text:
        return node.text.strip()
    return None


def normalize_film_title(entry_title: str) -> str:
    title = unescape(entry_title or "").strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    title = re.sub(r"\s+\(\d{4}\)\s*$", "", title).strip()
    title = re.sub(r",\s*\d{4}\s*$", "", title).strip()
    return title or "Фильм"


def parse_letterboxd_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    for item in root.findall(".//item"):
        title = _safe_child_text(item, "title") or ""
        link = _safe_child_text(item, "link")
        guid = _safe_child_text(item, "guid") or link or title
        items.append(
            {
                "guid": guid,
                "entry_title": title,
                "film_title": normalize_film_title(title),
                "link": link,
                "published": _safe_child_text(item, "pubDate"),
                "summary": _safe_child_text(item, "description"),
            }
        )
    return items


def parse_watchlist_html(html_text: str) -> list[dict]:
    pattern = re.compile(r'data-item-name="([^"]+)"[^>]*data-item-link="([^"]+)"', re.IGNORECASE)
    out: list[dict] = []
    seen: set[str] = set()
    for m in pattern.finditer(html_text):
        name = unescape(m.group(1).strip())
        link = unescape(m.group(2).strip())
        if link.startswith("/"):
            link = f"https://letterboxd.com{link}"
        if link in seen:
            continue
        seen.add(link)
        out.append(
            {
                "guid": link,
                "entry_title": name,
                "film_title": normalize_film_title(name),
                "link": link,
                "published": None,
                "summary": None,
            }
        )
    return out


def looks_like_letterboxd_rss(url: str) -> bool:
    u = (url or "").strip().lower()
    return (u.startswith("http://") or u.startswith("https://")) and "letterboxd.com/" in u and "/rss" in u


def derive_watchlist_rss_url(rss_url: str) -> Optional[str]:
    u = (rss_url or "").strip()
    low = u.lower()
    if "letterboxd.com/" not in low:
        return None
    if "/watchlist/rss" in low:
        return u
    if "/rss" in low:
        return re.sub(r"/rss/?$", "/watchlist/rss/", u, flags=re.IGNORECASE)
    return None


async def fetch_letterboxd_items(url: str) -> tuple[list[dict], Optional[str]]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                return [], f"RSS вернул {r.status_code}"
            items = parse_letterboxd_rss(r.text)
            if not items:
                return [], "в RSS нет записей"
            return items, None
    except Exception as e:
        return [], f"ошибка RSS: {e}"


async def fetch_watchlist_items(url: str) -> tuple[list[dict], Optional[str]]:
    items, err = await fetch_letterboxd_items(url)
    if items:
        return items, None
    if not err or "403" not in err:
        return items, err
    html_url = re.sub(r"/rss/?$", "/", url, flags=re.IGNORECASE)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(html_url)
            if r.status_code >= 400:
                return [], f"wishlist страница вернула {r.status_code}"
            parsed = parse_watchlist_html(r.text)
            if not parsed:
                return [], "не удалось распознать wishlist"
            return parsed, None
    except Exception as e:
        return [], f"ошибка wishlist: {e}"


def movie_action_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Актеры и режиссер", callback_data=f"mv:people:{entry_id}"),
                InlineKeyboardButton("Факты", callback_data=f"mv:facts:{entry_id}"),
            ],
            [InlineKeyboardButton("English", callback_data=f"mv:en:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def movie_back_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Назад", callback_data=f"mv:menu:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def people_carousel_keyboard(entry_id: int, idx: int, total: int) -> InlineKeyboardMarkup:
    if total <= 1:
        return movie_back_keyboard(entry_id)
    prev_idx = (idx - 1) % total
    next_idx = (idx + 1) % total
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️", callback_data=f"mvp:{entry_id}:{prev_idx}"),
                InlineKeyboardButton(f"{idx + 1}/{total}", callback_data=f"mvp:{entry_id}:{idx}"),
                InlineKeyboardButton("➡️", callback_data=f"mvp:{entry_id}:{next_idx}"),
            ],
            [InlineKeyboardButton("Назад", callback_data=f"mv:menu:{entry_id}")],
            [InlineKeyboardButton("Главное меню", callback_data=f"mv:home:{entry_id}")],
        ]
    )


def english_word_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Показать перевод", callback_data=f"eng:show:{word_id}"),
                InlineKeyboardButton("❌ Не выучил", callback_data=f"eng:hard:{word_id}"),
            ],
            [
                InlineKeyboardButton("✅ Выучил", callback_data=f"eng:learned:{word_id}"),
                InlineKeyboardButton("➡️ Следующее", callback_data=f"eng:next:{word_id}"),
            ],
            [
                InlineKeyboardButton("Назад", callback_data="eng:menu:0"),
                InlineKeyboardButton("Главное меню", callback_data="eng:home:0"),
            ],
        ]
    )


async def tmdb_search_movie(title: str) -> Optional[dict]:
    if not config.TMDB_API_KEY:
        return None
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": config.TMDB_API_KEY, "query": title, "include_adult": "false"}
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, params=params)
        if r.status_code >= 400:
            return None
        data = r.json()
    return data.get("results", [None])[0]


async def tmdb_movie_details(movie_id: int) -> Optional[dict]:
    if not config.TMDB_API_KEY:
        return None
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": config.TMDB_API_KEY, "append_to_response": "credits"}
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, params=params)
        if r.status_code >= 400:
            return None
        return r.json()


def tmdb_image_url(path: Optional[str]) -> Optional[str]:
    return f"https://image.tmdb.org/t/p/w500{path}" if path else None


async def build_movie_learning_suggestion(film_title: str) -> dict:
    dialogues = load_dialogues_for_film(film_title, config.SCRIPT_DB_ROOT, max_lines=80)
    fallback_pool = _extract_fallback_words_from_dialogues(film_title, dialogues, need=7)
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
    except Exception:
        return fallback


def build_movie_facts_text(film_title: str, details: Optional[dict]) -> str:
    if not details:
        return f"Не нашел детали по «{escape(film_title)}»."
    genres = ", ".join(g.get("name", "") for g in details.get("genres", []) if g.get("name")) or "—"
    lines = [
        f"🎞 <b>{escape(details.get('title') or film_title)}</b>",
        f"Год/дата: <b>{escape(details.get('release_date') or '—')}</b>",
        f"Длительность: <b>{escape(str(details.get('runtime') or '—'))} мин</b>",
        f"Жанры: <b>{escape(genres)}</b>",
    ]
    if isinstance(details.get("vote_average"), (int, float)):
        lines.append(f"Рейтинг TMDB: <b>{details['vote_average']:.1f}</b>")
    return "\n".join(lines)


def build_people_data(film_title: str, details: Optional[dict]) -> tuple[str, list[dict]]:
    if not details:
        return f"Не нашел актеров/режиссера по «{escape(film_title)}».", []
    credits = details.get("credits", {})
    crew = credits.get("crew", []) if isinstance(credits, dict) else []
    cast = credits.get("cast", []) if isinstance(credits, dict) else []
    director = next((p for p in crew if (p.get("job") or "").lower() == "director"), None)
    top_cast = cast[:6]
    lines = [f"🎭 <b>{escape(details.get('title') or film_title)}</b>"]
    lines.append(f"Режиссер: <b>{escape((director or {}).get('name', '—'))}</b>")
    people = []
    if director and director.get("profile_path"):
        people.append({"name": director["name"], "role": "Режиссер", "photo": tmdb_image_url(director["profile_path"])})
    for p in top_cast:
        if p.get("profile_path"):
            people.append({"name": p.get("name", "Actor"), "role": p.get("character") or "Актер", "photo": tmdb_image_url(p.get("profile_path"))})
    return "\n".join(lines), people


def build_english_text(film_title: str, lesson: dict) -> str:
    lines = [f"🇬🇧 <b>English по фильму {escape(film_title)}</b>"]
    for w in lesson.get("words", [])[:5]:
        lines.append(f"• {escape(str(w))}")
    for p in lesson.get("phrases", [])[:2]:
        lines.append(f"• {escape(str(p))}")
    if len(lines) == 1:
        lines.append("Пока нет данных.")
    return "\n".join(lines)


FALLBACK_WORD_BANK: list[dict] = [
    {"word": "ominous", "translation": "зловещий", "example": "The soundtrack feels ominous."},
    {"word": "intricate", "translation": "замысловатый", "example": "The plot is intricate."},
    {"word": "redemption", "translation": "искупление", "example": "The story explores redemption."},
    {"word": "ambiguity", "translation": "неоднозначность", "example": "The ending leaves ambiguity."},
    {"word": "haunting", "translation": "преследующий, навязчивый", "example": "It has a haunting atmosphere."},
    {"word": "resilient", "translation": "стойкий, выносливый", "example": "She remains resilient under pressure."},
    {"word": "vulnerable", "translation": "уязвимый", "example": "He feels vulnerable in that moment."},
    {"word": "relentless", "translation": "неумолимый", "example": "The pace is relentless from start to finish."},
    {"word": "uncertain", "translation": "неопределенный", "example": "Their future is uncertain."},
    {"word": "deception", "translation": "обман", "example": "The conflict is built on deception."},
    {"word": "sacrifice", "translation": "жертва, жертвовать", "example": "The hero makes a sacrifice."},
    {"word": "confrontation", "translation": "конфронтация, столкновение", "example": "A confrontation changes everything."},
]

FALLBACK_TRANSLATIONS: dict[str, str] = {x["word"]: x["translation"] for x in FALLBACK_WORD_BANK}
FALLBACK_TRANSLATIONS.update(
    {
        "ominously": "зловеще",
        "intricacy": "сложность, запутанность",
        "redeem": "искупать",
        "redemptive": "искупительный",
        "ambiguous": "неоднозначный",
        "vulnerability": "уязвимость",
        "relentlessly": "неумолимо",
        "uncertainty": "неопределенность",
        "deceptive": "обманчивый",
        "sacrificed": "пожертвовал",
        "confront": "сталкиваться, противостоять",
        "confronted": "столкнулся",
        "consequence": "последствие",
        "consequences": "последствия",
        "collapse": "крах, обрушение",
        "catastrophe": "катастрофа",
        "catastrophic": "катастрофический",
        "desperation": "отчаяние",
        "desperate": "отчаянный",
        "obsession": "одержимость",
        "obsessed": "одержимый",
        "betrayal": "предательство",
        "betrayed": "предал",
        "forgiveness": "прощение",
        "haunted": "преследуемый (мыслями)",
        "isolation": "изоляция",
        "isolated": "изолированный",
        "conscience": "совесть",
        "fragments": "фрагменты",
        "fragmented": "раздробленный",
        "fate": "судьба",
        "destiny": "предназначение",
        "survival": "выживание",
        "survivor": "выживший",
        "trauma": "травма",
        "traumatic": "травматичный",
        "mysterious": "таинственный",
        "mystery": "тайна",
        "inevitable": "неизбежный",
        "intensity": "интенсивность",
        "identity": "личность",
        "illusion": "иллюзия",
        "legacy": "наследие",
        "moral": "моральный, нравственный",
        "ethical": "этический",
        "tension": "напряжение",
        "turbulent": "бурный, неспокойный",
        "hostile": "враждебный",
        "conspiracy": "заговор",
        "anxiety": "тревога",
        "disturbing": "тревожный, disturbing",
        "devastating": "разрушительный",
        "wilderness": "дикая местность",
        "hostility": "враждебность",
        "integrity": "честность, целостность",
        "compassion": "сострадание",
        "conflicted": "внутренне противоречивый",
        "reckless": "безрассудный",
        "ruthless": "безжалостный",
        "redemptive": "искупительный",
        "brutality": "жестокость",
        "enigma": "загадка",
    }
)

COMMON_ENGLISH_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "almost",
    "always",
    "another",
    "around",
    "because",
    "before",
    "being",
    "between",
    "could",
    "didnt",
    "doesnt",
    "dont",
    "every",
    "first",
    "found",
    "going",
    "great",
    "heard",
    "himself",
    "inside",
    "into",
    "itself",
    "maybe",
    "might",
    "never",
    "nothing",
    "other",
    "out",
    "really",
    "right",
    "should",
    "something",
    "still",
    "their",
    "there",
    "these",
    "thing",
    "think",
    "those",
    "through",
    "together",
    "under",
    "until",
    "where",
    "which",
    "would",
    "youre",
    "your",
    "just",
    "have",
    "has",
    "had",
    "with",
    "what",
    "when",
    "they",
    "them",
    "then",
    "this",
    "that",
    "from",
    "were",
    "been",
    "will",
    "cant",
    "wont",
}

ADVANCED_SUFFIXES = (
    "tion",
    "sion",
    "ment",
    "ness",
    "ance",
    "ence",
    "ity",
    "ism",
    "ship",
    "ous",
    "ive",
    "able",
    "ible",
    "ial",
    "ary",
    "ory",
    "istic",
    "ical",
    "ward",
)


def _normalize_word_token(word: str) -> str:
    return re.sub(r"[^a-z]", "", (word or "").lower())


def _word_lookup_variants(word: str) -> list[str]:
    w = _normalize_word_token(word)
    if not w:
        return []
    variants = [w]
    for suffix in ("ies", "es", "s", "ed", "ing", "ly"):
        if w.endswith(suffix) and len(w) > len(suffix) + 3:
            if suffix == "ies":
                variants.append(w[:-3] + "y")
            else:
                variants.append(w[: -len(suffix)])
    dedup: list[str] = []
    for v in variants:
        if v and v not in dedup:
            dedup.append(v)
    return dedup


def _fallback_translation(word: str) -> Optional[str]:
    for v in _word_lookup_variants(word):
        t = FALLBACK_TRANSLATIONS.get(v)
        if t:
            return t
    return None


def _extract_fallback_words_from_dialogues(film_title: str, dialogues: list[str], need: int = 12) -> list[dict]:
    scored: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for line in dialogues:
        line_clean = re.sub(r"\s+", " ", (line or "").strip())
        if not line_clean:
            continue
        tokens = re.findall(r"[A-Za-z][A-Za-z'-]{4,}", line_clean)
        for token in tokens:
            word = _normalize_word_token(token)
            if len(word) < 5 or word in COMMON_ENGLISH_STOPWORDS:
                continue
            score = 1
            if len(word) >= 8:
                score += 2
            if len(word) >= 10:
                score += 2
            if any(word.endswith(suf) for suf in ADVANCED_SUFFIXES):
                score += 2
            scored[word] += score
            if word not in examples:
                examples[word] = line_clean[:180]

    ranked = sorted(scored.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    out: list[dict] = []
    used: set[str] = set()
    for word, _ in ranked:
        if word in used:
            continue
        tr = _fallback_translation(word)
        if not tr:
            continue
        out.append(
            {
                "word": word,
                "translation": tr,
                "example": examples.get(word) or f"In the film {film_title}, this word appears in dialogue.",
            }
        )
        used.add(word)
        if len(out) >= need:
            return out

    for item in FALLBACK_WORD_BANK:
        w = item["word"]
        if w in used:
            continue
        out.append(item)
        used.add(w)
        if len(out) >= need:
            break
    return out


def _parse_json_array_maybe(text: str) -> list[dict]:
    raw = (text or "").strip()
    if not raw:
        return []
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out: list[dict] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        w = str(it.get("word", "")).strip().lower()
        t = str(it.get("translation", "")).strip()
        ex = str(it.get("example", "")).strip()
        if w and t:
            out.append({"word": w, "translation": t, "example": ex})
    return out


def normalize_translation_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-zа-я0-9\\s-]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\\s+", " ", s)
    return s


def _normalize_button_text(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("ё", "е")
    s = re.sub(r"[^\w\sа-яa-z0-9-]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_movies_english_trigger(text: str) -> bool:
    n = _normalize_button_text(text)
    if n in {
        _normalize_button_text(config.BTN_MOVIES_ENGLISH),
        "изучение английского",
        "английский",
        "english",
        "learn english",
    }:
        return True
    return n.startswith("изучение english") or n.startswith("изучение англий")


def _is_menu_button_text(text: str) -> bool:
    buttons = {
        config.BTN_PLANNER,
        config.BTN_MOVIES,
        config.BTN_MOVIES_BIND,
        config.BTN_MOVIES_CHECK,
        config.BTN_MOVIES_CHECK_WISHLIST,
        config.BTN_MOVIES_ENGLISH,
        config.BTN_MOVIES_STATUS,
        config.BTN_MOVIES_UNBIND,
        config.BTN_BACK_MOVIES,
        config.BTN_HOME_MENU,
    }
    n = _normalize_button_text(text)
    normalized_buttons = {_normalize_button_text(x) for x in buttons}
    if _is_movies_english_trigger(text):
        return True
    return n in normalized_buttons


def english_word_card_text(row: dict, reveal: bool = False) -> str:
    film = row.get("film_title", "Фильм")
    word = row.get("word", "")
    translation = row.get("translation", "")
    example = row.get("example") or ""
    lines = [
        f"📘 <b>English по фильму {escape(film)}</b>",
        "",
        f"<b>Word:</b> {escape(word)}",
    ]
    if reveal:
        lines.append(f"<b>Перевод:</b> {escape(translation)}")
    else:
        lines.append("<b>Перевод:</b> ❓ (введи в чат или нажми 'Показать перевод')")
    if example:
        lines.append("")
        lines.append(f"<b>Example:</b> {escape(example)}")
    return "\n".join(lines)


async def generate_english_words_for_film(film_title: str) -> list[dict]:
    dialogues = load_dialogues_for_film(film_title, config.SCRIPT_DB_ROOT, max_lines=120)
    fallback_words = _extract_fallback_words_from_dialogues(film_title, dialogues, need=12)
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
            out = _parse_json_array_maybe(txt)
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


async def ensure_user_english_pool(user_id: int) -> tuple[bool, str]:
    due = db.get_due_english_word(user_id) or db.get_any_english_word(user_id)
    if due:
        return True, ""
    film_title = db.get_latest_film_title_for_user(user_id)
    if not film_title:
        return False, "Пока нет фильмов в логах/wishlist. Сначала добавь или залогай фильм."
    words = await generate_english_words_for_film(film_title)
    if not words:
        return False, "Не удалось сгенерировать слова сейчас. Попробуй позже."
    db.save_english_words(user_id, film_title, words)
    return True, ""


async def send_next_english_word(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    row = db.get_due_english_word(user_id) or db.get_any_english_word(user_id)
    if not row:
        await update.effective_message.reply_text(
            "Пока нет слов для повторения.",
            reply_markup=movies_menu_keyboard(),
        )
        return
    context.user_data["awaiting_english_word_id"] = int(row["id"])
    await update.effective_message.reply_text(
        english_word_card_text(row, reveal=False),
        parse_mode=ParseMode.HTML,
        reply_markup=english_word_keyboard(int(row["id"])),
    )


async def process_letterboxd_for_user(
    application: Application,
    user_id: int,
    rss_url: str,
    last_guid: Optional[str],
    silent_if_no_new: bool = True,
) -> tuple[int, Optional[str], Optional[str]]:
    items, err = await fetch_letterboxd_items(rss_url)
    if err:
        return 0, err, None
    newest = items[0]["guid"] if items else None
    new_items = []
    for i in items:
        if last_guid and i["guid"] == last_guid:
            break
        new_items.append(i)
    new_count = 0
    for i in reversed(new_items):
        entry_id = db.save_letterboxd_entry_if_new(
            user_id=user_id,
            guid=i["guid"],
            film_title=i["film_title"],
            entry_title=i["entry_title"],
            entry_link=i["link"],
            published_at=i["published"],
            summary=i["summary"],
        )
        if not entry_id:
            continue
        new_count += 1
        lines = [f"Вижу, вы посмотрели <b>{escape(i['film_title'])}</b> 👀", "Хочешь разбор по фильму? Выбери кнопку ниже."]
        if i.get("link"):
            lines.insert(1, f"<a href=\"{escape(i['link'])}\">Открыть запись в Letterboxd</a>")
        await application.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=movie_action_keyboard(entry_id),
        )
    if newest:
        db.update_letterboxd_last_guid(user_id, newest)
    if new_count == 0 and not silent_if_no_new:
        return 0, None, "Пока без новых логов."
    return new_count, None, None


async def process_letterboxd_watchlist_for_user(
    application: Application,
    user_id: int,
    rss_url: str,
    last_guid: Optional[str],
    silent_if_no_new: bool = True,
) -> tuple[int, Optional[str], Optional[str]]:
    items, err = await fetch_watchlist_items(rss_url)
    if err:
        return 0, err, None
    newest = items[0]["guid"] if items else None
    new_items = []
    for i in items:
        if last_guid and i["guid"] == last_guid:
            break
        new_items.append(i)
    new_count = 0
    for i in reversed(new_items):
        entry_id = db.save_letterboxd_entry_if_new(
            user_id=user_id,
            guid=f"wishlist:{i['guid']}",
            film_title=i["film_title"],
            entry_title=i["entry_title"],
            entry_link=i["link"],
            published_at=i["published"],
            summary=i["summary"],
        )
        if not entry_id:
            continue
        new_count += 1
        lines = [
            f"✨ Вижу, вы добавили в wishlist: <b>{escape(i['film_title'])}</b>",
            "Давайте подготовимся: изучим актеров и пару слов к фильму?",
        ]
        if i.get("link"):
            lines.insert(1, f"<a href=\"{escape(i['link'])}\">Открыть в Letterboxd</a>")
        await application.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=movie_action_keyboard(entry_id),
        )
    if newest:
        db.update_letterboxd_last_watchlist_guid(user_id, newest)
    if new_count == 0 and not silent_if_no_new:
        return 0, None, "Пока без новых фильмов в wishlist."
    return new_count, None, None


async def bind_letterboxd_rss_for_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    rss_url: str,
) -> tuple[bool, str]:
    items, err = await fetch_letterboxd_items(rss_url)
    if err:
        return False, f"Не смог прочитать RSS: {err}"
    watchlist_rss = derive_watchlist_rss_url(rss_url)
    db.set_letterboxd_subscription(user_id, rss_url, watchlist_rss)
    if items:
        db.update_letterboxd_last_guid(user_id, items[0]["guid"])
    if watchlist_rss:
        wl_items, _ = await fetch_watchlist_items(watchlist_rss)
        if wl_items:
            db.update_letterboxd_last_watchlist_guid(user_id, wl_items[0]["guid"])
    return True, "Letterboxd привязан. Буду отслеживать новые логи и wishlist."


async def movies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    ok, status = detect_script_db_ready(config.SCRIPT_DB_ROOT)
    script_hint = "✅ Script DB подключена" if ok else f"⚠️ Script DB: {status}"
    txt = (
        f"{config.BTN_MOVIES_BIND}\n"
        f"{config.BTN_MOVIES_ENGLISH}\n"
        f"{config.BTN_MOVIES_UNBIND}\n\n"
        f"{script_hint}"
    )
    await update.message.reply_text(txt, reply_markup=movies_menu_keyboard())


async def movies_english_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    ok, msg = await ensure_user_english_pool(user_id)
    if not ok:
        await update.message.reply_text(msg, reply_markup=movies_menu_keyboard())
        return
    await send_next_english_word(update, context, user_id)


async def movies_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    sub = db.get_letterboxd_subscription(update.effective_user.id)
    if not sub:
        await update.message.reply_text("Letterboxd не привязан.", reply_markup=movies_menu_keyboard())
        return
    await update.message.reply_text(
        f"Дневник: {sub['rss_url']}\nWishlist: {sub['watchlist_rss_url'] or 'не задан'}",
        reply_markup=movies_menu_keyboard(),
    )


async def movies_bind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    context.user_data["awaiting_letterboxd_rss"] = True
    await update.message.reply_text(
        "Пришлите RSS ссылку Letterboxd, например: https://letterboxd.com/<user>/rss/",
        reply_markup=movies_menu_keyboard(),
    )


async def movies_unbind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    ok = db.disable_letterboxd_subscription(update.effective_user.id)
    await update.message.reply_text("Letterboxd отвязан." if ok else "Активной привязки нет.", reply_markup=movies_menu_keyboard())


async def movies_check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    sub = db.get_letterboxd_subscription(user_id)
    if not sub:
        await update.message.reply_text("Сначала привяжите RSS.", reply_markup=movies_menu_keyboard())
        return
    _, err, info = await process_letterboxd_for_user(context.application, user_id, sub["rss_url"], sub["last_guid"], False)
    if err:
        await update.message.reply_text(f"Не удалось проверить RSS: {err}", reply_markup=movies_menu_keyboard())
    elif info:
        await update.message.reply_text(info, reply_markup=movies_menu_keyboard())


async def movies_check_wishlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cleanup.cleanup_trigger_message(update, context)
    user_id = update.effective_user.id
    sub = db.get_letterboxd_subscription(user_id)
    if not sub:
        await update.message.reply_text("Сначала привяжите RSS.", reply_markup=movies_menu_keyboard())
        return
    wl = sub["watchlist_rss_url"] or derive_watchlist_rss_url(sub["rss_url"])
    if not wl:
        await update.message.reply_text("Не удалось определить wishlist RSS.", reply_markup=movies_menu_keyboard())
        return
    _, err, info = await process_letterboxd_watchlist_for_user(context.application, user_id, wl, sub["last_watchlist_guid"], False)
    if err:
        await update.message.reply_text(f"Не удалось проверить wishlist: {err}", reply_markup=movies_menu_keyboard())
    elif info:
        await update.message.reply_text(info, reply_markup=movies_menu_keyboard())


async def movie_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "mv":
        return
    action, entry_id_s = parts[1], parts[2]
    try:
        entry_id = int(entry_id_s)
    except ValueError:
        return
    entry = db.get_letterboxd_entry(entry_id, query.from_user.id)
    if not entry:
        return
    film_title = entry["film_title"]
    movie = await tmdb_search_movie(film_title)
    details = await tmdb_movie_details(int(movie["id"])) if movie and movie.get("id") else None

    if action == "menu":
        txt = f"Вижу, вы посмотрели <b>{escape(film_title)}</b> 👀\nХочешь разбор по фильму? Выбери кнопку ниже."
        await query.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=movie_action_keyboard(entry_id))
        return
    if action == "home":
        await query.message.reply_text(
            "Главное меню:",
            reply_markup=main_menu_keyboard(),
        )
        return
    if action == "facts":
        await query.message.reply_text(build_movie_facts_text(film_title, details), parse_mode=ParseMode.HTML, reply_markup=movie_back_keyboard(entry_id))
        return
    if action == "en":
        lesson = await build_movie_learning_suggestion(film_title)
        await query.message.reply_text(build_english_text(film_title, lesson), parse_mode=ParseMode.HTML, reply_markup=movie_back_keyboard(entry_id))
        return
    if action == "people":
        _, people = build_people_data(film_title, details)
        if not people:
            await query.message.reply_text("Не нашел фото актеров/режиссера.", reply_markup=movie_back_keyboard(entry_id))
            return
        p = people[0]
        caption = f"🎭 <b>{escape(film_title)}</b>\n<b>{escape(p['name'])}</b>\n{escape(p['role'])}"
        await query.message.reply_photo(
            photo=p["photo"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=people_carousel_keyboard(entry_id, 0, len(people)),
        )


async def movie_people_carousel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "mvp":
        return
    try:
        entry_id = int(parts[1])
        idx = int(parts[2])
    except ValueError:
        return
    entry = db.get_letterboxd_entry(entry_id, query.from_user.id)
    if not entry:
        return
    movie = await tmdb_search_movie(entry["film_title"])
    details = await tmdb_movie_details(int(movie["id"])) if movie and movie.get("id") else None
    _, people = build_people_data(entry["film_title"], details)
    if not people:
        return
    idx %= len(people)
    p = people[idx]
    caption = f"🎭 <b>{escape(entry['film_title'])}</b>\n<b>{escape(p['name'])}</b>\n{escape(p['role'])}"
    try:
        await query.message.edit_media(
            media=InputMediaPhoto(media=p["photo"], caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=people_carousel_keyboard(entry_id, idx, len(people)),
        )
    except Exception:
        pass


async def english_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "eng":
        return

    action = parts[1]
    try:
        word_id = int(parts[2])
    except ValueError:
        word_id = 0

    user_id = query.from_user.id

    if action == "menu":
        await query.message.reply_text("Раздел Фильмы:", reply_markup=movies_menu_keyboard())
        return
    if action == "home":
        await query.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return

    row = db.get_english_word(word_id, user_id)
    if not row:
        await query.message.reply_text("Слово не найдено.", reply_markup=movies_menu_keyboard())
        return

    if action == "show":
        await query.message.reply_text(
            english_word_card_text(row, reveal=True),
            parse_mode=ParseMode.HTML,
            reply_markup=english_word_keyboard(word_id),
        )
        return
    if action == "learned":
        db.update_english_word_review(word_id, user_id, "learned")
        context.user_data.pop("awaiting_english_word_id", None)
        await send_next_english_word(update, context, user_id)
        return
    if action == "hard":
        db.update_english_word_review(word_id, user_id, "hard")
        context.user_data.pop("awaiting_english_word_id", None)
        await send_next_english_word(update, context, user_id)
        return
    if action == "next":
        context.user_data["awaiting_english_word_id"] = word_id
        await send_next_english_word(update, context, user_id)
        return


async def poll_letterboxd_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for sub in db.list_letterboxd_subscriptions():
        try:
            await process_letterboxd_for_user(context.application, sub["user_id"], sub["rss_url"], sub["last_guid"], True)
            if sub["watchlist_rss_url"]:
                await process_letterboxd_watchlist_for_user(
                    context.application,
                    sub["user_id"],
                    sub["watchlist_rss_url"],
                    sub["last_watchlist_guid"],
                    True,
                )
        except Exception as e:
            logger.exception("Letterboxd polling failed for user %s: %s", sub["user_id"], e)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    raw_text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if raw_text == config.BTN_MOVIES:
        await movies_cmd(update, context)
        return True
    if raw_text == config.BTN_PLANNER:
        await cleanup.cleanup_trigger_message(update, context)
        await update.message.reply_text("Режим планировщика активен. Просто отправь задачу.", reply_markup=main_menu_keyboard())
        return True
    if raw_text == config.BTN_MOVIES_BIND:
        await movies_bind_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_CHECK:
        await movies_check_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_CHECK_WISHLIST:
        await movies_check_wishlist_cmd(update, context)
        return True
    if _is_movies_english_trigger(raw_text):
        await movies_english_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_STATUS:
        await movies_status_cmd(update, context)
        return True
    if raw_text == config.BTN_MOVIES_UNBIND:
        await movies_unbind_cmd(update, context)
        return True
    if raw_text == config.BTN_BACK_MOVIES:
        await movies_cmd(update, context)
        return True
    if raw_text == config.BTN_HOME_MENU:
        await cleanup.cleanup_trigger_message(update, context)
        await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())
        return True

    awaiting_word_id = context.user_data.get("awaiting_english_word_id")
    if awaiting_word_id and raw_text and not raw_text.startswith("/") and not _is_menu_button_text(raw_text):
        row = db.get_english_word(int(awaiting_word_id), user_id)
        if row:
            expected_parts = re.split(r"[,/;]| или ", str(row["translation"]), flags=re.IGNORECASE)
            expected = [normalize_translation_text(x) for x in expected_parts if normalize_translation_text(x)]
            got = normalize_translation_text(raw_text)
            ok = any(got == e or (got and got in e) or (e and e in got) for e in expected)
            if ok:
                db.update_english_word_review(int(awaiting_word_id), user_id, "correct")
                await update.message.reply_text("Отлично, верно ✅", reply_markup=movies_menu_keyboard())
            else:
                db.update_english_word_review(int(awaiting_word_id), user_id, "failed")
                await update.message.reply_text(
                    f"Пока мимо ❌\nПравильный перевод: {row['translation']}",
                    reply_markup=movies_menu_keyboard(),
                )
            context.user_data.pop("awaiting_english_word_id", None)
            await send_next_english_word(update, context, user_id)
            return True

    if context.user_data.get("awaiting_letterboxd_rss"):
        if not (raw_text.startswith("http://") or raw_text.startswith("https://")):
            await update.message.reply_text("Это не похоже на ссылку.", reply_markup=movies_menu_keyboard())
            return True
        ok, msg = await bind_letterboxd_rss_for_user(context, user_id, raw_text)
        context.user_data["awaiting_letterboxd_rss"] = False
        await update.message.reply_text(msg, reply_markup=movies_menu_keyboard())
        return True

    if looks_like_letterboxd_rss(raw_text):
        _, msg = await bind_letterboxd_rss_for_user(context, user_id, raw_text)
        await update.message.reply_text(msg, reply_markup=movies_menu_keyboard())
        return True

    return False


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("movies", movies_cmd))
    application.add_handler(CommandHandler("movies_bind", movies_bind_cmd))
    application.add_handler(CommandHandler("movies_check", movies_check_cmd))
    application.add_handler(CommandHandler("movies_wishlist", movies_check_wishlist_cmd))
    application.add_handler(CommandHandler("movies_english", movies_english_cmd))
    application.add_handler(CommandHandler("movies_status", movies_status_cmd))
    application.add_handler(CommandHandler("movies_unbind", movies_unbind_cmd))
    application.add_handler(CallbackQueryHandler(english_word_callback, pattern=r"^eng:"))
    application.add_handler(CallbackQueryHandler(movie_people_carousel_callback, pattern=r"^mvp:"))
    application.add_handler(CallbackQueryHandler(movie_action_callback, pattern=r"^mv:"))
