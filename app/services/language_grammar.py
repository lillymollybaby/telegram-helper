from __future__ import annotations

import io
import json
import logging
import random
import re
from pathlib import Path
from typing import Any

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from app import config
from app.keyboards import grammar_topics_keyboard, language_level_keyboard

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    logger.debug("PyMuPDF import failed: %s", e)
    fitz = None

DATA_ROOT = Path("app") / "language" / "grammar_data"
DEFAULT_A1A2_PDF_PATH = Path(r"C:\Users\iamli\Downloads\Grammar_Reference_A2.pdf")
DEFAULT_B1B2_PDF_PATH = Path(r"C:\Users\iamli\Downloads\Grammar_Reference_B1.pdf")

LANG_CODE_MAP = {
    config.BTN_LANG_ENGLISH: "en",
    config.BTN_LANG_FRENCH: "fr",
    config.BTN_LANG_GERMAN: "de",
}

LEVEL_GROUP_MAP = {
    config.BTN_LEVEL_A: ("a1", "a2"),
    config.BTN_LEVEL_B: ("b1", "b2"),
    config.BTN_LEVEL_C: ("c1", "c2"),
}

_PDF_TOPICS_CACHE: dict[str, dict[str, int]] = {}


def _load_level_topics(lang_code: str, level_code: str) -> list[dict[str, Any]]:
    path = DATA_ROOT / lang_code / f"{level_code}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Failed to load grammar JSON %s: %s", path, e)
        return []
    if isinstance(data, dict):
        topics = data.get("topics", [])
        return topics if isinstance(topics, list) else []
    if isinstance(data, list):
        return data
    return []


def _render_topic(topic: dict[str, Any], lang_label: str, level_label: str) -> str:
    title = str(topic.get("title") or "Grammar Topic").strip()
    rule = str(topic.get("rule") or "Добавьте правило в JSON.").strip()
    examples = topic.get("examples", [])
    if not isinstance(examples, list):
        examples = []
    lines = [
        f"{lang_label} / {level_label} / Grammar",
        "",
        f"Тема: {title}",
        f"Правило: {rule}",
    ]
    if examples:
        lines.append("")
        lines.append("Примеры:")
        for ex in examples[:3]:
            lines.append(f"- {str(ex)}")
    return "\n".join(lines)


def _missing_paths_text(lang_code: str, levels: tuple[str, str]) -> str:
    p1 = DATA_ROOT / lang_code / f"{levels[0]}.json"
    p2 = DATA_ROOT / lang_code / f"{levels[1]}.json"
    return (
        "Для этого уровня пока нет тем Grammar.\n"
        "Заполните JSON-файлы:\n"
        f"- {p1}\n"
        f"- {p2}"
    )


def _resolve_pdf_path(level_label: str) -> Path | None:
    if level_label == config.BTN_LEVEL_A:
        if config.GRAMMAR_A1A2_PDF:
            p = Path(config.GRAMMAR_A1A2_PDF)
            if p.exists():
                return p
        if DEFAULT_A1A2_PDF_PATH.exists():
            return DEFAULT_A1A2_PDF_PATH
    elif level_label == config.BTN_LEVEL_B:
        if config.GRAMMAR_B1B2_PDF:
            p = Path(config.GRAMMAR_B1B2_PDF)
            if p.exists():
                return p
        if DEFAULT_B1B2_PDF_PATH.exists():
            return DEFAULT_B1B2_PDF_PATH
    return None


def _extract_topics_from_index_page(text: str) -> dict[str, int]:
    topics: dict[str, int] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("•"):
            topic = line.lstrip("•").strip()
            page_num: int | None = None
            j = i + 1
            while j < len(lines):
                if lines[j].startswith("•"):
                    break
                m = re.search(r"\b(\d{1,3})\b", lines[j])
                if m:
                    page_num = int(m.group(1))
                    break
                j += 1
            if topic and page_num and topic not in topics:
                topics[topic] = page_num
            i = j
        else:
            i += 1
    return topics


def _get_topics_from_pdf(level_label: str) -> tuple[Path | None, dict[str, int]]:
    pdf_path = _resolve_pdf_path(level_label)
    if not pdf_path or fitz is None:
        return None, {}

    cache_key = str(pdf_path)
    if cache_key in _PDF_TOPICS_CACHE and _PDF_TOPICS_CACHE[cache_key]:
        return pdf_path, dict(_PDF_TOPICS_CACHE[cache_key])

    try:
        doc = fitz.open(pdf_path)
        index_text = doc[0].get_text("text") if doc.page_count else ""
        topics = _extract_topics_from_index_page(index_text)
        doc.close()
    except Exception as e:
        logger.debug("Failed to parse grammar topics from PDF %s: %s", pdf_path, e)
        return pdf_path, {}

    _PDF_TOPICS_CACHE[cache_key] = dict(topics)
    return pdf_path, topics


