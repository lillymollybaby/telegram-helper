from __future__ import annotations

import re

from app import config
from app.services import movies_english


def normalize_button_text(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("ё", "е")
    s = re.sub(r"[^\w\sа-яa-z0-9-]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_movies_english_trigger(text: str) -> bool:
    n = normalize_button_text(text)
    if n in {
        normalize_button_text(config.BTN_MOVIES_ENGLISH),
        "изучение английского",
        "английский",
        "english",
        "learn english",
    }:
        return True
    return n.startswith("изучение english") or n.startswith("изучение англий")


def is_menu_button_text(text: str) -> bool:
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
    n = normalize_button_text(text)
    normalized_buttons = {normalize_button_text(x) for x in buttons}
    if is_movies_english_trigger(text):
        return True
    return n in normalized_buttons


def translation_match(expected_translation: str, user_answer: str) -> bool:
    expected_parts = re.split(r"[,/;]| или ", str(expected_translation), flags=re.IGNORECASE)
    expected = [movies_english.normalize_translation_text(x) for x in expected_parts if movies_english.normalize_translation_text(x)]
    got = movies_english.normalize_translation_text(user_answer)
    return any(got == e or (got and got in e) or (e and e in got) for e in expected)