async def _send_pdf_topic_snippet(
    update: Update,
    topic: str,
    page_number: int,
    pdf_path: Path,
    all_topics: list[str],
) -> None:
    if fitz is None:
        await update.effective_message.reply_text(
            "PyMuPDF не установлен. Установите зависимость `PyMuPDF`.",
            reply_markup=language_level_keyboard(),
        )
        return

    try:
        doc = fitz.open(pdf_path)
        if page_number < 1 or page_number >= doc.page_count:
            page_number = min(max(page_number, 1), max(doc.page_count - 1, 1))
        page = doc[page_number]

        clip = None
        matches = page.search_for(topic)
        if matches:
            top = min(matches, key=lambda r: r.y0)
            y0 = max(0, top.y0 - 35)
            y1 = min(page.rect.y1, y0 + 480)
            clip = fitz.Rect(0, y0, page.rect.x1, y1)

        if clip is None:
            clip = fitz.Rect(0, 0, page.rect.x1, min(page.rect.y1, 520))

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        img = io.BytesIO(pix.tobytes("png"))
        img.name = f"grammar_{page_number}_{topic}.png"
        img.seek(0)
        caption = f"{topic} (стр. {page_number})"
        await update.effective_message.reply_photo(
            photo=InputFile(img),
            caption=caption,
            reply_markup=grammar_topics_keyboard(all_topics),
        )
        doc.close()
    except Exception as e:
        logger.debug("Failed to render grammar snippet topic=%s page=%s pdf=%s: %s", topic, page_number, pdf_path, e)
        await update.effective_message.reply_text(
            "Не получилось вырезать тему из PDF. Проверьте путь к файлу и попробуйте снова.",
            reply_markup=language_level_keyboard(),
        )


async def start_grammar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang_label = context.user_data.get("lang_selected", config.BTN_LANG_ENGLISH)
    level_label = context.user_data.get("lang_level", config.BTN_LEVEL_A)

    if lang_label == config.BTN_LANG_ENGLISH and level_label in {config.BTN_LEVEL_A, config.BTN_LEVEL_B}:
        pdf_path, topic_map = _get_topics_from_pdf(level_label)
        if topic_map:
            topics = list(topic_map.keys())
            context.user_data["grammar_topics"] = topic_map
            context.user_data["grammar_pdf_path"] = str(pdf_path)
            context.user_data["screen"] = "lang_grammar_topics"
            await update.effective_message.reply_text(
                f"Выберите тему Grammar ({level_label}):",
                reply_markup=grammar_topics_keyboard(topics),
            )
            return

        if pdf_path is None:
            env_name = "GRAMMAR_A1A2_PDF" if level_label == config.BTN_LEVEL_A else "GRAMMAR_B1B2_PDF"
            await update.effective_message.reply_text(
                f"Файл {level_label} PDF не найден. Укажите путь в `{env_name}` в .env.",
                reply_markup=language_level_keyboard(),
            )
            return

    lang_code = LANG_CODE_MAP.get(lang_label, "en")
    levels = LEVEL_GROUP_MAP.get(level_label, ("a1", "a2"))

    topics = []
    for lvl in levels:
        topics.extend(_load_level_topics(lang_code, lvl))

    if not topics:
        await update.effective_message.reply_text(
            _missing_paths_text(lang_code, levels),
            reply_markup=language_level_keyboard(),
        )
        return

    topic = random.choice(topics)
    await update.effective_message.reply_text(
        _render_topic(topic, lang_label, level_label),
        reply_markup=language_level_keyboard(),
    )


async def handle_grammar_topic_click(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    topic_map = context.user_data.get("grammar_topics")
    pdf_path_raw = context.user_data.get("grammar_pdf_path")
    if not isinstance(topic_map, dict) or not pdf_path_raw:
        return False
    if text not in topic_map:
        return False

    page_number = int(topic_map.get(text, 1))
    pdf_path = Path(pdf_path_raw)
    await _send_pdf_topic_snippet(update, text, page_number, pdf_path, list(topic_map.keys()))
    return True
